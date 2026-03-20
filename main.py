import os
import psycopg2
from datetime import datetime
from telegram import Update, InlineKeyboardButton, InlineKeyboardMarkup
from telegram.ext import (
    ApplicationBuilder,
    CommandHandler,
    CallbackQueryHandler,
    MessageHandler,
    filters,
    ContextTypes,
)

# ==============================
# BASE DE DATOS
# ==============================

def get_connection():
    database_url = os.getenv("DATABASE_URL")
    if not database_url:
        raise ValueError("DATABASE_URL no configurada")
    return psycopg2.connect(database_url)


# ==============================
# VARIABLES TEMPORALES
# ==============================

user_states = {}


# ==============================
# START
# ==============================

async def start(update: Update, context: ContextTypes.DEFAULT_TYPE):
    keyboard = [[InlineKeyboardButton("Crear Ticket", callback_data="crear")]]
    await update.message.reply_text(
        "🔵 SUNDDE – Soporte Técnico\n\nPresiona el botón para crear un ticket.",
        reply_markup=InlineKeyboardMarkup(keyboard)
    )


# ==============================
# BOTONES
# ==============================

async def button_handler(update: Update, context: ContextTypes.DEFAULT_TYPE):
    query = update.callback_query
    await query.answer()

    user_id = query.from_user.id

    if query.data == "crear":
        user_states[user_id] = {"step": "tipo"}

        keyboard = [
            [InlineKeyboardButton("Acceso", callback_data="Acceso")],
            [InlineKeyboardButton("Red", callback_data="Red")],
            [InlineKeyboardButton("Sistema", callback_data="Sistema")],
            [InlineKeyboardButton("Impresora", callback_data="Impresora")],
            [InlineKeyboardButton("Correo", callback_data="Correo")],
            [InlineKeyboardButton("WiFi", callback_data="WiFi")]
        ]

        await query.edit_message_text(
            "Selecciona tipo de caso:",
            reply_markup=InlineKeyboardMarkup(keyboard)
        )

    else:
        user_states[user_id]["tipo"] = query.data
        user_states[user_id]["step"] = "piso"
        await query.edit_message_text("¿En qué piso y unidad?")


# ==============================
# FLUJO PRIVADO
# ==============================

async def text_handler(update: Update, context: ContextTypes.DEFAULT_TYPE):

    if update.effective_chat.type != "private":
        return

    user_id = update.message.from_user.id

    if user_id not in user_states:
        await update.message.reply_text("Usa /start para iniciar un ticket.")
        return

    step = user_states[user_id]["step"]

    if step == "piso":
        user_states[user_id]["piso"] = update.message.text
        user_states[user_id]["step"] = "sistema"
        await update.message.reply_text("¿Qué sistema o dispositivo está afectado?")

    elif step == "sistema":
        user_states[user_id]["sistema"] = update.message.text
        user_states[user_id]["step"] = "descripcion"
        await update.message.reply_text("Describe el problema brevemente:")

    elif step == "descripcion":

        user_states[user_id]["descripcion"] = update.message.text
        now = datetime.now()

        conn = get_connection()
        cursor = conn.cursor()

        cursor.execute("""
            INSERT INTO tickets (
                usuario_id,
                usuario_nombre,
                tipo,
                piso,
                sistema,
                descripcion,
                estado,
                asignado_a,
                fecha_creacion,
                fecha_actualizacion
            )
            VALUES (%s,%s,%s,%s,%s,%s,%s,%s,%s,%s)
            RETURNING id;
        """, (
            user_id,
            update.message.from_user.full_name,
            user_states[user_id]["tipo"],
            user_states[user_id]["piso"],
            user_states[user_id]["sistema"],
            user_states[user_id]["descripcion"],
            "ABIERTO",
            None,
            now,
            now
        ))

        ticket_id = cursor.fetchone()[0]

        group_id = context.application.bot_data["GROUP_ID"]

        text = f"""
🆕 TICKET #{ticket_id}
Estado: 🟢 ABIERTO
Creado: {now.strftime("%d/%m/%Y %H:%M")}

👤 Usuario: {update.message.from_user.full_name}
🧩 Tipo: {user_states[user_id]['tipo']}
🏢 Piso: {user_states[user_id]['piso']}
🖥 Sistema: {user_states[user_id]['sistema']}

📝 Descripción:
{user_states[user_id]['descripcion']}
"""

        msg = await context.bot.send_message(chat_id=group_id, text=text)

        cursor.execute(
            "UPDATE tickets SET message_id=%s WHERE id=%s",
            (msg.message_id, ticket_id)
        )

        conn.commit()
        cursor.close()
        conn.close()

        await update.message.reply_text(f"✅ Tu ticket #{ticket_id} fue creado.")

        del user_states[user_id]


# ==============================
# PROCESO (GRUPO)
# ==============================

async def proceso(update: Update, context: ContextTypes.DEFAULT_TYPE):

    await update.message.reply_text("PROCESO RECIBIDO")

    if not context.args:
        await update.message.reply_text("SIN ARGUMENTO")
        return

    ticket_id = int(context.args[0])

    conn = get_connection()
    cursor = conn.cursor()

    cursor.execute(
        "SELECT message_id FROM tickets WHERE id=%s",
        (ticket_id,)
    )

    result = cursor.fetchone()

    if not result:
        await update.message.reply_text("TICKET NO EXISTE EN DB")
        return

    message_id = result[0]

    await update.message.reply_text(f"message_id = {message_id}")

# ==============================
# CERRAR (GRUPO)
# ==============================

async def cerrar(update: Update, context: ContextTypes.DEFAULT_TYPE):

    if not context.args:
        return

    ticket_id = int(context.args[0])
    tecnico = update.message.from_user.full_name
    now = datetime.now()

    conn = get_connection()
    cursor = conn.cursor()

    cursor.execute("""
        UPDATE tickets
        SET estado='CERRADO',
            fecha_actualizacion=%s
        WHERE id=%s
        RETURNING message_id, usuario_id;
    """, (now, ticket_id))

    result = cursor.fetchone()

    if not result:
        await update.message.reply_text("Ticket no encontrado.")
        cursor.close()
        conn.close()
        return

    message_id, usuario_id = result

    await context.bot.edit_message_text(
        chat_id=update.effective_chat.id,
        message_id=message_id,
        text=f"🔴 TICKET #{ticket_id}\nEstado: CERRADO\nCerrado por: {tecnico}"
    )

    await context.bot.send_message(
        chat_id=usuario_id,
        text=f"✅ Tu ticket #{ticket_id} fue RESUELTO."
    )

    conn.commit()
    cursor.close()
    conn.close()


# ==============================
# MAIN
# ==============================

if __name__ == "__main__":

    TOKEN = os.getenv("BOT_TOKEN")
    GROUP_ID = os.getenv("GROUP_ID")

    app = ApplicationBuilder().token(TOKEN).build()
    app.bot_data["GROUP_ID"] = int(GROUP_ID)

    # ===== DEBUG GLOBAL =====
    async def debug(update: Update, context: ContextTypes.DEFAULT_TYPE):
        await update.message.reply_text("DEBUG OK")

    app.add_handler(CommandHandler("debug", debug))

    # ===== COMANDOS GRUPO =====
    app.add_handler(CommandHandler("proceso", proceso))
    app.add_handler(CommandHandler("cerrar", cerrar))

    # ===== PRIVADO =====
    app.add_handler(CommandHandler("start", start))
    app.add_handler(CallbackQueryHandler(button_handler))
    app.add_handler(
        MessageHandler(
            filters.ChatType.PRIVATE & filters.TEXT & ~filters.COMMAND,
            text_handler
        )
    )

    print("🚀 BOT LISTO")

    app.run_polling()
