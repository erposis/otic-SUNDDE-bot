import os
import psycopg2
from datetime import datetime
from telegram import (
    Update,
    InlineKeyboardButton,
    InlineKeyboardMarkup
)
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
# CONFIGURACIÓN
# ==============================

TIPOS_SOPORTE = ["Acceso", "Impresora", "Correo", "Internet", "WiFi", "Otro"]
PISOS = ["Sótano", "PB", "1", "2", "3", "4"]
SISTEMAS = [
    "PC", "Laptop", "Celular", "Central", "Impresora",
    "SO Windows", "MS Office", "LibreOffice", "Carp. Compartida",
    "Videobeam", "RUPDAE", "DENUNCIAS", "ASISTENCIA"
]
PRIORIDADES = ["Alta", "Media", "Baja"]

user_states = {}

# ==============================
# PERMISOS POR VARIABLES
# ==============================

ADMIN_IDS = [int(x) for x in os.getenv("ADMIN_IDS", "").split(",") if x]
SOPORTE_IDS = [int(x) for x in os.getenv("SOPORTE_IDS", "").split(",") if x]

# ==============================
# DB
# ==============================

def get_connection():
    DATABASE_URL = os.getenv("DATABASE_URL")
    if not DATABASE_URL:
        raise ValueError("DATABASE_URL no configurada")
    return psycopg2.connect(DATABASE_URL)

def prioridad_icono(prioridad):
    return {
        "Alta": "🔴",
        "Media": "🟡",
        "Baja": "🟢"
    }.get(prioridad, "🟡")

def estado_icono(estado):
    return {
        "ABIERTO": "🟢",
        "EN PROCESO": "🟡",
        "CERRADO": "🔴"
    }.get(estado, "🟡")

# ==============================
# START
# ==============================

async def start(update: Update, context: ContextTypes.DEFAULT_TYPE):
    keyboard = [[InlineKeyboardButton("Crear Ticket", callback_data="crear_ticket")]]
    await update.message.reply_text(
        "🎫 Soporte OTIC\n\nPresiona para crear un ticket.",
        reply_markup=InlineKeyboardMarkup(keyboard)
    )

# ==============================
# BOTONES
# ==============================

async def button_handler(update: Update, context: ContextTypes.DEFAULT_TYPE):

    query = update.callback_query
    await query.answer()
    user_id = query.from_user.id

    if query.data == "crear_ticket":
        user_states[user_id] = {"step": "tipo"}
        keyboard = [[InlineKeyboardButton(t, callback_data=f"tipo_{t}")]
                    for t in TIPOS_SOPORTE]
        await query.edit_message_text(
            "Selecciona el tipo de soporte:",
            reply_markup=InlineKeyboardMarkup(keyboard)
        )
        return

    if query.data.startswith("tipo_"):
        user_states[user_id]["tipo"] = query.data.replace("tipo_", "")
        user_states[user_id]["step"] = "piso"
        keyboard = [[InlineKeyboardButton(p, callback_data=f"piso_{p}")]
                    for p in PISOS]
        await query.edit_message_text(
            "Selecciona el piso:",
            reply_markup=InlineKeyboardMarkup(keyboard)
        )
        return

    if query.data.startswith("piso_"):
        user_states[user_id]["piso"] = query.data.replace("piso_", "")
        user_states[user_id]["step"] = "sistema"
        keyboard = [[InlineKeyboardButton(s, callback_data=f"sistema_{s}")]
                    for s in SISTEMAS]
        await query.edit_message_text(
            "Selecciona el sistema:",
            reply_markup=InlineKeyboardMarkup(keyboard)
        )
        return

    if query.data.startswith("sistema_"):
        user_states[user_id]["sistema"] = query.data.replace("sistema_", "")
        user_states[user_id]["step"] = "prioridad"
        keyboard = [[InlineKeyboardButton(p, callback_data=f"prioridad_{p}")]
                    for p in PRIORIDADES]
        await query.edit_message_text(
            "Selecciona la prioridad:",
            reply_markup=InlineKeyboardMarkup(keyboard)
        )
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
        await update.message.reply_text("Usa /start para iniciar.")
        return

    if user_states[user_id]["step"] != "descripcion":
        return

    descripcion = update.message.text
    current_time = datetime.now()
    group_id = int(os.getenv("GROUP_ID"))

    conn = get_connection()
    cursor = conn.cursor()

    cursor.execute("""
        INSERT INTO tickets (
            usuario_id, usuario_nombre, tipo, piso, sistema,
            descripcion, estado, asignado_a, prioridad,
            fecha_creacion, fecha_actualizacion
        )
        VALUES (%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s)
        RETURNING id;
    """, (
        user_id,
        update.message.from_user.full_name,
        user_states[user_id]["tipo"],
        user_states[user_id]["piso"],
        user_states[user_id]["sistema"],
        descripcion,
        "ABIERTO",
        None,
        user_states[user_id]["prioridad"],
        current_time,
        current_time
    ))

    ticket_id = cursor.fetchone()[0]
    conn.commit()

    prioridad = user_states[user_id]["prioridad"]

    ticket_text = f"""
🆕 TICKET #{ticket_id}
Prioridad: {prioridad_icono(prioridad)} {prioridad}
Estado: 🟢 ABIERTO
Creado: {current_time.strftime("%d/%m/%Y %H:%M")}

👤 Usuario: {update.message.from_user.full_name}
🧩 Tipo: {user_states[user_id]['tipo']}
🏢 Piso: {user_states[user_id]['piso']}
🖥 Sistema: {user_states[user_id]['sistema']}

📝 Descripción:
{descripcion}
"""

    msg = await context.bot.send_message(chat_id=group_id, text=ticket_text)

    cursor.execute("UPDATE tickets SET message_id=%s WHERE id=%s",
                   (msg.message_id, ticket_id))

    conn.commit()
    cursor.close()
    conn.close()

    await update.message.reply_text(f"✅ Ticket #{ticket_id} creado.")
    del user_states[user_id]

# ==============================
# CAMBIAR ESTADO ROBUSTO
# ==============================

async def cambiar_estado(update: Update, context: ContextTypes.DEFAULT_TYPE, nuevo_estado):

    if not context.args:
        await update.message.reply_text("Indica el ID del ticket.")
        return

    ticket_id = int(context.args[0])
    operador = update.message.from_user.full_name
    operador_id = update.effective_user.id
    group_id = int(os.getenv("GROUP_ID"))
    current_time = datetime.now()

    conn = get_connection()
    cursor = conn.cursor()

    # Obtener datos actuales del ticket
    cursor.execute("""
        SELECT asignado_a, message_id, tipo, piso, sistema, descripcion,
               prioridad, usuario_nombre, usuario_id
        FROM tickets
        WHERE id=%s
    """, (ticket_id,))

    result = cursor.fetchone()

    if not result:
        cursor.close()
        conn.close()
        await update.message.reply_text("Ticket no encontrado.")
        return

    asignado_actual, message_id, tipo, piso, sistema, descripcion, prioridad, usuario_nombre, usuario_id = result

    # ==============================
    # VALIDACIÓN PARA CERRAR
    # ==============================

    if nuevo_estado == "CERRADO":

        if operador_id not in ADMIN_IDS and asignado_actual != operador:
            cursor.close()
            conn.close()
            await update.message.reply_text("⛔ Solo quien tomó el ticket puede cerrarlo.")
            return

    # ==============================
    # ACTUALIZAR ESTADO
    # ==============================

    cursor.execute("""
        UPDATE tickets
        SET estado=%s,
            asignado_a=%s,
            fecha_actualizacion=%s
        WHERE id=%s
    """, (nuevo_estado, operador, current_time, ticket_id))

    conn.commit()

    ticket_text = f"""
🆕 TICKET #{ticket_id}
Prioridad: {prioridad_icono(prioridad)} {prioridad}
Estado: {estado_icono(nuevo_estado)} {nuevo_estado}
Actualizado: {current_time.strftime("%d/%m/%Y %H:%M")}
Asignado a: {operador}

👤 Usuario: {usuario_nombre}
🧩 Tipo: {tipo}
🏢 Piso: {piso}
🖥 Sistema: {sistema}

📝 Descripción:
{descripcion}
"""

    try:
        await context.bot.edit_message_text(
            chat_id=group_id,
            message_id=message_id,
            text=ticket_text
        )
    except BadRequest:
        new_msg = await context.bot.send_message(
            chat_id=group_id,
            text=ticket_text
        )
        cursor.execute("UPDATE tickets SET message_id=%s WHERE id=%s",
                       (new_msg.message_id, ticket_id))
        conn.commit()

    cursor.close()
    conn.close()

    # Notificación privada
    try:
        await context.bot.send_message(
            chat_id=usuario_id,
            text=f"📌 Tu ticket #{ticket_id} ahora está en estado: {nuevo_estado}"
        )
    except:
        pass

    await update.message.reply_text("Estado actualizado.")

async def proceso(update: Update, context: ContextTypes.DEFAULT_TYPE):

    user_id = update.effective_user.id

    if user_id not in SOPORTE_IDS and user_id not in ADMIN_IDS:
        await update.message.reply_text("⛔ No tienes permisos para poner tickets en proceso.")
        return

    await cambiar_estado(update, context, "EN PROCESO")

async def cerrar(update: Update, context: ContextTypes.DEFAULT_TYPE):
    await cambiar_estado(update, context, "CERRADO")

async def id_command(update: Update, context: ContextTypes.DEFAULT_TYPE):
    await update.message.reply_text(f"Tu user_id es: {update.effective_user.id}")

async def reporte(update: Update, context: ContextTypes.DEFAULT_TYPE):

    user_id = update.effective_user.id

    if user_id not in ADMIN_IDS:
        await update.message.reply_text("⛔ Solo ADMIN puede ver reportes.")
        return

    conn = get_connection()
    cursor = conn.cursor()

    # Totales por estado
    cursor.execute("""
        SELECT estado, COUNT(*) 
        FROM tickets
        GROUP BY estado
    """)
    estados = dict(cursor.fetchall())

    # Totales por prioridad
    cursor.execute("""
        SELECT prioridad, COUNT(*)
        FROM tickets
        GROUP BY prioridad
    """)
    prioridades = dict(cursor.fetchall())

    # Totales por operador
    cursor.execute("""
        SELECT asignado_a, COUNT(*)
        FROM tickets
        WHERE asignado_a IS NOT NULL
        GROUP BY asignado_a
    """)
    operadores = cursor.fetchall()

    cursor.close()
    conn.close()

    total = sum(estados.values())

    reporte_text = f"""
📊 REPORTE OPERATIVO

🎫 Total tickets: {total}

🟢 Abiertos: {estados.get('ABIERTO', 0)}
🟡 En proceso: {estados.get('EN PROCESO', 0)}
🔴 Cerrados: {estados.get('CERRADO', 0)}

🔴 Alta: {prioridades.get('Alta', 0)}
🟡 Media: {prioridades.get('Media', 0)}
🟢 Baja: {prioridades.get('Baja', 0)}

👨‍🔧 Operadores:
"""

    for op, count in operadores:
        reporte_text += f"\n{op}: {count}"

    await update.message.reply_text(reporte_text)

# ==============================
# MAIN
# ==============================

if __name__ == "__main__":

    TOKEN = os.getenv("BOT_TOKEN")
    GROUP_ID = os.getenv("GROUP_ID")

    app = ApplicationBuilder().token(TOKEN).build()

    app.add_handler(CommandHandler("proceso", proceso, filters=filters.ChatType.GROUPS))
    app.add_handler(CommandHandler("cerrar", cerrar, filters=filters.ChatType.GROUPS))
    app.add_handler(CommandHandler("start", start))
    app.add_handler(CommandHandler("id", id_command, filters=filters.ChatType.PRIVATE))
    
    app.add_handler(CallbackQueryHandler(button_handler))
    app.add_handler(
        MessageHandler(
            filters.ChatType.PRIVATE & filters.TEXT & ~filters.COMMAND,
            text_handler
        )
    )

    print("🚀 BOT ROBUSTO OPERATIVO")

    app.run_polling(drop_pending_updates=True)
