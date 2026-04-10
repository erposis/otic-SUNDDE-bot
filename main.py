import os
import psycopg2
from datetime import datetime, timezone, timedelta
from telegram import Update, InlineKeyboardButton, InlineKeyboardMarkup
from telegram.ext import (
    ApplicationBuilder,
    CommandHandler,
    CallbackQueryHandler,
    MessageHandler,
    ContextTypes,
    filters,
)
from telegram.error import BadRequest

# ==============================
# CONFIG
# ==============================

TIPOS_SOPORTE = ["Acceso", "Impresora", "Correo", "Internet", "WiFi", "Otro"]
PISOS = ["Sótano", "PB", "1", "2", "3", "4", "Cedros"]
SISTEMAS = ["PC", "Laptop", "Celular", "Central", "Impresora"]
PRIORIDADES = ["Alta", "Media", "Baja"]

user_states = {}

ADMIN_IDS = [int(x) for x in os.getenv("ADMIN_IDS", "").split(",") if x]
SOPORTE_IDS = [int(x) for x in os.getenv("SOPORTE_IDS", "").split(",") if x]

GROUP_ID = int(os.getenv("GROUP_ID", "0"))
TOKEN = os.getenv("BOT_TOKEN")

# ==============================
# TIME STANDARD (CRÍTICO)
# ==============================

def now_utc():
    return datetime.now(timezone.utc)

# ==============================
# DB
# ==============================

def get_connection():
    return psycopg2.connect(os.getenv("DATABASE_URL"))

def prioridad_icono(p):
    return {"Alta": "🔴", "Media": "🟡", "Baja": "🟢"}.get(p, "🟡")

def estado_icono(e):
    return {"ABIERTO": "🟢", "EN PROCESO": "🟡", "CERRADO": "🔴"}.get(e, "🟡")

# ==============================
# START
# ==============================

async def start(update: Update, context: ContextTypes.DEFAULT_TYPE):
    keyboard = [[InlineKeyboardButton("Crear Ticket", callback_data="crear_ticket")]]
    await update.message.reply_text(
        "🎫 Sistema de Soporte",
        reply_markup=InlineKeyboardMarkup(keyboard)
    )

# ==============================
# FLUJO CREACIÓN
# ==============================

async def button_handler(update: Update, context: ContextTypes.DEFAULT_TYPE):
    query = update.callback_query
    await query.answer()

    user_id = query.from_user.id

    if query.data == "crear_ticket":
        user_states[user_id] = {"step": "tipo"}
        keyboard = [[InlineKeyboardButton(t, callback_data=f"tipo_{t}")] for t in TIPOS_SOPORTE]
        await query.edit_message_text("Selecciona tipo:", reply_markup=InlineKeyboardMarkup(keyboard))
        return

    if query.data.startswith("tipo_"):
        user_states[user_id]["tipo"] = query.data.replace("tipo_", "")
        user_states[user_id]["step"] = "piso"
        keyboard = [[InlineKeyboardButton(p, callback_data=f"piso_{p}")] for p in PISOS]
        await query.edit_message_text("Selecciona piso:", reply_markup=InlineKeyboardMarkup(keyboard))
        return

    if query.data.startswith("piso_"):
        user_states[user_id]["piso"] = query.data.replace("piso_", "")
        user_states[user_id]["step"] = "sistema"
        keyboard = [[InlineKeyboardButton(s, callback_data=f"sistema_{s}")] for s in SISTEMAS]
        await query.edit_message_text("Selecciona sistema:", reply_markup=InlineKeyboardMarkup(keyboard))
        return

    if query.data.startswith("sistema_"):
        user_states[user_id]["sistema"] = query.data.replace("sistema_", "")
        user_states[user_id]["step"] = "prioridad"
        keyboard = [[InlineKeyboardButton(p, callback_data=f"prioridad_{p}")] for p in PRIORIDADES]
        await query.edit_message_text("Selecciona prioridad:", reply_markup=InlineKeyboardMarkup(keyboard))
        return

    if query.data.startswith("prioridad_"):
        user_states[user_id]["prioridad"] = query.data.replace("prioridad_", "")
        user_states[user_id]["step"] = "descripcion"
        await query.edit_message_text("Describe el problema:")
        return

# ==============================
# CREAR TICKET
# ==============================

async def text_handler(update: Update, context: ContextTypes.DEFAULT_TYPE):
    user_id = update.message.from_user.id

    if user_id not in user_states:
        return

    if user_states[user_id]["step"] != "descripcion":
        return

    data = user_states[user_id]
    descripcion = update.message.text
    now = now_utc()

    conn = get_connection()
    cur = conn.cursor()

    cur.execute("""
        INSERT INTO tickets (
            usuario_id, usuario_nombre, tipo, piso, sistema,
            descripcion, estado, asignado_a, prioridad,
            fecha_creacion, fecha_actualizacion
        )
        VALUES (%s,%s,%s,%s,%s,%s,'ABIERTO',NULL,%s,%s,%s)
        RETURNING id;
    """, (
        user_id,
        update.message.from_user.full_name,
        data["tipo"],
        data["piso"],
        data["sistema"],
        descripcion,
        data["prioridad"],
        now,
        now
    ))

    ticket_id = cur.fetchone()[0]
    conn.commit()

    msg = await context.bot.send_message(
    chat_id=GROUP_ID,
    text=f"""
🆕 TICKET #{ticket_id}
Prioridad: {prioridad_icono(data['prioridad'])} {data['prioridad']}
Estado: 🟢 ABIERTO
Creado: {now.strftime("%d/%m/%Y %H:%M")}

👤 Usuario: {update.message.from_user.full_name}
🧩 Tipo: {data['tipo']}
🏢 Piso: {data['piso']}
🖥 Sistema: {data['sistema']}

📝 Descripción:
{descripcion}
"""
)

    cur.execute("UPDATE tickets SET message_id=%s WHERE id=%s", (msg.message_id, ticket_id))
    conn.commit()

    cur.close()
    conn.close()

    del user_states[user_id]
    await update.message.reply_text(f"✅ Ticket #{ticket_id} creado")

# ==============================
# PROCESO (CONCURRENCIA REAL)
# ==============================

async def proceso(update: Update, context: ContextTypes.DEFAULT_TYPE):
    user_id = update.effective_user.id

    if user_id not in SOPORTE_IDS and user_id not in ADMIN_IDS:
        return await update.message.reply_text("⛔ Sin permisos")

    if not context.args:
        return await update.message.reply_text("Uso: /proceso <id>")

    ticket_id = int(context.args[0])

    conn = get_connection()
    cur = conn.cursor()

    cur.execute("""
        UPDATE tickets
        SET estado='EN PROCESO',
            asignado_a=%s,
            fecha_actualizacion=%s
        WHERE id=%s
        AND estado='ABIERTO'
        RETURNING id;
    """, (user_id, now_utc(), ticket_id))

    result = cur.fetchone()
    conn.commit()

    cur.close()
    conn.close()

    if result:
        await update.message.reply_text(f"✅ Ticket {ticket_id} tomado")
    else:
        await update.message.reply_text("❌ Ya fue tomado por otro técnico")

# ==============================
# CERRAR (PERMISOS REALES)
# ==============================

async def cerrar(update: Update, context: ContextTypes.DEFAULT_TYPE):
    user_id = update.effective_user.id

    if not context.args:
        return await update.message.reply_text("Uso: /cerrar <id>")

    ticket_id = int(context.args[0])

    conn = get_connection()
    cur = conn.cursor()

    cur.execute("SELECT asignado_a FROM tickets WHERE id=%s", (ticket_id,))
    row = cur.fetchone()

    if not row:
        return await update.message.reply_text("❌ No existe")

    assigned_to = row[0]

    if not (user_id in ADMIN_IDS or assigned_to == user_id):
        return await update.message.reply_text("⛔ No autorizado")

    cur.execute("""
        UPDATE tickets
        SET estado='CERRADO',
            closed_at=%s,
            closed_by=%s
        WHERE id=%s
        AND estado!='CERRADO'
        RETURNING id;
    """, (now_utc(), user_id, ticket_id))

    result = cur.fetchone()
    conn.commit()

    cur.close()
    conn.close()

    if result:
        await update.message.reply_text(f"✅ Ticket {ticket_id} cerrado")
    else:
        await update.message.reply_text("⚠️ Ya estaba cerrado")

# ==============================
# MAIN
# ==============================

if __name__ == "__main__":
    app = ApplicationBuilder().token(TOKEN).build()

    app.add_handler(CommandHandler("start", start))
    app.add_handler(CommandHandler("proceso", proceso))
    app.add_handler(CommandHandler("cerrar", cerrar))
    app.add_handler(CallbackQueryHandler(button_handler))
    app.add_handler(MessageHandler(filters.TEXT & ~filters.COMMAND, text_handler))

    print("🚀 BOT LISTO")
    app.run_polling(drop_pending_updates=True)
