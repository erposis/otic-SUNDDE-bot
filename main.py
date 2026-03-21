import os
import psycopg2
from datetime import datetime
from telegram import Update
from telegram.ext import (
    ApplicationBuilder,
    CommandHandler,
    ContextTypes,
)

# ==============================
# CONEXIÓN A POSTGRES
# ==============================

def get_connection():
    DATABASE_URL = os.getenv("DATABASE_URL")

    if not DATABASE_URL:
        raise ValueError("DATABASE_URL no configurada")

    return psycopg2.connect(DATABASE_URL)


# ==============================
# START
# ==============================

async def start(update: Update, context: ContextTypes.DEFAULT_TYPE):
    await update.message.reply_text("Usa /ticket para crear un ticket.")


# ==============================
# CREAR TICKET
# ==============================

async def ticket(update: Update, context: ContextTypes.DEFAULT_TYPE):

    user = update.message.from_user
    current_time = datetime.now()

    conn = get_connection()
    cursor = conn.cursor()

    cursor.execute("""
        INSERT INTO tickets (
            usuario_id,
            usuario_nombre,
            descripcion,
            estado,
            fecha_creacion,
            fecha_actualizacion
        ) VALUES (%s,%s,%s,%s,%s,%s)
        RETURNING id;
    """, (
        user.id,
        user.full_name,
        "Ticket generado manualmente",
        "ABIERTO",
        current_time,
        current_time
    ))

    ticket_id = cursor.fetchone()[0]

    conn.commit()
    cursor.close()
    conn.close()

    await update.message.reply_text(f"✅ Ticket #{ticket_id} creado.")


# ==============================
# PROCESO
# ==============================

async def proceso(update: Update, context: ContextTypes.DEFAULT_TYPE):

    if not context.args:
        await update.message.reply_text("Debes indicar el número del ticket.")
        return

    ticket_id = int(context.args[0])
    current_time = datetime.now()

    conn = get_connection()
    cursor = conn.cursor()

    cursor.execute("""
        UPDATE tickets
        SET estado='EN PROCESO',
            fecha_actualizacion=%s
        WHERE id=%s
        RETURNING usuario_id;
    """, (current_time, ticket_id))

    result = cursor.fetchone()

    conn.commit()
    cursor.close()
    conn.close()

    if not result:
        await update.message.reply_text("Ticket no encontrado.")
        return

    usuario_id = result[0]

    # Responder en grupo
    await update.message.reply_text(f"🛠 Ticket #{ticket_id} en proceso.")

    # Notificar al usuario por privado
    try:
        await context.bot.send_message(
            chat_id=usuario_id,
            text=f"Tu ticket #{ticket_id} ahora está EN PROCESO."
        )
    except:
        pass


# ==============================
# CERRAR
# ==============================

async def cerrar(update: Update, context: ContextTypes.DEFAULT_TYPE):

    if not context.args:
        await update.message.reply_text("Debes indicar el número del ticket.")
        return

    ticket_id = int(context.args[0])
    current_time = datetime.now()

    conn = get_connection()
    cursor = conn.cursor()

    cursor.execute("""
        UPDATE tickets
        SET estado='CERRADO',
            fecha_actualizacion=%s
        WHERE id=%s
        RETURNING usuario_id;
    """, (current_time, ticket_id))

    result = cursor.fetchone()

    conn.commit()
    cursor.close()
    conn.close()

    if not result:
        await update.message.reply_text("Ticket no encontrado.")
        return

    usuario_id = result[0]

    # Responder en grupo
    await update.message.reply_text(f"🔒 Ticket #{ticket_id} cerrado.")

    # Notificar al usuario por privado
    try:
        await context.bot.send_message(
            chat_id=usuario_id,
            text=f"Tu ticket #{ticket_id} fue CERRADO."
        )
    except:
        pass


# ==============================
# MAIN
# ==============================

if __name__ == "__main__":

    TOKEN = os.getenv("BOT_TOKEN")

    if not TOKEN:
        raise ValueError("BOT_TOKEN no configurado")

    app = ApplicationBuilder().token(TOKEN).build()

    app.add_handler(CommandHandler("start", start))
    app.add_handler(CommandHandler("ticket", ticket))
    app.add_handler(CommandHandler("proceso", proceso))
    app.add_handler(CommandHandler("cerrar", cerrar))

    print("🚀 BOT LISTO")

    app.run_polling(drop_pending_updates=True)
