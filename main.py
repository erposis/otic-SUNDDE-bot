import os
import psycopg2
import pytz
from datetime import datetime
from datetime import timedelta

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

# =========================
# CONFIGURACIÓN
# =========================

TIPOS_SOPORTE = ["Acceso", "Impresora", "Correo", "Internet", "WiFi", "Otro"]
PISOS = ["Sótano", "PB", "1", "2", "3", "4", "Cedros"]
SISTEMAS = ["PC", "Laptop", "Celular", "Impresora"]
PRIORIDADES = ["Alta", "Media", "Baja"]

user_states = {}

ADMIN_IDS = [int(x) for x in os.getenv("ADMIN_IDS", "").split(",") if x]
SOPORTE_IDS = [int(x) for x in os.getenv("SOPORTE_IDS", "").split(",") if x]

GROUP_ID = int(os.getenv("GROUP_ID"))
TOKEN = os.getenv("BOT_TOKEN")

# =========================
# ⏱️ HORA LOCAL (CARACAS)
# =========================

TZ = pytz.timezone("America/Caracas")

def now_local():
    return datetime.now(TZ)

# =========================
# DB
# =========================

def get_connection():
    return psycopg2.connect(os.getenv("DATABASE_URL"))

def prioridad_icono(p):
    return {"Alta": "🔴", "Media": "🟡", "Baja": "🟢"}.get(p, "🟡")

def calcular_sla(prioridad, base_time):
    if prioridad == "Alta":
        minutos = 30
    else:
        minutos = 120  # Media y Baja

    return base_time + timedelta(minutes=minutos)

def estado_icono(e):
    return {"ABIERTO": "🟢", "EN PROCESO": "🟡", "CERRADO": "🔴"}.get(e, "🟡")

# =========================
# START
# =========================

async def start(update: Update, context: ContextTypes.DEFAULT_TYPE):
    kb = [[InlineKeyboardButton("Crear Ticket", callback_data="crear_ticket")]]
    await update.message.reply_text(
        "🎫 Sistema de Soporte OTIC",
        reply_markup=InlineKeyboardMarkup(kb)
    )

# =========================
# FLUJO BOTONES
# =========================

async def button_handler(update: Update, context: ContextTypes.DEFAULT_TYPE):

    q = update.callback_query
    await q.answer()

    uid = q.from_user.id
    data = q.data

    if data == "crear_ticket":
        user_states[uid] = {"step": "tipo"}
        kb = [[InlineKeyboardButton(t, callback_data=f"tipo_{t}")] for t in TIPOS_SOPORTE]
        await q.edit_message_text("Selecciona tipo:", reply_markup=InlineKeyboardMarkup(kb))
        return

    if data.startswith("tipo_"):
        user_states[uid]["tipo"] = data.replace("tipo_", "")
        user_states[uid]["step"] = "piso"
        kb = [[InlineKeyboardButton(p, callback_data=f"piso_{p}")] for p in PISOS]
        await q.edit_message_text("Selecciona piso:", reply_markup=InlineKeyboardMarkup(kb))
        return

    if data.startswith("piso_"):
        user_states[uid]["piso"] = data.replace("piso_", "")
        user_states[uid]["step"] = "sistema"
        kb = [[InlineKeyboardButton(s, callback_data=f"sistema_{s}")] for s in SISTEMAS]
        await q.edit_message_text("Selecciona sistema:", reply_markup=InlineKeyboardMarkup(kb))
        return

    if data.startswith("sistema_"):
        user_states[uid]["sistema"] = data.replace("sistema_", "")
        user_states[uid]["step"] = "prioridad"
        kb = [[InlineKeyboardButton(p, callback_data=f"prioridad_{p}")] for p in PRIORIDADES]
        await q.edit_message_text("Selecciona prioridad:", reply_markup=InlineKeyboardMarkup(kb))
        return

    if data.startswith("prioridad_"):
        user_states[uid]["prioridad"] = data.replace("prioridad_", "")
        user_states[uid]["step"] = "descripcion"
        await q.edit_message_text("Escribe la descripción del problema:")
        return

# =========================
# CREAR TICKET
# =========================

async def text_handler(update: Update, context: ContextTypes.DEFAULT_TYPE):

    uid = update.message.from_user.id
    state = user_states.get(uid)

    if not state or state.get("step") != "descripcion":
        return

    descripcion = update.message.text
    now_time = now_local()

    sla_respuesta = calcular_sla(state["prioridad"], now_time)
    sla_cierre = calcular_sla(state["prioridad"], now_time)

    conn = get_connection()
    cur = conn.cursor()

    cur.execute("""
        INSERT INTO tickets (
            usuario_id, usuario_nombre, tipo, piso, sistema,
            descripcion, estado, asignado_a, prioridad,
            fecha_creacion, fecha_actualizacion,
            sla_respuesta_vence, sla_cierre_vence, sla_estado
        )
        VALUES (%s,%s,%s,%s,%s,%s,'ABIERTO',NULL,%s,%s,%s,%s,%s,'OK')
        RETURNING id;
    """, (
        uid,
        update.message.from_user.full_name,
        state["tipo"],
        state["piso"],
        state["sistema"],
        descripcion,
        state["prioridad"],
        now_time,
        now_time,
        sla_respuesta,
        sla_cierre
    ))

    ticket_id = cur.fetchone()[0]
    conn.commit()

    text = f"""
🆕 TICKET #{ticket_id}
Prioridad: {prioridad_icono(state['prioridad'])} {state['prioridad']}
Estado: 🟢 ABIERTO
Creado: {now_time.strftime("%d/%m/%Y %H:%M")}

👤 Usuario: {update.message.from_user.full_name}
🧩 Tipo: {state['tipo']}
🏢 Piso: {state['piso']}
🖥 Sistema: {state['sistema']}

📝 Descripción:
{descripcion}
"""

    msg = await context.bot.send_message(chat_id=GROUP_ID, text=text)

    cur.execute(
        "UPDATE tickets SET message_id=%s WHERE id=%s",
        (msg.message_id, ticket_id)
    )

    conn.commit()
    cur.close()
    conn.close()

    del user_states[uid]

    await update.message.reply_text(f"Ticket #{ticket_id} creado.")
    
# =========================
# CAMBIO DE ESTADO
# =========================

async def cambiar_estado(update: Update, context: ContextTypes.DEFAULT_TYPE, estado):

    if not context.args:
        await update.message.reply_text("Usa ID del ticket.")
        return

    ticket_id = int(context.args[0])
    operador = update.effective_user.full_name
    operador_id = update.effective_user.id
    now_time = now_local()

    conn = get_connection()
    cur = conn.cursor()

    cur.execute("""
        SELECT asignado_a, message_id, tipo, piso, sistema,
               descripcion, prioridad, usuario_nombre, usuario_id
        FROM tickets
        WHERE id=%s
    """, (ticket_id,))

    row = cur.fetchone()

    if not row:
        await update.message.reply_text("Ticket no encontrado")
        return

    asignado, message_id, tipo, piso, sistema, descripcion, prioridad, usuario_nombre, usuario_id = row

    if estado == "CERRADO":
        if operador_id not in ADMIN_IDS and asignado != operador:
            await update.message.reply_text("No autorizado para cerrar")
            return

    cur.execute("""
        UPDATE tickets
        SET estado=%s,
            asignado_a=%s,
            fecha_actualizacion=%s
        WHERE id=%s
    """, (estado, operador, now_time, ticket_id))

    conn.commit()

    text = f"""
🆕 TICKET #{ticket_id}
Estado: {estado_icono(estado)} {estado}
Asignado: {operador}

👤 Usuario: {usuario_nombre}
🧩 Tipo: {tipo}
🏢 Piso: {piso}
🖥 Sistema: {sistema}

📝 Descripción:
{descripcion}
"""

    try:
        await context.bot.edit_message_text(
            chat_id=GROUP_ID,
            message_id=message_id,
            text=text
        )
    except BadRequest:
        await context.bot.send_message(GROUP_ID, text)

    await context.bot.send_message(usuario_id, f"Tu ticket #{ticket_id} está: {estado}")
    await update.message.reply_text("Estado actualizado.")

# =========================
# COMANDOS
# =========================

async def proceso(update: Update, context: ContextTypes.DEFAULT_TYPE):
    if update.effective_user.id not in SOPORTE_IDS + ADMIN_IDS:
        return await update.message.reply_text("Sin permisos")
    await cambiar_estado(update, context, "EN PROCESO")


async def cerrar(update: Update, context: ContextTypes.DEFAULT_TYPE):
    if update.effective_user.id not in SOPORTE_IDS + ADMIN_IDS:
        return await update.message.reply_text("Sin permisos")
    await cambiar_estado(update, context, "CERRADO")

# =========================
# FUNCION MONITOR SLA
# =========================

async def monitor_sla(context: ContextTypes.DEFAULT_TYPE):
    
    print("🔥 MONITOR SLA EJECUTÁNDOSE")
    
    now_time = now_local()

    conn = get_connection()
    cur = conn.cursor()

    cur.execute("SELECT COUNT(*) FROM tickets WHERE estado != 'CERRADO'")
print("TICKETS ABIERTOS:", cur.fetchone()[0])

    cur.execute("""
    SELECT COUNT(*) FROM tickets
    WHERE estado != 'CERRADO'
    AND sla_cierre_vence < %s
    """, (now_time,))
    print("SLA VENCIDOS:", cur.fetchone()[0])

    # 🔴 SLA VENCIDO
    cur.execute("""
        UPDATE tickets
        SET sla_estado = 'BREACHED'
        WHERE estado != 'CERRADO'
        AND sla_cierre_vence IS NOT NULL
        AND sla_cierre_vence < %s
        AND sla_estado != 'BREACHED'
    """, (now_time,))

    # 🟡 SLA EN RIESGO (faltan <10 min)
    cur.execute("""
        UPDATE tickets
        SET sla_estado = 'WARNING'
        WHERE estado != 'CERRADO'
        AND sla_cierre_vence IS NOT NULL
        AND sla_cierre_vence BETWEEN %s AND %s
        AND sla_estado = 'OK'
    """, (now_time, now_time + timedelta(minutes=10)))

    conn.commit()
    cur.close()
    conn.close()

# =========================
# MAIN
# =========================

if __name__ == "__main__":

    app = ApplicationBuilder().token(TOKEN).build()
    
    print("JOB QUEUE:", app.job_queue)
    
    job_queue = app.job_queue
    job_queue.run_repeating(monitor_sla, interval=60, first=10)

    app.add_handler(CommandHandler("start", start))
    app.add_handler(CallbackQueryHandler(button_handler))
    app.add_handler(MessageHandler(filters.TEXT & ~filters.COMMAND, text_handler))
    app.add_handler(CommandHandler("proceso", proceso))
    app.add_handler(CommandHandler("cerrar", cerrar))

    print("BOT ACTIVO")

    app.run_polling(drop_pending_updates=True)
