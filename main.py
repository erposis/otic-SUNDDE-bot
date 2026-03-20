import os
from telegram import Update, InlineKeyboardButton, InlineKeyboardMarkup
from telegram.ext import ApplicationBuilder, CommandHandler, CallbackQueryHandler, MessageHandler, filters, ContextTypes

TOKEN = os.getenv("BOT_TOKEN")
GRUPO_ID = int(os.getenv("GROUP_ID"))

user_states = {}
ticket_counter = 1

async def start(update: Update, context: ContextTypes.DEFAULT_TYPE):
    keyboard = [[InlineKeyboardButton("Crear Ticket", callback_data="crear")]]
    await update.message.reply_text(
        "🔵 OTIC – Mesa de Ayuda",
        reply_markup=InlineKeyboardMarkup(keyboard)
    )

async def button_handler(update: Update, context: ContextTypes.DEFAULT_TYPE):
    global user_states
    query = update.callback_query
    await query.answer()

    if query.data == "crear":
        user_states[query.from_user.id] = {"step": "tipo"}
        keyboard = [
            [InlineKeyboardButton("Acceso", callback_data="Acceso")],
            [InlineKeyboardButton("Red", callback_data="Red")],
            [InlineKeyboardButton("Sistema", callback_data="Sistema")],
            [InlineKeyboardButton("Correo", callback_data="Correo")]
        ]
        await query.edit_message_text("Selecciona tipo de problema:",
                                      reply_markup=InlineKeyboardMarkup(keyboard))
    else:
        user_states[query.from_user.id]["tipo"] = query.data
        user_states[query.from_user.id]["step"] = "piso"
        await query.edit_message_text("¿En qué piso te encuentras?")

async def text_handler(update: Update, context: ContextTypes.DEFAULT_TYPE):
    global ticket_counter
    user_id = update.message.from_user.id

    if user_id not in user_states:
        await update.message.reply_text("Usa /start para iniciar un ticket.")
        return

    step = user_states[user_id]["step"]

    if step == "piso":
        user_states[user_id]["piso"] = update.message.text
        user_states[user_id]["step"] = "sistema"
        await update.message.reply_text("¿Qué sistema está afectado?")

    elif step == "sistema":
        user_states[user_id]["sistema"] = update.message.text
        user_states[user_id]["step"] = "descripcion"
        await update.message.reply_text("Describe el problema brevemente:")

    elif step == "descripcion":
        user_states[user_id]["descripcion"] = update.message.text

        ticket_text = f"""
🆕 TICKET #{ticket_counter}

👤 Usuario: {update.message.from_user.full_name}
🧩 Tipo: {user_states[user_id]['tipo']}
🏢 Piso: {user_states[user_id]['piso']}
🖥 Sistema: {user_states[user_id]['sistema']}

📝 Descripción:
{user_states[user_id]['descripcion']}
"""

        await context.bot.send_message(chat_id=GRUPO_ID, text=ticket_text)
        await update.message.reply_text(f"Tu ticket #{ticket_counter} fue creado.")

        ticket_counter += 1
        del user_states[user_id]

app = ApplicationBuilder().token(TOKEN).build()
app.add_handler(CommandHandler("start", start))
app.add_handler(CallbackQueryHandler(button_handler))
app.add_handler(MessageHandler(filters.TEXT & ~filters.COMMAND, text_handler))

app.run_polling()
