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
from telegram.error import BadRequest

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

# ==============================
# DB
# ==============================

def get_connection():
    return psycopg2.connect(os.getenv("DATABASE_URL"))

def now_utc():
    return datetime.now(timezone.utc)

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
        "🎫 Sistema OTIC\nCrear ticket:",
        reply_markup=InlineKeyboardMarkup(keyboard)
    )

# ==============================
# CALLBACK FLOW (WIZARD)
# ==============================

async def button_handler(update: Update, context: ContextTypes.DEFAULT_TYPE):
    query = update.callback_query
    await query.answer()

    user_id = query.from_user.id
    data = query.data

    print("🔥 CALLBACK:", data)

    # ------------------
    # INICIO
    # ------------------
    if data == "crear_ticket":
        user_states[user_id] = {"step": "tipo"}

        keyboard = [
            [InlineKeyboardButton(t, callback_data=f"tipo_{t}")]
            for t in TIPOS_SOPORTE
        ]

        await query.edit_message_text(
            "🧩 Selecciona tipo de soporte:",
            reply_markup=InlineKeyboardMarkup(keyboard)
        )
        return

    # ------------------
    # TIPO
    # ------------------
    if data.startswith("tipo_"):
        user_states[user_id] = {
            "step": "piso",
            "tipo": data.replace("tipo_", "")
        }

        keyboard = [
            [InlineKeyboardButton(p, callback_data=f"piso_{p}")]
            for p in PISOS
        ]

        await query.edit_message_text(
            "🏢 Selecciona piso:",
            reply_markup=InlineKeyboardMarkup(keyboard)
        )
        return

    # ------------------
    # PISO
    # ------------------
    if data.startswith("piso_"):
        user_states[user_id]["piso"] = data.replace("piso_", "")
        user_states[user_id]["step"] = "sistema"

        keyboard = [
            [InlineKeyboardButton(s, callback_data=f"sistema_{s}")]
            for s in SISTEMAS
        ]

        await query.edit_message_text(
            "🖥 Selecciona sistema:",
            reply_markup=InlineKeyboardMarkup(keyboard)
        )
        return

    # ------------------
    # SISTEMA
    # ------------------
    if data.startswith("sistema_"):
        user_states[user_id]["sistema"] = data.replace("sistema_", "")
        user_states[user_id]["step"] = "prioridad"

        keyboard = [
            [InlineKeyboardButton(p, callback_data=f"prioridad_{p}")]
            for p in PRIORIDADES
        ]

        await query.edit_message_text(
            "⚡ Selecciona prioridad:",
            reply_markup=InlineKeyboardMarkup(keyboard)
        )
        return

    # ------------------
    # PRIORIDAD
    # ------------------
    if data.startswith("prioridad_"):
        user_states[user_id]["prioridad"] = data.replace("prioridad_", "")
        user_states[user_id]["step"] = "descripcion"

        await query.edit_message_text("📝 Escribe la descripción del problema:")
        return

# ==============================
# CREAR TICKET (TEXT)
# ==============================

async def text_handler(update: Update, context: ContextTypes.DEFAULT_TYPE):

    user_id = update.message.from_user.id
    state = user_states.get(user_id)

    # 🚨 PROTECCIÓN CRÍTICA
    if not state or state.get("step") != "descripcion":
        return

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
        state["tipo"],
        state["piso"],
        state["sistema"],
        descripcion,
        state["prioridad"],
        now,
        now
    ))

    ticket_id = cur.fetchone()[0]
    conn.commit()

    text = f"""
🆕 TICKET #{ticket_id}
Prioridad: {prioridad_icono(state['prioridad'])} {state['prioridad']}
Estado: 🟢 ABIERTO
Creado: {now.strftime("%d/%m/%Y %H:%M")}

👤 Usuario: {update.message.from_user.full_name}
🧩 Tipo: {state['tipo']}
🏢 Piso: {state['piso']}
🖥 Sistema: {state['sistema']}

📝 Descripción:
{descripcion}
"""

    msg = await context.bot.send_message(
        chat_id=GROUP_ID,
        text=text
    )

    cur.execute(
        "UPDATE tickets SET message_id=%s WHERE id=%s",
        (msg.message_id, ticket_id)
    )

    conn.commit()
    cur.close()
    conn.close()

    del user_states[user_id]

    await update.message.reply_text(f"✅ Ticket #{ticket_id} creado")

# ==============================
# MAIN
# ==============================

if __name__ == "__main__":

    app = ApplicationBuilder().token(TOKEN).build()

    app.add_handler(CommandHandler("start", start))
    app.add_handler(CallbackQueryHandler(button_handler))
    app.add_handler(MessageHandler(filters.TEXT & ~filters.COMMAND, text_handler))

    print("🚀 BOT OPERATIVO")

    app.run_polling(drop_pending_updates=True)
