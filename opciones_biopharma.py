#!/usr/bin/env python3
"""
Scanner de volumen anomalo en opciones — Biofarmaceuticas + Empresas españolas en EEUU.
Datos via Yahoo Finance. Email diario a amarchall@gmail.com.
Incluye: señales de opciones, ratio put/call, calendario FDA, track record.
"""

import requests
import smtplib
import os
import time
import json
import uuid
import yfinance as yf
from bs4 import BeautifulSoup
from email.mime.text import MIMEText
from email.mime.multipart import MIMEMultipart
from datetime import datetime, date, timedelta

TRACK_RECORD_FILE = "track_record.json"

# ─── EMPRESAS A VIGILAR ───────────────────────────────────────────────────────

BIOFARMACEUTICAS = {
    "ABBV": "AbbVie",
    "AMGN": "Amgen",
    "BIIB": "Biogen",
    "BMY":  "Bristol-Myers Squibb",
    "GILD": "Gilead Sciences",
    "LLY":  "Eli Lilly",
    "MRK":  "Merck",
    "MRNA": "Moderna",
    "PFE":  "Pfizer",
    "REGN": "Regeneron",
    "VRTX": "Vertex",
    "ALNY": "Alnylam",
    "BMRN": "BioMarin",
    "INCY": "Incyte",
    "JAZZ": "Jazz Pharma",
    "NBIX": "Neurocrine Bio",
    "SRPT": "Sarepta",
    "HALO": "Halozyme",
    "IONS": "Ionis Pharma",
    "KYMR": "Kymera",
    "RARE": "Ultragenyx",
    "ACAD": "Acadia Pharma",
    "RCKT": "Rocket Pharma",
    "FATE": "Fate Therapeutics",
    "XNCR": "Xencor",
    "ZYME": "Zymeworks",
    "PCVX": "Vaxcyte",
    "LEGN": "Legend Biotech",
    "KRYS": "Krystal Biotech",
    "INSM": "Insmed",
    "NTLA": "Intellia Therapeutics",
    "BEAM": "Beam Therapeutics",
    "CRSP": "CRISPR Therapeutics",
    "EDIT": "Editas Medicine",
}

ESPAÑOLAS_EN_EEUU = {
    "SAN":  "Banco Santander (ADR)",
    "BBVA": "BBVA (ADR)",
}

TODOS_TICKERS = {**BIOFARMACEUTICAS, **ESPAÑOLAS_EN_EEUU}

# ─── PARAMETROS ───────────────────────────────────────────────────────────────

UMBRAL_VOL_OI     = 5.0   # subido de 3x a 5x — más convicción institucional
MIN_VOLUMEN       = 200
MIN_OPEN_INTEREST = 50
MAX_VENCIMIENTOS  = 3
MIN_DIAS_VENCIMIENTO = 3   # ignorar opciones que vencen en menos de 3 días
MAX_VARIACION_PCT    = 15.0  # ignorar apuestas que requieren >15% de movimiento
MAX_SEÑALES_TICKER   = 2   # máximo 2 señales por empresa por día

DESTINATARIOS  = ["amarchall@gmail.com", "cmarchal@marchalconsultores.com"]
EMAIL_ORIGEN   = os.environ.get("EMAIL_ORIGEN", "")
EMAIL_PASSWORD = os.environ.get("EMAIL_PASSWORD", "")
TRADIER_TOKEN  = os.environ.get("TRADIER_TOKEN", "")

TRADIER_HEADERS = {
    "Authorization": f"Bearer {TRADIER_TOKEN}",
    "Accept": "application/json"
}
TRADIER_BASE = "https://api.tradier.com/v1/markets"


# ─── ANALISIS ─────────────────────────────────────────────────────────────────

def score_anomalia(volume, ratio):
    score = ratio
    if volume > 1000:  score += 1
    if volume > 5000:  score += 2
    if volume > 10000: score += 3
    return round(score, 1)


def _obtener_oi_tradier(ticker):
    """
    Obtiene Open Interest por (fecha, tipo, strike) desde Tradier.
    Devuelve dict: {(fecha, tipo, strike): oi}
    """
    oi_map = {}
    if not TRADIER_TOKEN:
        return oi_map
    try:
        # Primero obtenemos las fechas de vencimiento disponibles
        r = requests.get(
            f"{TRADIER_BASE}/options/expirations",
            headers=TRADIER_HEADERS,
            params={"symbol": ticker, "includeAllRoots": "true"},
            timeout=10
        )
        if r.status_code != 200:
            return oi_map
        fechas = r.json().get("expirations", {}).get("date", [])
        if isinstance(fechas, str):
            fechas = [fechas]

        # Consultamos los primeros MAX_VENCIMIENTOS
        for fecha in fechas[:MAX_VENCIMIENTOS]:
            r2 = requests.get(
                f"{TRADIER_BASE}/options/chains",
                headers=TRADIER_HEADERS,
                params={"symbol": ticker, "expiration": fecha, "greeks": "false"},
                timeout=10
            )
            if r2.status_code != 200:
                continue
            opts = r2.json().get("options") or {}
            contratos = opts.get("option", []) if opts else []
            if isinstance(contratos, dict):
                contratos = [contratos]
            for c in contratos:
                oi = c.get("open_interest") or 0
                tipo = "CALL" if c.get("option_type") == "call" else "PUT"
                strike = float(c.get("strike", 0))
                if oi > 0:
                    oi_map[(fecha, tipo, strike)] = int(oi)
    except Exception:
        pass
    return oi_map


def analizar_ticker(ticker, nombre):
    """
    Busca opciones con volumen anomalo.
    Volumen: Yahoo Finance (fiable). Open Interest: Tradier (fiable) con fallback a Yahoo.
    """
    anomalias = []
    try:
        stock        = yf.Ticker(ticker)
        precio       = round(getattr(stock.fast_info, "last_price", 0) or 0, 2)
        vencimientos = stock.options

        if precio == 0 or not vencimientos:
            return anomalias

        # OI de Tradier (mas preciso que Yahoo)
        oi_tradier = _obtener_oi_tradier(ticker)

        for fecha in vencimientos[:MAX_VENCIMIENTOS]:

            # Filtro 1: ignorar vencimientos demasiado cercanos
            try:
                dias_hasta_venc = (datetime.strptime(fecha, "%Y-%m-%d").date() - date.today()).days
            except Exception:
                dias_hasta_venc = 99
            if dias_hasta_venc < MIN_DIAS_VENCIMIENTO:
                continue

            chain = stock.option_chain(fecha)
            for tipo_label, df in [("CALL", chain.calls), ("PUT", chain.puts)]:
                if df.empty:
                    continue
                df = df.copy()

                # Enriquecer OI con datos de Tradier cuando esten disponibles
                def get_oi(row, _fecha=fecha, _tipo=tipo_label):
                    clave = (_fecha, _tipo, float(row["strike"]))
                    return oi_tradier.get(clave, row.get("openInterest") or 0)

                df["oi_real"] = df.apply(get_oi, axis=1)

                # Filtrar: volumen minimo + OI minimo + ratio minimo
                df = df[(df["volume"] >= MIN_VOLUMEN) & (df["oi_real"] >= MIN_OPEN_INTEREST)]
                if df.empty:
                    continue

                df["ratio"] = df["volume"] / df["oi_real"]
                df = df[df["ratio"] >= UMBRAL_VOL_OI]

                for _, row in df.iterrows():
                    strike    = row["strike"]
                    oi        = int(row["oi_real"])
                    es_otm    = (tipo_label == "CALL" and strike > precio) or \
                                (tipo_label == "PUT"  and strike < precio)
                    var_pct   = round(abs(strike - precio) / precio * 100, 1) if precio > 0 else 0

                    # Filtro 2: ignorar apuestas que requieren movimientos irreales
                    if var_pct > MAX_VARIACION_PCT:
                        continue

                    precio_op = round(float(row.get("lastPrice") or 0), 2)

                    anomalias.append({
                        "ticker":               ticker,
                        "nombre":               nombre,
                        "tipo":                 tipo_label,
                        "strike":               strike,
                        "vencimiento":          fecha,
                        "volumen":              int(row["volume"]),
                        "open_interest":        oi,
                        "ratio":                round(row["ratio"], 1),
                        "precio_actual":        precio,
                        "otm":                  es_otm,
                        "variacion_pct":        var_pct,
                        "score":                score_anomalia(int(row["volume"]), round(row["ratio"], 1)),
                        "earnings":             None,
                        "ultimo_precio_opcion": precio_op,
                    })
    except Exception:
        pass

    # Filtro 3: máximo MAX_SEÑALES_TICKER por empresa — quedarse con las de mayor score
    anomalias.sort(key=lambda x: x["score"], reverse=True)
    return anomalias[:MAX_SEÑALES_TICKER]


# ─── RATIO PUT/CALL POR EMPRESA ───────────────────────────────────────────────

def calcular_ratio_put_call(ticker):
    """
    Calcula el ratio put/call usando OI de Tradier (mas preciso) con fallback a volumen de Yahoo.
    Un ratio alto (>2) = presion bajista. Ratio bajo (<0.5) = presion alcista.
    """
    # Intentar con OI de Tradier primero (mas representativo que el volumen diario)
    if TRADIER_TOKEN:
        try:
            r = requests.get(
                f"{TRADIER_BASE}/options/expirations",
                headers=TRADIER_HEADERS,
                params={"symbol": ticker, "includeAllRoots": "true"},
                timeout=10
            )
            if r.status_code == 200:
                fechas = r.json().get("expirations", {}).get("date", [])
                if isinstance(fechas, str):
                    fechas = [fechas]
                if fechas:
                    r2 = requests.get(
                        f"{TRADIER_BASE}/options/chains",
                        headers=TRADIER_HEADERS,
                        params={"symbol": ticker, "expiration": fechas[0], "greeks": "false"},
                        timeout=10
                    )
                    if r2.status_code == 200:
                        opts = r2.json().get("options") or {}
                        contratos = opts.get("option", []) if opts else []
                        if isinstance(contratos, dict):
                            contratos = [contratos]
                        oi_calls = sum(c.get("open_interest") or 0 for c in contratos if c.get("option_type") == "call")
                        oi_puts  = sum(c.get("open_interest") or 0 for c in contratos if c.get("option_type") == "put")
                        if oi_calls > 0:
                            return round(oi_puts / oi_calls, 2)
        except Exception:
            pass

    # Fallback: volumen de Yahoo Finance
    try:
        stock = yf.Ticker(ticker)
        fechas = stock.options
        if not fechas:
            return None
        chain = stock.option_chain(fechas[0])
        vol_calls = chain.calls["volume"].fillna(0).sum()
        vol_puts  = chain.puts["volume"].fillna(0).sum()
        if vol_calls == 0:
            return None
        return round(vol_puts / vol_calls, 2)
    except Exception:
        return None


# ─── CONSEJO EN LENGUAJE SIMPLE ───────────────────────────────────────────────

def generar_consejo(a):
    ticker    = a["ticker"]
    nombre    = a["nombre"]
    tipo      = a["tipo"]
    strike    = a["strike"]
    precio    = a["precio_actual"]
    venc      = a["vencimiento"]
    volumen   = a["volumen"]
    ratio     = a["ratio"]
    otm       = a["otm"]
    var_pct   = a["variacion_pct"]
    precio_op = a["ultimo_precio_opcion"]

    try:
        dias_restantes = (datetime.strptime(venc, "%Y-%m-%d").date() - date.today()).days
        venc_legible   = datetime.strptime(venc, "%Y-%m-%d").strftime("%d de %B de %Y")
    except Exception:
        dias_restantes = 30
        venc_legible   = venc

    if dias_restantes <= 14:
        urgencia = "🔴 Apuesta a MUY CORTO PLAZO"
        urgencia_texto = f"solo quedan <b>{dias_restantes} dias</b> — alguien espera un movimiento muy rapido"
    elif dias_restantes <= 45:
        urgencia = "🟡 Apuesta a CORTO PLAZO"
        urgencia_texto = f"quedan <b>{dias_restantes} dias</b> hasta el vencimiento"
    else:
        urgencia = "🟢 Apuesta a MEDIO PLAZO"
        urgencia_texto = f"quedan <b>{dias_restantes} dias</b> hasta el vencimiento"

    coste_aprox = f"~${round(precio_op * 100, 0):,.0f} por contrato" if precio_op > 0 else "consulta el precio en tu broker"

    if tipo == "CALL":
        if otm:
            explicacion = (f"Alguien ha apostado fuerte a que <b>{nombre} ({ticker})</b> va a subir un <b>{var_pct}%</b> "
                           f"en los proximos {dias_restantes} dias. Ahora cotiza a <b>${precio}</b> y la apuesta es que "
                           f"llegue a <b>${strike}</b> antes del {venc_legible}. "
                           f"Es una apuesta <b>agresiva</b> ({volumen:,} contratos, {ratio}x la actividad normal). {urgencia_texto.capitalize()}.")
        else:
            explicacion = (f"Alguien apuesta a que <b>{nombre} ({ticker})</b> va a mantenerse por encima de <b>${strike}</b> "
                           f"(ahora cotiza a <b>${precio}</b>). Con {volumen:,} contratos y ratio {ratio}x. {urgencia_texto.capitalize()}.")
        operacion_1  = f"Comprar un CALL de <b>{ticker}</b> con strike <b>${strike}</b> y vencimiento <b>{venc_legible}</b>"
        operacion_2  = f"Comprar acciones de <b>{ticker}</b> directamente a precio de mercado (~${precio})"
        ganancia_op1 = f"Si {ticker} llega a ${strike}, la opcion podria multiplicar su valor varias veces"
        ganancia_op2 = "Ganas proporcionalmente si la accion sube"
        riesgo_op1   = f"Pierdes todo lo invertido si la accion no llega a ${strike} antes del vencimiento"
        riesgo_op2   = "Solo pierdes si la accion baja de precio"
        color_titulo = "#1a7f37"
        emoji_tipo   = "📈 SEÑAL ALCISTA"
    else:
        if otm:
            explicacion = (f"Alguien ha apostado fuerte a que <b>{nombre} ({ticker})</b> va a CAER un <b>{var_pct}%</b> "
                           f"en los proximos {dias_restantes} dias. Ahora cotiza a <b>${precio}</b> y la apuesta es que "
                           f"baje a <b>${strike}</b> antes del {venc_legible}. "
                           f"Con {volumen:,} contratos y ratio {ratio}x. {urgencia_texto.capitalize()}.")
        else:
            explicacion = (f"Alguien apuesta a que <b>{nombre} ({ticker})</b> va a CAER por debajo de <b>${strike}</b> "
                           f"(ahora cotiza a <b>${precio}</b>). Con {volumen:,} contratos y ratio {ratio}x. {urgencia_texto.capitalize()}.")
        operacion_1  = f"Comprar un PUT de <b>{ticker}</b> con strike <b>${strike}</b> y vencimiento <b>{venc_legible}</b>"
        operacion_2  = f"Si tienes acciones de <b>{ticker}</b>, considera poner un stop-loss en ~${round(precio * 0.95, 2)}"
        ganancia_op1 = f"Si {ticker} cae a ${strike}, la opcion podria multiplicar su valor"
        ganancia_op2 = "Proteges tu cartera si tienes esa accion"
        riesgo_op1   = "Pierdes la prima si la accion no cae lo suficiente"
        riesgo_op2   = "Si no tienes la accion, esta opcion no aplica directamente"
        color_titulo = "#cf222e"
        emoji_tipo   = "📉 SEÑAL BAJISTA"

    if otm and dias_restantes <= 14:
        nivel_riesgo = "🔴 MUY ALTO — opcion agresiva con poco tiempo"
    elif otm:
        nivel_riesgo = "🟠 ALTO — apuesta especulativa"
    elif dias_restantes <= 14:
        nivel_riesgo = "🟡 MEDIO-ALTO — poco tiempo pero precio razonable"
    else:
        nivel_riesgo = "🟡 MEDIO — opcion mas conservadora"

    return dict(emoji_tipo=emoji_tipo, color_titulo=color_titulo, urgencia=urgencia,
                explicacion=explicacion, operacion_1=operacion_1, coste_aprox=coste_aprox,
                ganancia_op1=ganancia_op1, riesgo_op1=riesgo_op1, operacion_2=operacion_2,
                ganancia_op2=ganancia_op2, riesgo_op2=riesgo_op2, nivel_riesgo=nivel_riesgo)


# ─── CALENDARIO FDA (PDUFA) ──────────────────────────────────────────────────

# Mapa de nombres parciales -> ticker (para cruzar con nuestros tickers)
NOMBRE_A_TICKER = {
    "abbvie": "ABBV", "amgen": "AMGN", "biogen": "BIIB",
    "bristol": "BMY", "gilead": "GILD", "eli lilly": "LLY", "lilly": "LLY",
    "merck": "MRK", "moderna": "MRNA", "pfizer": "PFE",
    "regeneron": "REGN", "vertex": "VRTX", "alnylam": "ALNY",
    "biomarin": "BMRN", "biopharma": None, "incyte": "INCY",
    "jazz": "JAZZ", "neurocrine": "NBIX", "sarepta": "SRPT",
    "halozyme": "HALO", "ionis": "IONS", "kymera": "KYMR",
    "ultragenyx": "RARE", "acadia": "ACAD", "rocket": "RCKT",
    "fate": "FATE", "xencor": "XNCR", "zymeworks": "ZYME",
    "vaxcyte": "PCVX", "legend": "LEGN", "krystal": "KRYS",
    "insmed": "INSM", "intellia": "NTLA", "beam": "BEAM",
    "crispr": "CRSP", "editas": "EDIT",
}


def obtener_calendario_fda(dias_adelante=60):
    """
    Obtiene proximas fechas PDUFA de BiopharmaCatalyst y drugs.com.
    Devuelve lista de dicts: {ticker, nombre, farmaco, fecha, dias_restantes, descripcion}
    """
    eventos = []

    # ── Fuente 1: drugs.com/pdufa ──
    try:
        headers = {
            "User-Agent": "Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) "
                          "AppleWebKit/537.36 (KHTML, like Gecko) Chrome/120.0 Safari/537.36"
        }
        resp = requests.get("https://www.drugs.com/pdufa/", headers=headers, timeout=15)
        if resp.status_code == 200:
            soup = BeautifulSoup(resp.text, "lxml")
            hoy  = date.today()

            for row in soup.select("table tr"):
                celdas = row.find_all("td")
                if len(celdas) < 3:
                    continue
                try:
                    fecha_txt = celdas[0].get_text(strip=True)
                    farmaco   = celdas[1].get_text(strip=True)
                    empresa   = celdas[2].get_text(strip=True) if len(celdas) > 2 else ""
                    indicacion= celdas[3].get_text(strip=True) if len(celdas) > 3 else ""

                    # Intentar parsear fecha
                    fecha = None
                    for fmt in ("%B %d, %Y", "%b %d, %Y", "%m/%d/%Y", "%Y-%m-%d"):
                        try:
                            fecha = datetime.strptime(fecha_txt, fmt).date()
                            break
                        except ValueError:
                            continue

                    if fecha is None:
                        continue

                    dias = (fecha - hoy).days
                    if dias < 0 or dias > dias_adelante:
                        continue

                    # Cruzar empresa con nuestros tickers
                    empresa_lower = empresa.lower()
                    ticker = None
                    for clave, sym in NOMBRE_A_TICKER.items():
                        if clave in empresa_lower and sym:
                            ticker = sym
                            break

                    if ticker and ticker in TODOS_TICKERS:
                        eventos.append({
                            "ticker":         ticker,
                            "nombre":         TODOS_TICKERS[ticker],
                            "farmaco":        farmaco,
                            "indicacion":     indicacion,
                            "fecha":          str(fecha),
                            "dias_restantes": dias,
                            "fuente":         "drugs.com"
                        })
                except Exception:
                    continue
    except Exception:
        pass

    # ── Fuente 2: biopharmacatalyst.com ──
    if len(eventos) == 0:
        try:
            headers = {
                "User-Agent": "Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) "
                              "AppleWebKit/537.36 (KHTML, like Gecko) Chrome/120.0 Safari/537.36",
                "Accept": "text/html,application/xhtml+xml",
            }
            resp = requests.get(
                "https://www.biopharmacatalyst.com/calendars/fda-calendar",
                headers=headers, timeout=15
            )
            if resp.status_code == 200:
                soup = BeautifulSoup(resp.text, "lxml")
                hoy  = date.today()

                for row in soup.select("tr.fda-event, tr[data-ticker]"):
                    try:
                        ticker_attr = row.get("data-ticker", "").upper().strip()
                        if not ticker_attr or ticker_attr not in TODOS_TICKERS:
                            continue

                        fecha_cel  = row.select_one(".date, td:nth-child(1)")
                        drug_cel   = row.select_one(".drug, td:nth-child(2)")
                        indic_cel  = row.select_one(".indication, td:nth-child(3)")

                        fecha_txt  = fecha_cel.get_text(strip=True) if fecha_cel else ""
                        farmaco    = drug_cel.get_text(strip=True)  if drug_cel  else ""
                        indicacion = indic_cel.get_text(strip=True) if indic_cel else ""

                        fecha = None
                        for fmt in ("%b %d, %Y", "%B %d, %Y", "%Y-%m-%d", "%m/%d/%Y"):
                            try:
                                fecha = datetime.strptime(fecha_txt, fmt).date()
                                break
                            except ValueError:
                                continue

                        if fecha is None:
                            continue

                        dias = (fecha - hoy).days
                        if dias < 0 or dias > dias_adelante:
                            continue

                        eventos.append({
                            "ticker":         ticker_attr,
                            "nombre":         TODOS_TICKERS[ticker_attr],
                            "farmaco":        farmaco,
                            "indicacion":     indicacion,
                            "fecha":          str(fecha),
                            "dias_restantes": dias,
                            "fuente":         "biopharmacatalyst"
                        })
                    except Exception:
                        continue
        except Exception:
            pass

    # Deduplicar y ordenar por fecha
    vistos = set()
    resultado = []
    for e in sorted(eventos, key=lambda x: x["fecha"]):
        clave = f"{e['ticker']}-{e['fecha']}-{e['farmaco'][:10]}"
        if clave not in vistos:
            vistos.add(clave)
            resultado.append(e)

    return resultado


def construir_seccion_fda(eventos_fda):
    """Construye la seccion HTML del calendario FDA para el email."""
    if not eventos_fda:
        return ""

    hoy = date.today()

    html = ["""
    <div style="background:#f0f4ff;border:2px solid #1a3a8f;border-radius:10px;margin-bottom:24px;overflow:hidden">
        <div style="background:#1a3a8f;color:white;padding:14px 18px">
            <h2 style="margin:0;font-size:16px">🏛️ Calendario FDA — Decisiones proximas</h2>
            <p style="margin:4px 0 0 0;opacity:0.8;font-size:12px">
                Fechas PDUFA: cuando la FDA debe aprobar o rechazar un medicamento.
                Son los eventos que mas mueven las opciones biopharma.
            </p>
        </div>
        <div style="padding:14px 18px">
    """]

    for e in eventos_fda:
        dias  = e["dias_restantes"]
        ticker = e["ticker"]
        nombre = e["nombre"]
        farmaco = e["farmaco"]
        indicacion = e["indicacion"]

        if dias <= 7:
            urgencia_color = "#cf222e"
            urgencia_txt   = f"🔴 <b>ESTA SEMANA</b> — {dias} dia{'s' if dias != 1 else ''}"
            border_color   = "#cf222e"
        elif dias <= 14:
            urgencia_color = "#e36700"
            urgencia_txt   = f"🟠 En <b>{dias} dias</b>"
            border_color   = "#e36700"
        elif dias <= 30:
            urgencia_color = "#9a6700"
            urgencia_txt   = f"🟡 En <b>{dias} dias</b>"
            border_color   = "#9a6700"
        else:
            urgencia_color = "#555"
            urgencia_txt   = f"🔵 En <b>{dias} dias</b>"
            border_color   = "#aaa"

        # Formatear fecha legible
        try:
            fecha_legible = datetime.strptime(e["fecha"], "%Y-%m-%d").strftime("%-d de %B de %Y")
        except Exception:
            fecha_legible = e["fecha"]

        indicacion_html = f'<div style="font-size:11px;color:#555;margin-top:3px">{indicacion}</div>' if indicacion else ""

        html.append(f"""
        <div style="border-left:4px solid {border_color};background:white;border-radius:6px;
                    padding:12px 14px;margin-bottom:10px;box-shadow:0 1px 3px rgba(0,0,0,0.06)">
            <div style="display:flex;justify-content:space-between;align-items:center;flex-wrap:wrap;gap:6px">
                <div>
                    <span style="font-weight:bold;font-size:14px">{ticker}</span>
                    <span style="color:#555;font-size:13px"> — {nombre}</span>
                </div>
                <span style="font-size:12px;color:{urgencia_color}">{urgencia_txt}</span>
            </div>
            <div style="margin-top:6px;font-size:13px">
                💊 <b>{farmaco}</b>
                {indicacion_html}
            </div>
            <div style="margin-top:4px;font-size:12px;color:#777">
                📅 Fecha PDUFA: <b>{fecha_legible}</b>
            </div>
            <div style="margin-top:6px;font-size:12px;background:#fffbe6;border-radius:4px;padding:6px 8px;color:#7a5100">
                ⚡ Una decision de la FDA puede mover la accion entre un 20% y un 80% en un dia.
                Esto explica gran parte de la actividad inusual en opciones de esta empresa.
            </div>
        </div>""")

    html.append("</div></div>")
    return "\n".join(html)


# ─── CONSTRUCCION DEL EMAIL ───────────────────────────────────────────────────

def construir_email(todas_anomalias, ratios_pc, eventos_fda=None):
    hoy   = datetime.now().strftime("%d/%m/%Y")
    calls = sorted([a for a in todas_anomalias if a["tipo"] == "CALL"], key=lambda x: x["score"], reverse=True)
    puts  = sorted([a for a in todas_anomalias if a["tipo"] == "PUT"],  key=lambda x: x["score"], reverse=True)

    if len(calls) > len(puts) * 1.5:
        sesgo, sesgo_color = "ALCISTA 📈", "#1a7f37"
    elif len(puts) > len(calls) * 1.5:
        sesgo, sesgo_color = "BAJISTA 📉", "#cf222e"
    else:
        sesgo, sesgo_color = "NEUTRAL ⚖️", "#9a6700"

    html = [f"""
    <div style="font-family:Arial,sans-serif;max-width:680px;margin:auto;color:#1a1a1a">
    <div style="background:#1a1a2e;color:white;padding:24px;border-radius:10px;margin-bottom:20px">
        <div style="font-size:11px;letter-spacing:3px;text-transform:uppercase;opacity:0.5;margin-bottom:6px">HookFlow</div>
        <h1 style="margin:0;font-size:22px;font-weight:800">Catch the smart money before the move happens.</h1>
        <p style="margin:8px 0 0 0;opacity:0.6;font-size:12px">{hoy} · {len(todas_anomalias)} señales detectadas · Biopharma Options Scanner</p>
    </div>
    <table style="width:100%;border-collapse:collapse;margin-bottom:24px">
        <tr>
            <td style="background:#f0fff4;padding:14px;border-radius:8px;text-align:center;width:30%">
                <div style="font-size:32px;font-weight:bold;color:#1a7f37">{len(calls)}</div>
                <div style="color:#666;font-size:13px">señales ALCISTAS</div>
            </td>
            <td style="width:5%"></td>
            <td style="background:#fff0f0;padding:14px;border-radius:8px;text-align:center;width:30%">
                <div style="font-size:32px;font-weight:bold;color:#cf222e">{len(puts)}</div>
                <div style="color:#666;font-size:13px">señales BAJISTAS</div>
            </td>
            <td style="width:5%"></td>
            <td style="background:#fffbe6;padding:14px;border-radius:8px;text-align:center;width:30%">
                <div style="font-size:20px;font-weight:bold;color:{sesgo_color}">{sesgo}</div>
                <div style="color:#666;font-size:13px">sesgo general</div>
            </td>
        </tr>
    </table>
    """]

    # ── Señales individuales — PRIMERO ──
    if not todas_anomalias:
        html.append("""
        <div style="background:#f6f8fa;border-radius:8px;padding:24px;text-align:center;color:#666">
            <div style="font-size:40px">😴</div>
            <p><b>Hoy no hay actividad inusual.</b><br>El mercado esta tranquilo en las empresas vigiladas.</p>
        </div>""")
    else:
        for a in calls + puts:
            c = generar_consejo(a)
            otm_badge = '<span style="background:#ff9800;color:white;font-size:11px;padding:2px 6px;border-radius:4px;margin-left:6px">FUERA DEL PRECIO</span>' if a["otm"] else ""
            html.append(f"""
        <div style="border:2px solid {c['color_titulo']};border-radius:10px;margin-bottom:24px;overflow:hidden">
            <div style="background:{c['color_titulo']};color:white;padding:14px 18px">
                <div style="font-size:18px;font-weight:bold">{c['emoji_tipo']} — {a['nombre']} ({a['ticker']}){otm_badge}</div>
                <div style="opacity:0.9;font-size:13px;margin-top:4px">{c['urgencia']} &nbsp;·&nbsp; Score: {a['score']} &nbsp;·&nbsp; Ratio: {a['ratio']}x lo normal</div>
            </div>
            <div style="padding:16px 18px">
                <div style="background:#f6f8fa;border-radius:6px;padding:12px;margin-bottom:14px">
                    <div style="font-weight:bold;margin-bottom:6px">🔍 ¿Que esta pasando?</div>
                    <div style="font-size:14px;line-height:1.6">{c['explicacion']}</div>
                </div>
                <table style="width:100%;border-collapse:collapse;margin-bottom:14px;font-size:13px">
                    <tr style="background:#f0f0f0">
                        <td style="padding:6px 10px"><b>Precio actual</b></td>
                        <td style="padding:6px 10px"><b>Strike (objetivo)</b></td>
                        <td style="padding:6px 10px"><b>Vence el</b></td>
                        <td style="padding:6px 10px"><b>Contratos apostados</b></td>
                    </tr>
                    <tr>
                        <td style="padding:8px 10px;font-size:16px"><b>${a['precio_actual']}</b></td>
                        <td style="padding:8px 10px;font-size:16px"><b>${a['strike']}</b></td>
                        <td style="padding:8px 10px">{a['vencimiento']}</td>
                        <td style="padding:8px 10px"><b>{a['volumen']:,}</b> contratos</td>
                    </tr>
                </table>
                <div style="font-weight:bold;margin-bottom:10px">💡 ¿Que puedes hacer?</div>
                <div style="border:1px solid #ddd;border-radius:6px;padding:12px;margin-bottom:10px">
                    <div style="font-weight:bold;color:{c['color_titulo']};margin-bottom:6px">Opcion 1 — Seguir la apuesta (MAS AGRESIVO)</div>
                    <div style="font-size:13px;line-height:1.7">
                        👉 {c['operacion_1']}<br>
                        💰 Coste aproximado: <b>{c['coste_aprox']}</b><br>
                        ✅ Si funciona: {c['ganancia_op1']}<br>
                        ❌ Si no funciona: {c['riesgo_op1']}
                    </div>
                </div>
                <div style="border:1px solid #ddd;border-radius:6px;padding:12px;margin-bottom:10px">
                    <div style="font-weight:bold;color:#0066cc;margin-bottom:6px">Opcion 2 — Alternativa mas conservadora</div>
                    <div style="font-size:13px;line-height:1.7">
                        👉 {c['operacion_2']}<br>
                        ✅ Si funciona: {c['ganancia_op2']}<br>
                        ❌ Riesgo: {c['riesgo_op2']}
                    </div>
                </div>
                <div style="font-size:13px;color:#555">⚠️ <b>Nivel de riesgo:</b> {c['nivel_riesgo']}</div>
            </div>
        </div>""")

    # ── Ratio Put/Call — despues de las señales ──
    ratios_interesantes = {t: r for t, r in ratios_pc.items() if r is not None and (r >= 2.0 or r <= 0.5)}
    if ratios_interesantes:
        html.append("""
        <div style="background:#f0f4ff;border-radius:8px;padding:16px;margin-bottom:20px">
        <h3 style="margin:0 0 10px 0;font-size:15px">📊 Ratio Put/Call destacado — presion sostenida</h3>
        <p style="font-size:12px;color:#555;margin:0 0 10px 0">
            Un ratio alto (&gt;2) indica mucha mas apuesta bajista que alcista. Un ratio bajo (&lt;0.5) indica presion alcista fuerte.
        </p>
        <table style="width:100%;border-collapse:collapse;font-size:13px">
        <tr style="background:#dce8ff"><th style="padding:6px">Empresa</th><th style="padding:6px">Ratio Put/Call</th><th style="padding:6px">Señal</th></tr>
        """)
        for ticker, ratio in sorted(ratios_interesantes.items(), key=lambda x: x[1], reverse=True):
            nombre = TODOS_TICKERS.get(ticker, ticker)
            if ratio >= 2.0:
                señal = "⚠️ Presion bajista fuerte"
                color = "#cf222e"
            else:
                señal = "✅ Presion alcista fuerte"
                color = "#1a7f37"
            html.append(f"""
            <tr><td style="padding:6px"><b>{ticker}</b> — {nombre}</td>
            <td style="padding:6px;text-align:center;font-weight:bold;color:{color}">{ratio}</td>
            <td style="padding:6px">{señal}</td></tr>
            """)
        html.append("</table></div>")

    # ── Calendario FDA ──
    if eventos_fda:
        html.append(construir_seccion_fda(eventos_fda))

    # Track record (se pasa como parametro)
    html.append("<!-- TRACK_RECORD_PLACEHOLDER -->")

    html.append("""
    <div style="background:#f6f8fa;border-radius:8px;padding:16px;font-size:12px;color:#666;margin-top:16px">
        <b>⚠️ Aviso:</b> Solo informativo. Las opciones son instrumentos de alto riesgo.
        Puedes perder toda la cantidad invertida. Consulta con un asesor financiero.
    </div></div>""")

    return "\n".join(html)


# ─── ENVIO DE EMAIL ───────────────────────────────────────────────────────────

def enviar_email(cuerpo_html, n_anomalias):
    if not EMAIL_ORIGEN or not EMAIL_PASSWORD:
        print("ERROR: faltan credenciales de email.")
        return False

    asunto = f"HookFlow — {n_anomalias} señales detectadas — {datetime.now().strftime('%d/%m/%Y')}" \
             if n_anomalias > 0 else f"HookFlow — Sin actividad inusual hoy — {datetime.now().strftime('%d/%m/%Y')}"

    msg = MIMEMultipart("alternative")
    msg["Subject"] = asunto
    msg["From"]    = EMAIL_ORIGEN
    msg["To"]      = ", ".join(DESTINATARIOS)
    msg.attach(MIMEText(cuerpo_html, "html"))

    try:
        with smtplib.SMTP_SSL("smtp.gmail.com", 465) as server:
            server.login(EMAIL_ORIGEN, EMAIL_PASSWORD)
            server.sendmail(EMAIL_ORIGEN, DESTINATARIOS, msg.as_string())
        print(f"✅ Email enviado a {', '.join(DESTINATARIOS)}")
        return True
    except Exception as e:
        print(f"❌ Error: {e}")
        return False


# ─── TRACK RECORD ────────────────────────────────────────────────────────────

def cargar_track_record():
    try:
        with open(TRACK_RECORD_FILE, "r") as f:
            return json.load(f)
    except Exception:
        return []


def guardar_track_record(registros):
    with open(TRACK_RECORD_FILE, "w") as f:
        json.dump(registros, f, indent=2, default=str)


def obtener_precio_historico(ticker, fecha_str):
    """Precio de cierre de una accion en una fecha concreta."""
    try:
        datos = yf.download(ticker, start=fecha_str, end=fecha_str, progress=False, auto_adjust=True)
        if datos.empty:
            # Si cae en fin de semana, coger el siguiente dia habil
            import pandas as pd
            fecha = datetime.strptime(fecha_str, "%Y-%m-%d")
            for offset in range(1, 5):
                siguiente = (fecha + pd.Timedelta(days=offset)).strftime("%Y-%m-%d")
                siguiente_fin = (fecha + pd.Timedelta(days=offset+1)).strftime("%Y-%m-%d")
                datos = yf.download(ticker, start=siguiente, end=siguiente_fin, progress=False, auto_adjust=True)
                if not datos.empty:
                    break
        if not datos.empty:
            return round(float(datos["Close"].iloc[-1]), 2)
    except Exception:
        pass
    return None


def registrar_nuevas_señales(anomalias, registros_existentes):
    """Añade las señales de hoy al track record si no existen ya."""
    ids_existentes = {r["id"] for r in registros_existentes}
    nuevos = 0
    for a in anomalias:
        # Clave unica: ticker + tipo + strike + vencimiento + fecha_señal
        clave = f"{a['ticker']}-{a['tipo']}-{a['strike']}-{a['vencimiento']}-{date.today()}"
        if clave in ids_existentes:
            continue
        registros_existentes.append({
            "id":                    clave,
            "fecha_señal":           str(date.today()),
            "ticker":                a["ticker"],
            "nombre":                a["nombre"],
            "tipo":                  a["tipo"],
            "strike":                a["strike"],
            "vencimiento":           a["vencimiento"],
            "precio_accion_señal":   a["precio_actual"],
            "precio_opcion_señal":   a["ultimo_precio_opcion"],
            "score":                 a["score"],
            "ratio":                 a["ratio"],
            "otm":                   a["otm"],
            "variacion_necesaria_pct": a["variacion_pct"],
            "estado":                "pendiente",
            "precio_accion_vencimiento": None,
            "precio_spy_señal":      None,
            "precio_spy_vencimiento": None,
            "resultado":             None,
            "ganancia_opcion_pct":   None,
            "ganancia_spy_pct":      None,
            "fecha_evaluacion":      None,
        })
        nuevos += 1
    return nuevos


def evaluar_señales_vencidas(registros):
    """Comprueba las señales cuya fecha de vencimiento ya paso y calcula resultado."""
    hoy        = date.today()
    evaluados  = 0

    for r in registros:
        if r["estado"] != "pendiente":
            continue
        try:
            fecha_venc = datetime.strptime(r["vencimiento"], "%Y-%m-%d").date()
        except Exception:
            continue

        if fecha_venc > hoy:
            continue  # aun no ha vencido

        # Obtener precio al vencimiento
        precio_venc = obtener_precio_historico(r["ticker"], r["vencimiento"])
        if precio_venc is None:
            continue

        # Obtener precio SPY en fecha señal y vencimiento (benchmark)
        precio_spy_señal = obtener_precio_historico("SPY", r["fecha_señal"]) or 0
        precio_spy_venc  = obtener_precio_historico("SPY", r["vencimiento"]) or 0

        precio_señal = r["precio_accion_señal"]
        strike       = r["strike"]
        tipo         = r["tipo"]

        # ¿Habria ganado la opcion?
        if tipo == "CALL":
            en_dinero = precio_venc > strike
            variacion_real = round((precio_venc - precio_señal) / precio_señal * 100, 2)
        else:
            en_dinero = precio_venc < strike
            variacion_real = round((precio_señal - precio_venc) / precio_señal * 100, 2)

        ganancia_spy = round((precio_spy_venc - precio_spy_señal) / precio_spy_señal * 100, 2) \
                       if precio_spy_señal > 0 else 0

        r["estado"]                  = "ganancia" if en_dinero else "perdida"
        r["precio_accion_vencimiento"] = precio_venc
        r["precio_spy_señal"]        = precio_spy_señal
        r["precio_spy_vencimiento"]  = precio_spy_venc
        r["resultado"]               = "✅ GANANCIA" if en_dinero else "❌ PERDIDA"
        r["ganancia_opcion_pct"]     = variacion_real
        r["ganancia_spy_pct"]        = ganancia_spy
        r["fecha_evaluacion"]        = str(hoy)
        evaluados += 1

    return evaluados


def construir_seccion_track_record(registros, todos_registros=None):
    if todos_registros is None:
        todos_registros = registros
    """Construye la seccion HTML del track record para el email."""
    cerrados = [r for r in registros if r["estado"] in ("ganancia", "perdida")]
    pendientes = [r for r in registros if r["estado"] == "pendiente"]

    if not cerrados and not pendientes:
        return ""

    # Estadisticas globales
    ganancias  = [r for r in cerrados if r["estado"] == "ganancia"]
    perdidas   = [r for r in cerrados if r["estado"] == "perdida"]
    total_c    = len(cerrados)
    pct_acierto = round(len(ganancias) / total_c * 100) if total_c > 0 else 0

    # Comparativa vs SPY
    gan_med_op  = round(sum(r["ganancia_opcion_pct"] or 0 for r in ganancias) / len(ganancias), 1) if ganancias else 0
    spy_med     = round(sum(r["ganancia_spy_pct"] or 0 for r in cerrados) / total_c, 1) if total_c > 0 else 0

    color_acierto = "#1a7f37" if pct_acierto >= 50 else "#cf222e"

    # Comprobar si hay datos simulados (fechas anteriores al primer dia real)
    tiene_simulados = any(r.get("fecha_señal","") < "2026-05-14" for r in registros)

    aviso_simulacion = ""
    if tiene_simulados:
        aviso_simulacion = """
        <div style="background:#fff8e1;border-bottom:1px solid #ffe082;padding:10px 18px;font-size:12px;color:#7a5100">
            &#9888;&#65039; <b>Datos de ejemplo &mdash; SIMULACION.</b> Las señales anteriores al 14/05/2026 son ilustrativas
            y no corresponden a detecciones reales. El track record real comenzara a acumularse desde hoy.
        </div>"""

    html = [f"""
    <div style="margin-top:30px;border:2px solid #1a1a2e;border-radius:10px;overflow:hidden">
        <div style="background:#1a1a2e;color:white;padding:14px 18px">
            <h2 style="margin:0;font-size:17px">&#128200; Track Record &mdash; Historial de señales</h2>
            <p style="margin:4px 0 0 0;opacity:0.8;font-size:12px">Seguimiento automatico de todas las recomendaciones anteriores</p>
        </div>
        {aviso_simulacion}
        <div style="padding:16px 18px">
    """]

    # Resumen
    if total_c > 0:
        html.append(f"""
        <table style="width:100%;border-collapse:collapse;margin-bottom:20px">
            <tr>
                <td style="background:#f0f4ff;padding:12px;border-radius:8px;text-align:center;width:22%">
                    <div style="font-size:26px;font-weight:bold;color:{color_acierto}">{pct_acierto}%</div>
                    <div style="font-size:11px;color:#666">tasa de acierto</div>
                </td>
                <td style="width:3%"></td>
                <td style="background:#f0fff4;padding:12px;border-radius:8px;text-align:center;width:22%">
                    <div style="font-size:26px;font-weight:bold;color:#1a7f37">{len(ganancias)}</div>
                    <div style="font-size:11px;color:#666">señales acertadas</div>
                </td>
                <td style="width:3%"></td>
                <td style="background:#fff0f0;padding:12px;border-radius:8px;text-align:center;width:22%">
                    <div style="font-size:26px;font-weight:bold;color:#cf222e">{len(perdidas)}</div>
                    <div style="font-size:11px;color:#666">señales fallidas</div>
                </td>
                <td style="width:3%"></td>
                <td style="background:#fffbe6;padding:12px;border-radius:8px;text-align:center;width:22%">
                    <div style="font-size:14px;font-weight:bold;color:#9a6700">
                        Señales: {gan_med_op:+.1f}%<br>SPY: {spy_med:+.1f}%
                    </div>
                    <div style="font-size:11px;color:#666">variacion media</div>
                </td>
            </tr>
        </table>
        """)

    # Señales pendientes (aun no vencidas)
    if pendientes:
        pendientes_ordenados = sorted(pendientes, key=lambda x: x["vencimiento"])
        html.append(f"""
        <h4 style="margin:0 0 8px 0;color:#555">⏳ Señales en curso ({len(pendientes)})</h4>
        <table style="width:100%;border-collapse:collapse;font-size:12px;margin-bottom:16px">
        <tr style="background:#e8eaf6">
            <th style="padding:6px;text-align:left">Empresa</th>
            <th style="padding:6px">Tipo</th>
            <th style="padding:6px">Strike</th>
            <th style="padding:6px">Precio señal</th>
            <th style="padding:6px">Vence</th>
            <th style="padding:6px">Necesita</th>
        </tr>
        """)
        for r in pendientes_ordenados[:10]:
            dias = (datetime.strptime(r["vencimiento"], "%Y-%m-%d").date() - date.today()).days
            color_tipo = "#1a7f37" if r["tipo"] == "CALL" else "#cf222e"
            html.append(f"""
            <tr style="border-bottom:1px solid #eee">
                <td style="padding:6px"><b>{r['ticker']}</b></td>
                <td style="padding:6px;text-align:center;color:{color_tipo};font-weight:bold">{r['tipo']}</td>
                <td style="padding:6px;text-align:center">${r['strike']}</td>
                <td style="padding:6px;text-align:center">${r['precio_accion_señal']}</td>
                <td style="padding:6px;text-align:center">{r['vencimiento']}<br><span style="color:#888;font-size:10px">{dias} dias</span></td>
                <td style="padding:6px;text-align:center">
                    {'subir' if r['tipo'] == 'CALL' else 'bajar'} {r['variacion_necesaria_pct']}%
                </td>
            </tr>""")
        html.append("</table>")

    # Historial de señales cerradas
    if cerrados:
        cerrados_ordenados = sorted(cerrados, key=lambda x: x.get("fecha_evaluacion",""), reverse=True)
        html.append(f"""
        <h4 style="margin:16px 0 8px 0;color:#555">📋 Historial de señales vencidas ({total_c})</h4>
        <table style="width:100%;border-collapse:collapse;font-size:12px">
        <tr style="background:#f0f0f0">
            <th style="padding:6px;text-align:left">Empresa</th>
            <th style="padding:6px">Tipo</th>
            <th style="padding:6px">Strike</th>
            <th style="padding:6px">Precio entrada</th>
            <th style="padding:6px">Precio venc.</th>
            <th style="padding:6px">Resultado</th>
            <th style="padding:6px">Accion</th>
            <th style="padding:6px">vs SPY</th>
        </tr>
        """)
        for r in cerrados_ordenados[:20]:
            bg = "#f0fff4" if r["estado"] == "ganancia" else "#fff0f0"
            gan_color = "#1a7f37" if r["estado"] == "ganancia" else "#cf222e"
            spy_color = "#1a7f37" if (r.get("ganancia_spy_pct") or 0) > 0 else "#cf222e"
            html.append(f"""
            <tr style="background:{bg};border-bottom:1px solid #eee">
                <td style="padding:6px"><b>{r['ticker']}</b><br><span style="font-size:10px;color:#888">{r['fecha_señal']}</span></td>
                <td style="padding:6px;text-align:center;color:{'#1a7f37' if r['tipo']=='CALL' else '#cf222e'};font-weight:bold">{r['tipo']}</td>
                <td style="padding:6px;text-align:center">${r['strike']}</td>
                <td style="padding:6px;text-align:center">${r['precio_accion_señal']}</td>
                <td style="padding:6px;text-align:center">${r.get('precio_accion_vencimiento','—')}</td>
                <td style="padding:6px;text-align:center;font-weight:bold;color:{gan_color}">{r.get('resultado','—')}</td>
                <td style="padding:6px;text-align:center;color:{gan_color}">{r.get('ganancia_opcion_pct',0):+.1f}%</td>
                <td style="padding:6px;text-align:center;color:{spy_color}">{r.get('ganancia_spy_pct',0):+.1f}%</td>
            </tr>""")
        html.append("</table>")
        html.append("""
        <p style="font-size:11px;color:#888;margin-top:8px">
            * "Accion" muestra la variacion del precio de la accion entre la señal y el vencimiento.<br>
            * "vs SPY" muestra lo que habria ganado el S&P500 en ese mismo periodo como referencia.<br>
            * El resultado se calcula si la opcion habria terminado en dinero (in-the-money) al vencimiento.
        </p>
        """)

    html.append("</div></div>")
    return "\n".join(html)


# ─── MAIN ─────────────────────────────────────────────────────────────────────

def main():
    total = len(TODOS_TICKERS)
    print(f"Analizando {total} empresas...\n")

    todas     = []
    ratios_pc = {}

    for i, (ticker, nombre) in enumerate(TODOS_TICKERS.items(), 1):
        print(f"  [{i:02d}/{total}] {ticker}", end="\r")
        todas.extend(analizar_ticker(ticker, nombre))
        ratios_pc[ticker] = calcular_ratio_put_call(ticker)

    calls = [a for a in todas if a["tipo"] == "CALL"]
    puts  = [a for a in todas if a["tipo"] == "PUT"]
    print(f"\n\nResultados: {len(calls)} calls · {len(puts)} puts · {len(todas)} total")

    # ── Calendario FDA ──
    print("Consultando calendario FDA (PDUFA)...")
    eventos_fda = obtener_calendario_fda(dias_adelante=60)
    print(f"  Proximas decisiones FDA encontradas: {len(eventos_fda)}")
    for e in eventos_fda:
        print(f"    {e['ticker']} — {e['farmaco']} — {e['fecha']} ({e['dias_restantes']}d)")

    # ── Track record ──
    print("Actualizando track record...")
    registros   = cargar_track_record()
    nuevos      = registrar_nuevas_señales(todas, registros)
    evaluados   = evaluar_señales_vencidas(registros)
    guardar_track_record(registros)
    print(f"  Señales nuevas guardadas: {nuevos}")
    print(f"  Señales evaluadas hoy:    {evaluados}")

    # ── Email ──
    cuerpo           = construir_email(todas, ratios_pc, eventos_fda=eventos_fda)
    seccion_track    = construir_seccion_track_record(registros, todos_registros=registros)
    cuerpo_final     = cuerpo.replace("<!-- TRACK_RECORD_PLACEHOLDER -->", seccion_track)

    enviar_email(cuerpo_final, len(todas))


if __name__ == "__main__":
    main()
