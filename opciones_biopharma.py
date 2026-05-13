#!/usr/bin/env python3
"""
Scanner de volumen anomalo en opciones — Biofarmaceuticas + Empresas españolas en EEUU.
Envia un email diario a amarchall@gmail.com con instrucciones claras para no expertos.
"""

import yfinance as yf
import smtplib
import os
from email.mime.text import MIMEText
from email.mime.multipart import MIMEMultipart
from datetime import datetime, date

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
    "EXAS": "Exact Sciences",
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

UMBRAL_VOL_OI     = 3.0
MIN_VOLUMEN       = 200
MIN_OPEN_INTEREST = 50
MAX_VENCIMIENTOS  = 3

DESTINATARIO   = "amarchall@gmail.com"
EMAIL_ORIGEN   = os.environ.get("EMAIL_ORIGEN", "")
EMAIL_PASSWORD = os.environ.get("EMAIL_PASSWORD", "")


# ─── OBTENER PROXIMOS RESULTADOS ──────────────────────────────────────────────

def obtener_proximos_earnings(ticker):
    """Devuelve la fecha de proximos resultados si esta disponible."""
    try:
        cal = yf.Ticker(ticker).calendar
        if cal is not None and not cal.empty:
            fecha = cal.iloc[0].get("Earnings Date") or cal.columns[0]
            if hasattr(fecha, 'date'):
                return fecha.date()
            return None
    except Exception:
        return None


# ─── ANALISIS DE OPCIONES ─────────────────────────────────────────────────────

def score_anomalia(volume, ratio):
    score = ratio
    if volume > 1000:  score += 1
    if volume > 5000:  score += 2
    if volume > 10000: score += 3
    return round(score, 1)


def analizar_ticker(ticker, nombre):
    anomalias = []
    try:
        stock         = yf.Ticker(ticker)
        precio_actual = round(getattr(stock.fast_info, "last_price", 0) or 0, 2)
        fechas        = stock.options
        if not fechas or precio_actual == 0:
            return anomalias

        earnings = obtener_proximos_earnings(ticker)

        for fecha in fechas[:MAX_VENCIMIENTOS]:
            chain = stock.option_chain(fecha)
            for tipo, df in [("CALL", chain.calls), ("PUT", chain.puts)]:
                if df.empty:
                    continue
                df = df.copy()
                df = df[(df["volume"] >= MIN_VOLUMEN) & (df["openInterest"] >= MIN_OPEN_INTEREST)]
                if df.empty:
                    continue
                df["ratio"] = df["volume"] / df["openInterest"]
                df = df[df["ratio"] >= UMBRAL_VOL_OI].copy()

                for _, row in df.iterrows():
                    strike = row["strike"]
                    es_otm = (tipo == "CALL" and strike > precio_actual) or \
                             (tipo == "PUT"  and strike < precio_actual)
                    variacion_pct = round(abs(strike - precio_actual) / precio_actual * 100, 1)

                    anomalias.append({
                        "ticker":        ticker,
                        "nombre":        nombre,
                        "tipo":          tipo,
                        "strike":        strike,
                        "vencimiento":   fecha,
                        "volumen":       int(row["volume"]),
                        "open_interest": int(row["openInterest"]),
                        "ratio":         round(row["ratio"], 1),
                        "precio_actual": precio_actual,
                        "otm":           es_otm,
                        "variacion_pct": variacion_pct,
                        "score":         score_anomalia(int(row["volume"]), round(row["ratio"], 1)),
                        "earnings":      earnings,
                        "ultimo_precio_opcion": round(row.get("lastPrice", 0) or 0, 2),
                    })
    except Exception:
        pass
    return anomalias


# ─── GENERAR EXPLICACION Y CONSEJO PARA CADA SEÑAL ───────────────────────────

def generar_consejo(a):
    """Genera explicacion en lenguaje simple y operacion sugerida."""
    ticker   = a["ticker"]
    nombre   = a["nombre"]
    tipo     = a["tipo"]
    strike   = a["strike"]
    precio   = a["precio_actual"]
    venc     = a["vencimiento"]
    volumen  = a["volumen"]
    ratio    = a["ratio"]
    otm      = a["otm"]
    var_pct  = a["variacion_pct"]
    earnings = a["earnings"]
    precio_op = a["ultimo_precio_opcion"]

    # Fecha de vencimiento en formato legible
    try:
        dias_restantes = (datetime.strptime(venc, "%Y-%m-%d").date() - date.today()).days
        venc_legible = datetime.strptime(venc, "%Y-%m-%d").strftime("%d de %B de %Y")
    except Exception:
        dias_restantes = 30
        venc_legible = venc

    # Urgencia segun dias restantes
    if dias_restantes <= 14:
        urgencia = "🔴 Apuesta a MUY CORTO PLAZO"
        urgencia_texto = f"solo quedan <b>{dias_restantes} dias</b> hasta el vencimiento — alguien espera un movimiento muy rapido"
    elif dias_restantes <= 45:
        urgencia = "🟡 Apuesta a CORTO PLAZO"
        urgencia_texto = f"quedan <b>{dias_restantes} dias</b> hasta el vencimiento"
    else:
        urgencia = "🟢 Apuesta a MEDIO PLAZO"
        urgencia_texto = f"quedan <b>{dias_restantes} dias</b> hasta el vencimiento"

    # Contexto de earnings
    earnings_txt = ""
    if earnings:
        dias_earn = (earnings - date.today()).days
        if 0 < dias_earn <= 60:
            earnings_txt = f"<br>📅 <b>Atencion:</b> {nombre} publica resultados trimestrales en <b>{dias_earn} dias</b> ({earnings.strftime('%d/%m/%Y')}) — puede ser el motivo de esta apuesta."

    if tipo == "CALL":
        # ── CALL ──
        if otm:
            explicacion = (
                f"Alguien ha apostado fuerte a que <b>{nombre} ({ticker})</b> va a subir un <b>{var_pct}%</b> "
                f"en los proximos {dias_restantes} dias. Ahora cotiza a <b>${precio}</b> y la apuesta es que "
                f"llegue a <b>${strike}</b> antes del {venc_legible}. "
                f"Es una apuesta <b>agresiva</b> ({volumen:,} contratos, {ratio}x la actividad normal). "
                f"{urgencia_texto.capitalize()}."
            )
            operacion_1 = f"Comprar un CALL de <b>{ticker}</b> con strike <b>${strike}</b> y vencimiento <b>{venc_legible}</b>"
            coste_aprox = f"~${round(precio_op * 100, 0):,.0f} por contrato" if precio_op > 0 else "consulta el precio en tu broker"
            operacion_2 = f"Comprar acciones de <b>{ticker}</b> directamente a precio de mercado (~${precio})"
            ganancia_op1 = f"Si {ticker} llega a ${strike}, la opcion podria multiplicar su valor varias veces"
            ganancia_op2 = f"Ganas proporcionalmente si la accion sube"
            riesgo_op1 = "Pierdes todo lo invertido si la accion no llega a $" + str(strike) + " antes del vencimiento"
            riesgo_op2 = "Solo pierdes si la accion baja de precio"
        else:
            explicacion = (
                f"Alguien apuesta a que <b>{nombre} ({ticker})</b> va a mantenerse por encima de <b>${strike}</b> "
                f"(ahora cotiza a <b>${precio}</b>). Con {volumen:,} contratos y un ratio de {ratio}x, "
                f"es una apuesta mas conservadora pero con mucho dinero detras. {urgencia_texto.capitalize()}."
            )
            operacion_1 = f"Comprar un CALL de <b>{ticker}</b> con strike <b>${strike}</b> y vencimiento <b>{venc_legible}</b>"
            coste_aprox = f"~${round(precio_op * 100, 0):,.0f} por contrato" if precio_op > 0 else "consulta el precio en tu broker"
            operacion_2 = f"Comprar acciones de <b>{ticker}</b> a precio de mercado (~${precio})"
            ganancia_op1 = f"Ganas si {ticker} sube por encima de ${strike}"
            ganancia_op2 = f"Ganas si la accion sube cualquier cantidad"
            riesgo_op1 = "Menor que una OTM, pero sigues perdiendo la prima si baja"
            riesgo_op2 = "Solo pierdes si la accion baja"

        color_titulo = "#1a7f37"
        emoji_tipo   = "📈 SEÑAL ALCISTA"

    else:
        # ── PUT ──
        if otm:
            explicacion = (
                f"Alguien ha apostado fuerte a que <b>{nombre} ({ticker})</b> va a CAER un <b>{var_pct}%</b> "
                f"en los proximos {dias_restantes} dias. Ahora cotiza a <b>${precio}</b> y la apuesta es que "
                f"baje a <b>${strike}</b> antes del {venc_legible}. "
                f"Con {volumen:,} contratos y ratio {ratio}x, es una apuesta muy agresiva a la baja. "
                f"{urgencia_texto.capitalize()}."
            )
            operacion_1 = f"Comprar un PUT de <b>{ticker}</b> con strike <b>${strike}</b> y vencimiento <b>{venc_legible}</b>"
            coste_aprox = f"~${round(precio_op * 100, 0):,.0f} por contrato" if precio_op > 0 else "consulta el precio en tu broker"
            operacion_2 = f"Si tienes acciones de <b>{ticker}</b>, considera reducir tu posicion o ponerle un stop-loss en ~${round(precio * 0.95, 2)}"
            ganancia_op1 = f"Si {ticker} cae a ${strike}, la opcion podria multiplicar su valor"
            ganancia_op2 = "Proteges tu cartera si tienes esa accion"
            riesgo_op1 = "Pierdes la prima si la accion no cae lo suficiente"
            riesgo_op2 = "Si no tienes la accion, esta opcion no aplica directamente"
        else:
            explicacion = (
                f"Alguien apuesta a que <b>{nombre} ({ticker})</b> va a CAER por debajo de <b>${strike}</b> "
                f"(ahora cotiza a <b>${precio}</b>). Con {volumen:,} contratos y ratio {ratio}x. "
                f"{urgencia_texto.capitalize()}."
            )
            operacion_1 = f"Comprar un PUT de <b>{ticker}</b> con strike <b>${strike}</b> y vencimiento <b>{venc_legible}</b>"
            coste_aprox = f"~${round(precio_op * 100, 0):,.0f} por contrato" if precio_op > 0 else "consulta el precio en tu broker"
            operacion_2 = f"Si tienes acciones de <b>{ticker}</b>, pon un stop-loss en ~${round(precio * 0.95, 2)}"
            ganancia_op1 = f"Ganas si {ticker} cae por debajo de ${strike}"
            ganancia_op2 = "Proteges lo que tienes"
            riesgo_op1 = "Pierdes la prima si la accion no baja"
            riesgo_op2 = "Si no tienes la accion, no aplica directamente"

        color_titulo = "#cf222e"
        emoji_tipo   = "📉 SEÑAL BAJISTA"

    # Nivel de riesgo
    if otm and dias_restantes <= 14:
        nivel_riesgo = "🔴 MUY ALTO — opcion agresiva con poco tiempo"
    elif otm:
        nivel_riesgo = "🟠 ALTO — apuesta especulativa"
    elif dias_restantes <= 14:
        nivel_riesgo = "🟡 MEDIO-ALTO — poco tiempo pero precio razonable"
    else:
        nivel_riesgo = "🟡 MEDIO — opcion mas conservadora"

    return {
        "emoji_tipo":    emoji_tipo,
        "color_titulo":  color_titulo,
        "urgencia":      urgencia,
        "explicacion":   explicacion,
        "earnings_txt":  earnings_txt,
        "operacion_1":   operacion_1,
        "coste_aprox":   coste_aprox,
        "ganancia_op1":  ganancia_op1,
        "riesgo_op1":    riesgo_op1,
        "operacion_2":   operacion_2,
        "ganancia_op2":  ganancia_op2,
        "riesgo_op2":    riesgo_op2,
        "nivel_riesgo":  nivel_riesgo,
    }


# ─── CONSTRUCCION DEL EMAIL ───────────────────────────────────────────────────

def construir_email(todas_anomalias):
    hoy   = datetime.now().strftime("%d/%m/%Y")
    calls = sorted([a for a in todas_anomalias if a["tipo"] == "CALL"], key=lambda x: x["score"], reverse=True)
    puts  = sorted([a for a in todas_anomalias if a["tipo"] == "PUT"],  key=lambda x: x["score"], reverse=True)

    if len(calls) > len(puts) * 1.5:
        sesgo = "ALCISTA 📈"
        sesgo_color = "#1a7f37"
    elif len(puts) > len(calls) * 1.5:
        sesgo = "BAJISTA 📉"
        sesgo_color = "#cf222e"
    else:
        sesgo = "NEUTRAL ⚖️"
        sesgo_color = "#9a6700"

    html = [f"""
    <div style="font-family:Arial,sans-serif;max-width:680px;margin:auto;color:#1a1a1a">

    <div style="background:#1a1a2e;color:white;padding:20px;border-radius:10px;margin-bottom:20px">
        <h1 style="margin:0;font-size:22px">📊 Radar de Opciones Inusuales</h1>
        <p style="margin:6px 0 0 0;opacity:0.8">{hoy} · {len(todas_anomalias)} señales detectadas hoy</p>
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

    if not todas_anomalias:
        html.append("""
        <div style="background:#f6f8fa;border-radius:8px;padding:24px;text-align:center;color:#666">
            <div style="font-size:40px">😴</div>
            <p><b>Hoy no hay actividad inusual.</b><br>
            El mercado esta tranquilo en las empresas vigiladas.</p>
        </div>
        """)
    else:
        for grupo in [calls, puts]:
            for a in grupo:
                c = generar_consejo(a)
                otm_badge = '<span style="background:#ff9800;color:white;font-size:11px;padding:2px 6px;border-radius:4px;margin-left:6px">FUERA DEL PRECIO</span>' if a["otm"] else ""

                html.append(f"""
        <div style="border:2px solid {c['color_titulo']};border-radius:10px;margin-bottom:24px;overflow:hidden">

            <!-- CABECERA -->
            <div style="background:{c['color_titulo']};color:white;padding:14px 18px">
                <div style="font-size:18px;font-weight:bold">{c['emoji_tipo']} — {a['nombre']} ({a['ticker']}){otm_badge}</div>
                <div style="opacity:0.9;font-size:13px;margin-top:4px">{c['urgencia']} &nbsp;·&nbsp; Score de anomalia: {a['score']} &nbsp;·&nbsp; Ratio: {a['ratio']}x lo normal</div>
            </div>

            <div style="padding:16px 18px">

                <!-- QUE ESTA PASANDO -->
                <div style="background:#f6f8fa;border-radius:6px;padding:12px;margin-bottom:14px">
                    <div style="font-weight:bold;margin-bottom:6px">🔍 ¿Que esta pasando?</div>
                    <div style="font-size:14px;line-height:1.6">{c['explicacion']}{c['earnings_txt']}</div>
                </div>

                <!-- DATOS CLAVE -->
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

                <!-- OPCIONES DE OPERACION -->
                <div style="font-weight:bold;margin-bottom:10px">💡 ¿Que puedes hacer?</div>

                <!-- OPCION 1 -->
                <div style="border:1px solid #ddd;border-radius:6px;padding:12px;margin-bottom:10px">
                    <div style="font-weight:bold;color:{c['color_titulo']};margin-bottom:6px">
                        Opcion 1 — Seguir la apuesta (MAS AGRESIVO)
                    </div>
                    <div style="font-size:13px;line-height:1.7">
                        👉 {c['operacion_1']}<br>
                        💰 Coste aproximado: <b>{c['coste_aprox']}</b><br>
                        ✅ Si funciona: {c['ganancia_op1']}<br>
                        ❌ Si no funciona: {c['riesgo_op1']}
                    </div>
                </div>

                <!-- OPCION 2 -->
                <div style="border:1px solid #ddd;border-radius:6px;padding:12px;margin-bottom:10px">
                    <div style="font-weight:bold;color:#0066cc;margin-bottom:6px">
                        Opcion 2 — Alternativa mas conservadora
                    </div>
                    <div style="font-size:13px;line-height:1.7">
                        👉 {c['operacion_2']}<br>
                        ✅ Si funciona: {c['ganancia_op2']}<br>
                        ❌ Riesgo: {c['riesgo_op2']}
                    </div>
                </div>

                <!-- NIVEL DE RIESGO -->
                <div style="font-size:13px;color:#555">
                    ⚠️ <b>Nivel de riesgo:</b> {c['nivel_riesgo']}
                </div>

            </div>
        </div>
                """)

    html.append("""
    <div style="background:#f6f8fa;border-radius:8px;padding:16px;font-size:12px;color:#666;margin-top:10px">
        <b>⚠️ Aviso importante:</b> Este email es solo informativo y no constituye asesoramiento financiero.
        Las opciones son instrumentos de alto riesgo — puedes perder toda la cantidad invertida.
        Consulta siempre con un asesor financiero antes de operar. Datos de Yahoo Finance.
    </div>
    </div>
    """)

    return "\n".join(html)


# ─── ENVIO DE EMAIL ───────────────────────────────────────────────────────────

def enviar_email(cuerpo_html, n_anomalias):
    if not EMAIL_ORIGEN or not EMAIL_PASSWORD:
        print("ERROR: faltan credenciales de email.")
        return False

    if n_anomalias == 0:
        asunto = f"😴 Radar Opciones — Sin señales hoy — {datetime.now().strftime('%d/%m/%Y')}"
    else:
        asunto = f"🚨 Radar Opciones — {n_anomalias} señales inusuales — {datetime.now().strftime('%d/%m/%Y')}"

    msg = MIMEMultipart("alternative")
    msg["Subject"] = asunto
    msg["From"]    = EMAIL_ORIGEN
    msg["To"]      = DESTINATARIO
    msg.attach(MIMEText(cuerpo_html, "html"))

    try:
        with smtplib.SMTP_SSL("smtp.gmail.com", 465) as server:
            server.login(EMAIL_ORIGEN, EMAIL_PASSWORD)
            server.sendmail(EMAIL_ORIGEN, DESTINATARIO, msg.as_string())
        print(f"✅ Email enviado a {DESTINATARIO}")
        return True
    except Exception as e:
        print(f"❌ Error: {e}")
        return False


# ─── MAIN ─────────────────────────────────────────────────────────────────────

def main():
    total = len(TODOS_TICKERS)
    print(f"Analizando {total} empresas... (2-3 minutos)\n")

    todas = []
    for i, (ticker, nombre) in enumerate(TODOS_TICKERS.items(), 1):
        print(f"  [{i:02d}/{total}] {ticker}", end="\r")
        todas.extend(analizar_ticker(ticker, nombre))

    calls = [a for a in todas if a["tipo"] == "CALL"]
    puts  = [a for a in todas if a["tipo"] == "PUT"]
    print(f"\n\nResultados: {len(calls)} calls · {len(puts)} puts · {len(todas)} total")

    cuerpo = construir_email(todas)
    enviar_email(cuerpo, len(todas))


if __name__ == "__main__":
    main()
