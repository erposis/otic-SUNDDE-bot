import os
import logging
import psycopg2
from psycopg2 import pool
import pytz
from datetime import datetime, timedelta

from telegram import Update, InlineKeyboardButton, InlineKeyboardMarkup
from telegram.ext import (
    ApplicationBuilder, CommandHandler, CallbackQueryHandler,
    MessageHandler, ContextTypes, filters
)
from telegram.error import BadRequest

# =========================
# CONFIGURACIÓN Y LOGGING
# =========================

logging.basicConfig(format='%(asctime)s - %(name)s - %(levelname)s - %(message)s', level=logging.INFO)
logger = logging.getLogger(__name__)

# Parámetros del Sistema
TIPOS_SOPORTE = ["Acceso", "Impresora", "Correo", "Internet", "WiFi", "Otro"]
PISOS = ["Sótano", "PB", "1", "2", "3", "4", "Talento/Cedros", "Archivo Central", "Coord. Miranda", "Coord. Distrito"]
SISTEMAS = ["PC", "Laptop", "Celular", "Impresora"]
PRIORIDADES = ["Alta", "Media", "Baja"]

# Variables de Entorno
TOKEN = os.getenv("BOT_TOKEN")
GROUP_ID = int(os.getenv("GROUP_ID", 0))
DATABASE_URL = os.getenv("DATABASE_URL")
TZ = pytz.timezone(os.getenv("TZ", "America/Caracas"))
ID_FILE = ".dashboard_id"

ADMIN_IDS = [int(x) for x in os.getenv("ADMIN_IDS", "").split(",") if x]
SOPORTE_IDS = [int(x) for x in os.getenv("SOPORTE_IDS", "").split(",") if x]

user_states = {}

# =========================
# GESTIÓN DE BASE DE DATOS
# =========================

try:
    db_pool = psycopg2.pool.ThreadedConnectionPool(1, 20, dsn=DATABASE_URL)
    logger.info("✅ Pool de conexiones DB optimizado")
except Exception as e:
    logger.error(f"❌ Error de conexión DB: {e}")
    exit(1)

def get_db_conn(): return db_pool.getconn()
def release_db_conn(conn): db_pool.putconn(conn)

# =========================
# CONTROL DE HORARIOS
# =========================

def es_horario_laboral():
    ahora = datetime.now(TZ)
    hora_min = ahora.hour * 100 + ahora.minute
    
    # Rango mañana: 08:00 - 11:49
    # Rango tarde: 13:00 - 15:50
    if (800 <= hora_min <= 1149) or (1300 <= hora_min <= 1550):
        return True, ""
    
    if 1150 <= hora_min <= 1259:
        return False, "⏸️ Estamos en horario de almuerzo (11:50 AM - 01:00 PM). Por favor, intenta más tarde."
    
    return False, "🕒 El horario de atención es de 08:00 AM a 03:50 PM. ¡Te esperamos mañana!"

# =========================
# UTILIDADES DE FORMATO
# =========================

def now_local(): return datetime.now(TZ)
def fmt_12h(dt): return dt.astimezone(TZ).strftime("%I:%M") if dt else "N/A"
def prioridad_icono(p): return {"Alta": "🔴", "Media": "🟡", "Baja": "🟢"}.get(p, "⚪")
def estado_icono(e): return {"ABIERTO": "🟢", "EN PROCESO": "🟡", "CERRADO": "🔴"}.get(e, "⚪")
def sla_icono(s): return {"BREACHED": "❌", "WARNING": "⚠️", "OK": "✅"}.get(s, "⚪")

# =========================
# PERSISTENCIA DE ID DASHBOARD
# =========================

def save_dashboard_id(msg_id):
    with open(ID_FILE, "w") as f: f.write(str(msg_id))

def get_dashboard_id():
    env_id = os.getenv("DASHBOARD_MSG_ID")
    if env_id: return env_id
    if os.path.exists(ID_FILE):
        with open(ID_FILE, "r") as f: return f.read().strip()
    return None

# =========================
# LÓGICA DE TICKETS
# =========================

async def start(update: Update, context: ContextTypes.DEFAULT_TYPE):
    abierto, msg = es_horario_laboral()
    if not abierto:
        return await update.message.reply_text(msg)
        
    kb = [[InlineKeyboardButton("🎫 Crear Ticket", callback_data="crear_ticket")]]
    await update.message.reply_text("Soporte OTIC v2.2\nPresione para iniciar.", reply_markup=InlineKeyboardMarkup(kb))

async def button_handler(update: Update, context: ContextTypes.DEFAULT_TYPE):
    q = update.callback_query
    uid, data = q.from_user.id, q.data
    await q.answer()

    abierto, msg = es_horario_laboral()
    if not abierto and data == "crear_ticket":
        return await q.edit_message_text(msg)

    if data == "crear_ticket":
        user_states[uid] = {"step": "tipo"}
        kb = [[InlineKeyboardButton(t, callback_data=f"t_{t}")] for t in TIPOS_SOPORTE]
        await q.edit_message_text("Selecciona Tipo:", reply_markup=InlineKeyboardMarkup(kb))
    elif data.startswith("t_"):
        user_states[uid].update({"tipo": data[2:], "step": "piso"})
        kb = [[InlineKeyboardButton(p, callback_data=f"p_{p}")] for p in PISOS]
        await q.edit_message_text("Selecciona Piso:", reply_markup=InlineKeyboardMarkup(kb))
    elif data.startswith("p_"):
        user_states[uid].update({"piso": data[2:], "step": "sistema"})
        kb = [[InlineKeyboardButton(s, callback_data=f"s_{s}")] for s in SISTEMAS]
        await q.edit_message_text("Selecciona Equipo:", reply_markup=InlineKeyboardMarkup(kb))
    elif data.startswith("s_"):
        user_states[uid].update({"sistema": data[2:], "step": "prioridad"})
        kb = [[InlineKeyboardButton(p, callback_data=f"r_{p}")] for p in PRIORIDADES]
        await q.edit_message_text("Prioridad:", reply_markup=InlineKeyboardMarkup(kb))
    elif data.startswith("r_"):
        user_states[uid].update({"prioridad": data[2:], "step": "desc"})
        await q.edit_message_text("Escribe la descripción del problema:")

async def text_handler(update: Update, context: ContextTypes.DEFAULT_TYPE):
    uid = update.effective_user.id
    state = user_states.get(uid)
    if not state or state.get("step") != "desc": return

    abierto, msg = es_horario_laboral()
    if not abierto:
        del user_states[uid]
        return await update.message.reply_text(msg)

    desc = update.message.text
    now = now_local()
    vence = now + timedelta(minutes=(30 if state["prioridad"]=="Alta" else 60))
    
    conn = get_db_conn()
    try:
        cur = conn.cursor()
        cur.execute("""
            INSERT INTO tickets (usuario_id, usuario_nombre, tipo, piso, sistema, descripcion, prioridad, sla_cierre_vence, fecha_creacion, estado, sla_estado)
            VALUES (%s,%s,%s,%s,%s,%s,%s,%s,%s,'ABIERTO','OK') RETURNING id
        """, (uid, update.effective_user.full_name, state["tipo"], state["piso"], state["sistema"], desc, state["prioridad"], vence, now))
        tid = cur.fetchone()[0]
        conn.commit()
        
        txt = f"🆕 **TICKET #{tid}**\nPrioridad: {prioridad_icono(state['prioridad'])} {state['prioridad']}\nUsuario: {update.effective_user.full_name}\nFalla: {state['tipo']} - {state['piso']}\n🕒 Creado: {fmt_12h(now)}\n📝 {desc}"
        msg_sent = await context.bot.send_message(GROUP_ID, txt, parse_mode="Markdown")
        
        cur.execute("UPDATE tickets SET message_id=%s WHERE id=%s", (msg_sent.message_id, tid))
        conn.commit()
        await update.message.reply_text(f"✅ Ticket #{tid} creado con éxito.")
        del user_states[uid]
    finally: release_db_conn(conn)

# =========================
# TABLERO Y REPORTES
# =========================

async def generar_tablero_texto():
    conn = get_db_conn()
    try:
        cur = conn.cursor()
        cur.execute("""
            SELECT id, estado, prioridad, asignado_a, sla_estado, sla_cierre_vence 
            FROM tickets WHERE estado != 'CERRADO' 
            ORDER BY CASE prioridad WHEN 'Alta' THEN 1 WHEN 'Media' THEN 2 ELSE 3 END, sla_cierre_vence ASC
        """)
        rows = cur.fetchall()
        txt = f"📋 **TABLERO OTIC**\n🕒 Act: {now_local().strftime('%I:%M')}\n\n"
        if not rows: txt += "✅ No hay tickets pendientes."
        else:
            for r in rows:
                txt += f"#{r[0]} | {estado_icono(r[1])} | {prioridad_icono(r[2])} | {r[3] or 'S/A'} | {sla_icono(r[4])} {fmt_12h(r[5])}\n"
        return txt
    finally: release_db_conn(conn)

async def tablero(update: Update, context: ContextTypes.DEFAULT_TYPE):
    if update.effective_user.id not in ADMIN_IDS + SOPORTE_IDS: return
    txt = await generar_tablero_texto()
    sent = await context.bot.send_message(GROUP_ID, txt, parse_mode="Markdown")
    await context.bot.pin_chat_message(GROUP_ID, sent.message_id)
    save_dashboard_id(sent.message_id)
    await update.message.reply_text(f"📌 Tablero ID: {sent.message_id}")

async def auto_tablero(context: ContextTypes.DEFAULT_TYPE):
    # El tablero solo se actualiza en horario laboral
    abierto, _ = es_horario_laboral()
    if not abierto: return

    msg_id = get_dashboard_id()
    if not msg_id: return
    txt = await generar_tablero_texto()
    try: await context.bot.edit_message_text(txt, GROUP_ID, int(msg_id), parse_mode="Markdown")
    except Exception: pass

# =========================
# MONITOR SLA
# =========================

async def monitor_sla(context: ContextTypes.DEFAULT_TYPE):
    # El SLA también se detiene fuera de horario para no enviar alertas en la madrugada
    abierto, _ = es_horario_laboral()
    if not abierto: return

    now = now_local()
    conn = get_db_conn()
    try:
        cur = conn.cursor()
        cur.execute("""
            UPDATE tickets SET sla_estado = 'BREACHED'
            WHERE estado NOT IN ('CERRADO', 'EN PROCESO') AND sla_cierre_vence < %s AND sla_estado != 'BREACHED'
            RETURNING id, usuario_nombre
        """, (now,))
        for r in cur.fetchall():
            await context.bot.send_message(GROUP_ID, f"🚨 **SLA INCUMPLIDO**: Ticket #{r[0]} ({r[1]})")
        conn.commit()
    finally: release_db_conn(conn)

# =========================
# COMANDOS ADMIN
# =========================

async def cmd_estado(update: Update, context: ContextTypes.DEFAULT_TYPE, nuevo):
    if update.effective_user.id not in SOPORTE_IDS + ADMIN_IDS or not context.args: return
    tid = int(context.args[0])
    op = update.effective_user.full_name
    conn = get_db_conn()
    try:
        cur = conn.cursor()
        cur.execute("UPDATE tickets SET estado=%s, asignado_a=%s, fecha_actualizacion=%s WHERE id=%s", (nuevo, op, now_local(), tid))
        conn.commit()
        await update.message.reply_text(f"✅ Ticket #{tid} -> {nuevo}")
        await auto_tablero(context)
    finally: release_db_conn(conn)

# =========================
# MAIN
# =========================

if __name__ == "__main__":
    app = ApplicationBuilder().token(TOKEN).build()
    
    app.job_queue.run_repeating(monitor_sla, interval=60, first=10)
    app.job_queue.run_repeating(auto_tablero, interval=300, first=15)
    
    app.add_handler(CommandHandler("start", start))
    app.add_handler(CommandHandler("tablero", tablero))
    app.add_handler(CommandHandler("proceso", lambda u,c: cmd_estado(u,c,"EN PROCESO")))
    app.add_handler(CommandHandler("cerrar", lambda u,c: cmd_estado(u,c,"CERRADO")))
    
    app.add_handler(CallbackQueryHandler(button_handler))
    app.add_handler(MessageHandler(filters.TEXT & ~filters.COMMAND, text_handler))
    
    logger.info("🤖 Bot OTIC v2.2 - Control de Horario Activo")
    app.run_polling(drop_pending_updates=True)
