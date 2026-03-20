import os
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
# VARIABLES GLOBALES
# ==============================

user_states = {}
ticket_counter = 1
tickets = {}

# ==============================
# COMANDO START (SOLO PRIVADO)
# ==============================

async def start(update: Update, context: ContextTypes.DEFAULT_TYPE):
    keyboard = [[InlineKeyboardButton("Crear Ticket", callback_data="crear")]]

    await context.bot.send_message(
        chat_id=update.effective_chat.id,
        text="🔵 SUNDDE – Soporte Técnico\n\nPresiona el botón para crear un ticket.",
        reply_markup=InlineKeyboardMarkup(keyboard)
    )

# ==============================
# MANEJO DE BOTONES
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

        await query.edit_message_text("¿En cual Piso y Unidad?")

# ==============================
# MANEJO DE TEXTO (SOLO PRIVADO)
# ==============================

async def text_handler(update: Update, context: ContextTypes.DEFAULT_TYPE):
    global ticket_counter

    user_id = update.message.from_user.id

    if user_id not in user_states:
        user_states[user_id] = {"step": "tipo"}

        keyboard = [
            [InlineKeyboardButton("Acceso", callback_data="Acceso")],
            [InlineKeyboardButton("Red", callback_data="Red")],
            [InlineKeyboardButton("Sistema", callback_data="Sistema")],
            [InlineKeyboardButton("Impresora", callback_data="Impresora")],
            [InlineKeyboardButton("Correo", callback_data="Correo")],
            [InlineKeyboardButton("WiFi", callback_data="WiFi")]
        ]

        await context.bot.send_message(
            chat_id=update.effective_chat.id,
            text="🔵 SUNDDE – Soporte Técnico\n\nSelecciona tipo de problema:",
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

        group_id = context.application.bot_data["GROUP_ID"]

        ticket_text = f"""
🆕 TICKET #{ticket_counter}
Estado: ABIERTO

👤 Usuario: {update.message.from_user.full_name}
🧩 Tipo: {user_states[user_id]['tipo']}
🏢 Piso: {user_states[user_id]['piso']}
🖥 Sistema: {user_states[user_id]['sistema']}

📝 Descripción:
{user_states[user_id]['descripcion']}
"""

        msg = await context.bot.send_message(chat_id=group_id, text=ticket_text)

        tickets[ticket_counter] = {
            "user_id": user_id,
            "message_id": msg.message_id,
            "status": "ABIERTO"
        }

        await update.message.reply_text(f"✅ Tu ticket #{ticket_counter} fue creado.")

        ticket_counter += 1
        del user_states[user_id]

# ==============================
# COMANDOS DESDE GRUPO
# ==============================

async def proceso(update: Update, context: ContextTypes.DEFAULT_TYPE):
    if not context.args:
        return

    ticket_id = int(context.args[0])

    if ticket_id not in tickets:
        await update.message.reply_text("Ticket no encontrado.")
        return

    tickets[ticket_id]["status"] = "EN PROCESO"

    user_id = tickets[ticket_id]["user_id"]

    # Mensaje privado al usuario
    await context.bot.send_message(
        chat_id=user_id,
        text=f"🛠 Tu ticket #{ticket_id} está ahora EN PROCESO."
    )

    # Mensaje en el grupo
    await update.message.reply_text(
        f"🛠 Ticket #{ticket_id} marcado EN PROCESO."
    )

async def cerrar(update: Update, context: ContextTypes.DEFAULT_TYPE):
    if not context.args:
        return

    ticket_id = int(context.args[0])

    if ticket_id not in tickets:
        await update.message.reply_text("Ticket no encontrado.")
        return

    user_id = tickets[ticket_id]["user_id"]

    await context.bot.send_message(
        chat_id=user_id,
        text=f"✅ Tu ticket #{ticket_id} fue RESUELTO."
    )

    await update.message.reply_text(f"🔒 Ticket #{ticket_id} cerrado.")

# ==============================
# INICIO
# ==============================

if __name__ == "__main__":
    TOKEN = os.getenv("BOT_TOKEN")
    GROUP_ID = os.getenv("GROUP_ID")

    if not TOKEN:
        raise ValueError("❌ BOT_TOKEN no configurado en Railway")

    if not GROUP_ID:
        raise ValueError("❌ GROUP_ID no configurado en Railway")

    app = ApplicationBuilder().token(TOKEN).build()

    app.bot_data["GROUP_ID"] = int(GROUP_ID)

    # PRIVADO
    app.add_handler(CommandHandler("start", start, filters=filters.ChatType.PRIVATE))
    app.add_handler(CallbackQueryHandler(button_handler))
    app.add_handler(
        MessageHandler(
            filters.TEXT & ~filters.COMMAND & filters.ChatType.PRIVATE,
            text_handler
        )
    )

    # GRUPO
    app.add_handler(CommandHandler("proceso", proceso, filters=filters.ChatType.GROUPS))
    app.add_handler(CommandHandler("cerrar", cerrar, filters=filters.ChatType.GROUPS))

    print("🚀 Bot SUNDDE iniciado correctamente")

    app.run_polling()
