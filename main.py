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
        minutos = 60  # Media y Baja

    return base_time + timedelta(minutes=minutos)

def estado_icono(e):
    return {"ABIERTO": "🟢", "EN PROCESO": "🟡", "CERRADO": "🔴"}.get(e, "🟡")

# =========================
# ID
# =========================

async def myid(update: Update, context: ContextTypes.DEFAULT_TYPE):
    await update.message.reply_text(f"ID: {update.effective_user.id}")
    
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

    conn = None
    try:
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
            uid, update.message.from_user.full_name,
            state["tipo"], state["piso"], state["sistema"],
            descripcion, state["prioridad"],
            now_time, now_time, sla_respuesta, sla_cierre
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
        msg = await context.bot.send_message(chat_id=GROUP_ID, text=text.strip())

        cur.execute("UPDATE tickets SET message_id=%s WHERE id=%s", (msg.message_id, ticket_id))
        conn.commit()
        del user_states[uid]
        await update.message.reply_text(f"✅ Ticket #{ticket_id} creado.")

    except Exception as e:
        print(f"❌ Error creando ticket: {e}")
        await update.message.reply_text("❌ Error al crear el ticket. Inténtalo de nuevo.")
    finally:
        if conn:
            conn.close()
    
# =========================
# CAMBIO DE ESTADO
# =========================

async def cambiar_estado(update: Update, context: ContextTypes.DEFAULT_TYPE, estado):
    if not context.args:
        await update.message.reply_text("⚠️ Usa: /proceso <ID> o /cerrar <ID>")
        return

    ticket_id = int(context.args[0])
    operador = update.effective_user.full_name
    operador_id = update.effective_user.id
    now_time = now_local()

    conn = get_connection()
    cur = conn.cursor()
    try:
        # 1. Obtener estado actual del ticket
        cur.execute("""
            SELECT asignado_a, message_id, tipo, piso, sistema,
                   descripcion, prioridad, usuario_nombre, usuario_id, sla_estado
            FROM tickets WHERE id=%s
        """, (ticket_id,))
        row = cur.fetchone()
        if not row:
            await update.message.reply_text("❌ Ticket no encontrado")
            return

        asignado, message_id, tipo, piso, sistema, descripcion, prioridad, usuario_nombre, usuario_id, sla_estado_actual = row

        # 2. Validar permisos
        if estado == "CERRADO":
            if operador_id not in ADMIN_IDS and asignado != operador:
                await update.message.reply_text("🔒 No autorizado para cerrar este ticket.")
                return

        # 3. Preparar datos para UPDATE
        if estado == "CERRADO":
            # Preservamos historial SLA, mantenemos técnico original, registramos quién cierra
            sla_nuevo = sla_estado_actual if sla_estado_actual not in [None, "STOPPED"] else "OK"
            asignado_a_nuevo = asignado
            cerrado_por_nuevo = operador
            
            cur.execute("""
                UPDATE tickets
                SET estado=%s, asignado_a=%s, fecha_actualizacion=%s, sla_estado=%s, cerrado_por=%s
                WHERE id=%s
            """, (estado, asignado_a_nuevo, now_time, sla_nuevo, cerrado_por_nuevo, ticket_id))
        else:
            sla_nuevo = "OK"
            asignado_a_nuevo = operador
            cerrado_por_nuevo = None
            
            cur.execute("""
                UPDATE tickets
                SET estado=%s, asignado_a=%s, fecha_actualizacion=%s, sla_estado=%s
                WHERE id=%s
            """, (estado, asignado_a_nuevo, now_time, sla_nuevo, ticket_id))

        conn.commit()

        # 4. Formatear mensaje (sin sangría para Telegram)
        cierre_info = f"\n🔒 Cerrado por: {cerrado_por_nuevo}" if estado == "CERRADO" else ""
        
        text = f"""
🆕 TICKET #{ticket_id}
Estado: {estado_icono(estado)} {estado}
Asignado: {asignado_a_nuevo}{cierre_info}
👤 Usuario: {usuario_nombre}
🧩 Tipo: {tipo}
🏢 Piso: {piso}
🖥 Sistema: {sistema}
📝 {descripcion}
"""
        # 5. Actualizar mensaje en grupo
        try:
            await context.bot.edit_message_text(chat_id=GROUP_ID, message_id=message_id, text=text.strip())
        except BadRequest:
            await context.bot.send_message(GROUP_ID, text=text.strip())

        # 6. Notificar al usuario y confirmar
        await context.bot.send_message(usuario_id, f"📢 Tu ticket #{ticket_id} está: {estado}")
        await update.message.reply_text(f"✅ Ticket #{ticket_id} -> {estado}")

    except Exception as e:
        # 🔍 Esto imprimirá el error real en Railway para que lo veamos
        print(f"❌ ERROR CRÍTICO en cambiar_estado (ID {ticket_id}): {type(e).__name__} - {e}")
        await update.message.reply_text("❌ Error al actualizar la BD. Revisa los logs de Railway.")
    finally:
        cur.close()
        conn.close()
    
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

# ================================
# FUNCION MONITOR SLA (CORREGIDA)
# ================================

async def monitor_sla(context: ContextTypes.DEFAULT_TYPE):
    print("🔥 MONITOR SLA EJECUTÁNDOSE")
    now_time = now_local()
    conn = get_connection()
    cur = conn.cursor()
    try:
        # 1️⃣ Marcar como BREACHED y devolver IDs de los que cambiaron
        cur.execute("""
            UPDATE tickets SET sla_estado = 'BREACHED'
            WHERE estado NOT IN ('CERRADO', 'EN PROCESO')
              AND sla_cierre_vence IS NOT NULL
              AND sla_cierre_vence < %s
              AND sla_estado != 'BREACHED'
            RETURNING id, prioridad, usuario_nombre
        """, (now_time,))
        breached = cur.fetchall()

        # 2️⃣ Marcar como WARNING y devolver IDs de los que cambiaron
        cur.execute("""
            UPDATE tickets SET sla_estado = 'WARNING'
            WHERE estado NOT IN ('CERRADO', 'EN PROCESO')
              AND sla_cierre_vence IS NOT NULL
              AND sla_cierre_vence BETWEEN %s AND %s
              AND sla_estado = 'OK'
            RETURNING id, prioridad, usuario_nombre
        """, (now_time, now_time + timedelta(minutes=10)))
        warning = cur.fetchall()

        conn.commit()

        # 3️⃣ Enviar alertas SOLO por los tickets que realmente cambiaron
        for tid, prio, user in breached:
            await context.bot.send_message(
                chat_id=GROUP_ID, 
                text=f"🔴 SLA VENCIDO - Ticket #{tid} | {user} | Prioridad: {prio}"
            )
            
        for tid, prio, user in warning:
            await context.bot.send_message(
                chat_id=GROUP_ID, 
                text=f"🟡 SLA en riesgo (<10min) - Ticket #{tid} | {user} | Prioridad: {prio}"
            )

    except Exception as e:
        print(f"❌ Error en monitor_sla: {e}")
    finally:
        cur.close()
        conn.close()

# =========================
# COMANDO /REPORTE
# =========================
async def reporte(update: Update, context: ContextTypes.DEFAULT_TYPE):
    if update.effective_user.id not in ADMIN_IDS + SOPORTE_IDS:
        return await update.message.reply_text("🔒 Sin permisos para ver reportes.")

    # Filtro de tiempo
    periodo = context.args[0].lower() if context.args else "mes"
    now = now_local()
    
    if periodo == "hoy":
        desde = now.replace(hour=0, minute=0, second=0, microsecond=0)
        titulo = "Hoy"
    elif periodo == "semana":
        desde = now - timedelta(days=7)
        titulo = "Últimos 7 días"
    else:
        desde = now - timedelta(days=30)
        titulo = "Últimos 30 días"

    conn = get_connection()
    cur = conn.cursor()
    try:
        # 1️⃣ Tickets por estado
        cur.execute("SELECT estado, COUNT(*) FROM tickets WHERE fecha_creacion >= %s GROUP BY estado", (desde,))
        estados = dict(cur.fetchall())

        # 2️⃣ Cumplimiento SLA (solo tickets cerrados en el periodo)
        cur.execute("""
            SELECT 
                COUNT(*) FILTER (WHERE sla_estado = 'OK') as ok,
                COUNT(*) FILTER (WHERE sla_estado IN ('WARNING', 'BREACHED')) as mal,
                COUNT(*) as total
            FROM tickets 
            WHERE estado = 'CERRADO' AND fecha_actualizacion >= %s
        """, (desde,))
        sla_ok, sla_mal, sla_total = cur.fetchone()
        sla_pct = (sla_ok / sla_total * 100) if sla_total > 0 else 100

        # 3️⃣ Tiempo promedio de resolución (horas)
        cur.execute("""
            SELECT AVG(EXTRACT(EPOCH FROM (fecha_actualizacion - fecha_creacion))/3600)
            FROM tickets 
            WHERE estado = 'CERRADO' AND fecha_actualizacion >= %s
        """, (desde,))
        avg_h = cur.fetchone()[0] or 0

        # 4️⃣ Top 3 agentes
        cur.execute("""
            SELECT asignado_a, COUNT(*) as c 
            FROM tickets 
            WHERE estado = 'CERRADO' AND asignado_a IS NOT NULL AND fecha_actualizacion >= %s
            GROUP BY asignado_a 
            ORDER BY c DESC 
            LIMIT 3
        """, (desde,))
        agentes = cur.fetchall()

        # Formato seguro para Python 3.11
        estados_txt = "\n".join([f"• {estado_icono(e)} {e}: {c}" for e, c in estados.items()]) if estados else "• Sin datos"
        agentes_txt = "\n".join([f"• {a}: {c} tickets" for a, c in agentes]) if agentes else "• Sin agentes activos"

        msg = f"""
📈 REPORTE DE SOPORTE OTIC
🗓️ Período: {titulo}

📦 ESTADOS:
{estados_txt}

✅ CUMPLIMIENTO SLA: {sla_pct:.1f}%
   ({sla_ok} OK / {sla_mal} incumplidos de {sla_total} cerrados)

⏱️ TIEMPO PROM. RESOLUCIÓN: {avg_h:.1f} horas

🏆 TOP AGENTES:
{agentes_txt}

💡 Usa: /reporte hoy | semana | mes
"""
        await update.message.reply_text(msg.strip())

    except Exception as e:
        print(f"❌ Error generando reporte: {e}")
        await update.message.reply_text("⚠️ Error al generar el reporte. Inténtalo de nuevo.")
    finally:
        cur.close()
        conn.close()

# =========================
# COMANDO /TABLERO
# =========================
async def tablero(update: Update, context: ContextTypes.DEFAULT_TYPE):
    if update.effective_user.id not in ADMIN_IDS + SOPORTE_IDS:
        return await update.message.reply_text("🔒 Sin permisos para ver el tablero.")

    conn = get_connection()
    cur = conn.cursor()
    try:
        cur.execute("""
            SELECT id, estado, prioridad, asignado_a, sla_estado, sla_cierre_vence
            FROM tickets
            WHERE estado IN ('ABIERTO', 'EN PROCESO')
            ORDER BY
                CASE prioridad WHEN 'Alta' THEN 1 WHEN 'Media' THEN 2 WHEN 'Baja' THEN 3 END,
                sla_cierre_vence ASC
        """)
        tickets = cur.fetchall()

        ahora = now_local().strftime("%H:%M")
        lineas = [
            "📋 TABLERO",
            f"🕒: {ahora}",
            ""
        ]

        if not tickets:
            lineas.append("✅ Nada Pendiente.")
        else:
            abiertos = [t for t in tickets if t[1] == 'ABIERTO']
            en_proceso = [t for t in tickets if t[1] == 'EN PROCESO']

            if abiertos:
                lineas.append("🟢 ABIERTOS:")
                for tid, _, prio, asig, sla, vence in abiertos:
                    sla_icon = {"BREACHED": "🔴", "WARNING": "🟡", "OK": "🟢"}.get(sla, "⚪")
                    vence_str = vence.strftime("%H:%M") if vence else "N/A"
                    lineas.append(f"  🎫 #{tid} | {prio} | {asig or 'S/A'} | {sla_icon} {vence_str}")
                lineas.append("")

            if en_proceso:
                lineas.append("🟡 EN PROCESO:")
                for tid, _, prio, asig, sla, vence in en_proceso:
                    sla_icon = {"BREACHED": "🔴", "WARNING": "🟡", "OK": "🟢"}.get(sla, "⚪")
                    vence_str = vence.strftime("%H:%M") if vence else "N/A"
                    lineas.append(f"  🎫 #{tid} | {prio} | {asig or 'S/A'} | {sla_icon} {vence_str}")
                lineas.append("")

        msg_text = "\n".join(lineas).strip()
        dashboard_id = os.getenv("DASHBOARD_MSG_ID")

        if dashboard_id:
            await context.bot.edit_message_text(chat_id=GROUP_ID, message_id=int(dashboard_id), text=msg_text)
            if update.effective_message:
                await update.message.reply_text("🔄 Tablero actualizado.")
        else:
            sent = await context.bot.send_message(chat_id=GROUP_ID, text=msg_text)
            await context.bot.pin_chat_message(chat_id=GROUP_ID, message_id=sent.message_id, disable_notification=True)
            await update.message.reply_text(
                "📌 Tablero creado y fijado.\n"
                "⚠️ Ve a Railway → Variables y agrega:\n"
                f"`DASHBOARD_MSG_ID` = `{sent.message_id}`\n"
                "Reinicia el bot para activar actualizaciones automáticas."
            )

    except Exception as e:
        print(f"❌ Error en tablero: {e}")
        if update.effective_message:
            await update.message.reply_text("⚠️ Error al generar el tablero.")
    finally:
        cur.close()
        conn.close()

# =========================
# ACTUALIZACIÓN AUTOMÁTICA (08:00 - 15:59)
# =========================
async def auto_tablero(context: ContextTypes.DEFAULT_TYPE):
    ahora = now_local()
    # Horario laboral: 08:00 a 15:59
    if not (8 <= ahora.hour < 16):
        return

    dashboard_id = os.getenv("DASHBOARD_MSG_ID")
    if not dashboard_id:
        return

    conn = get_connection()
    cur = conn.cursor()
    try:
        cur.execute("""
            SELECT id, estado, prioridad, asignado_a, sla_estado, sla_cierre_vence
            FROM tickets WHERE estado IN ('ABIERTO', 'EN PROCESO')
            ORDER BY CASE prioridad WHEN 'Alta' THEN 1 WHEN 'Media' THEN 2 WHEN 'Baja' THEN 3 END, sla_cierre_vence ASC
        """)
        tickets = cur.fetchall()

        lineas = ["📋 TABLERO", f"🕒: {ahora.strftime('%H:%M')}", ""]
        if not tickets:
            lineas.append("✅ Sin Tickets.")
        else:
            abiertos = [t for t in tickets if t[1] == 'ABIERTO']
            en_proceso = [t for t in tickets if t[1] == 'EN PROCESO']

            if abiertos:
                lineas.append("🟢 ABIERTOS:")
                for tid, _, prio, asig, sla, vence in abiertos:
                    sla_icon = {"BREACHED": "🔴", "WARNING": "🟡", "OK": "🟢"}.get(sla, "⚪")
                    vence_str = vence.strftime("%H:%M") if vence else "N/A"
                    lineas.append(f"  🎫 #{tid} | {prio} | {asig or 'S/A'} | {sla_icon} {vence_str}")
                lineas.append("")
            if en_proceso:
                lineas.append("🟡 EN PROCESO:")
                for tid, _, prio, asig, sla, vence in en_proceso:
                    sla_icon = {"BREACHED": "🔴", "WARNING": "🟡", "OK": "🟢"}.get(sla, "⚪")
                    vence_str = vence.strftime("%H:%M") if vence else "N/A"
                    lineas.append(f"  🎫 #{tid} | {prio} | {asig or 'S/A'} | {sla_icon} {vence_str}")
                lineas.append("")

        msg_text = "\n".join(lineas).strip()
        await context.bot.edit_message_text(chat_id=GROUP_ID, message_id=int(dashboard_id), text=msg_text)

    except BadRequest as e:
        # Si el mensaje fue borrado, lo logueamos y evitamos que el job falle
        if "Message to edit not found" in str(e):
            print("⚠️ Tablero borrado o desfijado. Ejecuta /tablero para recrearlo.")
        else:
            print(f"❌ BadRequest editando tablero: {e}")
    except Exception as e:
        print(f"❌ Error auto_tablero: {e}")
    finally:
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
    
    app.add_handler(CommandHandler("tablero", tablero))
    app.job_queue.run_repeating(auto_tablero, interval=900, first=15)  # 900s = 15 min
    app.add_handler(CommandHandler("id", myid))
    app.add_handler(CommandHandler("start", start))
    app.add_handler(CallbackQueryHandler(button_handler))
    app.add_handler(MessageHandler(filters.TEXT & ~filters.COMMAND, text_handler))
    app.add_handler(CommandHandler("proceso", proceso))
    app.add_handler(CommandHandler("cerrar", cerrar))
    app.add_handler(CommandHandler("reporte", reporte))

    print("BOT ACTIVO")

    app.run_polling(
    drop_pending_updates=True,
    close_loop=True
)
