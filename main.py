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

user_states = {}
ticket_counter = 1


# ==============================
# COMANDO START
# ==============================

async def start(update: Update, context: ContextTypes.DEFAULT_TYPE):
    keyboard = [[InlineKeyboardButton("Crear Ticket", callback_data="crear")]]
    await update.message.reply_text(
        "🔵 OTIC – Mesa de Ayuda\n\nPresiona el botón para crear un ticket.",
        reply_markup=InlineKeyboardMarkup(keyboard)
    )


# ==============================
# MANEJO DE BOTONES
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
            [InlineKeyboardButton("Correo", callback_data="Correo")]
        ]

        await context.bot.send_message(
            chat_id=update.effective_chat.id,
            text="🔵 OTIC – Mesa de Ayuda\n\nSelecciona tipo de problema:",
            reply_markup=InlineKeyboardMarkup(keyboard)
        )
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

        group_id = context.application.bot_data["GROUP_ID"]

        ticket_text = f"""
🆕 TICKET #{ticket_counter}

👤 Usuario: {update.message.from_user.full_name}
🧩 Tipo: {user_states[user_id]['tipo']}
🏢 Piso: {user_states[user_id]['piso']}
🖥 Sistema: {user_states[user_id]['sistema']}

📝 Descripción:
{user_states[user_id]['descripcion']}
"""

        await context.bot.send_message(chat_id=group_id, text=ticket_text)
        await update.message.reply_text(f"✅ Tu ticket #{ticket_counter} fue creado.")

        ticket_counter += 1
        del user_states[user_id]

# ==============================
# INICIO SEGURO (ANTI-CRASH)
# ==============================

if __name__ == "__main__":
    TOKEN = os.getenv("BOT_TOKEN")
    GROUP_ID = os.getenv("GROUP_ID")

    if not TOKEN:
        raise ValueError("❌ BOT_TOKEN no configurado en Railway")

    if not GROUP_ID:
        raise ValueError("❌ GROUP_ID no configurado en Railway")

    app = ApplicationBuilder().token(TOKEN).build()

    # Guardamos el GROUP_ID de forma segura
    app.bot_data["GROUP_ID"] = int(GROUP_ID)

    app.add_handler(CommandHandler("start", start))
    app.add_handler(CallbackQueryHandler(button_handler))
    app.add_handler(MessageHandler(filters.TEXT & ~filters.COMMAND, text_handler))

    print("🚀 Bot OTIC iniciado correctamente")

    app.run_polling()
