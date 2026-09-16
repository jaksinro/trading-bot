"""Tableau de bord visuel unique avec onglets (EF-07 de la STB).

Chaque instance de bot ecrit ses propres donnees dans un petit fichier JS
(dashboard_data/{name}.js) plutot qu'une page HTML complete. Un unique
dashboard.html (statique, regenere a l'identique a chaque appel) les charge
tous dynamiquement et affiche un onglet par instance - ca permet de faire
tourner plusieurs bots (STB section 3.2) et de tous les suivre au meme
endroit, sans que l'un n'ecrase le fichier de l'autre.
"""

import json
import time
from pathlib import Path

from tradingbot.portfolio import Portfolio
from tradingbot.reporting.stats import compute_report

# Un bot est considere "en cours" tant qu'il a ecrit une mise a jour dans
# cette fenetre. Doit rester large par rapport au plus long cycle de poll
# possible (jusqu'a 60s, voir run_paper.py) pour ne pas clignoter a tort.
STALE_AFTER_MS = 3 * 60 * 1000

DASHBOARD_DIR = Path("dashboard_data")
MASTER_DASHBOARD_PATH = Path("dashboard.html")
REGISTRY_STATE_PATH = DASHBOARD_DIR / "registry.state"


def _update_registry(instance_name: str) -> None:
    DASHBOARD_DIR.mkdir(exist_ok=True)
    names = []
    if REGISTRY_STATE_PATH.exists():
        names = [n for n in REGISTRY_STATE_PATH.read_text(encoding="utf-8").splitlines() if n]
    if instance_name not in names:
        names.append(instance_name)
        REGISTRY_STATE_PATH.write_text("\n".join(names), encoding="utf-8")

    registry_js = "window.BOT_REGISTRY = " + json.dumps(names) + ";\n"
    (DASHBOARD_DIR / "registry.js").write_text(registry_js, encoding="utf-8")


def write_dashboard(
    instance_name: str,
    symbol: str,
    mode: str,
    portfolio: Portfolio,
    current_price: float,
    updated_at: str,
    logs: list[str] | None = None,
    probability_up_24h: float | None = None,
    orders: list[dict] | None = None,
    price_history: list[list] | None = None,
    trend_filter_status: dict | None = None,
    atr_sizer_status: dict | None = None,
    price_level_sizer_status: dict | None = None,
    pool_available_cash: float | None = None,
    effective_cap: float | None = None,
) -> None:
    DASHBOARD_DIR.mkdir(exist_ok=True)
    _update_registry(instance_name)

    equity_now = portfolio.equity(current_price)
    report = compute_report(portfolio)
    trades = portfolio.trade_history
    wins = [t for t in trades if t["pnl"] > 0]

    data = {
        "symbol": symbol,
        "mode": mode,
        "starting_capital": portfolio.starting_capital,
        "equity": equity_now,
        "current_price": current_price,
        "position_quantity": portfolio.total_position_quantity,
        # Argent reellement immobilise dans la/les position(s) ouverte(s) EN CE
        # MOMENT (quantite x prix actuel) - absent jusqu'ici du dashboard, qui
        # ne montrait que le plafond de mise (combien le bot PEUT engager), pas
        # combien il a REELLEMENT engage sur le trade en cours.
        "invested_now": portfolio.total_position_quantity * current_price,
        "open_positions_count": len(portfolio.positions),
        "updated_at": updated_at,
        "updated_at_ts": int(time.time() * 1000),
        "price_history": price_history or [],
        "logs": logs or [],
        "num_trades": len(trades),
        "win_rate": (len(wins) / len(trades)) if trades else None,
        "max_drawdown_pct": report.max_drawdown_pct,
        "realized_pnl": report.realized_pnl,
        "total_fees_paid": portfolio.total_fees_paid,
        "probability_up_24h": probability_up_24h,
        "orders": orders or [],
        "trend_filter": trend_filter_status,
        "atr_sizer": atr_sizer_status,
        "price_level_sizer": price_level_sizer_status,
        # Panier de capital commun (STC section 3.5 revisee) : `pool_available_cash`
        # est le meme nombre pour tous les bots (le solde global du panier partage),
        # `effective_cap` est propre a CE bot (son plafond de mise dynamique, base_cap
        # module par sa performance recente). None en mode backtest (pas de panier).
        "pool_available_cash": pool_available_cash,
        "effective_cap": effective_cap,
    }
    js_content = (
        "window.BOT_INSTANCES = window.BOT_INSTANCES || {};\n"
        f"window.BOT_INSTANCES[{json.dumps(instance_name)}] = {json.dumps(data)};\n"
    )
    (DASHBOARD_DIR / f"{instance_name}.js").write_text(js_content, encoding="utf-8")

    _write_master_dashboard()


def _write_master_dashboard() -> None:
    MASTER_DASHBOARD_PATH.write_text(_MASTER_DASHBOARD_HTML, encoding="utf-8")


_MASTER_DASHBOARD_HTML = """<!DOCTYPE html>
<html lang="fr">
<head>
<meta charset="utf-8">
<meta name="viewport" content="width=device-width, initial-scale=1">
<title>Trading Bot - Dashboard</title>
<link rel="preconnect" href="https://fonts.googleapis.com">
<link rel="preconnect" href="https://fonts.gstatic.com" crossorigin>
<link href="https://fonts.googleapis.com/css2?family=Inter:wght@400;500;600;700&family=JetBrains+Mono:wght@400;500&display=swap" rel="stylesheet">
<style>
  :root {
    --bg: #0a0c11;
    --bg-glow: radial-gradient(1100px 520px at 12% -8%, rgba(91,141,239,0.16), transparent 60%),
               radial-gradient(900px 480px at 100% 0%, rgba(124,92,255,0.12), transparent 55%);
    --surface: #12151d;
    --surface-2: #171b25;
    --surface-hover: #1c212c;
    --border: rgba(255,255,255,0.07);
    --border-strong: rgba(255,255,255,0.14);
    --text: #eceef4;
    --text-dim: #9aa2b5;
    --text-faint: #666f84;
    --accent: #5b8def;
    --accent-2: #7c5cff;
    --accent-soft: rgba(91,141,239,0.14);
    --green: #2fd699;
    --green-soft: rgba(47,214,153,0.14);
    --red: #ff6b6b;
    --red-soft: rgba(255,107,107,0.14);
    --amber: #f5b74f;
    --amber-soft: rgba(245,183,79,0.14);
    --purple: #b18cff;
    --purple-soft: rgba(177,140,255,0.14);
    --radius-lg: 16px;
    --radius-md: 10px;
    --radius-sm: 7px;
    --shadow-card: 0 1px 2px rgba(0,0,0,0.3), 0 12px 32px -16px rgba(0,0,0,0.55);
  }
  * { box-sizing: border-box; }
  ::selection { background: var(--accent); color: #fff; }
  ::-webkit-scrollbar { width: 10px; height: 10px; }
  ::-webkit-scrollbar-track { background: transparent; }
  ::-webkit-scrollbar-thumb { background: var(--border-strong); border-radius: 8px; }
  ::-webkit-scrollbar-thumb:hover { background: var(--text-faint); }
  html { color-scheme: dark; }
  body {
    font-family: 'Inter', system-ui, -apple-system, sans-serif;
    background: var(--bg) var(--bg-glow) no-repeat;
    background-attachment: fixed;
    color: var(--text);
    margin: 0;
    padding: 28px 28px 60px;
    -webkit-font-smoothing: antialiased;
    font-size: 14px;
    line-height: 1.5;
  }
  h1, h2, h3 { font-family: 'Inter', sans-serif; font-weight: 600; letter-spacing: -0.01em; color: var(--text); }
  h1 { font-size: 21px; margin: 0 0 4px 0; }
  h2 { font-size: 13px; text-transform: uppercase; letter-spacing: 0.06em; color: var(--text-dim); font-weight: 600; margin: 0 0 12px 0; }
  code { font-family: 'JetBrains Mono', ui-monospace, monospace; background: rgba(255,255,255,0.06); padding: 1px 6px; border-radius: 5px; font-size: 12px; color: #c9d2ea; }
  .muted { color: var(--text-dim); font-size: 13px; }
  .app-header { max-width: 1360px; margin: 0 auto 22px; display: flex; align-items: center; justify-content: space-between; gap: 16px; flex-wrap: wrap; }
  .app-header .brand { display: flex; align-items: center; gap: 12px; }
  .app-header .brand-mark { width: 38px; height: 38px; border-radius: 11px; background: linear-gradient(135deg, var(--accent), var(--accent-2)); display: flex; align-items: center; justify-content: center; font-size: 18px; box-shadow: 0 6px 18px -6px rgba(91,141,239,0.6); flex-shrink: 0; }
  .app-header .brand-text h1 { margin: 0; }
  .live-pill { display: inline-flex; align-items: center; gap: 7px; background: var(--surface); border: 1px solid var(--border); padding: 7px 13px; border-radius: 999px; font-size: 12.5px; color: var(--text-dim); }
  .live-pill .pulse { width: 7px; height: 7px; border-radius: 50%; background: var(--green); box-shadow: 0 0 0 0 rgba(47,214,153,0.6); animation: pulse 2s infinite; }
  @keyframes pulse { 0% { box-shadow: 0 0 0 0 rgba(47,214,153,0.55); } 70% { box-shadow: 0 0 0 7px rgba(47,214,153,0); } 100% { box-shadow: 0 0 0 0 rgba(47,214,153,0); } }
  .card { background: var(--surface); border: 1px solid var(--border); box-shadow: var(--shadow-card); border-radius: var(--radius-lg); padding: 24px 26px; max-width: 900px; margin: 0 auto; }
  .tabs { display: flex; gap: 6px; margin: 18px 0 22px 0; flex-wrap: wrap; border-bottom: 1px solid var(--border); padding-bottom: 12px; }
  .tab { background: transparent; color: var(--text-dim); border: 1px solid transparent; border-radius: var(--radius-sm); padding: 7px 13px; font-size: 12.5px; font-weight: 500; cursor: pointer; transition: background .15s ease, color .15s ease, border-color .15s ease; font-family: inherit; }
  .tab:hover { background: var(--surface-hover); color: var(--text); }
  .tab.active { background: var(--accent-soft); color: #a9c6ff; border-color: rgba(91,141,239,0.35); }
  .grid { display: grid; grid-template-columns: repeat(auto-fit, minmax(158px, 1fr)); gap: 12px; margin-top: 20px; }
  .grid > div { background: var(--surface-2); border: 1px solid var(--border); border-radius: var(--radius-md); padding: 13px 15px; transition: border-color .15s ease, transform .15s ease; }
  .grid > div:hover { border-color: var(--border-strong); }
  .stat-label { font-size: 11px; color: var(--text-faint); text-transform: uppercase; letter-spacing: 0.05em; font-weight: 600; }
  .stat-value { font-size: 22px; font-weight: 600; margin-top: 6px; letter-spacing: -0.01em; font-variant-numeric: tabular-nums; }
  .badge { display: inline-block; background: var(--surface-2); border: 1px solid var(--border); color: var(--text-dim); border-radius: 999px; padding: 3px 11px; font-size: 11.5px; font-weight: 500; }
  .status { display: inline-flex; align-items: center; gap: 6px; border-radius: 999px; padding: 4px 11px; font-size: 11.5px; font-weight: 500; margin-left: 8px; }
  .status.running { background: var(--green-soft); color: var(--green); }
  .status.stopped { background: var(--red-soft); color: var(--red); }
  .status .dot { width: 6px; height: 6px; border-radius: 50%; background: currentColor; }
  .empty { color: var(--text-dim); padding: 48px 0; text-align: center; font-size: 13.5px; }
  .logs { list-style: none; margin: 10px 0 0 0; padding: 0; font-family: 'JetBrains Mono', monospace; font-size: 12px; }
  .logs li { padding: 8px 2px; border-bottom: 1px solid var(--border); color: #c7cdd6; line-height: 1.5; }
  .logs li:last-child { border-bottom: none; }
  .logs .ts { color: var(--text-faint); margin-right: 10px; }
  table.bi { width: 100%; border-collapse: collapse; margin-top: 14px; font-size: 12.5px; }
  table.bi th, table.bi td { text-align: left; padding: 9px 10px; border-bottom: 1px solid var(--border); }
  table.bi th { color: var(--text-faint); font-weight: 600; text-transform: uppercase; font-size: 10.5px; letter-spacing: 0.04em; background: var(--surface); position: sticky; top: 0; }
  table.bi tbody tr { transition: background .12s ease; }
  table.bi tbody tr:hover { background: var(--surface-hover); }
  table.bi tbody tr:last-child td { border-bottom: none; }
  .tabs.subtabs { border-bottom: none; padding-bottom: 0; margin: -10px 0 20px 0; }
  .tabs.subtabs .tab { font-size: 12px; padding: 6px 11px; }
  #alerts { max-width: 1100px; margin: 0 auto 14px auto; }
  .alert-banner { background: var(--red-soft); border: 1px solid rgba(255,107,107,0.3); color: #ffb4b4; border-radius: var(--radius-md); padding: 11px 15px; font-size: 13px; margin-bottom: 8px; display: flex; justify-content: space-between; align-items: center; gap: 12px; }
  .alert-banner button { background: none; border: none; color: inherit; cursor: pointer; font-size: 14px; opacity: .7; }
  .alert-banner button:hover { opacity: 1; }
  .form-grid { display: grid; grid-template-columns: repeat(auto-fit, minmax(200px, 1fr)); gap: 13px; margin-top: 14px; }
  .field label { display: block; font-size: 12px; color: var(--text-dim); margin-bottom: 5px; font-weight: 500; }
  .field input, .field select { width: 100%; box-sizing: border-box; background: var(--bg); border: 1px solid var(--border-strong); color: var(--text); border-radius: var(--radius-sm); padding: 9px 11px; font-size: 13px; font-family: inherit; transition: border-color .15s ease, box-shadow .15s ease; }
  .field input:hover, .field select:hover { border-color: var(--text-faint); }
  .field input:focus, .field select:focus { outline: none; border-color: var(--accent); box-shadow: 0 0 0 3px var(--accent-soft); }
  .field input[type=checkbox] { width: auto; accent-color: var(--accent); }
  .form-actions { margin-top: 20px; display: flex; align-items: center; gap: 12px; }
  button { font-family: inherit; }
  button.primary { background: linear-gradient(135deg, var(--accent), #4a7de0); color: white; border: none; border-radius: var(--radius-sm); padding: 10px 18px; font-size: 13px; font-weight: 600; cursor: pointer; box-shadow: 0 4px 14px -4px rgba(91,141,239,0.5); transition: transform .1s ease, box-shadow .15s ease; }
  button.primary:hover { box-shadow: 0 6px 18px -4px rgba(91,141,239,0.65); }
  button.primary:active { transform: translateY(1px); }
  button.danger { background: var(--red-soft); color: #ffb4b4; border: 1px solid rgba(255,107,107,0.25); border-radius: var(--radius-sm); padding: 6px 12px; font-size: 12px; font-weight: 500; cursor: pointer; transition: background .15s ease; }
  button.danger:hover { background: rgba(255,107,107,0.24); }
  button.secondary { background: var(--surface-2); color: var(--text); border: 1px solid var(--border-strong); border-radius: var(--radius-sm); padding: 6px 12px; font-size: 12px; font-weight: 500; cursor: pointer; transition: background .15s ease, border-color .15s ease; }
  button.secondary:hover { background: var(--surface-hover); border-color: var(--text-faint); }
  button:disabled { opacity: 0.4; cursor: not-allowed; }
  .form-status { font-size: 13px; }
  .form-status.ok { color: var(--green); }
  .form-status.err { color: var(--red); }
  .progress-track { position: relative; height: 8px; background: var(--surface-2); border: 1px solid var(--border); border-radius: 999px; overflow: hidden; margin-top: 10px; }
  .progress-bar { height: 100%; background: linear-gradient(135deg, var(--accent), var(--accent-2)); border-radius: 999px; transition: width .3s ease; }
  .progress-bar.indeterminate { position: absolute; top: 0; left: 0; width: 35%; animation: progress-indeterminate 1.1s ease-in-out infinite; }
  @keyframes progress-indeterminate { 0% { left: -35%; } 100% { left: 100%; } }
  .progress-label { font-size: 12px; color: var(--text-dim); margin-top: 6px; }
  .range-selector { display: flex; gap: 5px; flex-wrap: wrap; margin: 12px 0 6px 0; background: var(--surface-2); border: 1px solid var(--border); border-radius: var(--radius-md); padding: 4px; width: fit-content; }
  .range-btn { background: transparent; color: var(--text-dim); border: none; border-radius: 6px; padding: 5px 12px; font-size: 12px; font-weight: 500; cursor: pointer; transition: background .15s ease, color .15s ease; font-family: inherit; }
  .range-btn:hover { color: var(--text); }
  .range-btn.active { background: var(--accent); color: white; }
  .adv-section { border: 1px solid var(--border); border-radius: var(--radius-md); margin-top: 12px; overflow: hidden; background: var(--surface-2); }
  .adv-section summary { list-style: none; cursor: pointer; padding: 12px 14px; font-size: 13px; font-weight: 600; color: var(--text); display: flex; align-items: center; justify-content: space-between; user-select: none; }
  .adv-section summary::-webkit-details-marker { display: none; }
  .adv-section summary .chev { transition: transform .15s ease; color: var(--text-faint); font-size: 11px; }
  .adv-section[open] summary .chev { transform: rotate(90deg); }
  .adv-section summary:hover { background: var(--surface-hover); }
  .adv-body { padding: 4px 14px 16px; border-top: 1px solid var(--border); }
  .adv-hint { font-size: 12px; color: var(--text-dim); margin: 10px 0 0; line-height: 1.55; }
  .section-block { margin-top: 22px; }
  hr.sep { border: none; border-top: 1px solid var(--border); margin: 22px 0; }
</style>
</head>
<body>
  <div class="app-header">
    <div class="brand">
      <div class="brand-mark">📈</div>
      <div class="brand-text">
        <h1>Trading Bot</h1>
        <p class="muted" style="margin:0;">Rafraichissement auto. toutes les 15s &middot; l'onglet selectionne est conserve</p>
      </div>
    </div>
    <div class="live-pill"><span class="pulse"></span>Connecte</div>
  </div>
  <div id="alerts"></div>
  <div class="card" style="max-width:1100px;">
    <div id="tabs" class="tabs"></div>
    <div id="subtabs" class="tabs subtabs"></div>
    <div id="content"></div>
  </div>

<script>
let currentMainTab = "home"; // "home" | "bot" | "config" | "test" - Accueil par defaut au demarrage
let currentBotName = null;
let currentConfigSubTab = "creation"; // "creation" | "supervision"
let currentTestSubTab = "backtest";
let previousRunningStatus = {};

if (window.Notification && Notification.permission === "default") {
  Notification.requestPermission();
}

function showStoppedAlert(name) {
  const alertsEl = document.getElementById("alerts");
  const banner = document.createElement("div");
  banner.className = "alert-banner";
  banner.innerHTML = `<span>⚠️ Le bot <strong>${name}</strong> semble arrete (plus de mise a jour recente).</span>`;
  const closeBtn = document.createElement("button");
  closeBtn.textContent = "✕";
  closeBtn.onclick = () => banner.remove();
  banner.appendChild(closeBtn);
  alertsEl.appendChild(banner);

  if (window.Notification && Notification.permission === "granted") {
    new Notification("Bot arrete", { body: `${name} ne repond plus.` });
  }
}

function checkForStoppedBots(names) {
  for (const name of names) {
    const data = window.BOT_INSTANCES[name];
    if (!data) continue;
    const isRunning = data.updated_at_ts && (Date.now() - data.updated_at_ts) < STALE_AFTER_MS;
    const wasRunning = previousRunningStatus[name];
    if (wasRunning === true && isRunning === false) {
      showStoppedAlert(name);
    }
    previousRunningStatus[name] = isRunning;
  }
}

function loadScript(src) {
  return new Promise((resolve, reject) => {
    const s = document.createElement("script");
    s.src = src + "?t=" + Date.now();
    s.onload = resolve;
    s.onerror = reject;
    document.head.appendChild(s);
  });
}

function fmtPrice(value) {
  return (value === null || value === undefined) ? "-" : value.toFixed(4);
}

const ORDER_REASON_LABELS = {
  stop_loss: "Stop-loss",
  take_profit: "Take-profit",
  trailing_stop: "Trailing stop",
  partial_take_profit: "Sortie partielle",
  flatten_on_start: "Liquidation (redemarrage)",
  signal: "Signal strategie",
};

function renderOrdersTable(orders, currentPrice) {
  if (!orders || orders.length === 0) {
    return '<p class="muted">Aucun ordre pour le moment.</p>';
  }
  // Les positions OUVERTES (l'argent engage MAINTENANT) remontent en premier -
  // c'est l'info qu'on cherche en priorite en arrivant sur cette page, pas
  // l'historique. Les cloturees suivent, la plus recente d'abord.
  const sorted = [...orders].sort((a, b) => {
    if (a.status !== b.status) return a.status === "ouvert" ? -1 : 1;
    return (b.exit_timestamp || b.entry_timestamp || 0) - (a.exit_timestamp || a.entry_timestamp || 0);
  });
  const rows = sorted.map(o => {
    const statusBadge = o.status === "ouvert"
      ? '<span class="status running"><span class="dot"></span>Ouvert</span>'
      : '<span class="status stopped"><span class="dot"></span>Vendu</span>';
    const pnlCell = (o.pnl === null || o.pnl === undefined)
      ? "-"
      : `<span style="color:${o.pnl >= 0 ? "#2fd699" : "#ff6b6b"}">${o.pnl >= 0 ? "+" : ""}${o.pnl.toFixed(4)}</span>`;
    const reasonLabel = o.reason ? (ORDER_REASON_LABELS[o.reason] || o.reason) : "-";
    // Montant investi = quantite x prix d'achat (le cout reel a l'entree),
    // identique pour une position ouverte ou deja cloturee - c'est LA reponse
    // a "combien d'argent y a-t-il dans ce trade", absente jusqu'ici du tableau.
    const montant = (o.quantity ?? 0) * (o.buy_price ?? 0);
    return `<tr>
      <td>${statusBadge}</td>
      <td>${fmtPrice(o.buy_price)}</td>
      <td>${o.quantity !== undefined ? o.quantity.toFixed(6) : "-"}</td>
      <td>${montant.toFixed(2)}</td>
      <td>${fmtPrice(o.target_stop_loss)}</td>
      <td>${fmtPrice(o.sell_price)}</td>
      <td>${reasonLabel}</td>
      <td>${pnlCell}</td>
    </tr>`;
  }).join("");
  return `<table class="bi">
      <thead><tr><th>Statut</th><th>Achat</th><th>Quantite</th><th>Montant</th><th>SL vise</th><th>Vente reelle</th><th>Raison</th><th>P&amp;L</th></tr></thead>
      <tbody>${rows}</tbody>
    </table>`;
}

function formatAxisPrice(v) {
  if (v >= 1000) return v.toLocaleString('fr-FR', {maximumFractionDigits: 0});
  if (v >= 1) return v.toFixed(2);
  if (v >= 0.01) return v.toFixed(4);
  return v.toFixed(6);
}

function formatAxisTime(ts, spanMs) {
  const d = new Date(ts);
  const DAY = 24 * 3600 * 1000;
  if (spanMs < 2 * DAY) return d.toLocaleTimeString('fr-FR', {hour: '2-digit', minute: '2-digit'});
  if (spanMs < 90 * DAY) return d.toLocaleDateString('fr-FR', {day: '2-digit', month: '2-digit'});
  if (spanMs < 3 * 365 * DAY) return d.toLocaleDateString('fr-FR', {month: '2-digit', year: '2-digit'});
  return d.toLocaleDateString('fr-FR', {year: 'numeric'});
}

function priceChartSvg(points, orders) {
  if (!points || points.length < 2) {
    return '<p class="muted">Pas encore assez de donnees pour un graphique.</p>';
  }
  const width = 760, height = 240;
  const padL = 66, padR = 14, padTop = 14, padBottom = 28;

  // Le domaine temporel du graphique est fixe par la fenetre de prix visible
  // (les ~200 dernieres bougies, ou la periode choisie via le selecteur) :
  // un vieux trade clos bien avant cette fenetre ne doit pas l'etirer, sinon
  // la courbe de prix reelle se retrouve ecrasee dans un coin. Les trades
  // hors fenetre sont ignores, ceux qui la chevauchent sont rognes a ses bornes.
  const minTs = points[0][0], maxTs = points[points.length - 1][0];
  const tsSpan = (maxTs - minTs) || 1;

  const relevantOrders = (orders || [])
    .filter(o => o.entry_timestamp && o.entry_timestamp <= maxTs && (o.exit_timestamp || maxTs) >= minTs)
    .map(o => ({
      ...o,
      entry_timestamp: Math.max(o.entry_timestamp, minTs),
      exit_timestamp: o.exit_timestamp ? Math.min(o.exit_timestamp, maxTs) : null,
    }));

  let allValues = points.map(p => p[1]);
  relevantOrders.forEach(o => {
    allValues.push(o.buy_price);
    if (o.sell_price !== null && o.sell_price !== undefined) allValues.push(o.sell_price);
  });
  const minV = Math.min(...allValues), maxV = Math.max(...allValues);
  const vSpan = (maxV - minV) || 1;

  const xScale = ts => ((ts - minTs) / tsSpan) * (width - padL - padR) + padL;
  const yScale = v => height - padBottom - ((v - minV) / vSpan) * (height - padTop - padBottom);

  const priceCoords = points.map(p => `${xScale(p[0]).toFixed(1)},${yScale(p[1]).toFixed(1)}`).join(" ");
  const lastPrice = points[points.length - 1][1], firstPrice = points[0][1];
  const priceColor = lastPrice >= firstPrice ? "#2fd699" : "#ff6b6b";
  const gradId = `pcg${Math.random().toString(36).slice(2, 9)}`;
  const areaBase = height - padBottom;
  const areaPath = `M${xScale(points[0][0]).toFixed(1)},${areaBase} L${priceCoords.split(" ").join(" L")} L${xScale(points[points.length - 1][0]).toFixed(1)},${areaBase} Z`;

  const tradeMarkers = relevantOrders.map(o => {
    const x1 = xScale(o.entry_timestamp);
    const x2 = xScale(o.exit_timestamp || maxTs);
    const yBuy = yScale(o.buy_price);
    const isClosed = o.sell_price !== null && o.sell_price !== undefined;
    const barIsWinning = isClosed ? (o.pnl >= 0) : (lastPrice >= o.buy_price);
    const barColor = barIsWinning ? "#2fd699" : "#ff6b6b";
    let svg = `<line x1="${x1.toFixed(1)}" y1="${yBuy.toFixed(1)}" x2="${x2.toFixed(1)}" y2="${yBuy.toFixed(1)}" stroke="${barColor}" stroke-width="4" stroke-linecap="round" opacity="0.8"><title>Achat @ ${o.buy_price}</title></line>`;
    svg += `<circle cx="${x1.toFixed(1)}" cy="${yBuy.toFixed(1)}" r="4" fill="#2fd699"><title>Achat @ ${o.buy_price}</title></circle>`;
    if (isClosed) {
      const ySell = yScale(o.sell_price);
      svg += `<circle cx="${x2.toFixed(1)}" cy="${ySell.toFixed(1)}" r="4" fill="#ff6b6b"><title>Vente @ ${o.sell_price}</title></circle>`;
    }
    return svg;
  }).join("");

  const Y_TICKS = 4, X_TICKS = 5;
  let yAxis = "";
  for (let i = 0; i <= Y_TICKS; i++) {
    const v = minV + (vSpan * i) / Y_TICKS;
    const y = yScale(v);
    yAxis += `<line x1="${padL}" y1="${y.toFixed(1)}" x2="${width - padR}" y2="${y.toFixed(1)}" stroke="rgba(255,255,255,0.07)" stroke-width="1" />`;
    yAxis += `<text x="${padL - 8}" y="${(y + 3).toFixed(1)}" text-anchor="end" font-size="10" fill="#6b7690">${formatAxisPrice(v)}</text>`;
  }
  let xAxis = "";
  for (let i = 0; i <= X_TICKS; i++) {
    const ts = minTs + (tsSpan * i) / X_TICKS;
    const x = xScale(ts);
    xAxis += `<text x="${x.toFixed(1)}" y="${height - padBottom + 16}" text-anchor="middle" font-size="10" fill="#6b7690">${formatAxisTime(ts, tsSpan)}</text>`;
  }

  return `<svg viewBox="0 0 ${width} ${height}" width="100%" height="${height}" style="background:var(--surface); border:1px solid var(--border); border-radius:10px;">
    <defs>
      <linearGradient id="${gradId}" x1="0" y1="0" x2="0" y2="1">
        <stop offset="0%" stop-color="${priceColor}" stop-opacity="0.28" />
        <stop offset="100%" stop-color="${priceColor}" stop-opacity="0" />
      </linearGradient>
    </defs>
    ${yAxis}
    <path d="${areaPath}" fill="url(#${gradId})" />
    ${tradeMarkers}
    <polyline points="${priceCoords}" fill="none" stroke="${priceColor}" stroke-width="2.25" stroke-linejoin="round" stroke-linecap="round" />
    ${xAxis}
  </svg>
  <p class="muted" style="margin-top:8px;">Ligne = cours du marche. Barre verte = position en gain, barre rouge = position en perte (calcule au prix actuel si encore ouverte). Point vert = achat, point rouge = vente.</p>`;
}

const PRICE_RANGES = ["live", "1h", "1j", "1mois", "1an", "5ans", "10ans"];
const PRICE_RANGE_LABELS = { live: "Live", "1h": "1 heure", "1j": "1 jour", "1mois": "1 mois", "1an": "1 an", "5ans": "5 ans", "10ans": "10 ans" };
let selectedPriceRange = {};       // { [instanceName]: rangeKey }, absent = "live"
let historicalPriceCache = {};     // { "instance|range": { points, fetchedAt } }
const HISTORICAL_CACHE_TTL_MS = 55000;

function getSelectedPriceRange(name) {
  return selectedPriceRange[name] || "live";
}

function selectPriceRange(name, range) {
  selectedPriceRange[name] = range;
  if (range !== "live") ensureHistoricalPriceData(name, range);
  renderBotContent();
}

async function ensureHistoricalPriceData(name, range, data) {
  const cacheKey = `${name}|${range}`;
  const cached = historicalPriceCache[cacheKey];
  if (cached && (Date.now() - cached.fetchedAt) < HISTORICAL_CACHE_TTL_MS) return;
  try {
    const symbol = (data || (window.BOT_INSTANCES || {})[name] || {}).symbol;
    if (!symbol) return;
    const resp = await fetch(`${CONTROL_SERVER}/api/price-history?symbol=${encodeURIComponent(symbol)}&range=${range}`);
    const result = await resp.json();
    if (result.error) return;
    historicalPriceCache[cacheKey] = { points: result.points, fetchedAt: Date.now() };
    if (currentMainTab === "bot" && currentBotName === name && getSelectedPriceRange(name) === range) renderBotContent();
  } catch (e) { /* control server pas accessible : on garde l'ancien affichage */ }
}

function renderPriceRangeSelector(name) {
  const active = getSelectedPriceRange(name);
  const buttons = PRICE_RANGES.map(r =>
    `<button class="range-btn ${r === active ? "active" : ""}" onclick="selectPriceRange('${name}','${r}')">${PRICE_RANGE_LABELS[r]}</button>`
  ).join("");
  return `<div class="range-selector">${buttons}</div>`;
}

function renderPriceChartSection(name, data) {
  const range = getSelectedPriceRange(name);
  let points;
  if (range === "live") {
    points = data.price_history;
  } else {
    const cacheKey = `${name}|${range}`;
    const cached = historicalPriceCache[cacheKey];
    points = cached ? cached.points : null;
    ensureHistoricalPriceData(name, range, data);
  }
  const chartHtml = points
    ? priceChartSvg(points, data.orders)
    : '<p class="muted">Chargement du cours historique...</p>';
  return `${renderPriceRangeSelector(name)}${chartHtml}`;
}

const CONTROL_SERVER = "http://localhost:8765";

// Top 10 cryptos par capitalisation (vs USDT) - liste figee volontairement
// courte pour guider vers des paires liquides/bien supportees par Binance,
// avec une echappatoire "Autre" pour ne pas bloquer un symbole hors liste.
// Types de bot creables depuis le formulaire de Creation (§5.1) - mean_reversion
// et market_making restent YAML uniquement, pas encore promus au formulaire.
const CREATABLE_STRATEGY_TYPES = new Set(["sma_cross", "scalp_dip", "dip_bounce_hourly", "dip_bounce_minute", "buy_and_hold"]);

const TOP10_SYMBOLS = [
  "BTC/USDT", "ETH/USDT", "XRP/USDT", "BNB/USDT", "SOL/USDT",
  "DOGE/USDT", "ADA/USDT", "TRX/USDT", "LINK/USDT", "AVAX/USDT",
];

function symbolSelectHtml(id, selectedValue) {
  const isKnown = TOP10_SYMBOLS.includes(selectedValue);
  const options = TOP10_SYMBOLS.map(s => `<option value="${s}"${s === selectedValue ? " selected" : ""}>${s}</option>`).join("");
  return `
    <select id="${id}" onchange="onSymbolSelectChange('${id}')">
      ${options}
      <option value="__other__"${isKnown ? "" : " selected"}>Autre...</option>
    </select>
    <input id="${id}_other" type="text" placeholder="ex: MATIC/USDT" style="margin-top:6px; ${isKnown ? "display:none;" : ""}" value="${isKnown ? "" : (selectedValue || "")}">
  `;
}

function onSymbolSelectChange(id) {
  const isOther = document.getElementById(id).value === "__other__";
  document.getElementById(`${id}_other`).style.display = isOther ? "block" : "none";
}

function symbolValueOf(id) {
  const select = document.getElementById(id).value;
  return select === "__other__" ? document.getElementById(`${id}_other`).value.trim() : select;
}

function setSymbolValue(id, value) {
  const select = document.getElementById(id);
  const isKnown = TOP10_SYMBOLS.includes(value);
  select.value = isKnown ? value : "__other__";
  document.getElementById(`${id}_other`).value = isKnown ? "" : (value || "");
  document.getElementById(`${id}_other`).style.display = isKnown ? "none" : "block";
}

const MAIN_TABS = [
  { id: "home", label: "🏠 Accueil" },
  { id: "bot", label: "🤖 Bot" },
  { id: "config", label: "⚙ Configuration" },
  { id: "test", label: "🧪 Test" },
];

function renderMainTabs() {
  const tabsEl = document.getElementById("tabs");
  tabsEl.innerHTML = MAIN_TABS.map(t =>
    `<button class="tab ${t.id === currentMainTab ? "active" : ""}" data-id="${t.id}">${t.label}</button>`
  ).join("");
  tabsEl.querySelectorAll(".tab").forEach(btn => {
    btn.onclick = () => { currentMainTab = btn.dataset.id; renderMainTabs(); renderSubTabsAndContent(); };
  });
}

function renderSubTabsAndContent() {
  const subtabsEl = document.getElementById("subtabs");

  if (currentMainTab === "bot") {
    const names = window.BOT_REGISTRY || [];
    if (!currentBotName || !names.includes(currentBotName)) currentBotName = names[0] || null;
    subtabsEl.style.display = names.length ? "flex" : "none";
    subtabsEl.innerHTML = names.map(name => {
      const d = (window.BOT_INSTANCES || {})[name];
      const isRunning = d && d.updated_at_ts && (Date.now() - d.updated_at_ts) < STALE_AFTER_MS;
      const dotColor = isRunning ? "var(--green)" : "var(--red)";
      return `<button class="tab ${name === currentBotName ? "active" : ""}" data-name="${name}">
        <span style="display:inline-block; width:6px; height:6px; border-radius:50%; background:${dotColor}; margin-right:7px; vertical-align:1px;"></span>${name}
      </button>`;
    }).join("");
    subtabsEl.querySelectorAll(".tab").forEach(btn => {
      btn.onclick = () => { currentBotName = btn.dataset.name; renderSubTabsAndContent(); };
    });
    renderBotContent();
    return;
  }

  if (currentMainTab === "config") {
    const subtabs = [{ id: "creation", label: "Creation" }, { id: "supervision", label: "Supervision" }];
    subtabsEl.style.display = "flex";
    subtabsEl.innerHTML = subtabs.map(s =>
      `<button class="tab ${s.id === currentConfigSubTab ? "active" : ""}" data-id="${s.id}">${s.label}</button>`
    ).join("");
    subtabsEl.querySelectorAll(".tab").forEach(btn => {
      btn.onclick = () => { currentConfigSubTab = btn.dataset.id; renderSubTabsAndContent(); };
    });
    renderConfigContent();
    return;
  }

  if (currentMainTab === "test") {
    const subtabs = [{ id: "backtest", label: "Backtest" }];
    subtabsEl.style.display = "flex";
    subtabsEl.innerHTML = subtabs.map(s =>
      `<button class="tab ${s.id === currentTestSubTab ? "active" : ""}" data-id="${s.id}">${s.label}</button>`
    ).join("");
    subtabsEl.querySelectorAll(".tab").forEach(btn => {
      btn.onclick = () => { currentTestSubTab = btn.dataset.id; renderSubTabsAndContent(); };
    });
    if (!document.getElementById("bt_run_btn")) renderTestContent();
    return;
  }

  // home
  subtabsEl.style.display = "none";
  subtabsEl.innerHTML = "";
  renderHome();
}

async function launchBot(payload) {
  const resp = await fetch(`${CONTROL_SERVER}/api/launch-bot`, {
    method: "POST",
    headers: { "Content-Type": "application/json" },
    body: JSON.stringify(payload),
  });
  return resp.json();
}

async function stopBot(name) {
  const resp = await fetch(`${CONTROL_SERVER}/api/stop-bot`, {
    method: "POST",
    headers: { "Content-Type": "application/json" },
    body: JSON.stringify({ name }),
  });
  const data = await resp.json();
  refresh();
  return data;
}

const STALE_AFTER_MS = 3 * 60 * 1000;

function renderLogs(logs) {
  if (!logs || logs.length === 0) {
    return '<p class="muted">Pas encore d\\'action enregistree.</p>';
  }
  const items = logs.slice(-10).reverse().map(entry =>
    `<li><span class="ts">${entry[0]}</span>${entry[1]}</li>`
  ).join("");
  return `<ul class="logs">${items}</ul>`;
}

function fmtPct(v) {
  if (v === null || v === undefined) return "-";
  return `${(v * 100).toFixed(1)} %`;
}

function renderHome() {
  const contentEl = document.getElementById("content");
  const names = window.BOT_REGISTRY || [];
  if (names.length === 0) {
    contentEl.innerHTML = '<div class="empty">Aucun bot detecte pour le moment.</div>';
    return;
  }

  const rows = names.map(name => {
    const d = window.BOT_INSTANCES[name];
    if (!d) return null;
    const pnl = d.equity - d.starting_capital;
    const pnlPct = d.starting_capital ? (pnl / d.starting_capital * 100) : 0;
    const isRunning = d.updated_at_ts && (Date.now() - d.updated_at_ts) < STALE_AFTER_MS;
    return { name, d, pnl, pnlPct, isRunning };
  }).filter(Boolean);

  const totalCapital = rows.reduce((s, r) => s + r.d.starting_capital, 0);
  const totalEquity = rows.reduce((s, r) => s + r.d.equity, 0);
  const totalPnl = totalEquity - totalCapital;
  const totalPnlPct = totalCapital ? (totalPnl / totalCapital * 100) : 0;
  const totalTrades = rows.reduce((s, r) => s + (r.d.num_trades || 0), 0);
  const runningCount = rows.filter(r => r.isRunning).length;
  const bestPnlPct = rows.length > 1 ? Math.max(...rows.map(r => r.pnlPct)) : null;
  // Le solde du panier commun est identique dans les donnees de chaque bot
  // (meme panier partage) : on prend la valeur la plus recente disponible.
  const poolRow = rows.find(r => r.d.pool_available_cash !== null && r.d.pool_available_cash !== undefined);
  const poolAvailable = poolRow ? poolRow.d.pool_available_cash : null;

  const sortedRows = [...rows].sort((a, b) => b.pnlPct - a.pnlPct);
  const bodyRows = sortedRows.map(r => `
    <tr>
      <td>${r.isRunning ? "🟢" : "🔴"} ${r.name}${bestPnlPct !== null && r.pnlPct === bestPnlPct ? " 🏆" : ""}</td>
      <td>${r.d.symbol}</td>
      <td>${r.d.starting_capital.toFixed(2)}</td>
      <td>${r.d.effective_cap !== null && r.d.effective_cap !== undefined ? r.d.effective_cap.toFixed(2) : "-"}</td>
      <td>${r.d.equity.toFixed(2)}</td>
      <td style="color:${r.pnl >= 0 ? "#2fd699" : "#ff6b6b"}">${r.pnl >= 0 ? "+" : ""}${r.pnlPct.toFixed(2)} %</td>
      <td>${r.d.num_trades ?? 0}</td>
      <td>${fmtPct(r.d.win_rate)}</td>
      <td>${fmtPct(r.d.max_drawdown_pct)}</td>
      <td>${r.isRunning ? `<button class="danger" onclick="stopBot('${r.name}')">Arreter</button>` : "-"}</td>
    </tr>
  `).join("");

  contentEl.innerHTML = `
    <h1>Accueil</h1>
    <p class="muted">Vue d'ensemble de tous les bots, triee par performance (P&amp;L %) - utile pour comparer des variantes A/B d'une meme strategie.</p>
    <div class="grid">
      <div>
        <div class="stat-label">Bots actifs</div>
        <div class="stat-value">${runningCount} / ${rows.length}</div>
      </div>
      <div>
        <div class="stat-label">Capital total alloue (plafonds de base)</div>
        <div class="stat-value">${totalCapital.toFixed(2)}</div>
      </div>
      <div>
        <div class="stat-label">Panier commun disponible</div>
        <div class="stat-value">${poolAvailable !== null ? poolAvailable.toFixed(2) : "-"}</div>
      </div>
      <div>
        <div class="stat-label">Valeur totale actuelle</div>
        <div class="stat-value">${totalEquity.toFixed(2)}</div>
      </div>
      <div>
        <div class="stat-label">P&amp;L global</div>
        <div class="stat-value" style="color:${totalPnl >= 0 ? "#2fd699" : "#ff6b6b"}">${totalPnl >= 0 ? "+" : ""}${totalPnl.toFixed(2)} (${totalPnlPct >= 0 ? "+" : ""}${totalPnlPct.toFixed(2)} %)</div>
      </div>
      <div>
        <div class="stat-label">Trades executes (tous bots)</div>
        <div class="stat-value">${totalTrades}</div>
      </div>
    </div>
    <p class="muted">Tous les bots piochent desormais dans un panier de capital commun (au lieu de fonds isoles) : le "Plafond effectif" de chaque bot evolue automatiquement selon sa performance recente (taux de reussite x rendement), des qu'il a cloture au moins 10 trades en live.</p>
    <table class="bi">
      <thead>
        <tr><th>Bot</th><th>Symbole</th><th>Plafond de base</th><th>Plafond effectif</th><th>Valeur</th><th>P&amp;L</th><th>Trades</th><th>Win rate</th><th>Drawdown max</th><th>Action</th></tr>
      </thead>
      <tbody>${bodyRows}</tbody>
    </table>
  `;
}

function strategyFieldsHtml(type) {
  if (type === "scalp_dip") {
    return `
      <div class="field"><label>Lookback (bougies)</label><input id="f_lookback" type="number" value="20"></div>
      <div class="field"><label>Seuil de creux (%)</label><input id="f_dip_threshold_pct" type="number" step="0.01" value="0.3"></div>
    `;
  }
  if (type === "dip_bounce_hourly" || type === "dip_bounce_minute") {
    const windowLabel = type === "dip_bounce_hourly" ? "24 bougies (24h)" : "60 bougies (1h)";
    return `
      <div class="field"><label>Seuil de creux (%, proximite du plus bas de la fenetre)</label><input id="f_dip_threshold_pct" type="number" step="0.01" value="0.5"></div>
      <div class="field"><label>Armement du verrou de gain (%)</label><input id="f_profit_lock_arm_pct" type="number" step="0.01" value="0.5"></div>
      <div class="field"><label>Declenchement du verrou de gain (%, doit etre &lt; armement)</label><input id="f_profit_lock_trigger_pct" type="number" step="0.01" value="0.43"></div>
      <div class="field"><label>Forcer un trade apres N heures sans achat (0 = desactive)</label><input id="f_force_trade_after_hours" type="number" step="1" min="0" value="0"></div>
      <p class="adv-hint" style="grid-column:1/-1;">Fenetre glissante fixe : ${windowLabel}. Achete des que le prix est proche du plus bas de la fenetre (aucune condition de tendance requise) ; hold jusqu'a etre rentable, sortie normale : le verrou de gain (arme au-dela du 1er seuil, vend si le gain retombe au 2e). <strong>Stop-loss optionnel</strong> (champ "Gestion du risque" ci-dessous, vide par defaut) : sans lui, une position peut rester ouverte longtemps en perte latente si elle n'atteint jamais le seuil d'armement - voir le manuel utilisateur. "Forcer un trade" assouplit progressivement (double a chaque periode supplementaire) le seuil de creux si aucun achat n'a eu lieu depuis N heures - idee proposee par l'utilisateur, desactive par defaut.</p>
    `;
  }
  if (type === "buy_and_hold") {
    return `
      <p class="adv-hint" style="grid-column:1/-1;">Achete UNE SEULE FOIS a son premier cycle, avec "Taille position max" du "Plafond de mise", puis ne revend jamais - pas de stop-loss, pas de take-profit, pas de rechauffement necessaire. Bot passif, comparable au benchmark "buy &amp; hold" utilise pour juger les autres strategies.</p>
    `;
  }
  return `
    <div class="field"><label>Moyenne courte (bougies)</label><input id="f_short_window" type="number" value="10"></div>
    <div class="field"><label>Moyenne longue (bougies)</label><input id="f_long_window" type="number" value="30"></div>
  `;
}

function onStrategyTypeChange(type) {
  document.getElementById("f_strategy_fields").innerHTML = strategyFieldsHtml(type);

  const isDipBounce = type === "dip_bounce_hourly" || type === "dip_bounce_minute";
  const noStopLoss = type === "buy_and_hold";

  const timeframeSelect = document.getElementById("f_timeframe");
  const timeframeHint = document.getElementById("f_timeframe_hint");
  if (isDipBounce) {
    timeframeSelect.value = type === "dip_bounce_hourly" ? "1h" : "1m";
    timeframeSelect.disabled = true;
    timeframeHint.textContent = "Fixe par la strategie choisie.";
    timeframeHint.style.display = "block";
  } else {
    timeframeSelect.disabled = false;
    timeframeHint.style.display = "none";
  }

  // Stop-loss : desactive pour de bon uniquement pour buy_and_hold (achat
  // unique, jamais revendu). Pour "Rebond de creux", redevient optionnel
  // (demande explicite de l'utilisateur, 2026-09-15) - vide reste desactive
  // par defaut (comportement historique inchange), une valeur l'active.
  const stopLossInput = document.getElementById("f_stop_loss_pct");
  const stopLossHint = document.getElementById("f_stop_loss_hint");
  if (noStopLoss) {
    stopLossInput.value = "";
    stopLossInput.disabled = true;
    stopLossInput.placeholder = "";
    stopLossHint.textContent = "Desactive : cette strategie n'a pas de stop-loss (decision assumee).";
    stopLossHint.style.display = "block";
  } else if (isDipBounce) {
    stopLossInput.disabled = false;
    stopLossInput.placeholder = "vide = desactive";
    if (stopLossInput.value === "2") stopLossInput.value = "";  // n'herite pas du defaut des autres strategies
    stopLossHint.textContent = "Optionnel, vide par defaut (decision historique de cette strategie) - une valeur l'active comme pour les autres strategies.";
    stopLossHint.style.display = "block";
  } else {
    stopLossInput.disabled = false;
    stopLossInput.placeholder = "";
    if (!stopLossInput.value) stopLossInput.value = "2";
    stopLossHint.style.display = "none";
  }
}

function renderConfigsTable(configs) {
  if (!configs || configs.length === 0) {
    return '<p class="muted">Aucune config trouvee dans config/.</p>';
  }
  const rows = configs.map(c => `
    <tr>
      <td>${c.running ? "🟢" : "🔴"} ${c.name}</td>
      <td>${c.symbol ?? "-"}</td>
      <td>${c.strategy_type ?? "-"}</td>
      <td>${c.timeframe ?? "-"}</td>
      <td>${c.capital_allocated ?? "-"}</td>
      <td style="display:flex; gap:6px; flex-wrap:wrap;">
        ${c.running
          ? `<button class="danger" onclick="stopBot('${c.name}')">Arreter</button>`
          : `<button class="primary" style="padding:5px 12px;" onclick="startExistingBot('${c.config_path}')">Demarrer</button>`}
        <button class="secondary" onclick="editBot('${c.name}')" ${c.running ? "disabled title=\\"arrete le bot pour le modifier\\"" : ""}>Modifier</button>
        <button class="danger" onclick="deleteBot('${c.name}')" ${c.running ? "disabled title=\\"arrete le bot pour le supprimer\\"" : ""}>Supprimer</button>
      </td>
    </tr>
  `).join("");
  return `<table class="bi">
    <thead><tr><th>Bot</th><th>Symbole</th><th>Strategie</th><th>Timeframe</th><th>Plafond</th><th>Actions</th></tr></thead>
    <tbody>${rows}</tbody>
  </table>`;
}

async function refreshExistingBotsList() {
  const el = document.getElementById("existing-bots-list");
  if (!el) return;
  try {
    const resp = await fetch(`${CONTROL_SERVER}/api/list-configs`);
    const data = await resp.json();
    el.innerHTML = renderConfigsTable(data.configs);
  } catch (e) {
    el.innerHTML = '<p class="form-status err">Serveur de controle non accessible. Lance \\'python -m tradingbot.control_server\\' (ou start_control_server.bat).</p>';
  }
}

function renderProposalsTable(proposals) {
  if (!proposals || proposals.length === 0) {
    return '<p class="muted">Aucune proposition de reoptimisation en attente. Clique "Lancer la reoptimisation de tous les bots" ci-dessus, ou lance <code>python -m tradingbot.reoptimizer --name &lt;bot&gt;</code> (etape 5 de la feuille de route performance).</p>';
  }
  const rows = proposals.map(p => {
    const group = p.group || "manuel";
    const groupBadge = group === "auto"
      ? '<span class="badge" style="background:var(--green-soft); color:#5eeab8; border-color:rgba(47,214,153,0.3);">auto</span>'
      : group === "control"
        ? '<span class="badge" style="background:var(--purple-soft); color:#cbb6ff; border-color:rgba(177,140,255,0.3);">control</span>'
        : '<span class="badge">manuel</span>';
    return `
    <tr>
      <td>${p.name}<br>${groupBadge}</td>
      <td>${p.current.description}<br><span class="muted">validation : ${p.current.test_return_pct === null ? "n/a" : (p.current.test_return_pct * 100).toFixed(2) + " %"}</span></td>
      <td>${p.proposed.description}<br><span class="muted">validation : ${(p.proposed.test_return_pct * 100).toFixed(2)} % (entrainement : ${p.proposed.train_return_pct === null ? "n/a" : (p.proposed.train_return_pct * 100).toFixed(2) + " %"})</span></td>
      <td style="display:flex; gap:6px; flex-wrap:wrap;">
        <button class="primary" style="padding:5px 12px;" onclick="applyProposal('${p.name}')">Appliquer</button>
        <button class="secondary" onclick="dismissProposal('${p.name}')">Rejeter</button>
      </td>
    </tr>
  `;
  }).join("");
  return `<table class="bi">
    <thead><tr><th>Bot</th><th>Config actuelle</th><th>Config proposee</th><th>Actions</th></tr></thead>
    <tbody>${rows}</tbody>
  </table>
  <p class="muted" style="margin-top:6px;">"Validation" = performance sur des donnees jamais vues pendant la recherche (out-of-sample). Badge "auto" = deja applique automatiquement par le test A/B (feuille de route etape 5), "control" = jamais applique automatiquement (reference du test), "manuel" = attend ta decision. Voir le manuel utilisateur.</p>`;
}

async function reoptimizeAllBots() {
  const btn = document.getElementById("f_reoptimize_all_btn");
  const statusEl = document.getElementById("f_reoptimize_all_status");
  btn.disabled = true;
  statusEl.textContent = "Lancement en cours (peut prendre plusieurs minutes pour tous les bots)...";
  try {
    const resp = await fetch(`${CONTROL_SERVER}/api/reoptimize-all`, {
      method: "POST",
      headers: { "Content-Type": "application/json" },
      body: JSON.stringify({}),
    });
    const data = await resp.json();
    if (data.error) {
      statusEl.textContent = `Erreur : ${data.error}`;
    } else {
      statusEl.textContent = "Reoptimisation lancee en arriere-plan - les propositions (et les changements automatiques du groupe auto) apparaitront ici au fil de l'eau, rafraichis toutes les 15s.";
    }
  } catch (e) {
    statusEl.textContent = "Serveur de controle non accessible.";
  } finally {
    btn.disabled = false;
  }
}

async function restartAllBots() {
  if (!confirm("Redemarrer tous les bots actuellement en cours ? Chacun est arrete puis relance depuis sa config sur disque - utile apres une mise a jour du logiciel pour que les bots (et l'affichage qu'ils regenerent) prennent en compte la derniere version. Les positions ouvertes sont restaurees a l'identique, rien n'est vendu.")) return;
  const btn = document.getElementById("f_restart_all_btn");
  const statusEl = document.getElementById("f_restart_all_status");
  btn.disabled = true;
  statusEl.textContent = "Redemarrage en cours (peut prendre du temps s'il y a plusieurs bots)...";
  try {
    const resp = await fetch(`${CONTROL_SERVER}/api/restart-all-bots`, {
      method: "POST",
      headers: { "Content-Type": "application/json" },
      body: JSON.stringify({}),
    });
    const data = await resp.json();
    if (data.error) {
      statusEl.textContent = `Erreur : ${data.error}`;
      btn.disabled = false;
      return;
    }
    const results = data.results || [];
    const failed = results.filter(r => !r.ok);
    if (results.length === 0) {
      statusEl.textContent = "Aucun bot n'etait en cours - rien a redemarrer.";
      btn.disabled = false;
      return;
    }
    statusEl.textContent = failed.length
      ? `${results.length - failed.length}/${results.length} redemarre(s). Echec(s) : ${failed.map(r => `${r.name} (${r.error})`).join(", ")}`
      : `${results.length} bot(s) redemarre(s). Rechargement de la page dans quelques secondes...`;
    await refreshExistingBotsList();
    setTimeout(() => { window.location.reload(); }, 4000);
  } catch (e) {
    statusEl.textContent = "Serveur de controle non accessible.";
    btn.disabled = false;
  }
}

async function refreshProposalsList() {
  const el = document.getElementById("proposals-list");
  if (!el) return;
  try {
    const resp = await fetch(`${CONTROL_SERVER}/api/list-proposals`);
    const data = await resp.json();
    el.innerHTML = renderProposalsTable(data.proposals);
  } catch (e) {
    el.innerHTML = '<p class="form-status err">Serveur de controle non accessible.</p>';
  }
}

async function applyProposal(name) {
  if (!confirm(`Appliquer la config proposee pour "${name}" ? Le bot sera redemarre s'il tourne.`)) return;
  try {
    const resp = await fetch(`${CONTROL_SERVER}/api/apply-proposal`, {
      method: "POST",
      headers: { "Content-Type": "application/json" },
      body: JSON.stringify({ name }),
    });
    const data = await resp.json();
    if (data.error) { alert(data.error); return; }
    await refreshProposalsList();
    await refreshExistingBotsList();
    setTimeout(refresh, 3000);
  } catch (e) {
    alert("Serveur de controle non accessible.");
  }
}

async function dismissProposal(name) {
  try {
    const resp = await fetch(`${CONTROL_SERVER}/api/dismiss-proposal`, {
      method: "POST",
      headers: { "Content-Type": "application/json" },
      body: JSON.stringify({ name }),
    });
    await resp.json();
    await refreshProposalsList();
  } catch (e) {
    alert("Serveur de controle non accessible.");
  }
}

const inFlightStarts = new Set();  // evite un double-lancement si on double-clique sur "Demarrer"

async function startExistingBot(configPath) {
  if (inFlightStarts.has(configPath)) return;
  inFlightStarts.add(configPath);
  try {
    const resp = await fetch(`${CONTROL_SERVER}/api/start-bot`, {
      method: "POST",
      headers: { "Content-Type": "application/json" },
      body: JSON.stringify({ config_path: configPath }),
    });
    const data = await resp.json();
    if (data.error) alert(data.error);
    await refreshExistingBotsList();
    setTimeout(refresh, 3000);
  } catch (e) {
    alert("Serveur de controle non accessible.");
  } finally {
    inFlightStarts.delete(configPath);
  }
}

function renderConfigContent() {
  if (currentConfigSubTab === "supervision") {
    renderSupervisionTab();
  } else {
    renderCreationTab();
  }
}

async function renderSupervisionTab() {
  const contentEl = document.getElementById("content");
  if (!document.getElementById("supervision-root")) {
    contentEl.innerHTML = `
    <div id="supervision-root">
    <h1>Supervision</h1>
    <p class="muted">Demarre ou arrete un bot existant, et gere les propositions de reoptimisation automatique (necessite <code>python -m tradingbot.control_server</code>).</p>

    <div class="section-block">
      <h2 style="display:flex; align-items:center; justify-content:space-between; gap:12px; flex-wrap:wrap;">
        <span>Propositions de reoptimisation</span>
        <button class="primary" style="padding:7px 15px; font-size:12px;" onclick="reoptimizeAllBots()" id="f_reoptimize_all_btn">Lancer la reoptimisation de tous les bots</button>
      </h2>
      <p class="muted" id="f_reoptimize_all_status"></p>
      <div id="proposals-list"><p class="muted">Chargement...</p></div>
    </div>

    <div class="section-block">
      <h2 style="display:flex; align-items:center; justify-content:space-between; gap:12px; flex-wrap:wrap;">
        <span>Bots existants</span>
        <button class="secondary" style="padding:7px 15px; font-size:12px;" onclick="restartAllBots()" id="f_restart_all_btn">Redemarrer tous les bots (recharge le code)</button>
      </h2>
      <p class="muted" id="f_restart_all_status"></p>
      <div id="existing-bots-list"><p class="muted">Chargement...</p></div>
    </div>
    </div>
    `;
  }
  await refreshProposalsList();
  await refreshExistingBotsList();
}

function renderCreationTab() {
  const contentEl = document.getElementById("content");
  if (!document.getElementById("manage-bots-root")) {
    contentEl.innerHTML = `
    <div id="manage-bots-root">
    <h1>Creation</h1>
    <p class="muted">Cree un nouveau bot directement depuis cette page, ou modifie un bot existant depuis l'onglet Supervision (necessite <code>python -m tradingbot.control_server</code>).</p>

    <h2 id="f_form_heading" style="font-size:16px; text-transform:none; letter-spacing:0; color:var(--text); margin-top:20px;">Creer un nouveau bot</h2>

    <div class="section-block" style="margin-top:16px;">
      <h2>General</h2>
      <div class="form-grid">
        <div class="field"><label>Nom (unique, sans espace)</label><input id="f_name" type="text" placeholder="ex: eth_swing_v1"></div>
        <div class="field"><label>Symbole</label>${symbolSelectHtml("f_symbol", "ETH/USDT")}</div>
        <div class="field" id="f_timeframe_wrap"><label>Timeframe</label>
          <select id="f_timeframe">
            <option value="1m">1 minute</option>
            <option value="5m">5 minutes</option>
            <option value="15m">15 minutes</option>
            <option value="1h" selected>1 heure</option>
            <option value="4h">4 heures</option>
            <option value="1d">1 jour</option>
          </select>
          <div id="f_timeframe_hint" class="muted" style="font-size:11px; margin-top:4px; display:none;"></div>
        </div>
        <div class="field"><label>Strategie</label>
          <select id="f_strategy_type" onchange="onStrategyTypeChange(this.value)">
            <option value="sma_cross">Croisement de moyennes (tendance)</option>
            <option value="scalp_dip">Scalp sur creux (gains rapides)</option>
            <option value="dip_bounce_hourly">Rebond de creux - horaire (24h)</option>
            <option value="dip_bounce_minute">Rebond de creux - minute (1h)</option>
            <option value="buy_and_hold">Buy &amp; hold (passif)</option>
          </select>
        </div>
        <div class="field"><label>Plafond de mise (panier commun)</label><input id="f_capital_allocated" type="number" value="200"></div>
        <div class="field"><label>Bougies de rechauffement</label><input id="f_warmup_candles" type="number" value="50"></div>
      </div>
      <div id="f_strategy_fields" class="form-grid" style="margin-top:13px;">${strategyFieldsHtml("sma_cross")}</div>
    </div>

    <div class="section-block">
      <h2>Gestion du risque</h2>
      <div class="form-grid">
        <div class="field"><label>Taille position max (%)</label><input id="f_max_position_size_pct" type="number" step="0.01" value="10"></div>
        <div class="field" id="f_stop_loss_wrap"><label>Stop-loss (%)</label><input id="f_stop_loss_pct" type="number" step="0.01" value="2">
          <div id="f_stop_loss_hint" class="muted" style="font-size:11px; margin-top:4px; display:none;"></div>
        </div>
        <div class="field"><label>Take-profit (%, vide = desactive)</label><input id="f_take_profit_pct" type="number" step="0.01" placeholder="vide = desactive"></div>
        <div class="field"><label>Perte max journaliere (%)</label><input id="f_max_daily_loss_pct" type="number" step="0.01" value="5"></div>
        <div class="field"><label>Positions simultanees max</label><input id="f_max_concurrent_positions" type="number" step="1" min="1" value="1"></div>
        <div class="field"><label>Trailing stop (%, vide = desactive)</label><input id="f_trailing_stop_pct" type="number" step="0.01" placeholder="vide = desactive"></div>
        <div class="field"><label>Frais par ordre (%)</label><input id="f_fee_pct" type="number" step="0.01" value="0.1"></div>
        <div class="field"><label>Timeframe de surveillance des sorties (ex: 5m, vide = desactive)</label><input id="f_exit_check_timeframe" type="text" placeholder="vide = desactive"></div>
      </div>
      <p class="adv-hint">"Timeframe de surveillance des sorties" verifie le stop-loss/verrou de gain/trailing stop plus souvent que le timeframe du bot (ex: toutes les 5 minutes au lieu d'une fois par heure), sans changer les entrees de la strategie - doit etre plus fin que le timeframe choisi ci-dessus. Voir le manuel utilisateur.</p>
      <p class="adv-hint">"Positions simultanees max" &gt; 1 permet au bot d'ouvrir plusieurs positions en parallele (chacune avec la meme taille) au lieu d'attendre que la precedente se cloture. Le nombre de positions x la taille par position ne doit pas depasser 100% du capital ; une nouvelle position n'est jamais ouverte si une position existante est deja en perte latente (protection automatique). "Trailing stop" fait suivre le stop-loss au prix quand il monte. "Frais par ordre" simule les frais reels de l'exchange (0.1% = taker Binance spot typique).</p>
    </div>

    <div class="section-block">
      <h2>Filtres avances (optionnel)</h2>

      <details class="adv-section">
        <summary><span>Sortie partielle (scale-out)</span><span class="chev">&#9656;</span></summary>
        <div class="adv-body">
          <div class="form-grid">
            <div class="field"><label>Palier de sortie partielle (%, vide = desactive)</label><input id="f_partial_take_profit_pct" type="number" step="0.01" placeholder="vide = desactive"
              onchange="document.getElementById('f_partial_exit_fraction_wrap').style.display = this.value ? 'block' : 'none'"></div>
            <div class="field" id="f_partial_exit_fraction_wrap" style="display:none;">
              <label>Fraction vendue au palier (%)</label>
              <input id="f_partial_exit_fraction" type="number" step="1" min="1" max="99" value="50">
            </div>
          </div>
          <p class="adv-hint">Vend une FRACTION du lot (ex: 50%) des qu'un premier gain est atteint, et laisse le reste continuer avec le stop-loss/trailing stop normal - securise une partie du gain sans plafonner le potentiel de hausse sur le reste. Doit etre strictement inferieur au "Take-profit" complet si les deux sont configures. Se declenche une seule fois par position.</p>
        </div>
      </details>

      <details class="adv-section">
        <summary><span>Filtre de probabilite (Monte Carlo)</span><span class="chev">&#9656;</span></summary>
        <div class="adv-body">
          <div class="form-grid">
            <div class="field">
              <label><input type="checkbox" id="f_probability_filter_enabled" style="width:auto; margin-right:6px;"
                onchange="document.getElementById('f_min_probability_wrap').style.display = this.checked ? 'block' : 'none'">
              Activer</label>
            </div>
            <div class="field" id="f_min_probability_wrap" style="display:none;">
              <label>Seuil de probabilite de hausse a 24h requis (%)</label>
              <input id="f_min_probability" type="number" step="1" value="55">
            </div>
          </div>
          <p class="adv-hint">Bloque un achat si la probabilite estimee de hausse sur 24h (simulation statistique sur 3 ans d'historique, pas une prediction fiable) est sous ce seuil. Voir le manuel utilisateur.</p>
        </div>
      </details>

      <details class="adv-section">
        <summary><span>Filtre de tendance (EMA)</span><span class="chev">&#9656;</span></summary>
        <div class="adv-body">
          <div class="form-grid">
            <div class="field">
              <label><input type="checkbox" id="f_trend_filter_enabled" style="width:auto; margin-right:6px;"
                onchange="document.getElementById('f_trend_filter_ema_wrap').style.display = this.checked ? 'block' : 'none'">
              Activer</label>
            </div>
            <div class="field" id="f_trend_filter_ema_wrap" style="display:none;">
              <label>Periode de l'EMA (bougies)</label>
              <input id="f_trend_filter_ema_period" type="number" step="1" min="2" value="200">
            </div>
          </div>
          <p class="adv-hint">Bloque un achat si le prix est sous la moyenne mobile exponentielle (regime baissier) - evite d'acheter a contre-courant d'une tendance de fond. Voir le manuel utilisateur.</p>
        </div>
      </details>

      <details class="adv-section">
        <summary><span>Sizing par volatilite (ATR)</span><span class="chev">&#9656;</span></summary>
        <div class="adv-body">
          <div class="form-grid">
            <div class="field">
              <label><input type="checkbox" id="f_atr_sizing_enabled" style="width:auto; margin-right:6px;"
                onchange="document.getElementById('f_atr_sizing_wrap').style.display = this.checked ? 'block' : 'none'">
              Activer</label>
            </div>
          </div>
          <div id="f_atr_sizing_wrap" class="form-grid" style="display:none; margin-top:13px;">
            <div class="field"><label>Periode ATR (bougies)</label><input id="f_atr_period" type="number" step="1" min="1" value="14"></div>
            <div class="field"><label>Periode de reference (bougies)</label><input id="f_atr_baseline_period" type="number" step="1" min="1" value="100"></div>
            <div class="field"><label>Taille minimum (% de la normale)</label><input id="f_atr_min_multiplier" type="number" step="1" min="1" max="100" value="20"></div>
          </div>
          <p class="adv-hint">Reduit la taille d'une position quand la volatilite recente (ATR) depasse sa moyenne habituelle - jamais plus que "Taille position max", seulement moins en periode agitee. Voir le manuel utilisateur.</p>
        </div>
      </details>

      <details class="adv-section">
        <summary><span>Sizing par niveau de prix (moyenne du mois)</span><span class="chev">&#9656;</span></summary>
        <div class="adv-body">
          <div class="form-grid">
            <div class="field">
              <label><input type="checkbox" id="f_price_level_sizing_enabled" style="width:auto; margin-right:6px;"
                onchange="document.getElementById('f_price_level_sizing_wrap').style.display = this.checked ? 'block' : 'none'">
              Activer</label>
            </div>
          </div>
          <div id="f_price_level_sizing_wrap" class="form-grid" style="display:none; margin-top:13px;">
            <div class="field"><label>Taille minimum (% de la normale)</label><input id="f_price_level_min_multiplier" type="number" step="1" min="1" value="50"></div>
            <div class="field"><label>Taille maximum (% de la normale)</label><input id="f_price_level_max_multiplier" type="number" step="1" min="1" value="150"></div>
          </div>
          <p class="adv-hint">Augmente la taille d'une position si le prix actuel est SOUS la moyenne du mois calendaire en cours (on met plus sur un creux relatif), la reduit s'il est AU-DESSUS - contrairement au sizing ATR, celui-ci peut aussi bien agrandir que reduire. Idee proposee par l'utilisateur. La moyenne se reinitialise chaque 1er du mois (bruitee en debut de mois).</p>
        </div>
      </details>
    </div>

    <div class="form-actions">
      <button class="primary" id="f_submit_btn" onclick="submitNewBotForm()">Lancer le bot</button>
      <button class="secondary" id="f_cancel_edit" style="display:none;" onclick="cancelEdit()">Annuler</button>
      <span id="f_status" class="form-status"></span>
    </div>
    </div>
    `;
  }
}

let editingBotName = null;

async function editBot(name) {
  currentMainTab = "config";
  currentConfigSubTab = "creation";
  renderMainTabs();
  renderSubTabsAndContent();
  try {
    const resp = await fetch(`${CONTROL_SERVER}/api/config?name=${encodeURIComponent(name)}`);
    const data = await resp.json();
    if (data.error) { alert(data.error); return; }
    fillFormWithConfig(name, data.config);
  } catch (e) {
    alert("Serveur de controle non accessible.");
  }
}

function formStrategyTypeFor(cfg) {
  // dip_bounce n'a qu'un seul `strategy.type` reel en config (voir
  // strategies/dip_bounce.py, agnostique du timeframe) mais 2 presets cote
  // formulaire - determine par la fenetre (24 = horaire, 60 = minute).
  if (cfg.strategy.type === "dip_bounce") {
    return cfg.strategy.trend_ma_period === 60 ? "dip_bounce_minute" : "dip_bounce_hourly";
  }
  return cfg.strategy.type;
}

function fillFormWithConfig(name, cfg) {
  editingBotName = name;
  const formType = formStrategyTypeFor(cfg);
  document.getElementById("f_name").value = cfg.name;
  setSymbolValue("f_symbol", cfg.symbol);
  document.getElementById("f_timeframe").value = cfg.timeframe;
  document.getElementById("f_strategy_type").value = formType;
  onStrategyTypeChange(formType);  // pose aussi les champs + verrouille timeframe/stop-loss si besoin

  if (cfg.strategy.type === "sma_cross") {
    document.getElementById("f_short_window").value = cfg.strategy.short_window;
    document.getElementById("f_long_window").value = cfg.strategy.long_window;
  } else if (cfg.strategy.type === "scalp_dip") {
    document.getElementById("f_lookback").value = cfg.strategy.lookback;
    document.getElementById("f_dip_threshold_pct").value = cfg.strategy.dip_threshold_pct * 100;
  } else if (cfg.strategy.type === "dip_bounce") {
    document.getElementById("f_dip_threshold_pct").value = cfg.strategy.dip_threshold_pct * 100;
    document.getElementById("f_profit_lock_arm_pct").value = (cfg.risk.profit_lock_arm_pct ?? 0.005) * 100;
    document.getElementById("f_profit_lock_trigger_pct").value = (cfg.risk.profit_lock_trigger_pct ?? 0.0043) * 100;
    document.getElementById("f_force_trade_after_hours").value = cfg.strategy.force_trade_after_hours ?? 0;
  }
  // buy_and_hold : aucun champ de strategie a peupler.

  document.getElementById("f_capital_allocated").value = cfg.capital_allocated;
  document.getElementById("f_max_position_size_pct").value = cfg.risk.max_position_size_pct * 100;
  if (cfg.risk.stop_loss_pct !== null && cfg.risk.stop_loss_pct !== undefined) {
    document.getElementById("f_stop_loss_pct").value = cfg.risk.stop_loss_pct * 100;
  }
  document.getElementById("f_take_profit_pct").value = cfg.risk.take_profit_pct !== null ? cfg.risk.take_profit_pct * 100 : "";
  document.getElementById("f_max_daily_loss_pct").value = cfg.risk.max_daily_loss_pct * 100;
  document.getElementById("f_max_concurrent_positions").value = cfg.risk.max_concurrent_positions ?? 1;
  document.getElementById("f_trailing_stop_pct").value = cfg.risk.trailing_stop_pct !== null && cfg.risk.trailing_stop_pct !== undefined ? cfg.risk.trailing_stop_pct * 100 : "";
  const partialEnabled = cfg.risk.partial_take_profit_pct !== null && cfg.risk.partial_take_profit_pct !== undefined;
  document.getElementById("f_partial_take_profit_pct").value = partialEnabled ? cfg.risk.partial_take_profit_pct * 100 : "";
  document.getElementById("f_partial_exit_fraction_wrap").style.display = partialEnabled ? "block" : "none";
  document.getElementById("f_partial_exit_fraction").value = (cfg.risk.partial_exit_fraction ?? 0.5) * 100;
  document.getElementById("f_fee_pct").value = (cfg.risk.fee_pct ?? 0.001) * 100;
  document.getElementById("f_exit_check_timeframe").value = cfg.exit_check_timeframe ?? "";
  document.getElementById("f_warmup_candles").value = cfg.warmup_candles;

  const pf = cfg.probability_filter;
  const pfEnabled = !!(pf && pf.enabled);
  document.getElementById("f_probability_filter_enabled").checked = pfEnabled;
  document.getElementById("f_min_probability_wrap").style.display = pfEnabled ? "block" : "none";
  document.getElementById("f_min_probability").value = pfEnabled ? pf.min_probability * 100 : 55;

  const tf = cfg.trend_filter;
  const tfEnabled = !!(tf && tf.enabled);
  document.getElementById("f_trend_filter_enabled").checked = tfEnabled;
  document.getElementById("f_trend_filter_ema_wrap").style.display = tfEnabled ? "block" : "none";
  document.getElementById("f_trend_filter_ema_period").value = tfEnabled ? tf.ema_period : 200;

  const atrs = cfg.atr_sizing;
  const atrsEnabled = !!(atrs && atrs.enabled);
  document.getElementById("f_atr_sizing_enabled").checked = atrsEnabled;
  document.getElementById("f_atr_sizing_wrap").style.display = atrsEnabled ? "block" : "none";
  document.getElementById("f_atr_period").value = atrsEnabled ? atrs.atr_period : 14;
  document.getElementById("f_atr_baseline_period").value = atrsEnabled ? atrs.baseline_period : 100;
  document.getElementById("f_atr_min_multiplier").value = atrsEnabled ? atrs.min_size_multiplier * 100 : 20;

  const pls = cfg.price_level_sizing;
  const plsEnabled = !!(pls && pls.enabled);
  document.getElementById("f_price_level_sizing_enabled").checked = plsEnabled;
  document.getElementById("f_price_level_sizing_wrap").style.display = plsEnabled ? "block" : "none";
  document.getElementById("f_price_level_min_multiplier").value = plsEnabled ? pls.min_size_multiplier * 100 : 50;
  document.getElementById("f_price_level_max_multiplier").value = plsEnabled ? pls.max_size_multiplier * 100 : 150;

  [
    [partialEnabled, "f_partial_take_profit_pct"],
    [pfEnabled, "f_probability_filter_enabled"],
    [tfEnabled, "f_trend_filter_enabled"],
    [atrsEnabled, "f_atr_sizing_enabled"],
    [plsEnabled, "f_price_level_sizing_enabled"],
  ].forEach(([enabled, fieldId]) => {
    if (!enabled) return;
    const details = document.getElementById(fieldId)?.closest("details.adv-section");
    if (details) details.open = true;
  });

  document.getElementById("f_form_heading").textContent = `Modifier "${name}"`;
  document.getElementById("f_submit_btn").textContent = "Enregistrer les modifications";
  document.getElementById("f_cancel_edit").style.display = "inline-block";
  document.getElementById("f_status").textContent = "";

  document.getElementById("manage-bots-root").scrollIntoView({ behavior: "smooth", block: "end" });
}

function cancelEdit() {
  editingBotName = null;
  document.getElementById("manage-bots-root")?.remove();
  renderCreationTab();
}

async function deleteBot(name) {
  if (!confirm(`Supprimer definitivement le bot "${name}" ?\\n(l'historique des trades en base SQLite est conserve dans data/${name}.db)`)) {
    return;
  }
  try {
    const resp = await fetch(`${CONTROL_SERVER}/api/delete-bot`, {
      method: "POST",
      headers: { "Content-Type": "application/json" },
      body: JSON.stringify({ name }),
    });
    const data = await resp.json();
    if (data.error) { alert(data.error); return; }
    await refreshExistingBotsList();
    setTimeout(refresh, 1000);
  } catch (e) {
    alert("Serveur de controle non accessible.");
  }
}

async function updateBot(payload) {
  const resp = await fetch(`${CONTROL_SERVER}/api/update-bot`, {
    method: "POST",
    headers: { "Content-Type": "application/json" },
    body: JSON.stringify(payload),
  });
  return resp.json();
}

let isSubmittingForm = false;  // evite un double-lancement si on double-clique sur le bouton

async function submitNewBotForm() {
  if (isSubmittingForm) return;
  isSubmittingForm = true;
  const submitBtn = document.getElementById("f_submit_btn");
  submitBtn.disabled = true;

  const statusEl = document.getElementById("f_status");
  statusEl.textContent = editingBotName ? "Enregistrement en cours..." : "Lancement en cours...";
  statusEl.className = "form-status";

  const strategyType = document.getElementById("f_strategy_type").value;
  const payload = {
    name: document.getElementById("f_name").value.trim(),
    symbol: symbolValueOf("f_symbol"),
    timeframe: document.getElementById("f_timeframe").value,
    strategy_type: strategyType,
    capital_allocated: document.getElementById("f_capital_allocated").value,
    max_position_size_pct: document.getElementById("f_max_position_size_pct").value / 100,
    stop_loss_pct: document.getElementById("f_stop_loss_pct").value
      ? document.getElementById("f_stop_loss_pct").value / 100 : "",
    take_profit_pct: document.getElementById("f_take_profit_pct").value
      ? document.getElementById("f_take_profit_pct").value / 100 : "",
    max_daily_loss_pct: document.getElementById("f_max_daily_loss_pct").value / 100,
    max_concurrent_positions: document.getElementById("f_max_concurrent_positions").value,
    trailing_stop_pct: document.getElementById("f_trailing_stop_pct").value
      ? document.getElementById("f_trailing_stop_pct").value / 100 : "",
    fee_pct: document.getElementById("f_fee_pct").value / 100,
    exit_check_timeframe: document.getElementById("f_exit_check_timeframe").value.trim() || "",
    partial_take_profit_pct: document.getElementById("f_partial_take_profit_pct").value
      ? document.getElementById("f_partial_take_profit_pct").value / 100 : "",
    partial_exit_fraction: document.getElementById("f_partial_exit_fraction").value / 100,
    warmup_candles: document.getElementById("f_warmup_candles").value,
    flatten_on_start: true,
    probability_filter_enabled: document.getElementById("f_probability_filter_enabled").checked,
    min_probability: document.getElementById("f_min_probability").value / 100,
    trend_filter_enabled: document.getElementById("f_trend_filter_enabled").checked,
    trend_filter_ema_period: document.getElementById("f_trend_filter_ema_period").value,
    atr_sizing_enabled: document.getElementById("f_atr_sizing_enabled").checked,
    atr_period: document.getElementById("f_atr_period").value,
    atr_baseline_period: document.getElementById("f_atr_baseline_period").value,
    atr_min_multiplier: document.getElementById("f_atr_min_multiplier").value / 100,
    price_level_sizing_enabled: document.getElementById("f_price_level_sizing_enabled").checked,
    price_level_min_multiplier: document.getElementById("f_price_level_min_multiplier").value / 100,
    price_level_max_multiplier: document.getElementById("f_price_level_max_multiplier").value / 100,
  };
  if (strategyType === "sma_cross") {
    payload.short_window = document.getElementById("f_short_window").value;
    payload.long_window = document.getElementById("f_long_window").value;
  } else if (strategyType === "scalp_dip") {
    payload.lookback = document.getElementById("f_lookback").value;
    payload.dip_threshold_pct = document.getElementById("f_dip_threshold_pct").value / 100;
  } else if (strategyType === "dip_bounce_hourly" || strategyType === "dip_bounce_minute") {
    payload.dip_threshold_pct = document.getElementById("f_dip_threshold_pct").value / 100;
    payload.profit_lock_arm_pct = document.getElementById("f_profit_lock_arm_pct").value / 100;
    payload.profit_lock_trigger_pct = document.getElementById("f_profit_lock_trigger_pct").value / 100;
    payload.force_trade_after_hours = document.getElementById("f_force_trade_after_hours").value || "";
  }
  // buy_and_hold : aucun champ de strategie a envoyer.
  if (editingBotName) {
    payload.original_name = editingBotName;
  }

  try {
    const result = editingBotName ? await updateBot(payload) : await launchBot(payload);
    if (result.error) {
      statusEl.textContent = `Erreur : ${result.error}`;
      statusEl.className = "form-status err";
    } else {
      statusEl.textContent = editingBotName ? `Bot "${result.name}" mis a jour !` : `Bot "${result.name}" lance !`;
      statusEl.className = "form-status ok";
      editingBotName = null;
      document.getElementById("f_form_heading").textContent = "Creer un nouveau bot";
      document.getElementById("f_submit_btn").textContent = "Lancer le bot";
      document.getElementById("f_cancel_edit").style.display = "none";
      await refreshExistingBotsList();
      setTimeout(refresh, 3000);
    }
  } catch (e) {
    statusEl.textContent = "Impossible de contacter le serveur de controle. Lance 'python -m tradingbot.control_server' d'abord.";
    statusEl.className = "form-status err";
  } finally {
    isSubmittingForm = false;
    submitBtn.disabled = false;
  }
}

function renderBotContent() {
  const contentEl = document.getElementById("content");
  const names = window.BOT_REGISTRY || [];
  if (names.length === 0) {
    contentEl.innerHTML = '<div class="empty">Aucun bot detecte pour le moment. Cree-en un dans l\\'onglet Configuration &rarr; Creation.</div>';
    return;
  }
  const data = (window.BOT_INSTANCES || {})[currentBotName];
  if (!data) {
    contentEl.innerHTML = '<div class="empty">Aucune donnee pour le moment.</div>';
    return;
  }
  const pnl = data.equity - data.starting_capital;
  const pnlPct = data.starting_capital ? (pnl / data.starting_capital * 100) : 0;
  const pnlColor = pnl >= 0 ? "#2fd699" : "#ff6b6b";
  const isRunning = data.updated_at_ts && (Date.now() - data.updated_at_ts) < STALE_AFTER_MS;
  const statusHtml = isRunning
    ? '<span class="status running"><span class="dot"></span>En cours</span>'
    : '<span class="status stopped"><span class="dot"></span>Arrete</span>';
  const stopBtn = isRunning ? `<button class="danger" style="margin-left:8px;" onclick="stopBot('${currentBotName}')">Arreter</button>` : "";
  const fmtMoney = v => (v ?? 0).toLocaleString(undefined, {minimumFractionDigits: 2, maximumFractionDigits: 2});

  // Plafond de mise (panier commun) : n'affiche le capital de depart (base_cap)
  // qu'en petite note s'il differe reellement du plafond effectif (allocation
  // dynamique deja active) - sinon c'est le meme nombre affiche deux fois.
  const hasPool = data.effective_cap !== null && data.effective_cap !== undefined;
  const capDiffers = hasPool && Math.abs(data.effective_cap - data.starting_capital) > 0.01;
  const capLabel = hasPool ? "Plafond de mise (panier commun)" : "Capital de depart";
  const capValue = hasPool ? data.effective_cap : data.starting_capital;

  const configDetailsWasOpen = document.getElementById("bot-config-details")?.open ?? false;

  contentEl.innerHTML = `
    <span class="badge">Mode ${data.mode}</span>${statusHtml}${stopBtn}
    <h1 style="margin-top:8px;">${currentBotName} &middot; ${data.symbol}</h1>
    <p class="muted">Derniere mise a jour : ${data.updated_at}${hasPool ? ` &middot; Panier commun disponible : ${fmtMoney(data.pool_available_cash)}` : ""}</p>

    <details class="adv-section" id="bot-config-details" ${configDetailsWasOpen ? "open" : ""} ontoggle="if (this.open) loadBotConfigPanel('${currentBotName}')">
      <summary><span>Configuration de ce bot</span><span class="chev">&#9656;</span></summary>
      <div class="adv-body" id="bot-config-content"><p class="muted">Chargement...</p></div>
    </details>

    <div class="grid">
      <div>
        <div class="stat-label">${capLabel}</div>
        <div class="stat-value">${fmtMoney(capValue)}</div>
        ${capDiffers ? `<div class="muted" style="font-size:11px; margin-top:2px;">base : ${fmtMoney(data.starting_capital)}</div>` : ""}
      </div>
      <div>
        <div class="stat-label">Investi actuellement</div>
        <div class="stat-value">${fmtMoney(data.invested_now)}</div>
      </div>
      <div>
        <div class="stat-label">Valeur actuelle</div>
        <div class="stat-value">${fmtMoney(data.equity)}</div>
      </div>
      <div>
        <div class="stat-label">Gain / Perte</div>
        <div class="stat-value" style="color:${pnlColor}">${pnl >= 0 ? "+" : ""}${pnl.toFixed(2)} (${pnlPct >= 0 ? "+" : ""}${pnlPct.toFixed(2)} %)</div>
      </div>
      <div>
        <div class="stat-label">Positions ouvertes</div>
        <div class="stat-value">${data.open_positions_count ?? 0}</div>
      </div>
      <div>
        <div class="stat-label">Trades executes</div>
        <div class="stat-value">${data.num_trades ?? 0}</div>
      </div>
      <div>
        <div class="stat-label">Win rate</div>
        <div class="stat-value">${fmtPct(data.win_rate)}</div>
      </div>
      <div>
        <div class="stat-label">Drawdown max</div>
        <div class="stat-value">${fmtPct(data.max_drawdown_pct)}</div>
      </div>
      ${data.probability_up_24h !== null && data.probability_up_24h !== undefined ? `
      <div>
        <div class="stat-label">Proba. hausse 24h (Monte Carlo)</div>
        <div class="stat-value">${data.probability_up_24h >= 0 ? fmtPct(data.probability_up_24h) : "indisponible"}</div>
      </div>` : ""}
      ${data.trend_filter ? `
      <div>
        <div class="stat-label">Regime de tendance (EMA${data.trend_filter.ema_period})</div>
        <div class="stat-value" style="color:${data.trend_filter.is_bullish === null ? "#9098a5" : (data.trend_filter.is_bullish ? "#2fd699" : "#ff6b6b")}">
          ${data.trend_filter.is_bullish === null ? "en formation" : (data.trend_filter.is_bullish ? "Haussier" : "Baissier")}
        </div>
      </div>` : ""}
      ${data.atr_sizer ? `
      <div>
        <div class="stat-label">Sizing volatilite (ATR${data.atr_sizer.atr_period})</div>
        <div class="stat-value">
          ${data.atr_sizer.size_multiplier === null ? "en formation" : `${(data.atr_sizer.size_multiplier * 100).toFixed(0)} % de la taille normale`}
        </div>
      </div>` : ""}
      ${data.price_level_sizer ? `
      <div>
        <div class="stat-label">Sizing niveau de prix (moyenne du mois)</div>
        <div class="stat-value">
          ${data.price_level_sizer.month_average === null ? "en formation" : `${(Math.max(data.price_level_sizer.min_size_multiplier, Math.min(data.price_level_sizer.max_size_multiplier, data.price_level_sizer.month_average / data.current_price)) * 100).toFixed(0)} % de la taille normale`}
        </div>
        ${data.price_level_sizer.month_average !== null ? `<div class="muted" style="font-size:11px; margin-top:2px;">moyenne du mois : ${data.price_level_sizer.month_average.toFixed(4)}</div>` : ""}
      </div>` : ""}
    </div>
    <h2 style="font-size:14px; color:#9098a5; margin-top:28px;">Cours du marche &amp; positions</h2>
    ${renderPriceChartSection(currentBotName, data)}
    <h2 style="font-size:14px; color:#9098a5; margin-top:28px;">Ordres</h2>
    ${renderOrdersTable(data.orders, data.current_price)}
    <h2 style="font-size:14px; color:#9098a5; margin-top:28px;">Dernieres actions</h2>
    ${renderLogs(data.logs)}
  `;
  if (configDetailsWasOpen) loadBotConfigPanel(currentBotName);
}

async function loadBotConfigPanel(name) {
  const el = document.getElementById("bot-config-content");
  if (!el) return;
  try {
    const resp = await fetch(`${CONTROL_SERVER}/api/config?name=${encodeURIComponent(name)}`);
    const data = await resp.json();
    if (data.error) { el.innerHTML = `<p class="form-status err">${data.error}</p>`; return; }
    el.innerHTML = renderConfigSummary(name, data.config);
  } catch (e) {
    el.innerHTML = '<p class="form-status err">Serveur de controle non accessible. Lance \\'python -m tradingbot.control_server\\'.</p>';
  }
}

function renderConfigSummary(name, cfg) {
  const rows = [
    ["Symbole", cfg.symbol],
    ["Timeframe", cfg.timeframe],
    ["Strategie", cfg.strategy.type],
    ["Plafond de mise (panier commun)", cfg.capital_allocated],
    ["Bougies de rechauffement", cfg.warmup_candles],
  ];
  if (cfg.exit_check_timeframe) rows.push(["Surveillance des sorties", cfg.exit_check_timeframe]);
  Object.entries(cfg.strategy).forEach(([k, v]) => { if (k !== "type" && v !== null && v !== undefined) rows.push([`Strategie – ${k}`, v]); });
  Object.entries(cfg.risk).forEach(([k, v]) => { if (v !== null && v !== undefined) rows.push([`Risque – ${k}`, v]); });
  if (cfg.trend_filter && cfg.trend_filter.enabled) rows.push(["Filtre de tendance", `EMA${cfg.trend_filter.ema_period}`]);
  if (cfg.atr_sizing && cfg.atr_sizing.enabled) rows.push(["Sizing par volatilite (ATR)", `periode ${cfg.atr_sizing.atr_period}, min ${(cfg.atr_sizing.min_size_multiplier * 100).toFixed(0)}%`]);
  if (cfg.price_level_sizing && cfg.price_level_sizing.enabled) rows.push(["Sizing par niveau de prix", `${(cfg.price_level_sizing.min_size_multiplier * 100).toFixed(0)}% – ${(cfg.price_level_sizing.max_size_multiplier * 100).toFixed(0)}%`]);
  if (cfg.probability_filter && cfg.probability_filter.enabled) rows.push(["Filtre de probabilite", `seuil ${(cfg.probability_filter.min_probability * 100).toFixed(0)}%`]);

  const body = rows.map(([k, v]) => `<tr><td class="muted" style="white-space:nowrap;">${k}</td><td>${v}</td></tr>`).join("");
  return `
    <table class="bi"><tbody>${body}</tbody></table>
    <div class="form-actions" style="margin-top:14px;">
      <button class="secondary" onclick="editBot('${name}')">Modifier cette configuration</button>
    </div>
  `;
}

let backtestPresets = null;

async function ensureBacktestPresetsLoaded() {
  if (backtestPresets) return;
  try {
    const resp = await fetch(`${CONTROL_SERVER}/api/backtest-strategies`);
    const data = await resp.json();
    backtestPresets = data.strategies || [];
  } catch (e) {
    backtestPresets = [];
  }
}

function backtestParamFieldHtml(spec, prefix) {
  const shownDefault = spec.unit === "%" ? spec.default * 100 : spec.default;
  const step = spec.kind === "int" ? "1" : "0.0001";
  return `<div class="field"><label>${spec.label}${spec.unit === "%" ? " (%)" : ""}</label>
    <input id="${prefix}_${spec.name}" type="number" step="${step}" value="${shownDefault}"></div>`;
}

function renderBacktestFieldsForPreset(key) {
  const preset = (backtestPresets || []).find(p => p.key === key);
  if (!preset) return "";
  const paramFields = preset.param_specs.map(s => backtestParamFieldHtml(s, "bt_p")).join("");
  const riskFields = preset.risk_param_specs.map(s => backtestParamFieldHtml(s, "bt_r")).join("");
  return `
    ${paramFields ? `<div class="section-block"><h2>Parametres de la strategie</h2><div class="form-grid">${paramFields}</div></div>` : ""}
    ${riskFields ? `<div class="section-block"><h2>Parametres de risque specifiques</h2><div class="form-grid">${riskFields}</div></div>` : ""}
  `;
}

function onBacktestStrategyChange(key) {
  document.getElementById("bt_dynamic_fields").innerHTML = renderBacktestFieldsForPreset(key);
  const preset = (backtestPresets || []).find(p => p.key === key);
  const isMarketMaking = preset && preset.key === "market_making";
  document.getElementById("bt_stop_loss_wrap").style.display = (preset && preset.supports_stop_loss) ? "block" : "none";
  document.getElementById("bt_take_profit_wrap").style.display = (preset && preset.supports_stop_loss) ? "block" : "none";
  // Stop-loss optionnel (dip_bounce, default_stop_loss_pct=None cote serveur) :
  // vide par defaut plutot que d'heriter du "2" des autres strategies, pour ne
  // pas laisser croire qu'un stop-loss de 2% est actif alors qu'il ne l'est pas.
  const stopLossInput = document.getElementById("bt_stop_loss_pct");
  if (preset && preset.supports_stop_loss) {
    if (preset.default_stop_loss_pct === null) {
      stopLossInput.value = "";
      stopLossInput.placeholder = "vide = desactive";
    } else {
      stopLossInput.placeholder = "";
      if (!stopLossInput.value) stopLossInput.value = "2";
    }
  }
  document.getElementById("bt_max_concurrent_wrap").style.display = isMarketMaking ? "none" : "block";
  document.getElementById("bt_risk_generic_wrap").style.display = isMarketMaking ? "none" : "contents";
  document.getElementById("bt_partial_wrap").style.display = isMarketMaking ? "none" : "block";
  document.getElementById("bt_price_level_wrap").style.display = isMarketMaking ? "none" : "block";
  document.getElementById("bt_trend_filter_wrap").style.display = isMarketMaking ? "none" : "block";
  document.getElementById("bt_atr_sizing_wrap").style.display = isMarketMaking ? "none" : "block";
  document.getElementById("bt_exit_check_wrap").style.display = isMarketMaking ? "none" : "block";

  // Timeframe : force et verrouille si le preset l'impose (ex: dip_bounce),
  // sinon laisse libre - meme comportement que le formulaire de creation de
  // bot (onStrategyTypeChange) pour la coherence preset/granularite.
  const timeframeSelect = document.getElementById("bt_timeframe");
  const timeframeHint = document.getElementById("bt_timeframe_hint");
  if (preset && preset.timeframe) {
    timeframeSelect.value = preset.timeframe;
    timeframeSelect.disabled = true;
    timeframeHint.textContent = `Fige a ${preset.timeframe} par ce type de bot.`;
    timeframeHint.style.display = "block";
  } else {
    timeframeSelect.disabled = false;
    timeframeHint.style.display = "none";
  }
}

async function renderTestContent() {
  const contentEl = document.getElementById("content");
  contentEl.innerHTML = '<p class="muted">Chargement...</p>';
  await ensureBacktestPresetsLoaded();

  const options = (backtestPresets || []).map(p => `<option value="${p.key}">${p.label}</option>`).join("");
  const firstKey = backtestPresets && backtestPresets[0] ? backtestPresets[0].key : "";

  contentEl.innerHTML = `
    <h1>Backtest</h1>
    <p class="muted">Teste un bot precis sur une periode/devise/parametres de ton choix, sans passer par le terminal - meme moteur que <code>python -m tradingbot.backtest_lab</code> (voir le manuel utilisateur).</p>
    <div class="section-block">
      <h2>General</h2>
      <div class="form-grid">
        <div class="field"><label>Type de bot</label><select id="bt_strategy" onchange="onBacktestStrategyChange(this.value)">${options}</select></div>
        <div class="field"><label>Symbole</label>${symbolSelectHtml("bt_symbol", "BTC/USDT")}</div>
        <div class="field" id="bt_timeframe_wrap"><label>Timeframe</label>
          <select id="bt_timeframe">
            <option value="1m">1 minute</option>
            <option value="5m">5 minutes</option>
            <option value="15m">15 minutes</option>
            <option value="1h" selected>1 heure</option>
            <option value="4h">4 heures</option>
            <option value="1d">1 jour</option>
          </select>
          <div id="bt_timeframe_hint" class="muted" style="font-size:11px; margin-top:4px; display:none;"></div>
        </div>
        <div class="field"><label>Exchange</label><input id="bt_exchange" type="text" value="binance"></div>
        <div class="field"><label>Debut</label><input id="bt_since" type="date" value="2025-01-01"></div>
        <div class="field"><label>Fin (vide = maintenant)</label><input id="bt_until" type="date"></div>
        <div class="field"><label>Capital de depart</label><input id="bt_capital" type="number" value="1000"></div>
        <div class="field"><label>Sous-periodes (1 = un seul test)</label><input id="bt_repeat" type="number" min="1" value="1"></div>
      </div>
      <p class="adv-hint">"Sous-periodes" decoupe la periode en N tronçons egaux et rejoue le test sur chacun independamment - utile pour verifier qu'un bon resultat ne repose pas sur une seule periode chanceuse.</p>
    </div>
    <div class="section-block">
      <h2>Gestion du risque</h2>
      <div class="form-grid">
        <div class="field" id="bt_max_concurrent_wrap"><label>Positions simultanees max</label><input id="bt_max_concurrent_positions" type="number" min="1" step="1" value="1"></div>
        <div class="field" id="bt_stop_loss_wrap"><label>Stop-loss (%)</label><input id="bt_stop_loss_pct" type="number" step="0.01" value="2"></div>
        <div class="field" id="bt_take_profit_wrap"><label>Take-profit (%, vide = desactive)</label><input id="bt_take_profit_pct" type="number" step="0.01" placeholder="vide = desactive"></div>
        <div id="bt_risk_generic_wrap" style="display:contents;">
          <div class="field"><label>Taille position max (%)</label><input id="bt_max_position_size_pct" type="number" step="0.01" value="10"></div>
          <div class="field"><label>Perte max journaliere (%)</label><input id="bt_max_daily_loss_pct" type="number" step="0.01" value="5"></div>
          <div class="field"><label>Trailing stop (%, vide = desactive)</label><input id="bt_trailing_stop_pct" type="number" step="0.01" placeholder="vide = desactive"></div>
          <div class="field"><label>Frais par ordre (%)</label><input id="bt_fee_pct" type="number" step="0.01" value="0.1"></div>
        </div>
      </div>
      <p class="adv-hint">"Positions simultanees max" > 1 permet d'ouvrir plusieurs positions en parallele au lieu d'attendre que la precedente se cloture - utile si une strategie reste souvent bloquee en attente d'une seule position (ex: verrou de gain sans stop-loss). A tester avec prudence : ca peut aussi accumuler des pertes correlees en marche baissier. "Trailing stop" fait suivre le stop-loss au prix quand il monte. "Frais par ordre" simule les frais reels de l'exchange (0.1% = taker Binance spot typique).</p>
    </div>
    <div class="section-block" id="bt_partial_wrap">
      <h2>Sortie partielle (scale-out, optionnel)</h2>
      <div class="form-grid">
        <div class="field"><label>Palier de sortie partielle (%, vide = desactive)</label><input id="bt_partial_take_profit_pct" type="number" step="0.01" placeholder="vide = desactive"
          onchange="document.getElementById('bt_partial_exit_fraction_wrap').style.display = this.value ? 'block' : 'none'"></div>
        <div class="field" id="bt_partial_exit_fraction_wrap" style="display:none;">
          <label>Fraction vendue au palier (%)</label>
          <input id="bt_partial_exit_fraction" type="number" step="1" min="1" max="99" value="50">
        </div>
      </div>
      <p class="adv-hint">Vend une FRACTION du lot des qu'un premier gain est atteint, et laisse le reste continuer avec le stop-loss/trailing stop normal. Doit etre strictement inferieur au "Take-profit" complet si les deux sont configures.</p>
    </div>
    <div class="section-block" id="bt_trend_filter_wrap">
      <h2>Filtre de tendance (EMA, optionnel)</h2>
      <div class="form-grid">
        <div class="field">
          <label><input type="checkbox" id="bt_trend_filter_enabled" style="width:auto; margin-right:6px;"
            onchange="document.getElementById('bt_trend_filter_period_wrap').style.display = this.checked ? 'block' : 'none'">
          Activer</label>
        </div>
        <div class="field" id="bt_trend_filter_period_wrap" style="display:none;">
          <label>Periode de l'EMA (bougies)</label>
          <input id="bt_trend_filter_ema_period" type="number" step="1" min="2" value="200">
        </div>
      </div>
      <p class="adv-hint">Bloque un achat si le prix est sous la moyenne mobile exponentielle (regime baissier) - evite d'acheter a contre-courant d'une tendance de fond.</p>
    </div>
    <div class="section-block" id="bt_atr_sizing_wrap">
      <h2>Sizing par volatilite (ATR, optionnel)</h2>
      <div class="form-grid">
        <div class="field">
          <label><input type="checkbox" id="bt_atr_sizing_enabled" style="width:auto; margin-right:6px;"
            onchange="document.getElementById('bt_atr_sizing_bounds').style.display = this.checked ? 'grid' : 'none'">
          Activer</label>
        </div>
      </div>
      <div id="bt_atr_sizing_bounds" class="form-grid" style="display:none; margin-top:13px;">
        <div class="field"><label>Periode ATR (bougies)</label><input id="bt_atr_period" type="number" step="1" min="1" value="14"></div>
        <div class="field"><label>Periode de reference (bougies)</label><input id="bt_atr_baseline_period" type="number" step="1" min="1" value="100"></div>
        <div class="field"><label>Taille minimum (% de la normale)</label><input id="bt_atr_min_multiplier" type="number" step="1" min="1" max="100" value="20"></div>
      </div>
      <p class="adv-hint">Reduit la taille d'une position quand la volatilite recente (ATR) depasse sa moyenne habituelle - jamais plus que "Taille position max", seulement moins en periode agitee.</p>
    </div>
    <div class="section-block" id="bt_price_level_wrap">
      <h2>Sizing par niveau de prix (optionnel)</h2>
      <div class="form-grid">
        <div class="field">
          <label><input type="checkbox" id="bt_price_level_sizing" style="width:auto; margin-right:6px;"
            onchange="document.getElementById('bt_price_level_bounds').style.display = this.checked ? 'grid' : 'none'">
          Activer</label>
        </div>
      </div>
      <div id="bt_price_level_bounds" class="form-grid" style="display:none; margin-top:13px;">
        <div class="field"><label>Taille minimum (%)</label><input id="bt_price_level_min_multiplier" type="number" step="1" min="1" value="50"></div>
        <div class="field"><label>Taille maximum (%)</label><input id="bt_price_level_max_multiplier" type="number" step="1" min="1" value="150"></div>
      </div>
      <p class="adv-hint">Module la taille d'une position selon l'ecart entre le prix actuel et la moyenne du mois calendaire en cours - plus grande sous la moyenne, plus petite au-dessus. Idee proposee par l'utilisateur, non testee empiriquement a ce jour.</p>
    </div>
    <div class="section-block" id="bt_exit_check_wrap">
      <h2>Verification des sorties sur un timeframe plus fin (optionnel)</h2>
      <div class="form-grid">
        <div class="field"><label>Timeframe de surveillance (ex: 5m, vide = desactive)</label><input id="bt_exit_check_timeframe" type="text" placeholder="vide = desactive"></div>
      </div>
      <p class="adv-hint">Verifie le stop-loss/verrou de gain/trailing stop a une frequence plus fine que les bougies utilisees pour les entrees (ex: toutes les 5 minutes au lieu d'une fois par heure) - les entrees de la strategie restent inchangees. Corrige un vrai probleme constate : un verrou de gain arme puis verifie une seule fois par heure peut vendre bien plus bas que son seuil si le prix chute vite entre deux verifications. Necessite de telecharger une deuxieme serie de bougies (peut prendre du temps la premiere fois).</p>
    </div>
    <div id="bt_dynamic_fields">${renderBacktestFieldsForPreset(firstKey)}</div>
    <div class="form-actions">
      <button class="primary" id="bt_run_btn" onclick="runBacktestFromForm()">Lancer le test</button>
      <span id="bt_status" class="form-status"></span>
    </div>
    <div id="bt_progress_wrap" style="display:none;">
      <div class="progress-track"><div id="bt_progress_bar" class="progress-bar indeterminate"></div></div>
      <p id="bt_progress_label" class="progress-label"></p>
    </div>
    <div id="bt_report_wrap" style="margin-top:20px;"></div>
  `;
  onBacktestStrategyChange(firstKey);
}

function updateBacktestProgressUI(progress) {
  const bar = document.getElementById("bt_progress_bar");
  const label = document.getElementById("bt_progress_label");
  if (!bar || !label) return;
  if (!progress) {
    bar.className = "progress-bar indeterminate";
    bar.style.width = "";
    label.textContent = "Preparation...";
    return;
  }
  if (progress.stage === "download") {
    bar.className = "progress-bar indeterminate";
    bar.style.width = "";
    label.textContent = progress.message || "Telechargement de l'historique...";
  } else if (progress.stage === "running" && progress.total > 1) {
    // Mode --repeat (sous-periodes) : progression reelle, pas juste une animation.
    bar.className = "progress-bar";
    bar.style.width = Math.round((progress.current / progress.total) * 100) + "%";
    label.textContent = progress.message || `Sous-periode ${progress.current}/${progress.total}`;
  } else {
    // Un seul test : aucune granularite fine disponible sans instrumenter le
    // moteur bougie par bougie (hors perimetre) - animation indeterminee.
    bar.className = "progress-bar indeterminate";
    bar.style.width = "";
    label.textContent = progress.message || "Simulation en cours...";
  }
}

async function runBacktestFromForm() {
  const btn = document.getElementById("bt_run_btn");
  const statusEl = document.getElementById("bt_status");
  const reportWrap = document.getElementById("bt_report_wrap");
  const progressWrap = document.getElementById("bt_progress_wrap");
  btn.disabled = true;
  statusEl.textContent = "Test en cours (peut prendre du temps si l'historique n'est pas encore en cache local)...";
  statusEl.className = "form-status";
  reportWrap.innerHTML = "";
  progressWrap.style.display = "block";
  updateBacktestProgressUI(null);

  // job_id genere cote client : le serveur publie la progression sous cette
  // cle pendant que la requete POST (bloquante) tourne encore - on la lit en
  // parallele via polling (ThreadingHTTPServer traite les deux requetes dans
  // des threads distincts, voir control_server.py).
  const jobId = `bt_${Date.now()}_${Math.random().toString(36).slice(2)}`;
  const pollHandle = setInterval(async () => {
    try {
      const r = await fetch(`${CONTROL_SERVER}/api/backtest-progress?job_id=${jobId}`);
      const d = await r.json();
      updateBacktestProgressUI(d.progress);
    } catch (e) {
      // Pas grave - on retente au prochain tick, la barre reste sur son dernier etat connu.
    }
  }, 600);

  const strategyKey = document.getElementById("bt_strategy").value;
  const preset = (backtestPresets || []).find(p => p.key === strategyKey);

  const payload = {
    strategy: strategyKey,
    symbol: symbolValueOf("bt_symbol"),
    timeframe: document.getElementById("bt_timeframe").value,
    exchange: document.getElementById("bt_exchange").value.trim(),
    since: document.getElementById("bt_since").value,
    until: document.getElementById("bt_until").value || "",
    capital: document.getElementById("bt_capital").value,
    repeat: document.getElementById("bt_repeat").value || 1,
    param: (preset ? preset.param_specs : []).map(s => `${s.name}=${document.getElementById(`bt_p_${s.name}`).value}`),
    risk: (preset ? preset.risk_param_specs : []).map(s => `${s.name}=${document.getElementById(`bt_r_${s.name}`).value}`),
    job_id: jobId,
  };
  if (preset && preset.supports_stop_loss) {
    payload.stop_loss_pct = document.getElementById("bt_stop_loss_pct").value || "";
    payload.take_profit_pct = document.getElementById("bt_take_profit_pct").value || "";
  }
  if (!preset || preset.key !== "market_making") {
    payload.max_concurrent_positions = document.getElementById("bt_max_concurrent_positions").value || 1;
    payload.max_position_size_pct = document.getElementById("bt_max_position_size_pct").value || "";
    payload.max_daily_loss_pct = document.getElementById("bt_max_daily_loss_pct").value || "";
    payload.trailing_stop_pct = document.getElementById("bt_trailing_stop_pct").value || "";
    payload.fee_pct = document.getElementById("bt_fee_pct").value || "";
    payload.partial_take_profit_pct = document.getElementById("bt_partial_take_profit_pct").value || "";
    if (payload.partial_take_profit_pct) {
      payload.partial_exit_fraction = document.getElementById("bt_partial_exit_fraction").value || 50;
    }
    payload.trend_filter_enabled = document.getElementById("bt_trend_filter_enabled").checked;
    if (payload.trend_filter_enabled) {
      payload.trend_filter_ema_period = document.getElementById("bt_trend_filter_ema_period").value || 200;
    }
    payload.atr_sizing_enabled = document.getElementById("bt_atr_sizing_enabled").checked;
    if (payload.atr_sizing_enabled) {
      payload.atr_period = document.getElementById("bt_atr_period").value || 14;
      payload.atr_baseline_period = document.getElementById("bt_atr_baseline_period").value || 100;
      payload.atr_min_multiplier = document.getElementById("bt_atr_min_multiplier").value || 20;
    }
    payload.price_level_sizing = document.getElementById("bt_price_level_sizing").checked;
    if (payload.price_level_sizing) {
      payload.price_level_min_multiplier = document.getElementById("bt_price_level_min_multiplier").value || 50;
      payload.price_level_max_multiplier = document.getElementById("bt_price_level_max_multiplier").value || 150;
    }
    payload.exit_check_timeframe = document.getElementById("bt_exit_check_timeframe").value.trim() || "";
  }

  try {
    const resp = await fetch(`${CONTROL_SERVER}/api/run-backtest`, {
      method: "POST",
      headers: { "Content-Type": "application/json" },
      body: JSON.stringify(payload),
    });
    const data = await resp.json();
    if (data.error) {
      statusEl.textContent = `Erreur : ${data.error}`;
      statusEl.className = "form-status err";
    } else {
      statusEl.textContent = "Test termine.";
      statusEl.className = "form-status ok";
      const escaped = data.report.replace(/&/g, "&amp;").replace(/</g, "&lt;");
      const exportable = CREATABLE_STRATEGY_TYPES.has(strategyKey);
      reportWrap.innerHTML = `<h2>Rapport</h2><pre style="white-space:pre-wrap; background:var(--surface-2); border:1px solid var(--border); border-radius:var(--radius-md); padding:16px; font-family:'JetBrains Mono',monospace; font-size:12px; line-height:1.6;">${escaped}</pre>
      <p class="muted">Egalement enregistre dans <code>${data.report_path}</code>.</p>
      <button class="secondary" onclick="exportBacktestToNewBot()" ${exportable ? "" : 'disabled title="Ce type de bot est seulement disponible en YAML pour le moment"'}>Exporter ces parametres vers un nouveau bot</button>`;
    }
  } catch (e) {
    statusEl.textContent = "Serveur de controle non accessible.";
    statusEl.className = "form-status err";
  } finally {
    clearInterval(pollHandle);
    progressWrap.style.display = "none";
    btn.disabled = false;
  }
}

function exportBacktestToNewBot() {
  // Reprend les reglages actuels du formulaire Test/Backtest et les reporte
  // dans le formulaire de Creation (§5.1/5.2), demande de l'utilisateur pour
  // ne pas avoir a retaper a la main une config qui a donne un bon resultat
  // en test. Les cles de strategie backtest/creation sont deja identiques
  // (sma_cross, scalp_dip, dip_bounce_hourly/minute, buy_and_hold) - seuls
  // mean_reversion/market_making n'ont pas d'equivalent creable (bouton
  // desactive dans ce cas, voir runBacktestFromForm).
  const strategyKey = document.getElementById("bt_strategy").value;
  if (!CREATABLE_STRATEGY_TYPES.has(strategyKey)) {
    alert("Ce type de bot n'est pas encore creable depuis ce formulaire (YAML uniquement pour l'instant).");
    return;
  }
  const preset = (backtestPresets || []).find(p => p.key === strategyKey);
  const val = id => { const el = document.getElementById(id); return el ? el.value : ""; };
  const checked = id => { const el = document.getElementById(id); return el ? el.checked : false; };

  const exported = {
    symbol: symbolValueOf("bt_symbol"),
    timeframe: val("bt_timeframe"),
    capital: val("bt_capital"),
    stopLoss: (preset && preset.supports_stop_loss) ? val("bt_stop_loss_pct") : "",
    takeProfit: (preset && preset.supports_stop_loss) ? val("bt_take_profit_pct") : "",
    maxPositionSize: val("bt_max_position_size_pct"),
    maxDailyLoss: val("bt_max_daily_loss_pct"),
    maxConcurrent: val("bt_max_concurrent_positions"),
    trailingStop: val("bt_trailing_stop_pct"),
    feePct: val("bt_fee_pct"),
    exitCheckTimeframe: val("bt_exit_check_timeframe"),
    partialTakeProfit: val("bt_partial_take_profit_pct"),
    partialExitFraction: val("bt_partial_exit_fraction"),
    trendFilterEnabled: checked("bt_trend_filter_enabled"),
    trendFilterEmaPeriod: val("bt_trend_filter_ema_period"),
    atrSizingEnabled: checked("bt_atr_sizing_enabled"),
    atrPeriod: val("bt_atr_period"),
    atrBaselinePeriod: val("bt_atr_baseline_period"),
    atrMinMultiplier: val("bt_atr_min_multiplier"),
    priceLevelSizingEnabled: checked("bt_price_level_sizing"),
    priceLevelMin: val("bt_price_level_min_multiplier"),
    priceLevelMax: val("bt_price_level_max_multiplier"),
  };
  if (strategyKey === "sma_cross") {
    exported.shortWindow = val("bt_p_short_window");
    exported.longWindow = val("bt_p_long_window");
  } else if (strategyKey === "scalp_dip") {
    exported.lookback = val("bt_p_lookback");
    exported.dipThresholdPct = val("bt_p_dip_threshold_pct");
  } else if (strategyKey === "dip_bounce_hourly" || strategyKey === "dip_bounce_minute") {
    exported.dipThresholdPct = val("bt_p_dip_threshold_pct");
    exported.forceTradeAfterHours = val("bt_p_force_trade_after_hours");
    exported.profitLockArmPct = val("bt_r_profit_lock_arm_pct");
    exported.profitLockTriggerPct = val("bt_r_profit_lock_trigger_pct");
  }

  currentMainTab = "config";
  currentConfigSubTab = "creation";
  renderMainTabs();
  editingBotName = null;
  document.getElementById("manage-bots-root")?.remove();  // formulaire vide, pas d'edition en cours (meme reset que cancelEdit)
  renderSubTabsAndContent();

  document.getElementById("f_strategy_type").value = strategyKey;
  onStrategyTypeChange(strategyKey);  // pose les champs de strategie + verrouille timeframe/stop-loss si besoin
  setSymbolValue("f_symbol", exported.symbol);
  if (!document.getElementById("f_timeframe").disabled && exported.timeframe) {
    document.getElementById("f_timeframe").value = exported.timeframe;
  }
  if (exported.capital) document.getElementById("f_capital_allocated").value = exported.capital;

  if (strategyKey === "sma_cross") {
    if (exported.shortWindow) document.getElementById("f_short_window").value = exported.shortWindow;
    if (exported.longWindow) document.getElementById("f_long_window").value = exported.longWindow;
  } else if (strategyKey === "scalp_dip") {
    if (exported.lookback) document.getElementById("f_lookback").value = exported.lookback;
    if (exported.dipThresholdPct) document.getElementById("f_dip_threshold_pct").value = exported.dipThresholdPct;
  } else if (strategyKey === "dip_bounce_hourly" || strategyKey === "dip_bounce_minute") {
    if (exported.dipThresholdPct) document.getElementById("f_dip_threshold_pct").value = exported.dipThresholdPct;
    if (exported.forceTradeAfterHours) document.getElementById("f_force_trade_after_hours").value = exported.forceTradeAfterHours;
    if (exported.profitLockArmPct) document.getElementById("f_profit_lock_arm_pct").value = exported.profitLockArmPct;
    if (exported.profitLockTriggerPct) document.getElementById("f_profit_lock_trigger_pct").value = exported.profitLockTriggerPct;
  }

  if (exported.maxPositionSize) document.getElementById("f_max_position_size_pct").value = exported.maxPositionSize;
  if (!document.getElementById("f_stop_loss_pct").disabled && exported.stopLoss) {
    document.getElementById("f_stop_loss_pct").value = exported.stopLoss;
  }
  document.getElementById("f_take_profit_pct").value = exported.takeProfit || "";
  if (exported.maxDailyLoss) document.getElementById("f_max_daily_loss_pct").value = exported.maxDailyLoss;
  if (exported.maxConcurrent) document.getElementById("f_max_concurrent_positions").value = exported.maxConcurrent;
  document.getElementById("f_trailing_stop_pct").value = exported.trailingStop || "";
  if (exported.feePct) document.getElementById("f_fee_pct").value = exported.feePct;
  document.getElementById("f_exit_check_timeframe").value = exported.exitCheckTimeframe || "";

  document.getElementById("f_partial_take_profit_pct").value = exported.partialTakeProfit || "";
  document.getElementById("f_partial_exit_fraction_wrap").style.display = exported.partialTakeProfit ? "block" : "none";
  if (exported.partialExitFraction) document.getElementById("f_partial_exit_fraction").value = exported.partialExitFraction;

  document.getElementById("f_trend_filter_enabled").checked = exported.trendFilterEnabled;
  document.getElementById("f_trend_filter_ema_wrap").style.display = exported.trendFilterEnabled ? "block" : "none";
  if (exported.trendFilterEmaPeriod) document.getElementById("f_trend_filter_ema_period").value = exported.trendFilterEmaPeriod;

  document.getElementById("f_atr_sizing_enabled").checked = exported.atrSizingEnabled;
  document.getElementById("f_atr_sizing_wrap").style.display = exported.atrSizingEnabled ? "block" : "none";
  if (exported.atrPeriod) document.getElementById("f_atr_period").value = exported.atrPeriod;
  if (exported.atrBaselinePeriod) document.getElementById("f_atr_baseline_period").value = exported.atrBaselinePeriod;
  if (exported.atrMinMultiplier) document.getElementById("f_atr_min_multiplier").value = exported.atrMinMultiplier;

  document.getElementById("f_price_level_sizing_enabled").checked = exported.priceLevelSizingEnabled;
  document.getElementById("f_price_level_sizing_wrap").style.display = exported.priceLevelSizingEnabled ? "block" : "none";
  if (exported.priceLevelMin) document.getElementById("f_price_level_min_multiplier").value = exported.priceLevelMin;
  if (exported.priceLevelMax) document.getElementById("f_price_level_max_multiplier").value = exported.priceLevelMax;

  [
    [exported.trendFilterEnabled, "f_trend_filter_enabled"],
    [exported.atrSizingEnabled, "f_atr_sizing_enabled"],
    [exported.priceLevelSizingEnabled, "f_price_level_sizing_enabled"],
  ].forEach(([enabled, fieldId]) => {
    if (!enabled) return;
    const details = document.getElementById(fieldId)?.closest("details.adv-section");
    if (details) details.open = true;
  });

  document.getElementById("f_status").textContent = "Parametres importes depuis le test - verifie le nom et le plafond de mise avant de lancer.";
  document.getElementById("f_status").className = "form-status ok";
  document.getElementById("manage-bots-root").scrollIntoView({ behavior: "smooth", block: "start" });
  document.getElementById("f_name").focus();
}

async function refresh() {
  window.BOT_REGISTRY = [];
  window.BOT_INSTANCES = window.BOT_INSTANCES || {};

  try {
    await loadScript("dashboard_data/registry.js");
  } catch (e) {
    // Pas encore de bot du tout (dashboard_data/registry.js n'existe pas) -
    // on reste sur l'onglet Accueil par defaut, pas de redirection forcee.
    renderMainTabs();
    renderSubTabsAndContent();
    return;
  }

  for (const name of window.BOT_REGISTRY) {
    try { await loadScript(`dashboard_data/${name}.js`); } catch (e) { /* instance pas encore prete */ }
  }

  checkForStoppedBots(window.BOT_REGISTRY);

  renderMainTabs();
  renderSubTabsAndContent();
}

refresh();
setInterval(refresh, 15000);
</script>
</body>
</html>
"""
