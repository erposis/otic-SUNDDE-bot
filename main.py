import os
import psycopg2
from datetime import datetime
from telegram import Update
from telegram.ext import (
    ApplicationBuilder,
    CommandHandler,
    MessageHandler,
    ContextTypes,
    filters,
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
# COMANDO START (PRIVADO)
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

    conn = get_connection()
    cursor = conn.cursor()

    cursor.execute("""
        UPDATE tickets
        SET estado='EN PROCESO',
            fecha_actualizacion=%s
        WHERE id=%s
    """, (datetime.now(), ticket_id))

    conn.commit()
    cursor.close()
    conn.close()

    await update.message.reply_text(f"🛠 Ticket #{ticket_id} en proceso.")


# ==============================
# CERRAR
# ==============================

async def cerrar(update: Update, context: ContextTypes.DEFAULT_TYPE):

    if not context.args:
        await update.message.reply_text("Debes indicar el número del ticket.")
        return

    ticket_id = int(context.args[0])

    conn = get_connection()
    cursor = conn.cursor()

    cursor.execute("""
        UPDATE tickets
        SET estado='CERRADO',
            fecha_actualizacion=%s
        WHERE id=%s
    """, (datetime.now(), ticket_id))

    conn.commit()
    cursor.close()
    conn.close()

    await update.message.reply_text(f"🔒 Ticket #{ticket_id} cerrado.")


# ==============================
# MAIN
# ==============================

if __name__ == "__main__":

    TOKEN = os.getenv("BOT_TOKEN")

    if not TOKEN:
        raise ValueError("BOT_TOKEN no configurado")

    app = ApplicationBuilder().token(TOKEN).build()

    # PRIVADO
    app.add_handler(CommandHandler("start", start))
    app.add_handler(CommandHandler("ticket", ticket))

    # GRUPO
    app.add_handler(CommandHandler("proceso", proceso))
    app.add_handler(CommandHandler("cerrar", cerrar))

    print("🚀 BOT LISTO")

    app.run_polling(drop_pending_updates=True)
