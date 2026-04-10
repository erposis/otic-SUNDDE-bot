import os
import psycopg2
from datetime import datetime, timezone
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
# CONFIG
# ==============================

TIPOS_SOPORTE = ["Acceso", "Impresora", "Correo", "Internet", "WiFi", "Otro"]
PISOS = ["Sótano", "PB", "1", "2", "3", "4", "Cedros"]
SISTEMAS = ["PC", "Laptop", "Celular", "Impresora"]
PRIORIDADES = ["Alta", "Media", "Baja"]

user_states = {}

ADMIN_IDS = [int(x) for x in os.getenv("ADMIN_IDS", "").split(",") if x]
SOPORTE_IDS = [int(x) for x in os.getenv("SOPORTE_IDS", "").split(",") if x]

GROUP_ID = int(os.getenv("GROUP_ID", "0"))
TOKEN = os.getenv("BOT_TOKEN")

DASHBOARD_MESSAGE_ID = None

# ==============================
# TIME
# ==============================

def now_utc():
    return datetime.now(timezone.utc)

# ==============================
# DB
# ==============================

def get_connection():
    return psycopg2.connect(os.getenv("DATABASE_URL"))

# ==============================
# DASHBOARD
# ==============================

async def update_dashboard(context):
    conn = get_connection()
    cur = conn.cursor()

    cur.execute("SELECT estado, COUNT(*) FROM tickets GROUP BY estado")
    estados = dict(cur.fetchall())

    cur.execute("""
        SELECT asignado_a, COUNT(*)
        FROM tickets
        WHERE estado != 'CERRADO'
        GROUP BY asignado_a
    """)
    carga = cur.fetchall()

    cur.close()
    conn.close()

    total = sum(estados.values())

    text = f"""
📊 DASHBOARD OTIC

🎫 Total tickets: {total}
🟢 Abiertos: {estados.get('ABIERTO',0)}
🟡 En proceso: {estados.get('EN PROCESO',0)}
🔴 Cerrados: {estados.get('CERRADO',0)}

👨‍💻 Carga:
"""

    for tech, count in carga:
        text += f"\n- {tech}: {count}"

    global DASHBOARD_MESSAGE_ID

    if DASHBOARD_MESSAGE_ID:
        await context.bot.edit_message_text(
            chat_id=GROUP_ID,
            message_id=DASHBOARD_MESSAGE_ID,
            text=text
        )
    else:
        msg = await context.bot.send_message(chat_id=GROUP_ID, text=text)
        DASHBOARD_MESSAGE_ID = msg.message_id

# ==============================
# START
# ==============================

async def start(update: Update, context: ContextTypes.DEFAULT_TYPE):
    keyboard = [[InlineKeyboardButton("Crear Ticket", callback_data="crear_ticket")]]
    await update.message.reply_text("Sistema OTIC", reply_markup=InlineKeyboardMarkup(keyboard))

# ==============================
# BOTONES
# ==============================

async def button_handler(update: Update, context: ContextTypes.DEFAULT_TYPE):
    query = update.callback_query
    await query.answer()

    user_id = query.from_user.id

    if query.data == "crear_ticket":
        user_states[user_id] = {"step": "tipo"}
        keyboard = [[InlineKeyboardButton(t, callback_data=f"tipo_{t}")] for t in TIPOS_SOPORTE]
        await query.edit_message_text("Tipo:", reply_markup=InlineKeyboardMarkup(keyboard))

# ==============================
# CREAR TICKET
# ==============================

async def text_handler(update: Update, context: ContextTypes.DEFAULT_TYPE):
    user_id = update.message.from_user.id

    if user_id not in user_states:
        return

    data = user_states[user_id]
    descripcion = update.message.text
    now = now_utc()

    conn = get_connection()
    cur = conn.cursor()

    cur.execute("""
        INSERT INTO tickets (
            usuario_id, usuario_nombre, tipo, piso, sistema,
            descripcion, estado, prioridad,
            fecha_creacion, fecha_actualizacion
        )
        VALUES (%s,%s,%s,%s,%s,%s,'ABIERTO',%s,%s,%s)
        RETURNING id;
    """, (
        user_id,
        update.message.from_user.full_name,
        data["tipo"],
        data.get("piso",""),
        data.get("sistema",""),
        descripcion,
        data.get("prioridad","Media"),
        now,
        now
    ))

    ticket_id = cur.fetchone()[0]
    conn.commit()

    msg = await context.bot.send_message(
        chat_id=GROUP_ID,
        text=f"🆕 TICKET #{ticket_id}\nEstado: ABIERTO\n\n{descripcion}"
    )

    cur.execute("UPDATE tickets SET message_id=%s WHERE id=%s", (msg.message_id, ticket_id))
    conn.commit()

    cur.close()
    conn.close()

    del user_states[user_id]

    await update_dashboard(context)

    await update.message.reply_text(f"Ticket #{ticket_id} creado")

# ==============================
# MAIN
# ==============================

if __name__ == "__main__":
    app = ApplicationBuilder().token(TOKEN).build()

    app.add_handler(CommandHandler("start", start))
    app.add_handler(CallbackQueryHandler(button_handler))
    app.add_handler(MessageHandler(filters.TEXT & ~filters.COMMAND, text_handler))

    # 🔥 DASHBOARD AUTO REFRESH
    app.job_queue.run_repeating(update_dashboard, interval=60, first=10)

    print("BOT CON DASHBOARD ACTIVO")
    app.run_polling()
