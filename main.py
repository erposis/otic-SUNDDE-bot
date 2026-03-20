import os
import psycopg2
from urllib.parse import urlparse
from datetime import datetime
from telegram import Update, InlineKeyboardButton, InlineKeyboardMarkup
from telegram.ext import (
    ApplicationBuilder,
    CommandHandler,
    CallbackQueryHandler,
    MessageHandler,
    ContextTypes,
    filters,
)

# ==============================
# VARIABLES GLOBALES
# ==============================

user_states = {}
ticket_counter = 1
tickets = {}
def get_connection():
    url = os.getenv("DATABASE_URL")
    result = urlparse(url)

    conn = psycopg2.connect(
        database=result.path[1:],
        user=result.username,
        password=result.password,
        host=result.hostname,
        port=result.port
    )

    return conn
    
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
            "Selecciona tipo de Caso:",
            reply_markup=InlineKeyboardMarkup(keyboard)
        )
    else:
        user_states[user_id]["tipo"] = query.data
        user_states[user_id]["step"] = "piso"
        await query.edit_message_text("¿En cuál Piso y Unidad?")

# ==============================
# TEXTO PRIVADO
# ==============================

async def text_handler(update: Update, context: ContextTypes.DEFAULT_TYPE):

    # 🔒 SOLO PRIVADO
    if update.effective_chat.type != "private":
        return

    global ticket_counter

    user_id = update.message.from_user.id

    if user_id not in user_states:
        keyboard = [[InlineKeyboardButton("Crear Ticket", callback_data="crear")]]
        await update.message.reply_text(
            "🔵 SUNDDE – Soporte Técnico\n\nPresiona el botón para crear un ticket.",
            reply_markup=InlineKeyboardMarkup(keyboard)
        )
        return

    step = user_states[user_id]["step"]

    if step == "piso":
        user_states[user_id]["piso"] = update.message.text
        user_states[user_id]["step"] = "sistema"
        await update.message.reply_text("¿Qué Dispositivo o Sistema está afectado?")

    elif step == "sistema":
        user_states[user_id]["sistema"] = update.message.text
        user_states[user_id]["step"] = "descripcion"
        await update.message.reply_text("Describe tu requerimiento brevemente:")

elif step == "descripcion":
    user_states[user_id]["descripcion"] = update.message.text

    current_time = datetime.now()

    group_id = context.application.bot_data["GROUP_ID"]

    # ==============================
    # INSERTAR EN BASE DE DATOS
    # ==============================

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
        ) VALUES (%s,%s,%s,%s,%s,%s,%s,%s,%s,%s)
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
        current_time,
        current_time
    ))

    ticket_id = cursor.fetchone()[0]

    conn.commit()
    cursor.close()
    conn.close()

    # ==============================
    # ENVIAR MENSAJE AL GRUPO
    # ==============================

    ticket_text = f"""
🆕 TICKET #{ticket_id}
Estado: 🟢 ABIERTO
Creado: {current_time.strftime("%d/%m/%Y %H:%M")}

👤 Usuario: {update.message.from_user.full_name}
🧩 Tipo: {user_states[user_id]['tipo']}
🏢 Piso: {user_states[user_id]['piso']}
🖥 Sistema: {user_states[user_id]['sistema']}

📝 Descripción:
{user_states[user_id]['descripcion']}
"""

    msg = await context.bot.send_message(chat_id=group_id, text=ticket_text)

    await update.message.reply_text(f"✅ Tu ticket #{ticket_id} fue creado.")

    del user_states[user_id]

# ==============================
# CAMBIAR A PROCESO
# ==============================

async def proceso(update: Update, context: ContextTypes.DEFAULT_TYPE):

    if update.effective_chat.type == "private":
        return

    if not context.args:
        await update.message.reply_text("Usa: /proceso <numero_ticket>")
        return

    ticket_id = int(context.args[0])

    if ticket_id not in tickets:
        await update.message.reply_text("Ticket no encontrado.")
        return

    current_time = datetime.now().strftime("%d/%m/%Y %H:%M")
    tecnico = update.effective_user.full_name

    tickets[ticket_id]["status"] = "EN PROCESO"

    new_text = tickets[ticket_id]["base_text"].replace(
        "🟢 ABIERTO",
        f"🟡 EN PROCESO\nAsignado a: {tecnico}\nActualizado: {current_time}"
    )

    await context.bot.edit_message_text(
        chat_id=update.effective_chat.id,
        message_id=tickets[ticket_id]["message_id"],
        text=new_text
    )

    user_id = tickets[ticket_id]["user_id"]

    await context.bot.send_message(
        chat_id=user_id,
        text=f"🛠 Tu ticket #{ticket_id} está EN PROCESO."
    )

# ==============================
# CERRAR TICKET
# ==============================

async def cerrar(update: Update, context: ContextTypes.DEFAULT_TYPE):

    if update.effective_chat.type == "private":
        return

    if not context.args:
        await update.message.reply_text("Usa: /cerrar <numero_ticket>")
        return

    ticket_id = int(context.args[0])

    if ticket_id not in tickets:
        await update.message.reply_text("Ticket no encontrado.")
        return

    current_time = datetime.now().strftime("%d/%m/%Y %H:%M")
    tecnico = update.effective_user.full_name

    tickets[ticket_id]["status"] = "CERRADO"

    new_text = tickets[ticket_id]["base_text"].replace(
        "🟢 ABIERTO",
        f"🔴 CERRADO\nCerrado por: {tecnico}\nActualizado: {current_time}"
    )

    await context.bot.edit_message_text(
        chat_id=update.effective_chat.id,
        message_id=tickets[ticket_id]["message_id"],
        text=new_text
    )

    user_id = tickets[ticket_id]["user_id"]

    await context.bot.send_message(
        chat_id=user_id,
        text=f"🔒 Tu ticket #{ticket_id} fue RESUELTO."
    )

# ==============================
# MAIN
# ==============================

if __name__ == "__main__":

    TOKEN = os.getenv("BOT_TOKEN")
    GROUP_ID = os.getenv("GROUP_ID")

    if not TOKEN:
        raise ValueError("❌ BOT_TOKEN no configurado")

    if not GROUP_ID:
        raise ValueError("❌ GROUP_ID no configurado")

    app = ApplicationBuilder().token(TOKEN).build()

    app.bot_data["GROUP_ID"] = int(GROUP_ID)

    # Privado
    app.add_handler(CommandHandler("start", start))
    app.add_handler(CallbackQueryHandler(button_handler))
    app.add_handler(MessageHandler(filters.TEXT & ~filters.COMMAND, text_handler))

    # Grupo
    app.add_handler(CommandHandler("proceso", proceso))
    app.add_handler(CommandHandler("cerrar", cerrar))

    print("🚀 Bot SUNDDE iniciado correctamente")
    
    # ==============================
    # CREAR TABLA SI NO EXISTE
    # ==============================

    conn = get_connection()
    cursor = conn.cursor()

    cursor.execute("""
    CREATE TABLE IF NOT EXISTS tickets (
        id SERIAL PRIMARY KEY,
        usuario_id BIGINT,
        usuario_nombre TEXT,
        tipo TEXT,
        piso TEXT,
        sistema TEXT,
        descripcion TEXT,
        estado TEXT,
        asignado_a TEXT,
        fecha_creacion TIMESTAMP,
        fecha_actualizacion TIMESTAMP
    );
    """)

    conn.commit()
    cursor.close()
    conn.close()
    
    app.run_polling()
