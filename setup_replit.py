#!/usr/bin/env python3
"""
Setup script — integra el scanner de biopharma en el dashboard de Replit.
Ejecutar desde la raiz del proyecto en Replit: python3 setup_replit.py
"""
import os, re

ROOT = "/home/runner/workspace"

# ─── 1. RUTA BACKEND ─────────────────────────────────────────────────────────

biopharma_route = '''\
import { Router, type IRouter } from "express";

const router: IRouter = Router();

// Obtiene las señales y track record desde GitHub
router.get("/biopharma/signals", async (_req, res) => {
  try {
    const url = "https://raw.githubusercontent.com/amarchall-bot/biopharma-opciones/main/track_record.json";
    const response = await fetch(url);
    if (!response.ok) throw new Error("GitHub fetch failed");
    const data = await response.json();
    res.json(data);
  } catch {
    res.json([]); // devuelve array vacio si falla
  }
});

export default router;
'''

path = f"{ROOT}/artifacts/api-server/src/routes/biopharma.ts"
with open(path, "w") as f:
    f.write(biopharma_route)
print("✅ Creado: routes/biopharma.ts")


# ─── 2. REGISTRAR RUTA EN INDEX.TS ───────────────────────────────────────────

index_path = f"{ROOT}/artifacts/api-server/src/routes/index.ts"
with open(index_path, "r") as f:
    content = f.read()

if "biopharmaRouter" not in content:
    content = content.replace(
        'import flowRouter from "./flow";',
        'import flowRouter from "./flow";\nimport biopharmaRouter from "./biopharma";'
    )
    content = content.replace(
        "router.use(flowRouter);",
        "router.use(flowRouter);\nrouter.use(biopharmaRouter);"
    )
    with open(index_path, "w") as f:
        f.write(content)
    print("✅ Actualizado: routes/index.ts")
else:
    print("⏭️  routes/index.ts ya estaba actualizado")


# ─── 3. PAGINA FRONTEND ───────────────────────────────────────────────────────

biopharma_page = '''\
import { useEffect, useState } from "react";
import { Activity, TrendingUp, TrendingDown, Clock, CheckCircle, XCircle, BarChart2 } from "lucide-react";

interface Señal {
  id: string;
  fecha_señal: string;
  ticker: string;
  nombre: string;
  tipo: "CALL" | "PUT";
  strike: number;
  vencimiento: string;
  precio_accion_señal: number;
  precio_opcion_señal: number;
  score: number;
  ratio: number;
  otm: boolean;
  variacion_necesaria_pct: number;
  estado: "pendiente" | "ganancia" | "perdida";
  precio_accion_vencimiento?: number;
  resultado?: string;
  ganancia_opcion_pct?: number;
  ganancia_spy_pct?: number;
  fecha_evaluacion?: string;
}

function diasHasta(fecha: string) {
  const hoy = new Date();
  const venc = new Date(fecha);
  return Math.ceil((venc.getTime() - hoy.getTime()) / (1000 * 60 * 60 * 24));
}

function Badge({ children, color }: { children: React.ReactNode; color: string }) {
  return (
    <span style={{
      background: color + "22", color, border: `1px solid ${color}44`,
      borderRadius: 4, padding: "2px 7px", fontSize: 11, fontWeight: 700,
      fontFamily: "var(--font-mono)"
    }}>
      {children}
    </span>
  );
}

export default function Biopharma() {
  const [señales, setSeñales] = useState<Señal[]>([]);
  const [loading, setLoading] = useState(true);
  const [filtro, setFiltro] = useState<"todas" | "pendiente" | "ganancia" | "perdida">("todas");

  useEffect(() => {
    fetch("/api/biopharma/signals")
      .then(r => r.json())
      .then(data => { setSeñales(data); setLoading(false); })
      .catch(() => setLoading(false));
  }, []);

  const pendientes = señales.filter(s => s.estado === "pendiente");
  const cerradas   = señales.filter(s => s.estado !== "pendiente");
  const ganancias  = señales.filter(s => s.estado === "ganancia");
  const perdidas   = señales.filter(s => s.estado === "perdida");
  const pctAcierto = cerradas.length > 0 ? Math.round(ganancias.length / cerradas.length * 100) : null;

  const filtradas = filtro === "todas" ? señales
    : señales.filter(s => s.estado === filtro);

  return (
    <div style={{ maxWidth: 900 }}>

      {/* Cabecera */}
      <div style={{ display: "flex", alignItems: "center", gap: 12, marginBottom: 20 }}>
        <div style={{
          width: 32, height: 32, borderRadius: 8, background: "var(--bull)",
          display: "flex", alignItems: "center", justifyContent: "center"
        }}>
          <Activity size={16} color="#000" />
        </div>
        <div>
          <h1 style={{ fontFamily: "var(--font-display)", fontSize: 20, fontWeight: 800, color: "var(--text)" }}>
            Radar Biopharma
          </h1>
          <p style={{ fontSize: 11, color: "var(--text-3)" }}>
            Señales reales de volumen inusual en opciones · actualizado cada dia a las 8:30am
          </p>
        </div>
      </div>

      {/* Stats */}
      <div style={{ display: "grid", gridTemplateColumns: "repeat(4, 1fr)", gap: 10, marginBottom: 20 }}>
        {[
          { label: "En curso", value: pendientes.length, icon: <Clock size={14}/>, color: "var(--text-2)" },
          { label: "Acertadas", value: ganancias.length, icon: <CheckCircle size={14}/>, color: "var(--bull)" },
          { label: "Fallidas",  value: perdidas.length,  icon: <XCircle size={14}/>,   color: "var(--bear)" },
          { label: "% Acierto", value: pctAcierto !== null ? `${pctAcierto}%` : "—",
            icon: <BarChart2 size={14}/>, color: pctAcierto !== null ? (pctAcierto >= 50 ? "var(--bull)" : "var(--bear)") : "var(--text-2)" },
        ].map(({ label, value, icon, color }) => (
          <div key={label} style={{
            background: "var(--bg-2)", border: "1px solid var(--border)",
            borderRadius: 10, padding: "12px 14px"
          }}>
            <div style={{ display: "flex", alignItems: "center", gap: 6, color: "var(--text-3)", marginBottom: 6 }}>
              {icon}
              <span style={{ fontSize: 11 }}>{label}</span>
            </div>
            <div style={{ fontSize: 24, fontWeight: 800, color, fontFamily: "var(--font-mono)" }}>
              {value}
            </div>
          </div>
        ))}
      </div>

      {/* Filtros */}
      <div style={{ display: "flex", gap: 6, marginBottom: 16 }}>
        {(["todas", "pendiente", "ganancia", "perdida"] as const).map(f => (
          <button key={f} onClick={() => setFiltro(f)} style={{
            padding: "5px 12px", borderRadius: 6, fontSize: 11, cursor: "pointer", fontWeight: 600,
            background: filtro === f ? "var(--bull)" : "var(--bg-2)",
            color: filtro === f ? "#000" : "var(--text-2)",
            border: `1px solid ${filtro === f ? "var(--bull)" : "var(--border)"}`,
          }}>
            {f === "todas" ? "Todas" : f === "pendiente" ? "En curso" : f === "ganancia" ? "Acertadas" : "Fallidas"}
          </button>
        ))}
      </div>

      {/* Tabla */}
      {loading ? (
        <div style={{ color: "var(--text-3)", padding: 40, textAlign: "center" }}>Cargando señales...</div>
      ) : filtradas.length === 0 ? (
        <div style={{
          background: "var(--bg-2)", border: "1px solid var(--border)",
          borderRadius: 10, padding: 40, textAlign: "center", color: "var(--text-3)"
        }}>
          <Activity size={32} style={{ marginBottom: 12, opacity: 0.3 }} />
          <p style={{ fontSize: 14 }}>
            {señales.length === 0
              ? "Aun no hay señales registradas. Llegarán a partir de mañana a las 8:30am."
              : "No hay señales con este filtro."}
          </p>
        </div>
      ) : (
        <div style={{ display: "flex", flexDirection: "column", gap: 8 }}>
          {filtradas.map(s => {
            const esPendiente = s.estado === "pendiente";
            const esGanancia  = s.estado === "ganancia";
            const dias        = esPendiente ? diasHasta(s.vencimiento) : null;
            const colorTipo   = s.tipo === "CALL" ? "var(--bull)" : "var(--bear)";

            return (
              <div key={s.id} style={{
                background: "var(--bg-2)",
                border: `1px solid ${esPendiente ? "var(--border)" : esGanancia ? "var(--bull)" : "var(--bear)"}22`,
                borderLeft: `3px solid ${esPendiente ? "var(--border)" : esGanancia ? "var(--bull)" : "var(--bear)"}`,
                borderRadius: 10, padding: "14px 16px",
              }}>
                <div style={{ display: "flex", alignItems: "center", gap: 10, flexWrap: "wrap" }}>

                  {/* Ticker y nombre */}
                  <div style={{ minWidth: 120 }}>
                    <div style={{ fontFamily: "var(--font-mono)", fontWeight: 700, fontSize: 15, color: "var(--text)" }}>
                      {s.ticker}
                    </div>
                    <div style={{ fontSize: 10, color: "var(--text-3)" }}>{s.nombre}</div>
                  </div>

                  {/* Tipo */}
                  <Badge color={colorTipo}>
                    {s.tipo === "CALL" ? <TrendingUp size={10} style={{verticalAlign:"middle",marginRight:3}}/> : <TrendingDown size={10} style={{verticalAlign:"middle",marginRight:3}}/>}
                    {s.tipo}
                  </Badge>

                  {/* OTM */}
                  {s.otm && <Badge color="#f97316">OTM</Badge>}

                  {/* Strike y precio */}
                  <div style={{ fontSize: 12, color: "var(--text-2)" }}>
                    Strike <span style={{ fontFamily: "var(--font-mono)", fontWeight: 700 }}>${s.strike}</span>
                    {" · "}entrada <span style={{ fontFamily: "var(--font-mono)" }}>${s.precio_accion_señal}</span>
                  </div>

                  {/* Vencimiento */}
                  <div style={{ fontSize: 11, color: "var(--text-3)" }}>
                    Vence {s.vencimiento}
                    {esPendiente && dias !== null && (
                      <span style={{
                        marginLeft: 4, color: dias <= 7 ? "var(--bear)" : dias <= 14 ? "#f97316" : "var(--text-3)"
                      }}>({dias}d)</span>
                    )}
                  </div>

                  {/* Score */}
                  <div style={{ marginLeft: "auto", display: "flex", alignItems: "center", gap: 8 }}>
                    <div style={{ fontSize: 10, color: "var(--text-3)", textAlign: "right" }}>
                      ratio <span style={{ fontFamily: "var(--font-mono)", color: "var(--text-2)" }}>{s.ratio}x</span>
                      {" · "}score <span style={{ fontFamily: "var(--font-mono)", color: "var(--bull)" }}>{s.score}</span>
                    </div>

                    {/* Resultado */}
                    {!esPendiente && (
                      <div style={{
                        background: esGanancia ? "var(--bull-bg)" : "var(--bear-bg)",
                        color: esGanancia ? "var(--bull)" : "var(--bear)",
                        borderRadius: 6, padding: "4px 10px", fontSize: 12, fontWeight: 700,
                        fontFamily: "var(--font-mono)"
                      }}>
                        {esGanancia ? "✅" : "❌"} {s.ganancia_opcion_pct !== undefined ? `${s.ganancia_opcion_pct > 0 ? "+" : ""}${s.ganancia_opcion_pct}%` : ""}
                        {s.ganancia_spy_pct !== undefined && (
                          <span style={{ fontSize: 10, opacity: 0.7, marginLeft: 4 }}>
                            vs SPY {s.ganancia_spy_pct > 0 ? "+" : ""}{s.ganancia_spy_pct}%
                          </span>
                        )}
                      </div>
                    )}

                    {/* Estado pendiente */}
                    {esPendiente && (
                      <div style={{
                        background: "var(--bg-3)", borderRadius: 6, padding: "4px 10px",
                        fontSize: 11, color: "var(--text-3)"
                      }}>
                        ⏳ En curso
                      </div>
                    )}
                  </div>
                </div>

                {/* Detalles resultado */}
                {!esPendiente && s.precio_accion_vencimiento && (
                  <div style={{ marginTop: 8, fontSize: 11, color: "var(--text-3)", borderTop: "1px solid var(--border)", paddingTop: 8 }}>
                    Precio al vencimiento: <span style={{ fontFamily: "var(--font-mono)", color: "var(--text-2)" }}>${s.precio_accion_vencimiento}</span>
                    {" · "}Señal del {s.fecha_señal}
                    {" · "}Evaluado el {s.fecha_evaluacion}
                  </div>
                )}
              </div>
            );
          })}
        </div>
      )}

      {/* Nota */}
      <p style={{ fontSize: 11, color: "var(--text-3)", marginTop: 20, lineHeight: 1.6 }}>
        * Las señales se detectan automaticamente cada dia laborable a las 8:30am.
        El resultado se calcula cuando la opcion vence: ✅ si el precio llego al strike, ❌ si no.
        La comparativa vs SPY muestra cuanto habria subido el mercado en el mismo periodo.
      </p>
    </div>
  );
}
'''

path = f"{ROOT}/artifacts/market-pulse/src/pages/Biopharma.tsx"
with open(path, "w") as f:
    f.write(biopharma_page)
print("✅ Creado: pages/Biopharma.tsx")


# ─── 4. ACTUALIZAR APP.TSX ────────────────────────────────────────────────────

app_path = f"{ROOT}/artifacts/market-pulse/src/App.tsx"
with open(app_path, "r") as f:
    content = f.read()

if "Biopharma" not in content:
    content = content.replace(
        'import Simulator from "@/pages/Simulator";',
        'import Simulator from "@/pages/Simulator";\nimport Biopharma from "@/pages/Biopharma";'
    )
    content = content.replace(
        '<Route path="/simulator" component={Simulator} />',
        '<Route path="/simulator" component={Simulator} />\n                  <Route path="/biopharma" component={Biopharma} />'
    )
    with open(app_path, "w") as f:
        f.write(content)
    print("✅ Actualizado: App.tsx")
else:
    print("⏭️  App.tsx ya estaba actualizado")


# ─── 5. AÑADIR ENLACE EN EL MENU ─────────────────────────────────────────────

shell_files = []
for dirpath, dirnames, filenames in os.walk(f"{ROOT}/artifacts/market-pulse/src/components/layout"):
    for fname in filenames:
        shell_files.append(os.path.join(dirpath, fname))

for fpath in shell_files:
    with open(fpath, "r") as f:
        content = f.read()
    if "biopharma" not in content.lower() and ("/scanner" in content or "/flow" in content):
        # Buscar donde esta el enlace al scanner y añadir biopharma despues
        new_content = re.sub(
            r'(/simulator["\'].*?(?:Simulador|Simulator)["\'].*?\n)',
            lambda m: m.group(0) + m.group(0)
                .replace("/simulator", "/biopharma")
                .replace("Simulador", "Biopharma")
                .replace("Simulator", "Biopharma"),
            content, count=1
        )
        if new_content != content:
            with open(fpath, "w") as f:
                f.write(new_content)
            print(f"✅ Menu actualizado: {os.path.basename(fpath)}")
            break

print("\n✅ Instalacion completada.")
print("   Visita: /biopharma en tu dashboard")
print("   (puede necesitar reiniciar el servidor: pkill node && pnpm run dev)")
