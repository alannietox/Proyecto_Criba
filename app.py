import xml.etree.ElementTree as ET
import re
import glob
import os
import time
import threading
import locale
import html
from datetime import datetime, timedelta
import json
import openai
import tkinter as tk
from fpdf import FPDF
from tkinter import messagebox, filedialog
import customtkinter as ctk
from ftplib import FTP
import sys
from dotenv import load_dotenv

# Ruta base del proyecto (donde está el ejecutable o app.py)
if getattr(sys, 'frozen', False):
    # Si estamos ejecutando el binario compilado por PyInstaller
    ROOT_DIR = os.path.dirname(sys.executable)
else:
    # Si estamos ejecutando app.py en entorno de desarrollo
    ROOT_DIR = os.path.dirname(os.path.abspath(__file__))

CONFIG_FILE_PATH = os.path.join(ROOT_DIR, ".config_ine.json")

# =========================================================
# --- FILTROS POR PALABRAS PROHIBIDAS
# =========================================================

_PALABRAS_PROHIBIDAS = [
    'facturación', 'facturaciones', 'factura', 'facturas', 'facturó', 'facturaron', 
    'ebitda', 'adquiere', 'adquieren', 'fusión', 'fusiones', 'nombra', 'nombran', 
    'premia', 'premian', 'premio', 'premios', 'galardón', 'galardones', 
    'patrocina', 'patrocinan', 'alianza', 'alianzas', 'dimite', 'dimiten', 
    'ceo', 'ceos', 'dividendo', 'dividendos', 'recompra', 'recompras', 
    'salida a bolsa', 'salidas a bolsa', 
    'von der leyen',
    'mercosur', 
    'moda', 'modas', 'publicitaria', 'publicitarias', 
    'campaña', 'campañas', 'lanzamiento', 'lanzamientos', 'juvenil', 'juveniles', 
    'colección', 'colecciones', 'fichaje', 'fichajes', 'marketing', 
    'deportes', 'deporte', 'fútbol', 'baloncesto', 'tenis', 'champions', 
    'cine', 'cines', 'estreno', 'estrenos', 'película', 'películas', 
    'concierto', 'conciertos', 'música', 'artista', 'artistas', 
    'vacaciones', 'actriz', 'actrices', 'vacación', 'viajes', 'viaje', 'cantante', 'cantantes',
    'política', 'políticas', 'partido', 'partidos', 'voto', 'votos', 
    'elecciones', 'elección', 'escaños', 'escaño', 'parlamento', 'parlamentos',
    'multinacional', 'multinacionales', 'corporativo', 'corporativos', 
    'apple', 'macbook', 'macbooks', 'iphone', 'iphones', 'microsoft', 'google', 'amazon', 
    'csic', 'currículo', 'currículos', 'aula', 'aulas', 
    'educación primaria', 'educación secundaria', 'eso','consejo de ministros'  
    # ── Sucesos / Judicial ──
    'asesinato', 'homicidio', 'juzgado', 'audiencia', 'tribunal', 'fiscalía', 'magistrado', 'sentencia', 'cárcel', 'prisión', 'detenido', 'policía', 'guardia civil', 'violencia machista', 'accidente', 'fallecido', 'fallecidos',
    # ── Bolsa / EpData / Ayudas Locales ──
    'ibex', 'bolsa española', 'wall street', 'dow jones', 'epdata', 'ayuntamiento', 'ayuntamientos', 'subvención', 'subvenciones', 'expediente', 'expedientes', 'adif'
]
_RE_PROHIBIDAS = re.compile(r'\b(' + '|'.join(_PALABRAS_PROHIBIDAS) + r')\b', re.IGNORECASE)

# Palabras prohibidas ESTRICTAS (no tienen salvoconducto y se descartan inmediatamente)
_PROHIBIDAS_ESTRICTAS = [
    'bce', 'banco central europeo'
]
_RE_PROHIBIDAS_ESTRICTAS = re.compile(r'\b(' + '|'.join(_PROHIBIDAS_ESTRICTAS) + r')\b', re.IGNORECASE)

# Palabras "salvoconducto": si la noticia contiene alguna de estas,
# se ignoran las palabras prohibidas y pasa directamente a la IA.
# Ejemplo: "apple" está prohibida, pero "apple" + "ere" sí interesa.
_PALABRAS_SALVO = [
    'ere', 'erte', 'empleo', 'empleos', 'política energética',
    'política fiscal', 'políticas fiscales', 'política tributaria', 'políticas tributarias',
    'política económica', 'políticas económicas', 'política monetaria', 'políticas monetarias',
    'política de empleo', 'políticas de empleo', 'política industrial', 'políticas industriales',
    'política comercial', 'políticas comerciales', 'política arancelaria', 'políticas arancelarias',
    'corredor atlántico', 'corredores atlánticos', 'corredor atlantico', 'corredores atlanticos',
    'corredor mediterráneo', 'corredores mediterráneos', 'corredor mediterraneo', 'corredores mediterraneos'
]
_RE_SALVO = re.compile(r'\b(' + '|'.join(_PALABRAS_SALVO) + r')\b', re.IGNORECASE)

# =========================================================
# --- IA CALLS (Con Reintentos y Limpieza de JSON)
# =========================================================
def llamar_ia_con_reintentos(instrucciones, provider, api_key, logger, max_retries=3):
    for intento in range(max_retries):
        try:
            if "Online" in provider:
                # Mapeo de modelos según la selección en la UI
                if "Gemini" in provider:
                    model_id = "google/gemini-2.0-flash-001"
                elif "Llama 3.1" in provider:
                    model_id = "meta-llama/llama-3.1-8b-instruct"
                else:
                    # Por defecto si no es Gemini pero es Online (seguridad)
                    model_id = "google/gemini-2.0-flash-001"

                if intento == 0: logger(f"📡 [AI] Solicitando análisis a {model_id} (OpenRouter)...")
                client = openai.OpenAI(
                    base_url="https://openrouter.ai/api/v1",
                    api_key=api_key,
                )
                respuesta = client.chat.completions.create(
                    model=model_id,
                    temperature=0.0,
                    messages=[{"role": "user", "content": instrucciones}],
                    stream=True,
                    extra_body={"provider": {"allow_fallbacks": True}}
                )
                
                contenido = ""
                for chunk in respuesta:
                    if chunk.choices and chunk.choices[0].delta.content:
                        contenido += chunk.choices[0].delta.content
                        
                inicio = contenido.find('{')
                fin = contenido.rfind('}') + 1
                if inicio != -1 and fin != -1:
                    contenido = contenido[inicio:fin]
                return json.loads(contenido)
            
                
        except openai.RateLimitError:
            wait_time = (intento + 1) * 12
            logger(f"⏳ [IA] Límite de velocidad (429) alcanzado. Reintentando en {wait_time}s...")
            time.sleep(wait_time)
        except Exception as e:
            wait_time = (intento + 1) * 4
            error_msg = str(e)
            if "invalid_api_key" in error_msg.lower() or "401" in error_msg:
                logger("❌ Error: Clave API no válida o expirada.")
            elif "insufficient_quota" in error_msg.lower() or "402" in error_msg:
                logger("❌ Error: Cuota insuficiente en la cuenta de OpenRouter.")
            else:
                logger(f"⚠️ Intento {intento + 1}/{max_retries} fallido en {provider}: {e}")
            
            if intento < max_retries - 1:
                logger(f"⏳ Reintentando en {wait_time}s...")
                time.sleep(wait_time)
            else:
                logger(f"❌ Error definitivo en IA tras {max_retries} intentos.")
                raise e


# =========================================================
# --- PDF GENERATION
# =========================================================
def limpiar_unicode(texto):
    if not texto: return ""
    # Mapeo de caracteres comunes que no están en Latin-1/Win-1252
    replacements = {
        "–": "-", "—": "-", 
        "“": '"', "”": '"', 
        "‘": "'", "’": "'", 
        "…": "...", "\xa0": " ", 
        "€": "EUR", "•": "*",
        "·": ".", "º": "o", "ª": "a",
        "©": "(c)", "®": "(r)", "™": "(tm)"
    }
    for old, new in replacements.items():
        texto = texto.replace(old, new)
    
    # Forzar a cp1252 (que es lo que suele usar FPDF para fuentes estándar)
    # eliminando cualquier carácter que no sea compatible para evitar el crash.
    try:
        return texto.encode('cp1252', errors='replace').decode('cp1252').replace('?', '')
    except:
        # Fallback total: solo caracteres ASCII básicos si falla lo anterior
        return "".join(c for c in texto if ord(c) < 128)

def formatear_cuerpo_teletipo(texto):
    if not texto: return ""
    
    texto = html.unescape(texto)
    texto = re.sub(r'<[^>]+>', '', texto)
    
    # Eliminar textos promocionales de gráficos e inserciones multimedia y todo lo que le sigue
    texto = re.sub(r'(?i)GRÁFICO:\s*Enlace\s+a\s+gráfico\s+disponible\s+al\s+final\s+del\s+texto\.?', '', texto)
    texto = re.sub(r'(?is)(?:\s*-{3,})?\s*Contenido\s+multimedia:.*$', '', texto)
    texto = re.sub(r'(?is)\beyp\s*/\s*apc\b.*$', '', texto)
    texto = re.sub(r'(?is)\b[a-z]{2,4}\s*/\s*[a-z]{2,4}\b.*$', '', texto)
    
    # Separar subtítulo de la cabecera si vienen juntos en la primera línea con espacios
    patron_separador = r'(\S.*?)\s{3,}([A-ZÁÉÍÓÚÑa-záéíóúñ\s]+,?\s*\d+(?:\s*(?:de\s*)?[A-Za-zÁÉÍÓÚÑáéíóúñ]+\.?)?\s*\([^)]+\))'
    texto = re.sub(patron_separador, r'\1\n\2', texto)

    # 1. Formato de Cabecera (Dateline): Procesar primero para evitar que sea detectada como ladillo
    def estandarizar_cabecera(match):
        ciudad = match.group(1).replace(',', '').strip().upper()
        fecha_raw = match.group(2)
        resto = match.group(3).strip()
        
        # Extraer limpiamente el nombre de la agencia para homogeneizar (EFE).- y (EUROPA PRESS) -
        m_agencia = re.search(r'\(([^)]+)\)', resto)
        if m_agencia:
            agencia = m_agencia.group(1)
            resto = f"({agencia}) -"
        else:
            if not re.search(r'[-–—]$', resto):
                resto += " -"
            
        m_fecha = re.search(r'(\d+)(?:\s*(?:de\s*)?([A-Za-zÁÉÍÓÚÑáéíóúñ]+))?', fecha_raw)
        if m_fecha and m_fecha.group(2):
            dia = m_fecha.group(1)
            mes = m_fecha.group(2).lower()
            mapa_meses = {'enero': 'Ene', 'febrero': 'Feb', 'marzo': 'Mar', 'abril': 'Abr', 'mayo': 'May', 'junio': 'Jun', 'julio': 'Jul', 'agosto': 'Ago', 'septiembre': 'Sep', 'octubre': 'Oct', 'noviembre': 'Nov', 'diciembre': 'Dic'}
            mes_abrev = mapa_meses.get(mes, mes.capitalize()[:3])
            fecha_str = f"{dia} {mes_abrev}."
        elif m_fecha:
            dia = m_fecha.group(1)
            meses_arr = ['Ene', 'Feb', 'Mar', 'Abr', 'May', 'Jun', 'Jul', 'Ago', 'Sep', 'Oct', 'Nov', 'Dic']
            mes_actual = meses_arr[datetime.now().month - 1]
            fecha_str = f"{dia} {mes_actual}."
        else:
            fecha_str = fecha_raw.strip()
            
        return f"@@DATELINE@@{ciudad} {fecha_str} {resto}@@ENDDATELINE@@"

    texto = re.sub(r'(?m)^\s*([A-ZÁÉÍÓÚÑa-záéíóúñ \t]+,?\s*)(\d+(?:\s*(?:de\s*)?[A-Za-zÁÉÍÓÚÑáéíóúñ]+\.?)?\s*)(\([^)]+\)\s*\.?\s*[-–—]*)\s*\n*\s*', estandarizar_cabecera, texto)
    
    # Todo lo que esté antes de la cabecera (Dateline) se considera título/subtítulo, así que lo marcamos como ladillo para que salga en negrita
    if "@@DATELINE@@" in texto:
        partes = texto.split("@@DATELINE@@", 1)
        lineas_pre = partes[0].splitlines()
        for i in range(len(lineas_pre)):
            if lineas_pre[i].strip():
                lineas_pre[i] = f"@@LADILLO@@{lineas_pre[i].strip()}@@ENDLADILLO@@"
        partes[0] = "\n".join(lineas_pre) + ("\n" if lineas_pre else "")
        texto = "@@DATELINE@@".join(partes)
    
    # Detectar posibles ladillos sin etiqueta si son líneas cortas todo en mayúsculas
    lineas = texto.splitlines()
    for i in range(len(lineas)):
        l = lineas[i].strip()
        if "@@DATELINE@@" in l or "@@LADILLO@@" in l:
            continue
        if len(l) > 2 and len(l) < 100 and l.isupper():
            lineas[i] = f"@@LADILLO@@{l}@@ENDLADILLO@@"
    texto = "\n".join(lineas)
    
    for char in ["*", "_", "`", "[", "]", "~", ">", "#", "|", "{", "}", "\\"]:
        texto = texto.replace(char, "")
    
    # Reemplazar dobles guiones que causan subrayados en el motor Markdown de FPDF
    texto = texto.replace("--", "-")
    
    texto = "".join(c for c in texto if ord(c) >= 32 or c in "\n\r\t")
    # Colapsar todos los saltos de línea múltiples en uno solo para que sea compacto
    texto = re.sub(r'\n{2,}', '\n', texto).strip()

    # Quitar los tokens temporales de DATELINE
    texto = texto.replace("@@DATELINE@@", "").replace("@@ENDDATELINE@@", "")

    # 2. Formato de Ladillos: negrita y un solo salto de línea (sin espacio extra) con el siguiente párrafo
    texto = re.sub(r'@@LADILLO@@(.*?)@@ENDLADILLO@@\s*\n*', r'**\1**\n', texto)

    patrones = [
        (r'\bInstituto Nacional de Estad[íi]stica \(INE\)\b', 'Instituto Nacional de Estadística (INE)'),
        (r'\bInstituto Nacional de Estad[íi]stica\b', 'Instituto Nacional de Estadística'),
        (r'\bINE\b', 'INE')
    ]
    
    for i, (regex, _) in enumerate(patrones):
        texto = re.sub(regex, f'@@MARK{i}@@', texto, flags=re.IGNORECASE)
    for i, (_, reemplazo) in enumerate(patrones):
        texto = texto.replace(f'@@MARK{i}@@', f'**{reemplazo}**')

    # Eliminar firmas finales típicas de agencias (ej: " EFE\nala/jlm" o solo "ala/jlm")
    # Busca " EFE" (opcional) seguido de iniciales "xxx/yyy" al final del texto.
    texto = re.sub(r'(?:\s+EFE|\s+EUROPA PRESS|\s+EP)?\s*\n*\s*[a-zA-Z]{2,4}/[a-zA-Z]{2,4}\s*$', '', texto)
    # Por si queda un " EFE" suelto justo al final después de un punto
    texto = re.sub(r'\.\s+(?:EFE|EUROPA PRESS|EP)\s*$', '.', texto)
            
    return texto

def obtener_titulo_formateado(n):
    titulo_original = re.sub(r'<[^>]+>', '', n.get('titulo', '')).strip()
    match_cat = re.match(r'^([^/-]+(?:/[^.-]+)?)\.?\s*[-–]\s*(.+)$', titulo_original)
    if match_cat:
        categoria_raw = match_cat.group(1).strip()
        # Tomar la última parte y capitalizarla (ej: "Vivienda" de "Economía/Vivienda" o "Economía" de "Economía")
        cat_base = categoria_raw.split('/')[-1].strip(".- ")
        categoria = cat_base.capitalize()
        titulo_sin_prefijo = match_cat.group(2).strip(".- ")
    else:
        ai_cat = n.get("ai_categoria", "") or ""
        mapeo_cats = {
            "PRECIOS": "Precios",
            "EMPLEO": "Empleo",
            "PIB": "Pib",
            "VIVIENDA": "Vivienda",
            "COMERCIO_EXTERIOR": "Comercio exterior",
            "TURISMO": "Turismo",
            "TRANSPORTE": "Transporte",
            "ENERGIA": "Energía",
            "DEPENDENCIA": "Dependencia",
            "CONSUMO": "Consumo",
            "OTROS": "Otros"
        }
        categoria = mapeo_cats.get(ai_cat.upper(), ai_cat.capitalize()).strip(".- ")
        titulo_sin_prefijo = titulo_original.strip(".- ")

    # Si hay una categoría válida, formatear como "Categoría.- Título", sino sólo Título
    if categoria:
        return f"{categoria}.- {titulo_sin_prefijo}"
    else:
        return titulo_sin_prefijo

def generar_pdf(noticias_finales, carpeta_destino, logger):
    if not noticias_finales:
        logger("❌ No hay noticias para añadir al PDF.")
        return

    logger("📑 Generando el archivo PDF con formato teletipo y negritas...")

    try:
        locale.setlocale(locale.LC_TIME, 'es_ES.UTF-8')
    except locale.Error:
        try:
            locale.setlocale(locale.LC_TIME, 'esp')
        except locale.Error:
            pass

    mes_actual = datetime.now().strftime("%B").lower()
    fecha_hoy = f"{datetime.now().day} {mes_actual} de {datetime.now().year}"

    pdf = FPDF()
    pdf.MARKDOWN_LINK_UNDERLINE = False
    
    pdf.add_page()
    pdf.set_auto_page_break(auto=True, margin=20)
    pdf.set_left_margin(25)
    pdf.set_right_margin(25)

    # Nota: Si quisieras usar fuentes Unicode reales para no tener que limpiar símbolos como el €, 
    # tendrías que descomentar estas líneas y tener los archivos TTF en la carpeta del script:
    # pdf.add_font("DejaVu", "", "DejaVuSansCondensed.ttf")
    # pdf.add_font("DejaVu", "B", "DejaVuSansCondensed-Bold.ttf")
    # fuente_principal = "DejaVu"
    fuente_principal = "Times"

    # --- CABECERA ---
    pdf.set_font(fuente_principal, "B", 14)
    pdf.cell(w=0, h=6, text="RESUMEN DE TELETIPOS", new_x="LMARGIN", new_y="NEXT", align="C")
    
    pdf.set_font(fuente_principal, "B", 12)
    pdf.cell(w=0, h=6, text=fecha_hoy, new_x="LMARGIN", new_y="NEXT", align="C")
    pdf.ln(12) 
    
    # --- BUCLE DE NOTICIAS ---
    for n in noticias_finales:
        # Parseo de fecha tolerante para mostrar solo HH:MM h
        hora_raw = n.get("hora", "")
        dt_hora = parse_date_safe(hora_raw)
        hora_texto = dt_hora.strftime("%H:%Mh") if dt_hora != datetime.min else "Hora N/E"
        
        titulo_formateado = obtener_titulo_formateado(n)
        titulo_limpio = limpiar_unicode(titulo_formateado)
        
        # --- Lógica 'Keep Together': Si no queda espacio para hora + título, saltar página ---
        if pdf.get_y() > 230:
            pdf.add_page()

        # 1. Hora
        pdf.set_font(fuente_principal, "B", 12)
        pdf.cell(w=0, h=6, text=hora_texto, new_x="LMARGIN", new_y="NEXT", align="L")
        
        # 2. Título (incluye categoría e.g. "Economía.- Título")
        pdf.set_font(fuente_principal, "B", 12)
        pdf.multi_cell(w=0, h=5, text=titulo_limpio, new_x="LMARGIN", new_y="NEXT", align="J")
        
        # 3. Cuerpo
        pdf.set_font(fuente_principal, "", 12)
        cuerpo_formateado = limpiar_unicode(formatear_cuerpo_teletipo(n['descripcion']))
        
        cuerpo_formateado = re.sub(r'\[([^\]]+)\]\([^\)]+\)', r'\1', cuerpo_formateado)
        cuerpo_formateado = re.sub(r'http[s]?://\S+', '', cuerpo_formateado)
        cuerpo_formateado = re.sub(r'<[^>]+>', '', cuerpo_formateado)

        pdf.multi_cell(w=0, h=5, text=cuerpo_formateado, new_x="LMARGIN", new_y="NEXT", align="L", markdown=True)
        pdf.ln(8)

    fecha_str = datetime.now().strftime("%Y%m%d")
    archivo_pdf = os.path.join(carpeta_destino, f"resumen_teletipos_{fecha_str}.pdf")
    pdf.output(archivo_pdf)
    logger(f"\n✅ PDF generado con éxito: {archivo_pdf}")

def escape_rtf(texto):
    if not texto: return ""
    # Escapar caracteres de control de RTF
    texto = texto.replace('\\', '\\\\').replace('{', '\\{').replace('}', '\\}')
    # Mapa de caracteres ANSI para tildes y eñes (CP1252)
    mapa = {
        'á': r"\'e1", 'é': r"\'e9", 'í': r"\'ed", 'ó': r"\'f3", 'ú': r"\'fa",
        'Á': r"\'c1", 'É': r"\'c9", 'Í': r"\'cd", 'Ó': r"\'d3", 'Ú': r"\'da",
        'ñ': r"\'f1", 'Ñ': r"\'d1", '¿': r"\'bf", '¡': r"\'a1", '€': "EUR"
    }
    for original, escape in mapa.items():
        texto = texto.replace(original, escape)
    # Convertir saltos de línea a formato RTF
    texto = texto.replace("\n", "\\par ")
    return texto

def generar_rtf(noticias_finales, carpeta_destino, logger):
    try:
        ahora = datetime.now()
        meses = ["enero", "febrero", "marzo", "abril", "mayo", "junio", "julio", "agosto", "septiembre", "octubre", "noviembre", "diciembre"]
        fecha_txt = f"{ahora.day} de {meses[ahora.month-1]} de {ahora.year}"

        # Cabecera RTF (ANSI, Fuente Times New Roman)
        rtf = r"{\rtf1\ansi\deff0 {\fonttbl{\f0 Times New Roman;}}\f0\fs24 "
        rtf += r"\qc\b\fs28 RESUMEN DE TELETIPOS\b0\par "
        rtf += f"\\qc\\b {escape_rtf(fecha_txt)}\\b0\\par\\par\\pard "

        for n in noticias_finales:
            # 1. Hora y Titulo en Negrita
            hora_raw = n.get("hora", "")
            dt_hora = parse_date_safe(hora_raw)
            hora_limpia = dt_hora.strftime("%H:%M h") if dt_hora != datetime.min else "Hora N/E"
            hora = escape_rtf(hora_limpia)
            
            titulo_formateado = obtener_titulo_formateado(n)
            titulo = escape_rtf(titulo_formateado)
            
            rtf += f"\\b {hora}\\b0\\par "
            rtf += f"\\b {titulo}\\b0\\par "

            # 2. Cuerpo con procesamiento de negritas (**)
            cuerpo = formatear_cuerpo_teletipo(n.get("descripcion", ""))
            cuerpo = escape_rtf(cuerpo)
            
            # Convertir **texto** en \b texto \b0
            partes = cuerpo.split("**")
            cuerpo_rtf = ""
            for i, parte in enumerate(partes):
                if i % 2 == 1: # Parte impar = entre asteriscos
                    cuerpo_rtf += f"\\b {parte}\\b0 "
                else:
                    cuerpo_rtf += parte
            
            rtf += f"{cuerpo_rtf}\\par\\par "

        rtf += "}"
        
        fecha_str = datetime.now().strftime("%Y%m%d")
        archivo_rtf = os.path.join(carpeta_destino, f"resumen_teletipos_{fecha_str}.rtf")
        with open(archivo_rtf, "w", encoding="ascii", errors="ignore") as f:
            f.write(rtf)
        
        logger(f"✅ RTF generado con éxito: {archivo_rtf}")
    except Exception as e:
        logger(f"❌ Error generando RTF: {e}")

# =========================================================
# --- UTILIDADES DE FECHA Y ORDENACIÓN
# =========================================================
def parse_date_safe(date_str):
    if not date_str:
        return datetime.min
    try:
        # Extraer solo la hora y minuto sin importar el día
        match_hora = re.search(r'(\d{1,2}):(\d{2})', date_str)
        if match_hora:
            hh, mm = map(int, match_hora.groups())
            # Usamos una fecha fija (año 2000) para que el orden sea ÚNICAMENTE por hora
            return datetime(2000, 1, 1, hh, mm)
        
        # Si es formato ISO pero queremos ignorar el día, también extraemos HH:MM
        d_str = date_str.replace('Z', '+00:00').replace('GMT', '').strip()
        if 'T' in d_str:
            dt = datetime.fromisoformat(d_str)
            if dt.tzinfo is not None:
                dt = dt.astimezone()
            return datetime(2000, 1, 1, dt.hour, dt.minute)
    except: pass
    return datetime.min

# =========================================================
# --- FTP SYNC & CLEANUP
# =========================================================
def limpiar_carpeta_local(carpeta, logger):
    logger(f"🗑️ Limpiando archivos XML antiguos en {carpeta}...")
    # Buscamos archivos .xml tanto en la carpeta principal como en subcarpetas si las hay
    archivos_raw = glob.glob(os.path.join(carpeta, "*.xml")) + glob.glob(os.path.join(carpeta, "*.XML"))
    archivos = list(set(os.path.abspath(f) for f in archivos_raw))
    for f in archivos:
        try:
            os.remove(f)
        except: pass
    logger(f"🧹 Carpeta limpia ({len(archivos)} archivos eliminados).")

def descargar_desde_ftp(host, user, password, carpeta_remota, carpeta_local, logger):
    logger(f"🌐 Conectando a FTP: {host}...")
    try:
        ftp = FTP(host)
        ftp.login(user=user, passwd=password)
        
        if carpeta_remota != "/":
            ftp.cwd(carpeta_remota)
        
        # Obtener lista de archivos
        archivos_remotos = [f for f in ftp.nlst() if f.lower().endswith('.xml')]
        
        # Filtro de fecha (Hoy)
        hoy = datetime.now()
        hoy_str = hoy.strftime("%Y%m%d")
        if "epress.coonic.com" in host:
            archivos_remotos = [f for f in archivos_remotos if f.startswith(hoy_str)]
            logger(f"📅 [{host}] Filtrando Europa Press por fecha hoy ({hoy_str}): {len(archivos_remotos)} archivos restantes.")
        elif "efe.coonic.com" in host:
            # Nuevo formato EFE: BAS-X-NACIONAL_AAAAMMDD_HHMM.XML
            archivos_remotos = [f for f in archivos_remotos if f"_{hoy_str}_" in f.upper()]
            logger(f"📅 [{host}] Filtrando EFE por fecha hoy ({hoy_str}): {len(archivos_remotos)} archivos restantes.")
        else:
            logger(f"📂 [{host}] Encontrados {len(archivos_remotos)} archivos XML.")
        
        descargados = 0
        for archivo in archivos_remotos:
            ruta_local = os.path.join(carpeta_local, archivo)
            with open(ruta_local, 'wb') as f:
                ftp.retrbinary(f'RETR {archivo}', f.write)
            descargados += 1
        
        ftp.quit()
        logger(f"✅ [{host}] Sincronización completada ({descargados} archivos).")
        return True
    except Exception as e:
        logger(f"❌ Error FTP [{host}]: {e}")
        return False

DEFAULT_PROMPT_SYSTEM = """Eres un filtro estricto de noticias para el INE (Instituto Nacional de Estadística) de España.
Tu única misión es identificar noticias con DATOS ESTADÍSTICOS MACROECONÓMICOS REALES que reflejen la evolución de la economía española.

SELECCIONAR (seleccionada: true) si la noticia contiene estadísticas sobre:
- PRECIOS: IPC, inflación, precio vivienda alquiler/compraventa, precio coches segunda mano, precio energía, precio alimentos.
- EMPLEO AGREGADO y ESPECÍFICO: paro nacional, EPA, afiliación Seguridad Social, bajas laborales por sector, absentismo, salarios medios. EREs y ERTEs tanto de empresas concretas como estadísticas nacionales.
- PIB: crecimiento económico, contabilidad nacional.
- DEUDA y DÉFICIT público.
- HIPOTECAS y COMPRAVENTA de vivienda (registradores, notarios, portales).
- COMERCIO EXTERIOR: exportaciones e importaciones de España.
- TURISMO: estadísticas de viajeros, pernoctaciones, gasto turístico en España.
- TRANSPORTE: estadísticas sectoriales de tráfico aéreo, ferroviario, marítimo a nivel nacional (Enaire, AENA, Renfe, Puertos del Estado).
- ENERGÍA: estadísticas de consumo/producción energética nacional (Red Eléctrica, Enagás, CORES).
- DEPENDENCIA y SERVICIOS SOCIALES: estadísticas de personas mayores, dependencia, pensiones.
- CONSUMO de los hogares españoles.

DESCARTAR siempre (seleccionada: false):
- Bolsa, IBEX 35, mercados financieros, cotizaciones bursátiles.
- Startups, venture capital, inversión privada en tecnología.
- Resultados financieros, fusiones, adquisiciones de empresas privadas.
- Informes autopromocionales de consultoras privadas (PwC, Deloitte, South Summit, etc.).
- Noticias corporativas o autopromocionales de empresas privadas de transporte, turismo, energía, etc. (como aerolíneas del tipo Vueling, Iberia, Ryanair o cadenas hoteleras) que hablen sobre sus propios aumentos de plazas, asientos, nuevas rutas, vuelos o planes de negocio propios. Solo interesan estadísticas macroeconómicas del sector general.
- Aprobación de leyes, decretos, reales decretos, reformas legislativas o acuerdos del Consejo de Ministros (ej: "El Gobierno aprueba...").
- Política, elecciones, partidos, declaraciones políticas sin datos económicos.
- Deportes, cultura, ocio, sucesos, tribunales.
- Declaraciones de cargos públicos en ruedas de prensa, desayunos informativos o foros sin datos estadísticos verificables detrás (ej: "el ministro asegura que...", "el secretario de estado afirma que...").
- Nombramientos de directivos, premios empresariales.

CLAVE PARA ENTIDADES: Enaire, AENA, Renfe, Red Eléctrica, Enagás, CORES, Puertos del Estado, Turespaña son organismos públicos que publican ESTADÍSTICAS SECTORIALES → SELECCIONAR.
Vueling, Iberia, Ryanair, Nissan, Meliá, South Summit, PwC, Ancove, Idealista, etc. son entidades privadas → solo SELECCIONAR si sus datos reflejan tendencias del mercado general (ej: precio medio coches segunda mano), no si hablan de sí mismas.

Categorías posibles: PRECIOS, EMPLEO, PIB, VIVIENDA, COMERCIO_EXTERIOR, TURISMO, TRANSPORTE, ENERGIA, DEPENDENCIA, CONSUMO, OTROS.

Responde ÚNICAMENTE con un JSON puro (sin texto adicional):
{
  "0": {"seleccionada": true, "razon": "Estadística tráfico aéreo nacional +3,5%", "categoria": "TRANSPORTE"},
  "1": {"seleccionada": false, "razon": "ERE de empresa privada concreta", "categoria": "OTROS"}
}"""

# =========================================================
# --- MOTOR EXTRACTOR
# =========================================================
def motor_extractor(carpeta_xml, provider, api_key, logger, on_finish, progress_cb, on_selection_ready, limite_caracteres=1000, prompt_system=None):
    try:
        start_time = time.time()
        progress_cb(0.1, "🔍 Fase 1: Escaneando archivos...")
        archivos_raw = glob.glob(os.path.join(carpeta_xml, "*.xml")) + glob.glob(os.path.join(carpeta_xml, "*.XML"))
        # En Windows glob puede ser case-insensitive, así que eliminamos duplicados de rutas
        archivos = list(set(os.path.abspath(f) for f in archivos_raw))
        
        if not archivos:
            logger("❌ No se encontraron archivos XML en la carpeta seleccionada.")
            return

        logger(f"🔍 Fase 1: Leyendo {len(archivos)} archivos XML...")
        noticias_candidatas = []
        for arch in archivos:
            try:
                root = ET.parse(arch).getroot()
                # Buscamos de forma agnóstica para soportar EFE (NewsML) y Europa Press (NOTICIA)
                for item in root.iter():
                    if not isinstance(item.tag, str):
                        continue
                    tag_limpio = item.tag.split('}')[-1].lower()
                    
                    # Detectamos el inicio de una noticia (EFE o Europa Press)
                    if tag_limpio in ["newsitem", "noticia"]:
                        titulo = ""
                        desc = ""
                        fecha_str = ""
                        hora_str = ""
                        
                        # Buscamos campos dentro del bloque de la noticia
                        for sub in item.iter():
                            if not isinstance(sub.tag, str):
                                continue
                            sub_tag = sub.tag.split('}')[-1].lower()
                            
                            # Título (HeadLine en EFE, Titular en EP)
                            if sub_tag in ["headline", "titular"] and not titulo:
                                titulo = "".join(sub.itertext()).strip()
                            # Contenido (DataContent en EFE, Contenido en EP)
                            elif sub_tag in ["datacontent", "contenido"] and not desc:
                                body_content = next((el for el in sub.iter() if isinstance(el.tag, str) and el.tag.split('}')[-1].lower() == "body.content"), None)
                                if body_content is not None:
                                    text_lines = []
                                    for p in body_content.iter():
                                        if isinstance(p.tag, str):
                                            tag_name = p.tag.split('}')[-1].lower()
                                            p_text = "".join(p.itertext()).strip()
                                            if not p_text: continue
                                            
                                            # Detectar ladillos de varias formas: etiqueta <ladillo>, <crosshead>, <subhead>, o <p class="ladillo">
                                            es_ladillo = False
                                            if tag_name in ["ladillo", "crosshead", "subhead"]:
                                                es_ladillo = True
                                            elif tag_name == "p":
                                                clase = p.get("class", "").lower()
                                                if "ladillo" in clase or "subhead" in clase:
                                                    es_ladillo = True
                                                    
                                            if es_ladillo:
                                                text_lines.append(f"@@LADILLO@@{p_text}@@ENDLADILLO@@")
                                            elif tag_name == "p":
                                                text_lines.append(p_text)
                                                
                                    desc = "\n".join(text_lines) if text_lines else "".join(body_content.itertext()).strip()
                                else:
                                    desc = "".join(sub.itertext()).strip()
                            # Fecha/Hora (FirstCreated en EFE, Fecha/Hora en EP)
                            elif sub_tag == "firstcreated":
                                fecha_str = sub.text.strip() if sub.text else ""
                            elif sub_tag == "fecha":
                                fecha_str = sub.text.strip() if sub.text else ""
                            elif sub_tag == "hora":
                                hora_str = sub.text.strip() if sub.text else ""
                        
                        if titulo:
                            if desc:
                                # Limpiar cada línea (quitar espacios iniciales) y quitar líneas vacías
                                lineas = [l.strip() for l in desc.splitlines() if l.strip()]
                                desc = "\n".join(lineas)
                            
                            # Recomponer la hora para la ordenación
                            hora_final = f"{fecha_str} {hora_str}".strip() if hora_str else fecha_str
                            
                            # Fallback de hora general si sigue vacío
                            if not hora_final:
                                for f_root in root.iter():
                                    if isinstance(f_root.tag, str) and f_root.tag.split('}')[-1].lower() == "dateandtime":
                                        hora_final = f_root.text.strip() if f_root.text else ""
                                        break

                            # --- FILTRO DE FECHA (HOY) ---
                            # EFE: YYYYMMDDTHHMMSS...
                            # EP: DD/MM/YYYY
                            hoy = datetime.now()
                            hoy_efe = hoy.strftime("%Y%m%d")
                            hoy_ep = hoy.strftime("%d/%m/%Y")
                            
                            pasa_fecha = False
                            if not hora_final:
                                pasa_fecha = True
                            elif hoy_efe in hora_final:
                                pasa_fecha = True
                            elif hoy_ep in hora_final:
                                pasa_fecha = True
                                
                            if not pasa_fecha:
                                continue
                            
                            # --- DEDUPLICACIÓN POR TÍTULO ---
                            ya_existe = False
                            
                            t_nueva_base = re.sub(r'\s*\([^)]*amp[^)]*\)\s*|\s*-\s*ampliación\s*|\s*\([^)]*avance[^)]*\)\s*', '', titulo.lower()).strip()
                            es_amp_nueva = "(amp" in titulo.lower() or "ampliación" in titulo.lower()
                            nueva_avisa_amp = "habrá ampliación" in desc.lower() or "habra ampliacion" in desc.lower()

                            for n_c in noticias_candidatas:
                                t_exist_base = re.sub(r'\s*\([^)]*amp[^)]*\)\s*|\s*-\s*ampliación\s*|\s*\([^)]*avance[^)]*\)\s*', '', n_c["titulo"].lower()).strip()
                                es_amp_exist = "(amp" in n_c["titulo"].lower() or "ampliación" in n_c["titulo"].lower()
                                exist_avisa_amp = "habrá ampliación" in n_c["descripcion"].lower() or "habra ampliacion" in n_c["descripcion"].lower()
                                
                                if t_nueva_base == t_exist_base and t_nueva_base != "":
                                    # Comparten el título base. Comprobamos si son versiones diferentes.
                                    if es_amp_nueva != es_amp_exist:
                                        continue # Una es ampliación explícita y la otra no. Conservamos ambas.
                                        
                                    if exist_avisa_amp and not nueva_avisa_amp:
                                        continue # La antigua era avance y la nueva no. Conservamos ambas.
                                        
                                    if nueva_avisa_amp and not exist_avisa_amp:
                                        continue # La nueva es avance y la antigua no. Conservamos ambas.
                                        
                                    # Si son exactamente el mismo tipo de versión, sí es un duplicado
                                    ya_existe = True
                                    break
                            
                            if not ya_existe:
                                noticias_candidatas.append({
                                    "titulo": titulo,
                                    "descripcion": desc or "Sin descripción",
                                    "hora": hora_final
                                })
            except Exception as e:
                logger(f"⚠️ Error procesando XML {arch}: {e}")
        # Fase 2: Filtrado por Título
        progress_cb(0.3, "⚡ Fase 2: Filtrando por Título...")

        logger("⚡ Fase 2: Aplicando filtros por palabras clave en el Título...")
        candidatas_fase2 = []
        descartadas_palabras = []
        pasa_directo_ine = []
        for cand in noticias_candidatas:
            t_min = cand["titulo"].lower()
            d_min = cand["descripcion"].lower()
            texto_completo = (cand["titulo"] + "\n" + cand["descripcion"]).lower()
            
            # --- CORTAFUEGOS: Boletines diarios y Agendas de eventos ---
            # 1. Detección por Título/Temática
            terminos_agenda = ["temas del día", "temas del dia", "agenda informativa", "agenda de previsiones", "agenda de previsión", "agenda de prevision", "previsiones del día", "previsiones del dia"]
            contiene_termino_agenda = any(term in t_min for term in terminos_agenda)
            
            # 2. Detección por Exceso de Horas ("Convocatorias")
            # Buscamos horas con formato como 09:00h, 10:30h, 09.00h, etc.
            horas_encontradas = re.findall(r'\b\d{1,2}[:.]\d{2}\s*[hH]\b', texto_completo)
            exceso_horas = len(horas_encontradas) > 3
            
            if contiene_termino_agenda or exceso_horas:
                razon_descarte = []
                if contiene_termino_agenda:
                    razon_descarte.append("Término de boletín/agenda en título")
                if exceso_horas:
                    razon_descarte.append(f"Exceso de horas con formato de agenda ({len(horas_encontradas)} horas)")
                
                cand["ai_selected"] = False
                cand["ai_razon"] = f"Cortafuegos: Descartado por agenda/previsiones ({', '.join(razon_descarte)})"
                cand["ai_categoria"] = "FILTRO"
                descartadas_palabras.append(cand)
                continue
            
            # Paso directo si contiene INE o Instituto Nacional de Estadística
            if re.search(r'\b(ine|instituto nac?ional de estad[ií]stica)\b', t_min) or \
               re.search(r'\b(ine|instituto nac?ional de estad[ií]stica)\b', d_min):
                cand["ai_selected"] = True
                cand["ai_razon"] = "Paso directo por contener INE / Instituto Nacional de Estadística"
                cand["ai_categoria"] = "OTROS"
                pasa_directo_ine.append(cand)
                continue
            
            # Filtro estricto (BCE, FED, etc. se descartan directamente)
            match_estricto = _RE_PROHIBIDAS_ESTRICTAS.search(t_min)
            if match_estricto:
                palabra_detectada = match_estricto.group(0)
                cand["ai_selected"] = False
                cand["ai_razon"] = f"Descartada estrictamente por palabra clave (Título): '{palabra_detectada}'"
                cand["ai_categoria"] = "FILTRO"
                descartadas_palabras.append(cand)
                continue

            # Comprobar salvoconducto: si tiene palabra clave especial, pasa aunque tenga prohibidas
            tiene_salvo = _RE_SALVO.search(t_min) or _RE_SALVO.search(d_min)
            match_p = _RE_PROHIBIDAS.search(t_min)
            if match_p and not tiene_salvo:
                palabra_detectada = match_p.group(0)
                cand["ai_selected"] = False
                cand["ai_razon"] = f"Descartada por palabra clave (Título): '{palabra_detectada}'"
                cand["ai_categoria"] = "FILTRO"
                descartadas_palabras.append(cand)
                continue
            candidatas_fase2.append(cand)
        logger(f"📊 [Estadísticas] Fase 2 (Filtro Título): {len(candidatas_fase2)} noticias pasan el filtro.")

        # Fase 3: Filtrado por Descripción
        progress_cb(0.5, "⚡ Fase 3: Filtrando por Descripción...")
        logger("⚡ Fase 3: Aplicando filtros por palabras clave en la Descripción...")
        candidatas_fase3 = []
        for cand in candidatas_fase2:
            d_min = cand["descripcion"].lower()
            t_min = cand["titulo"].lower()
            
            # Filtro estricto en el cuerpo
            match_estricto_cuerpo = _RE_PROHIBIDAS_ESTRICTAS.search(d_min)
            if match_estricto_cuerpo:
                palabra_detectada = match_estricto_cuerpo.group(0)
                cand["ai_selected"] = False
                cand["ai_razon"] = f"Descartada estrictamente por palabra clave (Cuerpo): '{palabra_detectada}'"
                cand["ai_categoria"] = "FILTRO"
                descartadas_palabras.append(cand)
                continue

            # Misma lógica: el salvoconducto anula el filtro
            tiene_salvo = _RE_SALVO.search(t_min) or _RE_SALVO.search(d_min)
            match_p = _RE_PROHIBIDAS.search(d_min)
            if match_p and not tiene_salvo:
                palabra_detectada = match_p.group(0)
                cand["ai_selected"] = False
                cand["ai_razon"] = f"Descartada por palabra clave (Cuerpo): '{palabra_detectada}'"
                cand["ai_categoria"] = "FILTRO"
                descartadas_palabras.append(cand)
                continue
            candidatas_fase3.append(cand)
        logger(f"📊 [Estadísticas] Fase 3 (Filtro Descripción): {len(candidatas_fase3)} noticias pasan el filtro.")

        # Fase 4: Filtrado por IA (en lotes, primeros 1000 caracteres)
        TAMANO_LOTE = 2
        MAX_WORKERS = 8
        
        progress_cb(0.8, "🧠 Fase 4: Filtrando con IA...")
        logger(f"🧠 Fase 4: Enviando {len(candidatas_fase3)} noticias a la IA en lotes de {TAMANO_LOTE} (con {MAX_WORKERS} hilos en paralelo)...")
        lista_final = []
        
        lotes = [candidatas_fase3[i:i+TAMANO_LOTE] for i in range(0, len(candidatas_fase3), TAMANO_LOTE)]
        from concurrent.futures import ThreadPoolExecutor
        
        def procesar_lote(lote, batch_idx):
            logger(f"   ↳ Analizando lote {batch_idx+1}/{len(lotes)} ({len(lote)} noticias)...")
            texto_evaluar = "{\n"
            for j, cand in enumerate(lote):
                texto_limpio = f"{cand['titulo']}\n{cand['descripcion']}"[:limite_caracteres].replace('"', "'").replace('\n', ' ')
                texto_evaluar += f'  "{j}": "{texto_limpio}",\n'
            texto_evaluar += "}"

            prompt_actual = prompt_system if prompt_system is not None else DEFAULT_PROMPT_SYSTEM
            instrucciones = f"{prompt_actual}\n\nNOTICIAS A EVALUAR:\n{texto_evaluar}"
            
            lote_final = []
            try:
                datos_ia = llamar_ia_con_reintentos(instrucciones, provider, api_key, logger)
                for j, cand in enumerate(lote):
                    idx_str = str(j)
                    item_ia = datos_ia.get(idx_str, {})
                    # Marcamos la decisión de la IA pero no descartamos aún
                    cand["ai_selected"] = item_ia.get("seleccionada", False)
                    cand["ai_razon"] = item_ia.get("razon", "Sin razón")
                    cand["ai_categoria"] = item_ia.get("categoria", "OTROS")
            except Exception as e:
                logger(f"   ⚠️ Fallo en lote IA {batch_idx+1}: {e}")
                # En caso de fallo, por defecto no seleccionada pero visible
                for cand in lote: 
                    cand["ai_selected"] = False
                    cand["ai_razon"] = "Error IA"
            return True

        with ThreadPoolExecutor(max_workers=MAX_WORKERS) as executor:
            futuros = [executor.submit(procesar_lote, lote, idx) for idx, lote in enumerate(lotes)]
            # Esperar a que todos los hilos procesen sus lotes
            for futuro in futuros:
                futuro.result()
                
        logger(f"📊 [Estadísticas] Fase 4 (Análisis IA): {len(candidatas_fase3)} noticias analizadas.")

        # Unimos las que pasaron a la IA, las de paso directo por INE y las que se descartaron por palabra clave
        todas_para_revisar = candidatas_fase3 + pasa_directo_ine + descartadas_palabras
        
        # ORDENACIÓN: Primero las recomendadas por la IA, luego el resto por hora
        todas_para_revisar.sort(key=lambda x: (not x.get("ai_selected", False), parse_date_safe(x.get("hora", ""))), reverse=False)
        
        progress_cb(0.95, "📄 Fase final: Abriendo panel de revisión...")
        
        # Pasamos TODAS las candidatas (incluyendo las descartadas por filtro)
        # para que el usuario pueda recuperarlas.
        on_selection_ready(todas_para_revisar)
        
    except Exception as e:
        logger(f"❌ Error fatal: {e}")
        on_finish() # Re-habilitar botón en caso de error

# =========================================================
# --- SELECTION WINDOW
# =========================================================
class VentanaSeleccionNoticias(ctk.CTkToplevel):
    def __init__(self, parent, noticias, callback_confirmar):
        super().__init__(parent)
        self.title("Revisión de Noticias Seleccionadas")
        # Abrir en una ventana grande pero no maximizada a la fuerza
        self.geometry("1280x800")
        self.transient(parent)
        self.grab_set()
        
        self.noticias = noticias
        self.callback_confirmar = callback_confirmar
        self.vars_seleccion = []

        # Vincular scroll global al entrar/salir de la ventana
        self.bind("<Enter>", lambda e: self.bind_global_scroll())
        self.bind("<Leave>", lambda e: self.unbind_global_scroll())

        # Si el usuario cierra con la 'X', se cierra todo el programa
        self.protocol("WM_DELETE_WINDOW", parent.destroy)

        self.grid_columnconfigure(0, weight=1)
        self.grid_rowconfigure(1, weight=1)
        self.configure(fg_color="#0F0F0F")

        # Header con info y controles
        self.header_frame = ctk.CTkFrame(self, fg_color="transparent")
        self.header_frame.grid(row=0, column=0, pady=(20, 10), padx=20, sticky="ew")
        self.header_frame.columnconfigure(0, weight=1)

        self.lbl_info = ctk.CTkLabel(self.header_frame, text="Revisión de Noticias", 
                                font=("Inter", 16, "bold"), text_color="#3A86FF")
        self.lbl_info.grid(row=0, column=0, sticky="w")

        # Buscador (Nuevo)
        self.entry_search = ctk.CTkEntry(self.header_frame, placeholder_text="Filtrar por título...", 
                                        width=200, height=28, font=("Inter", 11))
        self.entry_search.grid(row=0, column=1, padx=10, sticky="e")
        self.entry_search.bind("<KeyRelease>", lambda e: self.filtrar_noticias())

        self.btn_show_all = ctk.CTkButton(self.header_frame, text="Ver Descartadas", 
                                         fg_color="#333333", height=28, font=("Inter", 11),
                                         command=self.mostrar_descartadas)
        
        self.descartadas = [n for n in self.noticias if not n.get("ai_selected")]
        if self.descartadas:
            self.btn_show_all.grid(row=0, column=2, sticky="e")
            self.btn_show_all.configure(text=f"Rescatar ({len(self.descartadas)})", state="disabled") # Deshabilitar hasta que cargue

        # Scrollable Frame para las noticias
        self.scroll_frame = ctk.CTkScrollableFrame(self, fg_color="#050505", border_width=1, border_color="#222222")
        self.scroll_frame.grid(row=1, column=0, padx=20, pady=10, sticky="nsew")
        self.scroll_frame.columnconfigure(0, weight=1)
        self.scroll_frame.columnconfigure(1, weight=1)

        self.cards_widgets = []
        self.ver_descartadas = False
        self._spinner_chars = ['⠋', '⠙', '⠹', '⠸', '⠼', '⠴', '⠦', '⠧', '⠇', '⠏']
        self._spinner_idx = 0
        self._spinner_running = True

        # Overlay de carga que cubre el scroll_frame
        self.overlay = ctk.CTkFrame(self, fg_color="#050505", corner_radius=0)
        self.overlay.grid(row=1, column=0, padx=20, pady=10, sticky="nsew")
        self.overlay.grid_columnconfigure(0, weight=1)
        self.overlay.grid_rowconfigure(0, weight=1)

        frame_centro = ctk.CTkFrame(self.overlay, fg_color="transparent")
        frame_centro.grid(row=0, column=0)

        self.lbl_spinner = ctk.CTkLabel(frame_centro, text="⠋", font=("Courier", 48, "bold"), text_color="#3A86FF")
        self.lbl_spinner.grid(row=0, column=0, pady=(0, 10))

        self.lbl_cargando = ctk.CTkLabel(frame_centro, text="Cargando noticias...", font=("Inter", 13), text_color="#FFFFFF")
        self.lbl_cargando.grid(row=1, column=0)

        # Animar el spinner
        self._animar_spinner()

        # Construir todo en segundo plano y mostrar de golpe
        self.after(100, self.cargar_noticias_inicial)

        # Footer con botones
        self.frame_buttons = ctk.CTkFrame(self, fg_color="transparent")
        self.frame_buttons.grid(row=2, column=0, pady=20, padx=20, sticky="e")

        self.btn_cancel = ctk.CTkButton(self.frame_buttons, text="Cancelar", fg_color="#333333", command=self.destroy)
        self.btn_cancel.grid(row=0, column=0, padx=10)

        self.btn_ok = ctk.CTkButton(self.frame_buttons, text="Generar Boletín PDF/RTF", fg_color="#3A86FF", 
                                     hover_color="#2A76EF", command=self.confirmar)
        self.btn_ok.grid(row=0, column=1, padx=10)

    def filtrar_noticias(self, callback_final=None):
        busqueda = self.entry_search.get().lower()
        self._filtrar_por_lote(0, busqueda, callback_final)

    def _filtrar_por_lote(self, idx, busqueda, callback_final):
        TAMANO_LOTE = 20
        for i in range(TAMANO_LOTE):
            current = idx + i
            if current < len(self.cards_widgets):
                card, n = self.cards_widgets[current]
                es_recomendada = n.get("ai_selected", False)
                match_busqueda = busqueda in n['titulo'].lower()
                
                if self.ver_descartadas:
                    visible = match_busqueda
                else:
                    visible = es_recomendada and match_busqueda
                
                if visible:
                    card.grid()
                else:
                    card.grid_remove()
            else:
                if callback_final:
                    callback_final()
                return
        
        # Siguiente lote de filtrado para no bloquear el spinner
        self.after(5, lambda: self._filtrar_por_lote(idx + TAMANO_LOTE, busqueda, callback_final))

    def mostrar_descartadas(self):
        # Mostrar el overlay de carga de nuevo para dar feedback
        self.lbl_cargando.configure(text="Procesando lista completa...")
        self.overlay.grid(row=1, column=0, padx=20, pady=10, sticky="nsew")
        self._spinner_running = True
        self._animar_spinner()
        
        def proceso():
            self.ver_descartadas = not self.ver_descartadas
            texto = "Ocultar Descartadas" if self.ver_descartadas else f"Rescatar ({len(self.descartadas_lista)})"
            self.btn_show_all.configure(text=texto, fg_color="#238636" if self.ver_descartadas else "#333333")
            # Llamar al filtrado por lotes y ocultar overlay al final
            self.filtrar_noticias(callback_final=lambda: self.after(300, self._revelar_contenido))

        self.after(100, proceso)

    def _animar_spinner(self):
        if self._spinner_running:
            self.lbl_spinner.configure(text=self._spinner_chars[self._spinner_idx % len(self._spinner_chars)])
            self._spinner_idx += 1
            self.after(80, self._animar_spinner)

    def cargar_noticias_inicial(self):
        self.recomendadas = [n for n in self.noticias if n.get("ai_selected")]
        self.descartadas_lista = [n for n in self.noticias if not n.get("ai_selected")]

        # Cargar recomendadas en pequeños lotes para no congelar el spinner
        self._cargar_lote_recomendadas(0)

    def _cargar_lote_recomendadas(self, idx):
        TAMANO_LOTE = 5
        for i in range(TAMANO_LOTE):
            current = idx + i
            if current < len(self.recomendadas):
                self.crear_tarjeta(self.recomendadas[current], current)
            else:
                # Terminado recomendadas, empezar descartadas
                self.after(10, lambda: self._cargar_lote_descartadas(0))
                return
        
        # Siguiente lote de recomendadas
        self.after(5, lambda: self._cargar_lote_recomendadas(idx + TAMANO_LOTE))

    def _cargar_lote_descartadas(self, idx):
        TAMANO_LOTE = 10
        start_row = len(self.recomendadas)
        for i in range(TAMANO_LOTE):
            current = idx + i
            if current < len(self.descartadas_lista):
                self.crear_tarjeta(self.descartadas_lista[current], start_row + current)
            else:
                # Terminado todo
                self.after(50, self._revelar_contenido)
                return
        
        # Siguiente lote de descartadas
        self.after(5, lambda: self._cargar_lote_descartadas(idx + TAMANO_LOTE))

    def _cargar_lote_y_revelar(self, start_idx):
        # Este método ya no se usa, pero lo mantenemos por si acaso o lo borramos
        pass

    def _revelar_contenido(self):
        """Oculta el overlay y revela el scroll_frame."""
        self._spinner_running = False
        self.overlay.grid_remove()
        recomendadas_count = len(self.recomendadas)
        self.lbl_info.configure(text=f"Revisión: {recomendadas_count} recomendadas / {len(self.descartadas_lista)} descartadas")
        self.btn_show_all.configure(state="normal") # Ya se puede usar el botón
        self.bind_global_scroll()


    def crear_tarjeta(self, n, i):
        var = tk.BooleanVar(value=n.get("ai_selected", False))
        self.vars_seleccion.append(var)
        
        es_ia_ok = n.get("ai_selected", False)
        
        # Tarjeta completa (Restaurada según petición)
        card_bg = "#161B22" if es_ia_ok else "#0D1117"
        border_color = "#238636" if es_ia_ok else "#30363D"
        text_color = "#E6EDF3" if es_ia_ok else "#8B949E"
        
        card = ctk.CTkFrame(self.scroll_frame, fg_color=card_bg, border_color=border_color, border_width=1, corner_radius=8)
        
        # Nueva disposición en dos columnas para evitar el límite de 32k píxeles de Tkinter
        row_idx = i // 2
        col_idx = i % 2
        
        # Si no es recomendada y no estamos viendo descartadas, ocultar de inicio
        if es_ia_ok or self.ver_descartadas:
            card.grid(row=row_idx, column=col_idx, sticky="ew", padx=10, pady=6)
        else:
            card.grid(row=row_idx, column=col_idx, sticky="ew", padx=10, pady=6)
            card.grid_remove()
            
        card.grid_columnconfigure(1, weight=1)

        cb = ctk.CTkCheckBox(card, text="", variable=var, width=24, checkbox_width=20, checkbox_height=20, 
                             border_color="#238636" if es_ia_ok else "#555555", fg_color="#238636", hover_color="#2EA043")
        cb.grid(row=0, column=0, rowspan=2, padx=(15, 10), pady=15, sticky="nw")
        
        hora = n.get("hora", "")
        dt_hora = parse_date_safe(hora)
        hora_txt = dt_hora.strftime("%H:%M") if dt_hora != datetime.min else "--:--"
        
        title_text = f"[{hora_txt}] {n['titulo']}"
        lbl_title = ctk.CTkLabel(card, text=title_text, font=("Inter", 11, "bold" if es_ia_ok else "normal"), 
                                 text_color=text_color, wraplength=340, justify="left")
        lbl_title.grid(row=0, column=1, padx=(5, 10), pady=(10, 0), sticky="w")
        
        frame_tags = ctk.CTkFrame(card, fg_color="transparent")
        frame_tags.grid(row=1, column=1, padx=(5, 15), pady=(6, 12), sticky="w")
        
        ai_badge_color = "#1F4A2C" if es_ia_ok else "#21262D"
        ai_badge_text = "IA: RECOMENDADA" if es_ia_ok else "IA: DESCARTADA"
        ai_badge_text_color = "#3FB950" if es_ia_ok else "#8B949E"
        
        lbl_badge = ctk.CTkLabel(frame_tags, text=ai_badge_text, font=("Inter", 10, "bold"), 
                                 fg_color=ai_badge_color, text_color=ai_badge_text_color, corner_radius=4, padx=8, pady=2)
        lbl_badge.grid(row=0, column=0, sticky="w", padx=(0, 10))

        reason = n.get("ai_razon", "")
        if reason:
            lbl_reason = ctk.CTkLabel(frame_tags, text=f"• {reason}", font=("Inter", 10), text_color="#7A8490", wraplength=280, justify="left")
            lbl_reason.grid(row=0, column=1, sticky="w")
            
        self.cards_widgets.append((card, n))

    def _on_mousewheel(self, event):
        # En Linux Button-4 es scroll up (4) y Button-5 es scroll down (5)
        # Usamos self.scroll_frame._parent_canvas que es el canvas interno de CTK
        canvas = self.scroll_frame._parent_canvas
        if event.num == 4 or (hasattr(event, 'delta') and event.delta > 0):
            canvas.yview_scroll(-3, "units")
        elif event.num == 5 or (hasattr(event, 'delta') and event.delta < 0):
            canvas.yview_scroll(3, "units")
        return "break"

    def bind_global_scroll(self):
        # Vincular el ratón a toda la ventana de nivel superior para que funcione siempre
        self.bind_all("<Button-4>", self._on_mousewheel)
        self.bind_all("<Button-5>", self._on_mousewheel)
        self.bind_all("<MouseWheel>", self._on_mousewheel)

    def unbind_global_scroll(self, event=None):
        self.unbind_all("<Button-4>")
        self.unbind_all("<Button-5>")
        self.unbind_all("<MouseWheel>")

    def confirmar(self):
        # Mapear los BooleanVars a sus noticias correspondientes
        # Como ahora las tarjetas se crean bajo demanda, necesitamos asegurar el mapeo correcto
        seleccionadas = []
        # En la VentanaSeleccionNoticias, las tarjetas se crean y añaden vars_seleccion en el orden en que se crean.
        # Para evitar líos con el orden, guardaremos la referencia en la propia tarjeta o usaremos un diccionario.
        # Pero para simplificar, si el usuario solo usa las recomendadas, funciona.
        # Vamos a mejorar el mapeo:
        for i, var in enumerate(self.vars_seleccion):
            if var.get():
                # Buscamos la noticia que corresponde a este var. 
                # Como self.vars_seleccion se llena en el orden de creación de tarjetas:
                # 1. Recomendadas
                # 2. Descartadas (si se pulsa el botón)
                if i < len(self.recomendadas):
                    seleccionadas.append(self.recomendadas[i])
                else:
                    seleccionadas.append(self.descartadas_lista[i - len(self.recomendadas)])
        
        self.callback_confirmar(seleccionadas)
        self.destroy()

class VentanaOpcionesAvanzadas(ctk.CTkToplevel):
    def __init__(self, parent, api_key_actual, prompt_actual, callback_guardar):
        super().__init__(parent)
        self.title("Configuración Avanzada")
        self.geometry("800x650")
        self.transient(parent)
        self.grab_set()
        
        self.callback_guardar = callback_guardar
        self.configure(fg_color="#0F0F0F")
        
        self.grid_columnconfigure(0, weight=1)
        self.grid_rowconfigure(3, weight=1)
        
        # 1. API Key
        lbl_api = ctk.CTkLabel(self, text="Clave API (OpenRouter):", font=("Inter", 11, "bold"), text_color="#3A86FF")
        lbl_api.grid(row=0, column=0, padx=20, pady=(20, 5), sticky="w")
        
        self.entry_api = ctk.CTkEntry(self, width=760, height=35, fg_color="#050505", border_color="#222222")
        self.entry_api.insert(0, api_key_actual)
        self.entry_api.grid(row=1, column=0, padx=20, pady=(0, 15), sticky="ew")
        
        # 2. Prompt Editable
        frame_prompt_header = ctk.CTkFrame(self, fg_color="transparent")
        frame_prompt_header.grid(row=2, column=0, padx=20, pady=(5, 5), sticky="ew")
        frame_prompt_header.grid_columnconfigure(0, weight=1)
        
        lbl_prompt = ctk.CTkLabel(frame_prompt_header, text="Prompt del Sistema (Filtro IA):", font=("Inter", 11, "bold"), text_color="#3A86FF")
        lbl_prompt.grid(row=0, column=0, sticky="w")
        
        btn_restablecer = ctk.CTkButton(
            frame_prompt_header, 
            text="Restablecer original", 
            font=("Inter", 10, "bold"), 
            height=26, 
            width=130,
            fg_color="#D90429", 
            hover_color="#EF233C", 
            command=self.restablecer_prompt
        )
        btn_restablecer.grid(row=0, column=1, sticky="e")
        
        self.txt_prompt = ctk.CTkTextbox(self, font=("JetBrains Mono", 11), fg_color="#050505", border_color="#222222", border_width=1)
        self.txt_prompt.insert("1.0", prompt_actual)
        self.txt_prompt.grid(row=3, column=0, padx=20, pady=(0, 20), sticky="nsew")
        
        # 3. Botones Guardar / Cancelar
        frame_buttons = ctk.CTkFrame(self, fg_color="transparent")
        frame_buttons.grid(row=4, column=0, padx=20, pady=(0, 20), sticky="e")
        
        btn_cancelar = ctk.CTkButton(frame_buttons, text="Cancelar", fg_color="#333333", command=self.destroy)
        btn_cancelar.grid(row=0, column=0, padx=10)
        
        btn_guardar = ctk.CTkButton(frame_buttons, text="Guardar Cambios", fg_color="#3A86FF", hover_color="#2A76EF", command=self.guardar)
        btn_guardar.grid(row=0, column=1, padx=10)
        
    def restablecer_prompt(self):
        confirmar = messagebox.askyesno(
            "Restablecer Prompt", 
            "¿Está seguro de que desea restablecer el prompt al valor original de fábrica?\n\n(Perderá cualquier modificación no guardada)"
        )
        if confirmar:
            self.txt_prompt.delete("1.0", "end")
            self.txt_prompt.insert("1.0", DEFAULT_PROMPT_SYSTEM)

    def guardar(self):
        confirmar = messagebox.askyesno("Confirmar Cambios", "¿Está seguro de que desea guardar los cambios en el prompt del sistema y la configuración?")
        if confirmar:
            new_api = self.entry_api.get().strip()
            new_prompt = self.txt_prompt.get("1.0", "end-1c").strip()
            self.callback_guardar(new_api, new_prompt)
            self.destroy()

# =========================================================
# --- GUI
# =========================================================
class AppExtractorNoticias(ctk.CTk):
    def __init__(self):
        super().__init__()
        self.title("News Extract AI - Pro Dashboard")
        
        # Iniciar en ventana grande (no maximizada forzosamente)
        self.geometry("1280x800")
        self.minsize(900, 650)
        ctk.set_appearance_mode("dark")
        
        # Grid Principal: 2 Columnas (Panel de Control | Terminal Pro)
        self.grid_columnconfigure(0, weight=0, minsize=420) 
        self.grid_columnconfigure(1, weight=1)             
        self.grid_rowconfigure(0, weight=1)
        self.configure(fg_color="#0A0A0A")

        # --- PANEL IZQUIERDO (PASOS Y CONFIGURACIÓN) ---
        self.frame_left = ctk.CTkFrame(self, fg_color="#0F0F0F", corner_radius=0)
        self.frame_left.grid(row=0, column=0, sticky="nsew")
        self.frame_left.grid_columnconfigure(0, weight=1)

        # Header con logo/título
        self.lbl_logo = ctk.CTkLabel(self.frame_left, text="📡 NEWS EXTRACT AI", 
                                    font=("Inter", 26, "bold"), text_color="#FFFFFF")
        self.lbl_logo.grid(row=0, column=0, pady=(40, 30))

        # --- PASO 1: ORIGEN ---
        self.frame_step1 = self.crear_seccion(self.frame_left, "1. ORIGEN DE DATOS", "📂")
        self.frame_step1.grid(row=1, column=0, padx=25, pady=10, sticky="ew")
        
        self.str_carpeta = tk.StringVar(value=os.path.join(ROOT_DIR, "xml-ftp"))
        
        self.frame_path_row = ctk.CTkFrame(self.frame_step1, fg_color="transparent")
        self.frame_path_row.grid(row=1, column=0, padx=15, pady=(5, 15), sticky="ew")
        self.frame_path_row.grid_columnconfigure(0, weight=1)
        
        self.entry_folder = ctk.CTkEntry(self.frame_path_row, textvariable=self.str_carpeta, height=35, fg_color="#050505", border_color="#222222")
        self.entry_folder.grid(row=0, column=0, sticky="ew")
        self.btn_browse = ctk.CTkButton(self.frame_path_row, text="...", command=self.seleccionar_carpeta, width=45, height=35, fg_color="#333333")
        self.btn_browse.grid(row=0, column=1, padx=(10, 0))

        # --- PASO 2: INTELIGENCIA ---
        self.frame_step2 = self.crear_seccion(self.frame_left, "2. CEREBRO IA", "🧠")
        self.frame_step2.grid(row=2, column=0, padx=25, pady=10, sticky="ew")
        
        self.var_ia = tk.StringVar(value="(Online) Gemini 2.0 Flash")
        self.combo_ia = ctk.CTkOptionMenu(self.frame_step2, values=["(Online) Gemini 2.0 Flash", "(Online) Llama 3.1 8B"], 
                                         variable=self.var_ia, fg_color="#151515", button_color="#222222", height=35)
        self.combo_ia.grid(row=1, column=0, padx=15, pady=(5, 5), sticky="ew")

        # Variables internas de configuración avanzada (Cargar persistencia o por defecto)
        self.cargar_configuracion()

        # Botón de opciones avanzadas
        self.btn_advanced = ctk.CTkButton(self.frame_step2, text="OPCIONES AVANZADAS", height=35, fg_color="#151515", border_color="#222222", border_width=1, hover_color="#222222", command=self.abrir_opciones_avanzadas)
        self.btn_advanced.grid(row=2, column=0, padx=15, pady=(5, 10), sticky="ew")

        self.lbl_limit_title = ctk.CTkLabel(self.frame_step2, text="Límite caracteres noticia:", font=("Inter", 10, "bold"), text_color="#555555")
        self.lbl_limit_title.grid(row=3, column=0, padx=15, pady=(5, 0), sticky="w")

        self.entry_limit = ctk.CTkEntry(self.frame_step2, height=35, fg_color="#050505", border_color="#222222")
        self.entry_limit.insert(0, "1000")
        self.entry_limit.grid(row=4, column=0, padx=15, pady=(5, 15), sticky="ew")

        # --- PANEL DE ESTADO / RESULTADOS ---
        self.frame_results = self.crear_seccion(self.frame_left, "ESTADO Y RESULTADOS", "📊")
        self.frame_results.grid(row=3, column=0, padx=25, pady=10, sticky="ew")
        
        self.lbl_status = ctk.CTkLabel(self.frame_results, text="Sistema listo para comenzar", font=("Inter", 12), text_color="#888888")
        self.lbl_status.grid(row=1, column=0, padx=15, pady=(10, 15))
        
        self.progress = ctk.CTkProgressBar(self.frame_results, height=4, progress_color="#3A86FF", fg_color="#000000")
        self.progress.grid(row=2, column=0, padx=15, pady=(0, 15), sticky="ew")
        self.progress.set(0)

        # Botón de Acción (Footer)
        self.btn_run = ctk.CTkButton(self.frame_left, text="🚀 INICIAR EXTRACCIÓN", command=self.iniciar, 
                                     height=70, corner_radius=0, fg_color="#3A86FF", hover_color="#2A76EF", font=("Inter", 16, "bold"))
        self.btn_run.grid(row=4, column=0, sticky="ew", pady=(30, 0))

        # --- PANEL DERECHO (TERMINAL) ---
        self.frame_right = ctk.CTkFrame(self, fg_color="#050505", corner_radius=0)
        self.frame_right.grid(row=0, column=1, sticky="nsew")
        self.frame_right.grid_columnconfigure(0, weight=1)
        self.frame_right.grid_rowconfigure(0, weight=1)

        self.console = ctk.CTkTextbox(self.frame_right, font=("JetBrains Mono", 12), 
                                     fg_color="#050505", border_width=0, corner_radius=0)
        self.console.grid(row=0, column=0, sticky="nsew", padx=20, pady=20)
        self.console.configure(state="disabled")

        self.grid_rowconfigure(0, weight=1)

    def crear_seccion(self, parent, titulo, icono):
        frame = ctk.CTkFrame(parent, fg_color="#181818", corner_radius=12, border_width=1, border_color="#222222")
        frame.grid_columnconfigure(0, weight=1)
        lbl = ctk.CTkLabel(frame, text=f"{icono} {titulo}", font=("Inter", 11, "bold"), text_color="#3A86FF")
        lbl.grid(row=0, column=0, padx=15, pady=(12, 8), sticky="w")
        return frame

    def cargar_configuracion(self):
        # Valores por defecto
        self.api_key = os.getenv("OPENROUTER_API_KEY", "")
        self.prompt_system = DEFAULT_PROMPT_SYSTEM
        
        if os.path.exists(CONFIG_FILE_PATH):
            try:
                with open(CONFIG_FILE_PATH, "r", encoding="utf-8") as f:
                    data = json.load(f)
                    if "api_key" in data:
                        self.api_key = data["api_key"]
                    if "prompt_system" in data:
                        self.prompt_system = data["prompt_system"]
            except Exception as e:
                print(f"Error al cargar configuración: {e}")

    def guardar_configuracion(self):
        try:
            data = {
                "api_key": self.api_key,
                "prompt_system": self.prompt_system
            }
            with open(CONFIG_FILE_PATH, "w", encoding="utf-8") as f:
                json.dump(data, f, ensure_ascii=False, indent=2)
            
            # Ocultar el archivo en Windows para no molestar en la carpeta principal
            if os.name == 'nt':
                import ctypes
                # FILE_ATTRIBUTE_HIDDEN = 0x02
                ctypes.windll.kernel32.SetFileAttributesW(CONFIG_FILE_PATH, 0x02)
        except Exception as e:
            print(f"Error al guardar configuración: {e}")

    def abrir_opciones_avanzadas(self):
        VentanaOpcionesAvanzadas(self, self.api_key, self.prompt_system, self.guardar_opciones_avanzadas)

    def guardar_opciones_avanzadas(self, nueva_api, nuevo_prompt):
        self.api_key = nueva_api
        self.prompt_system = nuevo_prompt
        self.guardar_configuracion()
        self.log("Configuración avanzada guardada con éxito.")

    def seleccionar_carpeta(self):
        p = filedialog.askdirectory(initialdir=self.str_carpeta.get())
        if p: self.str_carpeta.set(p)

    def log(self, m):
        self.after(0, lambda: self._log(m))

    def _log(self, m):
        self.console.configure(state="normal")
        # Colores simples según el prefijo
        color = "#a6adc8" # Default
        if "❌" in m or "⚠️" in m: color = "#f38ba8"
        elif "✨" in m: color = "#a6e3a1"
        elif "🧠" in m or "📡" in m or "🦙" in m: color = "#cba6f7"
        elif "📊" in m: color = "#89b4fa"

        self.console.insert("end", m + "\n")
        # En CTK Textbox no es trivial aplicar tags línea a línea sin heredar, 
        # pero para logs simples la inserción estándar es suficiente.
        self.console.see("end")
        self.console.configure(state="disabled")

    def progress_update(self, val, msg):
        self.after(0, lambda: self._progress_update(val, msg))

    def _progress_update(self, val, msg):
        self.progress.set(val)
        self.lbl_status.configure(text=msg)

    def iniciar(self):
        self.btn_run.configure(state="disabled", text="PROCESANDO...", fg_color="#222222", text_color="#888888")
        self.console.configure(state="normal")
        self.console.delete("1.0", "end")
        self.console.configure(state="disabled")
        
        self.progress.set(0)
        self.lbl_status.configure(text="INICIANDO MOTOR...")

        provider = self.var_ia.get()
        # Esto lee el archivo .env oculto y carga las contraseñas en memoria
        load_dotenv()
        # Datos de los servidores FTP
        FTP_SOURCES = [
            {"host": os.getenv("FTP_EPRESS_HOST"), "user": os.getenv("FTP_EPRESS_USER"), "pass": os.getenv("FTP_EPRESS_PASS"), "path": "/"},
            {"host": os.getenv("FTP_EFE_HOST"), "user": os.getenv("FTP_EFE_USER"), "pass": os.getenv("FTP_EFE_PASS"), "path": "/efe.coonic.com"}
        ]

        def job():
            ruta_seleccionada = self.str_carpeta.get().rstrip("/\\")
            
            # DETERMINAR SI HACEMOS SYNC FTP O SOLO LECTURA
            # Si la ruta es la raíz del proyecto o la carpeta xml-ftp del proyecto, hacemos el ciclo completo
            if ruta_seleccionada == ROOT_DIR or ruta_seleccionada == os.path.join(ROOT_DIR, "xml-ftp"):
                carpeta_xml = os.path.join(ROOT_DIR, "xml-ftp")
                if not os.path.exists(carpeta_xml): os.makedirs(carpeta_xml)
                
                # 1. Limpieza y 2. Descarga (Solo en modo automático)
                limpiar_carpeta_local(carpeta_xml, self.log)
                for src in FTP_SOURCES:
                    descargar_desde_ftp(src["host"], src["user"], src["pass"], src["path"], carpeta_xml, self.log)
            else:
                # MODO MANUAL: Solo leer lo que haya en la carpeta seleccionada
                carpeta_xml = ruta_seleccionada
                self.log(f"📂 Modo manual: Extrayendo solo de {carpeta_xml} (Sin FTP ni limpieza)")

            # Obtener el límite de caracteres del entry con fallback a 1000 si está vacío o no es un número
            try:
                limite_caracteres_val = int(self.entry_limit.get().strip())
            except ValueError:
                limite_caracteres_val = 1000

            # 3. Motor Extractor común
            motor_extractor(
                carpeta_xml, 
                provider, 
                self.api_key, 
                self.log, 
                self.done,
                self.progress_update,
                self.abrir_ventana_seleccion,
                limite_caracteres=limite_caracteres_val,
                prompt_system=self.prompt_system
            )

        threading.Thread(target=job, daemon=True).start()

    def abrir_ventana_seleccion(self, noticias):
        # Ejecutar en el hilo principal
        self.after(0, lambda: self._abrir_ventana_seleccion(noticias))

    def _abrir_ventana_seleccion(self, noticias):
        if not noticias:
            self.log("⚠️ No se encontraron noticias que pasaran los filtros.")
            self.done()
            messagebox.showinfo("Sin resultados", "No hay noticias seleccionadas por la IA para revisar.")
            return
            
        # NUEVA LÓGICA: Solo abrir rescate si hay MENOS de 5 recomendadas
        recomendadas = [n for n in noticias if n.get("ai_selected")]
        if len(recomendadas) >= 5:
            self.log(f"✅ {len(recomendadas)} noticias recomendadas. Generando boletín directamente...")
            self.finalizar_con_seleccion(recomendadas)
        else:
            self.log(f"⚠️ Solo hay {len(recomendadas)} recomendadas. Abriendo ventana de rescate...")
            VentanaSeleccionNoticias(self, noticias, self.finalizar_con_seleccion)

    def finalizar_con_seleccion(self, noticias_finales):
        if not noticias_finales:
            self.log("❌ Generación cancelada: No se seleccionó ninguna noticia.")
            self.done()
            return

        # Ahora sí, generamos los archivos con lo que el usuario eligió
        self.log(f"📄 Generando boletín final con {len(noticias_finales)} noticias...")
        
        resultados_dir = os.path.join(ROOT_DIR, "resultados")
        if not os.path.exists(resultados_dir):
            os.makedirs(resultados_dir)
            
        try:
            generar_pdf(noticias_finales, resultados_dir, self.log)
            generar_rtf(noticias_finales, resultados_dir, self.log)
            
            # Notificar al usuario dónde están los archivos
            self.log(f"📂 Archivos guardados en: {resultados_dir}")
            if os.name == 'nt': # Windows
                os.startfile(resultados_dir)
            elif os.name == 'posix': # Linux
                import subprocess
                subprocess.Popen(['xdg-open', resultados_dir])
        except Exception as e:
            self.log(f"❌ Error al guardar archivos: {e}")
            messagebox.showerror("Error", f"No se pudo generar el boletín: {e}")
        
        self.progress_update(1.0, "✨ ¡Proceso completado!")
        self.log(f"✨ ¡Proceso completado con éxito! Se han incluido {len(noticias_finales)} noticias.")
        self.done()

    def done(self):
        self.after(0, lambda: self.btn_run.configure(state="normal", text="INICIAR EXTRACCIÓN", fg_color="#3A86FF", text_color="#FFFFFF"))

if __name__ == "__main__":
    AppExtractorNoticias().mainloop()