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
    chart_levels: list[dict] | None = None,
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
        # EF-88 : niveaux de la strategie (ex. tendance et seuils d'achat/sortie
        # de trend_regime), traces sur le graphique si l'utilisateur les active.
        "chart_levels": chart_levels or [],
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
<link rel="icon" href="data:image/svg+xml,%3Csvg xmlns='http://www.w3.org/2000/svg' viewBox='0 0 32 32'%3E%3Crect width='32' height='32' rx='8' fill='%235b8def'/%3E%3Cpath d='M7 21l5-6 4 3 4-7 5 5' fill='none' stroke='%23fff' stroke-width='2.5' stroke-linecap='round' stroke-linejoin='round'/%3E%3C/svg%3E">
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
  .section-block > h2 { display: flex; align-items: center; gap: 9px; }
  .section-block > h2::before { content: ""; width: 3px; height: 13px; border-radius: 2px; background: linear-gradient(var(--accent), var(--accent-2)); flex-shrink: 0; }
  code { font-family: 'JetBrains Mono', ui-monospace, monospace; background: rgba(255,255,255,0.06); padding: 1px 6px; border-radius: 5px; font-size: 12px; color: #c9d2ea; }
  .muted { color: var(--text-dim); font-size: 13px; }
  .app-header { max-width: 1360px; margin: 0 auto 22px; display: flex; align-items: center; justify-content: space-between; gap: 16px; flex-wrap: wrap; }
  .app-header .brand { display: flex; align-items: center; gap: 12px; }
  .app-header .brand-mark { width: 38px; height: 38px; border-radius: 11px; background: linear-gradient(135deg, var(--accent), var(--accent-2)); display: flex; align-items: center; justify-content: center; font-size: 18px; box-shadow: 0 6px 18px -6px rgba(91,141,239,0.6); flex-shrink: 0; }
  .app-header .brand-text h1 { margin: 0; }
  .live-pill { display: inline-flex; align-items: center; gap: 7px; background: var(--surface); border: 1px solid var(--border); padding: 7px 13px; border-radius: 999px; font-size: 12.5px; color: var(--text-dim); }
  .live-pill .pulse { width: 7px; height: 7px; border-radius: 50%; background: var(--green); box-shadow: 0 0 0 0 rgba(47,214,153,0.6); animation: pulse 2s infinite; }
  @keyframes pulse { 0% { box-shadow: 0 0 0 0 rgba(47,214,153,0.55); } 70% { box-shadow: 0 0 0 7px rgba(47,214,153,0); } 100% { box-shadow: 0 0 0 0 rgba(47,214,153,0); } }
  .card { background: var(--surface); border: 1px solid var(--border); box-shadow: var(--shadow-card); border-radius: var(--radius-lg); padding: 26px 30px; max-width: 1360px; margin: 0 auto; }
  .tabs { display: flex; gap: 6px; margin: 18px 0 22px 0; flex-wrap: wrap; border-bottom: 1px solid var(--border); padding-bottom: 12px; }
  .tab { background: transparent; color: var(--text-dim); border: 1px solid transparent; border-radius: var(--radius-sm); padding: 7px 13px; font-size: 12.5px; font-weight: 500; cursor: pointer; transition: background .15s ease, color .15s ease, border-color .15s ease; font-family: inherit; }
  .tab:hover { background: var(--surface-hover); color: var(--text); }
  .tab.active { background: var(--accent-soft); color: #a9c6ff; border-color: rgba(91,141,239,0.35); }
  .grid { display: grid; grid-template-columns: repeat(auto-fit, minmax(158px, 1fr)); gap: 12px; margin-top: 20px; }
  .grid > div { background: var(--surface-2); border: 1px solid var(--border); border-radius: var(--radius-md); padding: 15px 17px; transition: border-color .15s ease, transform .15s ease; }
  .grid > div:hover { border-color: var(--border-strong); }
  .stat-label { font-size: 11px; color: var(--text-faint); text-transform: uppercase; letter-spacing: 0.05em; font-weight: 600; }
  .stat-value { font-size: 26px; font-weight: 600; margin-top: 7px; letter-spacing: -0.02em; font-variant-numeric: tabular-nums; line-height: 1.15; }
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
  table.bi { width: 100%; border-collapse: collapse; margin-top: 14px; font-size: 13px; }
  table.bi th, table.bi td { text-align: left; padding: 11px 13px; border-bottom: 1px solid var(--border); white-space: nowrap; }
  table.bi tbody tr:nth-child(even) { background: rgba(255,255,255,0.018); }
  table.bi td { font-variant-numeric: tabular-nums; }
  /* Une valeur coupee en deux lignes ("+0.00" puis "%") est illisible : on
     empeche le retour a la ligne dans les cellules, et la premiere colonne
     (nom du bot) absorbe la largeur restante. Un conteneur defilant evite
     tout debordement horizontal de la page si les colonnes sont nombreuses. */
  table.bi th:first-child, table.bi td:first-child { min-width: 180px; }
  .table-scroll { overflow-x: auto; }
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
  .form-grid { display: grid; grid-template-columns: repeat(auto-fit, minmax(210px, 1fr)); gap: 14px; margin-top: 14px; max-width: 1120px; }
  .card > p.muted, .card > .adv-hint { max-width: 78ch; }
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
  .adv-hint { font-size: 12px; color: var(--text-dim); margin: 12px 0 0; line-height: 1.6; background: rgba(91,141,239,0.05); border-left: 2px solid rgba(91,141,239,0.35); border-radius: 0 var(--radius-sm) var(--radius-sm) 0; padding: 10px 13px; }
  .section-block { margin-top: 22px; }
  .dot-legend { display: inline-flex; align-items: center; gap: 12px; margin-left: auto; padding-left: 14px; font-size: 11.5px; color: var(--text-faint); }
  .dot-legend-item { display: inline-flex; align-items: center; gap: 5px; }
  .dot-legend .dot { width: 6px; height: 6px; border-radius: 50%; display: inline-block; }
  .dot-legend-count { color: var(--text-dim); border-left: 1px solid var(--border); padding-left: 12px; }
  span.adv-hint { display: block; margin-top: 5px; }
  /* --- Graphique TradingView et alertes (EF-87) --- */
  .chart-ohlc { position: absolute; top: 8px; left: 12px; font-size: 11.5px; color: var(--text-dim); font-variant-numeric: tabular-nums; pointer-events: none; z-index: 3; }
  .pill { display: inline-block; padding: 3px 10px; border-radius: 999px; font-size: 12px; font-weight: 600; }
  .pill-ok { background: var(--green-soft); color: var(--green); }
  .pill-off { background: rgba(255,255,255,0.06); color: var(--text-dim); }

  /* --- Onglet Manuel (EF-81) --- */
  .manual-layout { display: grid; grid-template-columns: minmax(300px, 380px) 1fr; gap: 16px; margin-top: 14px; }
  @media (max-width: 900px) { .manual-layout { grid-template-columns: 1fr; } }
  .order-panel { background: var(--surface-2); border: 1px solid var(--border); border-radius: var(--radius-md); padding: 16px; display: flex; flex-direction: column; gap: 12px; align-self: start; }
  .order-panel label { display: flex; flex-direction: column; gap: 5px; font-size: 11px; text-transform: uppercase; letter-spacing: 0.04em; color: var(--text-faint); font-weight: 600; }
  .order-panel input, .order-panel select { font-size: 14px; padding: 9px 11px; }
  .side-toggle { display: grid; grid-template-columns: 1fr 1fr; gap: 6px; background: var(--surface); border: 1px solid var(--border); border-radius: var(--radius-sm); padding: 4px; }
  .side-toggle button { padding: 8px; border: none; background: transparent; color: var(--text-dim); font-weight: 600; }
  .side-toggle button.active-buy { background: var(--green-soft); color: var(--green); }
  .side-toggle button.active-sell { background: var(--red-soft); color: var(--red); }
  .quick-row { display: flex; gap: 6px; }
  .quick-row button { flex: 1; font-size: 11.5px; padding: 6px 4px; }
  .live-price { display: flex; align-items: baseline; gap: 8px; }
  .live-price .px { font-size: 26px; font-weight: 650; font-variant-numeric: tabular-nums; letter-spacing: -0.01em; }
  .live-price .sym { color: var(--text-dim); font-size: 13px; }
  .submit-buy { background: var(--green); color: #05130d; font-weight: 700; font-size: 15px; padding: 12px; }
  .submit-sell { background: var(--red); color: #fff; font-weight: 700; font-size: 15px; padding: 12px; }
  .order-estimate { font-size: 12px; color: var(--text-dim); font-variant-numeric: tabular-nums; }
  .manual-msg { margin-top: 10px; font-size: 13px; }
  /* --- Onglet Investissement : cartes de position et graphiques (EF-78) --- */
  .invest-toolbar { display: flex; gap: 10px; flex-wrap: wrap; align-items: center; margin: 16px 0 4px 0;
    padding: 12px 14px; background: var(--surface-2); border: 1px solid var(--border); border-radius: var(--radius-md); }
  .invest-toolbar .tb-label { font-size: 10.5px; text-transform: uppercase; letter-spacing: 0.04em;
    color: var(--text-faint); font-weight: 600; }
  .invest-toolbar .tb-value { font-size: 17px; font-weight: 650; font-variant-numeric: tabular-nums; min-width: 84px; text-align: center; }
  .step-btn { width: 34px; height: 34px; padding: 0; font-size: 17px; line-height: 1; font-weight: 600;
    border-radius: var(--radius-sm); }
  .tb-sep { flex: 1 1 auto; }

  .pos-grid { display: grid; grid-template-columns: repeat(auto-fill, minmax(268px, 1fr)); gap: 14px; margin-top: 16px; }
  .pos-card { background: var(--surface-2); border: 1px solid var(--border); border-radius: var(--radius-md);
    padding: 14px; display: flex; flex-direction: column; gap: 10px; }
  .pos-card.empty { opacity: 0.62; }
  .pos-head { display: flex; align-items: baseline; gap: 8px; }
  .pos-dot { width: 9px; height: 9px; border-radius: 50%; flex: 0 0 auto; }
  .pos-sym { font-weight: 650; font-size: 14px; letter-spacing: 0.01em; }
  .pos-qty { margin-left: auto; font-size: 12px; color: var(--text-dim); font-variant-numeric: tabular-nums; }
  .pos-price { display: flex; align-items: baseline; gap: 9px; }
  .pos-price .now { font-size: 25px; font-weight: 650; font-variant-numeric: tabular-nums; letter-spacing: -0.01em; }
  .pos-price .chg { font-size: 13px; font-weight: 600; font-variant-numeric: tabular-nums; }
  .pos-rows { display: grid; grid-template-columns: auto 1fr; gap: 3px 10px; font-size: 12px; }
  .pos-rows dt { color: var(--text-faint); }
  .pos-rows dd { margin: 0; text-align: right; font-variant-numeric: tabular-nums; }
  .alloc { margin-top: 2px; }
  .alloc-track { position: relative; height: 7px; background: rgba(255,255,255,0.07); border-radius: 4px; overflow: visible; }
  .alloc-fill { height: 100%; border-radius: 4px; }
  .alloc-target { position: absolute; top: -3px; width: 2px; height: 13px; background: var(--text-dim); border-radius: 1px; }
  .alloc-legend { display: flex; justify-content: space-between; font-size: 10.5px; color: var(--text-faint);
    margin-top: 5px; font-variant-numeric: tabular-nums; }
  .pos-actions { display: flex; gap: 7px; margin-top: auto; padding-top: 4px; }
  .pos-actions button { flex: 1; font-size: 12px; padding: 7px 9px; }

  .chart-legend { display: flex; gap: 14px; flex-wrap: wrap; margin-top: 10px; font-size: 12px; }
  .chart-legend .li { display: flex; align-items: center; gap: 6px; }
  .chart-legend .sw { width: 11px; height: 3px; border-radius: 2px; flex: 0 0 auto; }
  .chart-legend .val { color: var(--text-dim); font-variant-numeric: tabular-nums; }
  .dca-report { margin-top: 14px; }
  .dca-pre { background: var(--surface-2); border: 1px solid var(--border); border-radius: var(--radius-md); padding: 14px 16px; font-size: 12px; line-height: 1.5; white-space: pre-wrap; overflow-x: auto; font-family: ui-monospace, SFMono-Regular, Menlo, Consolas, monospace; }
  hr.sep { border: none; border-top: 1px solid var(--border); margin: 22px 0; }
</style>
<!-- EF-87 : TradingView Lightweight Charts (Apache 2.0), version FIGEE et
     empreinte verifiee : le navigateur refuse le script si le CDN servait un
     jour autre chose que ce fichier precis. S'il ne charge pas (hors ligne),
     le graphique retombe sur le dessin maison. -->
<script src="https://cdn.jsdelivr.net/npm/lightweight-charts@4.2.3/dist/lightweight-charts.standalone.production.js"
        integrity="sha384-stKllnUqA9AD0gsKCuUtf5XlqAW7PwIgDagoNsTWkjkBmJ/GZ/uHTgEBxdLV2VSK"
        crossorigin="anonymous"></script>
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
let currentMainTab = "home"; // "home" | "bot" | "invest" | "config" | "test" - Accueil par defaut au demarrage
let currentBotName = null;
let currentConfigSubTab = "creation"; // "creation" | "supervision"
let currentTestSubTab = "backtest";
let currentInvestSubTab = "suivi"; // "suivi" | "reglages"
let currentInvestBot = null;
let investBotsCache = [];
// Rapports de passage deja affiches, conserves par bot : le rafraichissement
// automatique du dashboard reconstruit l'onglet toutes les 15 s et effacerait
// sinon le rapport que l'utilisateur vient de demander.
let lastDcaReports = {};
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


function formatAxisTime(ts, spanMs) {
  const d = new Date(ts);
  const DAY = 24 * 3600 * 1000;
  if (spanMs < 2 * DAY) return d.toLocaleTimeString('fr-FR', {hour: '2-digit', minute: '2-digit'});
  if (spanMs < 90 * DAY) return d.toLocaleDateString('fr-FR', {day: '2-digit', month: '2-digit'});
  if (spanMs < 3 * 365 * DAY) return d.toLocaleDateString('fr-FR', {month: '2-digit', year: '2-digit'});
  return d.toLocaleDateString('fr-FR', {year: 'numeric'});
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
  // EF-84 : chandeliers + triangles d'achat/vente, meme dessin que l'onglet
  // Test. Le canvas ne peut etre dessine qu'une fois insere dans la page :
  // on memorise ce qu'il faut tracer, `drawPendingBotChart()` le fait ensuite.
  pendingBotChart = points ? { points, orders: data.orders, name, levels: data.chart_levels || [], price: data.current_price } : null;
  const chartHtml = points
    ? `${renderChartZoneToggles()}
       <div style="position:relative;">
         <div id="bot_price_chart" style="width:100%; height:340px; background:var(--surface-2); border:1px solid var(--border); border-radius:var(--radius-md); overflow:hidden;"></div>
         <div id="bot_price_legend" class="chart-ohlc"></div>
       </div>
       <p class="muted" style="font-size:11px; margin-top:6px;">Molette = zoom, glisser = se deplacer, survol = ouverture / haut / bas / cloture de la bougie.
       Fleche verte = achat, fleche rouge = vente, "ouvert" = position encore ouverte. Graphique : TradingView Lightweight Charts.
       <strong>Clique sur le graphique</strong> pour poser un ordre : acheter si le cours descend sous le prix clique.</p>
       <div id="bot_triggers_list"></div>`
    : '<p class="muted">Chargement du cours historique...</p>';
  return `${renderPriceRangeSelector(name)}${chartHtml}`;
}

let pendingBotChart = null;

// Convertit l'historique [t, cloture, ouverture, haut, bas] en bougies. Un
// ancien point sans ouverture/haut/bas (bot pas encore redemarre depuis
// l'ajout des chandeliers) vaut une bougie plate a sa cloture : le graphique
// passe alors en courbe, plutot que d'afficher des traits sans corps.
function pointsToCandles(points) {
  return points.map(p => ({
    t: p[0], c: p[1],
    o: p.length > 2 ? p[2] : p[1],
    h: p.length > 3 ? p[3] : p[1],
    l: p.length > 4 ? p[4] : p[1],
  }));
}

// Les ordres du bot (entree/sortie horodatees) deviennent les marqueurs du
// dessin des tests : achat et vente pour un trade clos, achat cercle pour une
// position encore ouverte.
function ordersToMarkers(orders) {
  const closed = [], open = [];
  (orders || []).forEach(o => {
    if (!o.entry_timestamp) return;
    const isClosed = o.sell_price !== null && o.sell_price !== undefined && o.exit_timestamp;
    if (isClosed) closed.push({ buy_t: o.entry_timestamp, buy_p: o.buy_price, sell_t: o.exit_timestamp, sell_p: o.sell_price });
    else open.push({ buy_t: o.entry_timestamp, buy_p: o.buy_price });
  });
  return { closed, open };
}

// EF-87 : le graphique des bots utilise TradingView Lightweight Charts (zoom,
// deplacement, reticule, valeurs de la bougie survolee). Si la bibliotheque
// n'a pas pu etre chargee (hors ligne, CDN indisponible), on retombe sur le
// dessin maison (EF-84) : le graphique ne disparait jamais.
let botChartInstance = null;
let botChartRanges = {};   // "bot|periode" -> zone visible, conservee entre deux rafraichissements

function drawPendingBotChart() {
  const host = document.getElementById("bot_price_chart");
  if (!pendingBotChart || !host) return;
  const candles = pointsToCandles(pendingBotChart.points);
  if (candles.length < 2) return;
  const hasOhlc = pendingBotChart.points.some(p => p.length > 4);
  const { closed, open } = ordersToMarkers(pendingBotChart.orders);
  if (botChartInstance) { try { botChartInstance.remove(); } catch (e) {} botChartInstance = null; }
  if (window.LightweightCharts) {
    try { drawTradingViewChart(host, candles, closed, open, hasOhlc); return; }
    catch (e) { console.error("graphique TradingView indisponible, repli sur le dessin maison :", e); host.innerHTML = ""; }
  }
  botChartSeries = null;
  refreshBotTriggers(pendingBotChart.name, null);
  host.innerHTML = '<canvas id="bot_price_canvas" style="width:100%; height:100%; display:block;"></canvas>';
  drawBacktestCandlestickChart(candles, closed, open, hasOhlc, "bot_price_canvas");
}

function drawTradingViewChart(host, candles, closed, open, hasOhlc) {
  const key = pendingBotChart.name + "|" + getSelectedPriceRange(pendingBotChart.name);
  const css = getComputedStyle(document.documentElement);
  const token = (name, fallback) => (css.getPropertyValue(name) || fallback).trim();
  const up = token("--green", "#2fd699"), down = token("--red", "#ff6b6b");
  const grid = token("--border", "rgba(255,255,255,0.07)");

  const chart = LightweightCharts.createChart(host, {
    autoSize: true,
    layout: { background: { type: "solid", color: "transparent" }, textColor: token("--text-dim", "#9aa2b5"), fontSize: 11 },
    grid: { vertLines: { color: grid }, horzLines: { color: grid } },
    rightPriceScale: { borderColor: grid },
    timeScale: { borderColor: grid, timeVisible: true, secondsVisible: false },
    crosshair: { mode: LightweightCharts.CrosshairMode.Normal },
    localization: { locale: "fr-FR" },
  });
  botChartInstance = chart;

  // La bibliotheque exige des temps en SECONDES, strictement croissants et
  // uniques, et affiche l'heure en UTC. Le reste du dashboard est en heure
  // LOCALE : sans ce decalage, l'axe marquait 01:00 pour la bougie que la
  // legende datait de 03:00 (constate en verifiant le graphique). Decalage
  // unique, celui d'aujourd'hui : sur un historique qui traverse un
  // changement d'heure, les bougies d'avant sont decalees d'une heure.
  const tzShift = -new Date().getTimezoneOffset() * 60;
  const seen = new Set();
  const data = candles
    .filter(c => { if (seen.has(c.t)) return false; seen.add(c.t); return true; })
    .sort((a, b) => a.t - b.t)
    .map(c => ({ time: Math.floor(c.t / 1000) + tzShift, open: c.o, high: c.h, low: c.l, close: c.c }));

  const series = hasOhlc
    ? chart.addCandlestickSeries({ upColor: up, downColor: down, borderUpColor: up, borderDownColor: down, wickUpColor: up, wickDownColor: down })
    : chart.addLineSeries({ color: token("--accent", "#5b8def"), lineWidth: 2 });
  series.setData(hasOhlc ? data : data.map(d => ({ time: d.time, value: d.close })));

  // Un marqueur doit tomber sur une bougie existante : on le rattache a la
  // bougie qui contient l'instant du trade (la derniere qui commence avant).
  const times = data.map(d => d.time);
  const step = times.length > 1 ? times[times.length - 1] - times[times.length - 2] : 3600;
  function snap(ms) {
    const s = Math.floor(ms / 1000) + tzShift;
    if (s < times[0] || s > times[times.length - 1] + step) return null;
    let lo = 0, hi = times.length - 1;
    while (lo < hi) { const mid = (lo + hi + 1) >> 1; if (times[mid] <= s) lo = mid; else hi = mid - 1; }
    return times[lo];
  }
  const fmt = v => Number(v).toLocaleString("fr-FR", { maximumFractionDigits: 6 });
  const markers = [];
  closed.forEach(tr => {
    const b = snap(tr.buy_t), s = snap(tr.sell_t);
    if (b !== null) markers.push({ time: b, position: "belowBar", color: up, shape: "arrowUp", text: "achat " + fmt(tr.buy_p) });
    if (s !== null) markers.push({ time: s, position: "aboveBar", color: down, shape: "arrowDown", text: "vente " + fmt(tr.sell_p) });
  });
  open.forEach(pos => {
    const b = snap(pos.buy_t);
    if (b !== null) markers.push({ time: b, position: "belowBar", color: up, shape: "arrowUp", text: "achat " + fmt(pos.buy_p) + " (ouvert)" });
  });
  markers.sort((a, b) => a.time - b.time);
  series.setMarkers(markers);

  // Valeurs de la bougie survolee (remplace l'info-bulle perdue a EF-84).
  const legend = document.getElementById("bot_price_legend");
  const showLegend = bar => {
    if (!legend) return;
    if (!bar) { legend.textContent = ""; return; }
    // bar.time porte deja le decalage local : on le formate donc "en UTC".
    const d = new Date(bar.time * 1000).toLocaleString("fr-FR", { dateStyle: "short", timeStyle: "short", timeZone: "UTC" });
    legend.textContent = bar.open !== undefined
      ? d + "   O " + fmt(bar.open) + "   H " + fmt(bar.high) + "   B " + fmt(bar.low) + "   C " + fmt(bar.close)
      : d + "   " + fmt(bar.value);
  };
  chart.subscribeCrosshairMove(param => showLegend(param && param.time ? param.seriesData.get(series) : null));

  // EF-88 : zones (stop-loss, objectifs, seuils de la strategie, ordres manuels)
  // tracees en lignes horizontales, chaque famille activable a part.
  botChartSeries = series;
  drawChartZones(series);
  refreshBotTriggers(pendingBotChart.name, series);

  // Clic sur le graphique : poser un ordre "acheter si le cours descend sous X".
  const clickedName = pendingBotChart.name, clickedPrice = pendingBotChart.price;
  chart.subscribeClick(param => {
    if (!param || !param.point) return;
    const price = series.coordinateToPrice(param.point.y);
    if (price === null || !isFinite(price) || price <= 0) return;
    placeBuyTrigger(clickedName, price, clickedPrice);
  });

  // Le dashboard se redessine toutes les 15 s : on conserve le zoom choisi.
  const saved = botChartRanges[key];
  if (saved) chart.timeScale().setVisibleLogicalRange(saved);
  else chart.timeScale().fitContent();
  chart.timeScale().subscribeVisibleLogicalRangeChange(range => { if (range) botChartRanges[key] = range; });
}

// --- Zones et ordres declenches sur le graphique des bots (EF-88) ------------
const CHART_ZONE_KINDS = [
  { id: "risk", label: "Stop-loss et objectifs" },
  { id: "strategy", label: "Seuils de la strategie" },
  { id: "triggers", label: "Ordres manuels" },
];
let botChartSeries = null;
let botZoneLines = [];
let botTriggerLines = [];
let botTriggersCache = {};

function zoneEnabled(id) {
  try { return localStorage.getItem("zone_" + id) !== "off"; } catch (e) { return true; }
}

function toggleZone(id, on) {
  try { localStorage.setItem("zone_" + id, on ? "on" : "off"); } catch (e) {}
  if (botChartSeries) { drawChartZones(botChartSeries); drawTriggerLines(botChartSeries); }
}

function renderChartZoneToggles() {
  const boxes = CHART_ZONE_KINDS.map(k =>
    `<label style="display:inline-flex; align-items:center; gap:6px; font-size:12px; color:var(--text-dim); cursor:pointer;">
       <input type="checkbox" ${zoneEnabled(k.id) ? "checked" : ""} onchange="toggleZone('${k.id}', this.checked)"> ${k.label}</label>`
  ).join("");
  return `<div style="display:flex; gap:16px; flex-wrap:wrap; margin:4px 0 8px 0;">${boxes}</div>`;
}

function tokenColor(name, fallback) {
  return (getComputedStyle(document.documentElement).getPropertyValue(name) || fallback).trim();
}

function addLine(series, store, price, color, title, style) {
  if (price === null || price === undefined || !isFinite(price) || price <= 0) return;
  store.push(series.createPriceLine({
    price, color, title, lineWidth: 1, axisLabelVisible: true,
    lineStyle: style === undefined ? LightweightCharts.LineStyle.Dashed : style,
  }));
}

function drawChartZones(series) {
  botZoneLines.forEach(l => { try { series.removePriceLine(l); } catch (e) {} });
  botZoneLines = [];
  if (!pendingBotChart) return;
  const red = tokenColor("--red", "#ff6b6b"), green = tokenColor("--green", "#2fd699");
  const amber = tokenColor("--amber", "#f5b74f"), purple = tokenColor("--purple", "#b18cff");
  const accent = tokenColor("--accent", "#5b8def");
  const L = LightweightCharts.LineStyle;
  if (zoneEnabled("risk")) {
    (pendingBotChart.orders || []).filter(o => o.status === "ouvert").forEach(o => {
      addLine(series, botZoneLines, o.target_stop_loss, red, "stop-loss", L.Dashed);
      addLine(series, botZoneLines, o.target_take_profit, green, "objectif", L.Dashed);
      addLine(series, botZoneLines, o.target_trailing_stop, amber, "trailing stop", L.Dashed);
      addLine(series, botZoneLines, o.profit_lock_arm, purple, "verrou arme au-dessus", L.Dotted);
      addLine(series, botZoneLines, o.profit_lock_trigger, purple, "verrou : vente sous", L.Dashed);
      addLine(series, botZoneLines, o.buy_price, tokenColor("--text-dim", "#9aa2b5"), "prix d'achat", L.Dotted);
    });
  }
  if (zoneEnabled("strategy")) {
    (pendingBotChart.levels || []).forEach(lv => {
      const color = lv.kind === "entry" ? green : lv.kind === "exit" ? red : accent;
      addLine(series, botZoneLines, lv.price, color, lv.label, lv.kind === "trend" ? L.Solid : L.Dotted);
    });
  }
}

function drawTriggerLines(series) {
  botTriggerLines.forEach(l => { try { series.removePriceLine(l); } catch (e) {} });
  botTriggerLines = [];
  if (!pendingBotChart || !zoneEnabled("triggers")) return;
  const list = botTriggersCache[pendingBotChart.name] || [];
  list.filter(tr => tr.status === "en attente").forEach(tr =>
    addLine(series, botTriggerLines, tr.trigger_price, tokenColor("--amber", "#f5b74f"),
            "achat si <= " + Number(tr.trigger_price).toLocaleString("fr-FR", { maximumFractionDigits: 6 }) + " (#" + tr.id + ")",
            LightweightCharts.LineStyle.LargeDashed));
}

async function refreshBotTriggers(name, series) {
  try {
    const resp = await fetch(`${CONTROL_SERVER}/api/bot-triggers?name=${encodeURIComponent(name)}`);
    const d = await resp.json();
    if (d.error) return;
    botTriggersCache[name] = d.triggers || [];
  } catch (e) { return; }
  if (series && botChartSeries === series) drawTriggerLines(series);
  renderBotTriggersList(name);
}

function renderBotTriggersList(name) {
  const el = document.getElementById("bot_triggers_list");
  if (!el || !pendingBotChart || pendingBotChart.name !== name) return;
  const list = botTriggersCache[name] || [];
  if (!list.length) { el.innerHTML = ""; return; }
  const fmt = v => Number(v).toLocaleString("fr-FR", { maximumFractionDigits: 6 });
  const color = s => s === "execute" ? "var(--green)" : s === "refuse" ? "var(--red)" : s === "en attente" ? "var(--amber)" : "var(--text-faint)";
  const rows = list.map(tr => `<tr>
    <td>#${tr.id}</td>
    <td>achat si le cours descend sous <strong>${fmt(tr.trigger_price)}</strong></td>
    <td style="color:${color(tr.status)};">${tr.status}</td>
    <td class="muted" style="white-space:normal; font-size:11.5px;">${(tr.detail || "").replace(/</g, "&lt;")}</td>
    <td>${tr.status === "en attente" ? `<button onclick="cancelBuyTrigger('${name}', ${tr.id})" style="font-size:11.5px; padding:4px 9px;">Annuler</button>` : ""}</td>
  </tr>`).join("");
  el.innerHTML = `<h2 style="font-size:13px; color:#9098a5; margin-top:16px;">Ordres manuels sur ce bot</h2>
    <table class="bi"><thead><tr><th>#</th><th>Ordre</th><th>Etat</th><th>Detail</th><th></th></tr></thead><tbody>${rows}</tbody></table>`;
}

async function placeBuyTrigger(name, price, currentPrice) {
  const digits = price >= 100 ? 2 : price >= 1 ? 4 : 6;
  const rounded = Number(price.toFixed(digits));
  const fmt = v => Number(v).toLocaleString("fr-FR", { maximumFractionDigits: 6 });
  // Retours a la ligne sans antislash : ce JS vit dans une chaine Python non
  // brute, ou la sequence d'echappement serait interpretee avant d'arriver
  // au navigateur (piege rencontre trois fois).
  const NL = String.fromCharCode(10);
  const lines = ["Poser un ordre sur " + name + " :", "", "ACHETER si le cours descend sous " + fmt(rounded) + "."];
  if (currentPrice) lines.push("Cours actuel : " + fmt(currentPrice) + ".");
  if (currentPrice && currentPrice <= rounded) lines.push("", "ATTENTION : le cours est DEJA sous ce seuil - l'achat partira au prochain passage du bot (moins d'une minute).");
  lines.push("", "L'ordre passe par les memes garde-fous que la strategie (nombre de positions, panier commun) : il peut etre refuse. Argent fictif (testnet).");
  const text = lines.join(NL);
  if (!confirm(text)) return;
  try {
    const resp = await fetch(`${CONTROL_SERVER}/api/bot-trigger`, {
      method: "POST", headers: { "Content-Type": "application/json" },
      body: JSON.stringify({ name, price: rounded }),
    });
    const d = await resp.json();
    if (d.error) { alert(d.error); return; }
  } catch (e) { alert("Serveur de controle injoignable : " + e); return; }
  refreshBotTriggers(name, botChartSeries);
}

async function cancelBuyTrigger(name, id) {
  try {
    const resp = await fetch(`${CONTROL_SERVER}/api/bot-trigger-cancel`, {
      method: "POST", headers: { "Content-Type": "application/json" }, body: JSON.stringify({ name, id }),
    });
    const d = await resp.json();
    if (d.error) alert(d.error);
  } catch (e) { alert("Serveur de controle injoignable : " + e); }
  refreshBotTriggers(name, botChartSeries);
}

// --- Onglet Alertes : alertes TradingView recues par webhook (EF-87) ---------
async function renderAlertsTab() {
  const contentEl = document.getElementById("content");
  if (!document.getElementById("alerts-root")) {
    const hookUrl = window.location.origin + "/api/tv-webhook";
    contentEl.innerHTML = `<div id="alerts-root">
      <h1>Alertes TradingView</h1>
      <p class="muted">TradingView n'offre pas d'API pour lire ses analyses. En revanche, une analyse ecrite en Pine Script
      tourne en continu sur ses serveurs et peut <strong>appeler ton app</strong> quand elle se declenche (webhook). Les alertes
      recues arrivent ici. Elles peuvent aussi devenir des ordres <strong>paper</strong> dans le panier Manuel, si tu l'as
      explicitement active.</p>
      <div id="alerts-status"></div>
      <div class="section-block">
        <div class="section-header"><h2>Brancher TradingView</h2></div>
        <ol class="muted" style="line-height:1.7; font-size:13px; padding-left:18px;">
          <li>Dans le fichier <code>.env</code> du serveur, definis <code>TRADINGVIEW_WEBHOOK_SECRET=</code> (une longue chaine au hasard), puis relance le serveur.</li>
          <li>Rends le serveur joignable depuis internet en <strong>HTTPS sur le port 443</strong> - TradingView refuse tout autre port. Un tunnel (Cloudflare Tunnel, ngrok) est le plus simple et n'ouvre aucun port sur ta box.</li>
          <li>Sur TradingView, cree une alerte, coche <em>Webhook URL</em> et colle l'adresse publique suivie de <code>/api/tv-webhook</code>. Adresse vue d'ici : <code>${hookUrl}</code></li>
          <li>Dans le message de l'alerte, colle ce modele en remplacant le secret :</li>
        </ol>
        <pre class="dca-pre">{
  "secret": "TON_SECRET",
  "ticker": "{{exchange}}:{{ticker}}",
  "action": "buy",
  "price": "{{close}}",
  "amount": 20,
  "message": "{{strategy.order.comment}}"
}</pre>
        <p class="muted" style="font-size:12px;"><code>action</code> : <code>buy</code>, <code>sell</code>, ou n'importe quel autre mot pour une simple information.
        <code>amount</code> : montant d'achat en USDT (plafonne). A la vente, <code>quantity</code> vaut tout par defaut.
        Conditions TradingView : abonnement donnant droit aux webhooks, et double authentification activee sur le compte.</p>
        <div style="display:flex; gap:10px; flex-wrap:wrap; align-items:center; margin-top:10px;">
          <button class="primary" onclick="sendTestAlert('test')">Envoyer une alerte de test</button>
          <button onclick="sendTestAlert('buy')">Tester une alerte d'achat</button>
          <span class="muted" style="font-size:12px;">L'alerte de test passe par exactement le meme traitement qu'une vraie.</span>
        </div>
        <div id="alerts-msg" class="manual-msg"></div>
      </div>
      <div id="alerts-list"></div>
    </div>`;
  }
  await refreshAlerts();
}

async function refreshAlerts() {
  let d;
  try {
    const resp = await fetch(`${CONTROL_SERVER}/api/tv-alerts`);
    d = await resp.json();
  } catch (e) {
    document.getElementById("alerts-status").innerHTML = investServerDownHtml();
    return;
  }
  const pill = (ok, yes, no) => `<span class="pill ${ok ? "pill-ok" : "pill-off"}">${ok ? yes : no}</span>`;
  document.getElementById("alerts-status").innerHTML = `<div class="section-block"><div class="grid">
    <div><div class="stat-label">Reception</div><div class="stat-value" style="font-size:16px;">${pill(d.enabled, "active", "desactivee")}</div></div>
    <div><div class="stat-label">Ordres automatiques</div><div class="stat-value" style="font-size:16px;">${pill(d.auto_orders, "actifs (paper)", "desactives")}</div></div>
    <div><div class="stat-label">Plafond par alerte</div><div class="stat-value">${d.max_order_usdt} USDT</div></div>
    <div><div class="stat-label">Alertes recues</div><div class="stat-value">${d.alerts.length}</div></div>
  </div>
  ${d.enabled ? "" : '<p class="muted" style="margin-top:10px;">Reception desactivee : aucun <code>TRADINGVIEW_WEBHOOK_SECRET</code> dans <code>.env</code>. Tout appel est refuse.</p>'}
  ${d.auto_orders ? "" : '<p class="muted" style="margin-top:6px; font-size:12px;">Les alertes sont consignees mais ne passent aucun ordre. Pour qu\\'un <em>buy</em>/<em>sell</em> devienne un ordre paper dans le panier Manuel : <code>TRADINGVIEW_AUTO_ORDERS=1</code> dans <code>.env</code>.</p>'}
  </div>`;

  const list = document.getElementById("alerts-list");
  if (!d.alerts.length) {
    list.innerHTML = '<div class="section-block"><div class="section-header"><h2>Alertes recues</h2></div><p class="muted">Aucune alerte pour le moment.</p></div>';
    return;
  }
  const color = s => s === "execute" ? "var(--green)" : (s === "refuse" || s === "erreur") ? "var(--red)" : s === "en cours" ? "var(--amber)" : "var(--text-faint)";
  const rows = d.alerts.map(a => `<tr>
    <td class="muted">${a.received_at.replace("T", " ").replace("+00:00", " UTC")}</td>
    <td><strong>${a.ticker || "-"}</strong></td>
    <td>${a.action || "-"}</td>
    <td style="text-align:right;">${a.price === null ? "-" : a.price}</td>
    <td style="max-width:260px; white-space:normal;">${(a.message || "").replace(/</g, "&lt;")}</td>
    <td style="color:${color(a.order_status)}; white-space:normal;" title="${(a.order_detail || "").replace(/"/g, "&quot;")}">${a.order_status || "-"}<br><span class="muted" style="font-size:11px;">${(a.order_detail || "").replace(/</g, "&lt;")}</span></td>
    <td class="muted" style="font-size:11px;">${a.source_ip || ""}</td>
  </tr>`).join("");
  list.innerHTML = `<div class="section-block"><div class="section-header"><h2>Alertes recues</h2></div>
    <table class="bi"><thead><tr><th>Quand</th><th>Ticker</th><th>Action</th><th style="text-align:right;">Prix</th><th>Message</th><th>Suite donnee</th><th>Origine</th></tr></thead>
    <tbody>${rows}</tbody></table></div>`;
}

async function sendTestAlert(action) {
  const msg = document.getElementById("alerts-msg");
  if (action === "buy" && !confirm("Envoyer une alerte d'ACHAT de test ?\\n\\nSi les ordres automatiques sont actifs, elle passera un vrai ordre paper (testnet) dans le panier Manuel.")) return;
  try {
    const resp = await fetch(`${CONTROL_SERVER}/api/tv-test`, {
      method: "POST", headers: { "Content-Type": "application/json" },
      body: JSON.stringify({ action, ticker: "BINANCE:ETHUSDT" }),
    });
    const d = await resp.json();
    msg.innerHTML = d.error ? `<span style="color:var(--red);">${d.error}</span>` : `<span style="color:var(--green);">Alerte recue (#${d.id}) - ${d.detail}</span>`;
  } catch (e) {
    msg.innerHTML = `<span style="color:var(--red);">Serveur de controle injoignable : ${e}</span>`;
  }
  await refreshAlerts();
}

// EF-82 : l'adresse du serveur est celle qui a servi cette page - c'est ce
// qui permet d'ouvrir le dashboard depuis un telephone ou un autre PC de la
// maison. "localhost:8765" en dur ne fonctionnait que sur la machine du
// serveur : depuis un autre appareil, le navigateur cherchait le serveur sur
// lui-meme. Le repli ne sert que si le fichier est ouvert directement
// (file://), sans serveur.
const CONTROL_SERVER = window.location.protocol.startsWith("http")
  ? window.location.origin
  : "http://localhost:8765";

// Top 10 cryptos par capitalisation (vs USDT) - liste figee volontairement
// courte pour guider vers des paires liquides/bien supportees par Binance,
// avec une echappatoire "Autre" pour ne pas bloquer un symbole hors liste.
// Types de bot creables depuis le formulaire de Creation (§5.1) - mean_reversion
// et market_making restent YAML uniquement, pas encore promus au formulaire.
const CREATABLE_STRATEGY_TYPES = new Set(["sma_cross", "scalp_dip", "dip_bounce_hourly", "dip_bounce_minute", "dip_bounce_daily", "mean_dip", "slope_dip", "trend_regime", "buy_and_hold"]);

const TOP10_SYMBOLS = [
  "BTC/USDT", "ETH/USDT", "XRP/USDT", "BNB/USDT", "SOL/USDT",
  "DOGE/USDT", "ADA/USDT", "TRX/USDT", "LINK/USDT", "AVAX/USDT",
];

// EF-65 (2026-09-17, demande de l'utilisateur : "selectionner les actions
// avec une liste") - actions Euronext deja testees en session (voir STC
// §3.47) + quelques grandes capitalisations frequentes, memes tickers
// Interactive Brokers/Yahoo Finance (suffixe ".PA" = Paris, ".AS" = Amsterdam).
const TOP_STOCKS = [
  "TTE.PA", "ORA.PA", "GLE.PA", "RNO.PA", "AF.PA", "MT.AS",
  "AI.PA", "MC.PA", "OR.PA", "SAN.PA", "BNP.PA",
];

function symbolSelectHtml(id, selectedValue, options, otherPlaceholder) {
  const list = options || TOP10_SYMBOLS;
  const placeholder = otherPlaceholder || "ex: MATIC/USDT";
  const isKnown = list.includes(selectedValue);
  const optionsHtml = list.map(s => `<option value="${s}"${s === selectedValue ? " selected" : ""}>${s}</option>`).join("");
  return `
    <select id="${id}" onchange="onSymbolSelectChange('${id}')">
      ${optionsHtml}
      <option value="__other__"${isKnown ? "" : " selected"}>Autre...</option>
    </select>
    <input id="${id}_other" type="text" placeholder="${placeholder}" style="margin-top:6px; ${isKnown ? "display:none;" : ""}" value="${isKnown ? "" : (selectedValue || "")}">
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

function setSymbolValue(id, value, list) {
  const options = list || TOP10_SYMBOLS;
  const select = document.getElementById(id);
  const isKnown = options.includes(value);
  select.value = isKnown ? value : "__other__";
  document.getElementById(`${id}_other`).value = isKnown ? "" : (value || "");
  document.getElementById(`${id}_other`).style.display = isKnown ? "none" : "block";
}

const MAIN_TABS = [
  { id: "home", label: "🏠 Accueil" },
  { id: "bot", label: "🤖 Bot" },
  { id: "invest", label: "💰 Investissement" },
  { id: "manual", label: "🖐 Manuel" },
  { id: "alerts", label: "🔔 Alertes" },
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
      const dotTitle = isRunning
        ? "Bot actif : donnees recues il y a moins de 3 minutes"
        : "Bot a l'arret ou silencieux depuis plus de 3 minutes";
      return `<button class="tab ${name === currentBotName ? "active" : ""}" data-name="${name}" title="${dotTitle}">
        <span title="${dotTitle}" style="display:inline-block; width:6px; height:6px; border-radius:50%; background:${dotColor}; margin-right:7px; vertical-align:1px;"></span>${name}
      </button>`;
    }).join("");
    subtabsEl.querySelectorAll(".tab").forEach(btn => {
      btn.onclick = () => { currentBotName = btn.dataset.name; renderSubTabsAndContent(); };
    });
    if (names.length) {
      const running = names.filter(n => {
        const d = (window.BOT_INSTANCES || {})[n];
        return d && d.updated_at_ts && (Date.now() - d.updated_at_ts) < STALE_AFTER_MS;
      }).length;
      subtabsEl.insertAdjacentHTML("beforeend",
        `<span class="dot-legend" title="Un bot est considere actif s'il a envoye des donnees il y a moins de 3 minutes">
          <span class="dot-legend-item"><i class="dot" style="background:var(--green)"></i>actif</span>
          <span class="dot-legend-item"><i class="dot" style="background:var(--red)"></i>arrete</span>
          <span class="dot-legend-count">${running}/${names.length} en marche</span>
        </span>`);
    }
    renderBotContent();
    return;
  }

  if (currentMainTab === "invest") {
    const subtabs = [{ id: "suivi", label: "Suivi" }, { id: "reglages", label: "Reglages" }];
    subtabsEl.style.display = "flex";
    subtabsEl.innerHTML = subtabs.map(s =>
      `<button class="tab ${s.id === currentInvestSubTab ? "active" : ""}" data-id="${s.id}">${s.label}</button>`
    ).join("");
    subtabsEl.querySelectorAll(".tab").forEach(btn => {
      btn.onclick = () => { currentInvestSubTab = btn.dataset.id; renderSubTabsAndContent(); };
    });
    renderInvestContent();
    return;
  }

  if (currentMainTab === "alerts") {
    subtabsEl.style.display = "none";
    renderAlertsTab();
    return;
  }

  if (currentMainTab === "manual") {
    subtabsEl.style.display = "none";
    renderManualTab();
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
  if (type === "dip_bounce_daily") {
    return `
      <div class="field"><label>Fenetre de tendance (jours)</label><input id="f_trend_ma_period" type="number" step="1" min="2" value="20"></div>
      <div class="field"><label>Seuil de creux (%, proximite du plus bas de la fenetre)</label><input id="f_dip_threshold_pct" type="number" step="0.01" value="2"></div>
      <p class="adv-hint" style="grid-column:1/-1;">2026-09-16, ajoute pour les actions (paper trading IBKR, "Type de compte" ci-dessus) - meme strategie "Rebond de creux" que les presets crypto, mais en bougies JOURNALIERES avec une fenetre de tendance REGLABLE : contrairement aux presets horaire/minute, la recherche empirique sur plusieurs actions (voir le manuel utilisateur) montre que la fenetre optimale varie fortement d'une action a l'autre (10 jours pour Renault, 40 pour Air France-KLM par exemple) - pas de valeur universelle a figer. <strong>Pas de verrou de gain</strong> pour ce preset (les meilleurs reglages trouves n'en utilisaient aucun) : seuls le Stop-loss (optionnel, "Gestion du risque" ci-dessous) et le Trailing stop ferment une position. <strong>Constat honnete</strong> : aucun edge demontre sur des actions en tendance haussiere forte (TotalEnergies, Orange...) ; plus credible (protection de capital, pas alpha) sur des actions en baisse ou chahutees.</p>
    `;
  }
  if (type === "mean_dip") {
    return `
      <div class="field"><label>Fenetre (bougies 5 min, ~1h = 12)</label><input id="f_window" type="number" step="1" min="2" value="12"></div>
      <div class="field"><label>Largeur des bandes (ecarts-types)</label><input id="f_num_std" type="number" step="0.1" value="2.0"></div>
      <p class="adv-hint" style="grid-column:1/-1;">2026-09-16, idee proposee par l'utilisateur : detecte un creux comme un ECART a la moyenne mobile recente (bandes de Bollinger), pas une proximite a un plus bas glissant comme "Rebond de creux" - capte les pics descendants brefs (quelques dizaines de minutes) invisibles a l'echelle 24h. Achete des que le prix passe sous la bande basse (moyenne - N ecarts-types) ; <strong>aucune sortie geree par la strategie elle-meme</strong> (pas de verrou de gain, pas de retour a la moyenne) - seuls le Stop-loss et le Trailing stop (ci-dessous, "Gestion du risque") ferment une position. Stop-loss <strong>obligatoire</strong> ici (contrairement a "Rebond de creux") : sans lui ni verrou de gain, rien ne fermerait jamais une position perdante. <strong>"Positions simultanees max" pre-rempli a 10</strong> (au lieu de 1) : teste empiriquement le 2026-09-16, avec 1 seule position la strategie reste quasi inactive (une position bloque toute nouvelle entree pendant potentiellement plusieurs jours). Reglages testes sur plusieurs periodes sans edge robuste demontre - voir le manuel utilisateur.</p>
    `;
  }
  if (type === "slope_dip") {
    return `
      <div class="field"><label>Seuil de pente (%)</label><input id="f_slope_threshold_pct" type="number" step="0.01" value="0.5"></div>
      <div class="field"><label>Nombre de bougies pour mesurer la pente</label><input id="f_candles_window" type="number" step="1" min="2" value="2"></div>
      <div class="field"><label style="display:flex; align-items:center; gap:6px; font-weight:400;"><input id="f_one_buy_per_slope" type="checkbox"> Limiter a 1 achat par pente continue</label></div>
      <p class="adv-hint" style="grid-column:1/-1;">2026-09-16, idee proposee par l'utilisateur : "detecteur de pente" - compare la cloture de la bougie courante a celle d'il y a N bougies 1 minute (2 par defaut = la bougie precedente immediate) ; si la chute depasse le seuil, achete immediatement. <strong>Aucune sortie geree par la strategie elle-meme</strong> : "on garde l'ordre" (demande explicite), seul le Trailing stop (ci-dessous, "Gestion du risque", suggere a 5% comme demande) ferme normalement une position ; Stop-loss <strong>optionnel</strong> en filet de securite (vide par defaut, comme "Rebond de creux"). <strong>Elargir a 5 bougies</strong> (teste le 2026-09-16) augmente le rendement moyen sur plusieurs periodes mais aussi fortement la variance (pire cas ~4x plus large) - pas un edge demontre, a essayer au cas par cas. <strong>"Limiter a 1 achat par pente continue"</strong> (2026-09-16, constat reel de l'utilisateur : "sa foire pendant les longues pentes") : sur une derive baissiere continue, la condition de pente reste vraie a chaque bougie - sans cette case, la strategie empile un achat par bougie sur la MEME tendance au lieu d'un seul. Cochee, un seul achat par episode de chute continue (se rearme des que la chute s'interrompt, meme brievement). Desactivee par defaut (comportement d'origine).</p>
    `;
  }
  if (type === "trend_regime") {
    return `
      <div class="field"><label>Fenetre de tendance (bougies)</label><input id="f_ema_period" type="number" step="1" min="2" value="500"></div>
      <div class="field"><label>Marge pour entrer (%)</label><input id="f_entry_buffer_pct" type="number" step="0.1" min="0" value="3"></div>
      <div class="field"><label>Marge pour sortir (%)</label><input id="f_exit_buffer_pct" type="number" step="0.1" min="0" value="0"></div>
      <p class="adv-hint" style="grid-column:1/-1;">2026-09-17, demande de l'utilisateur ("un modele rentable en haussier, et si possible en baissier") : reste investi tant que le cours est au-dessus de sa tendance de fond, et passe <strong>tout en liquidites</strong> des qu'il repasse dessous. C'est la difference avec le "Filtre de tendance" ci-dessous, qui bloque seulement les nouveaux achats sans jamais fermer une position ouverte - on traversait donc tout le marche baissier en portefeuille. <strong>Mesure sur ETH/USDT, 6,7 ans de bougies 1h</strong>, reglee sur les 70% d'entrainement puis evaluee une seule fois sur les 30% restants : <strong>+34,8% en test (execution decalee, realiste) contre -35,1% pour le buy &amp; hold</strong>, et 41 reglages sur 45 battent le buy &amp; hold - l'effet ne depend pas d'un reglage precis. Par regime sur tout l'historique : <strong>+61% par semestre haussier, +0,7% par semestre baissier</strong> (contre +83% / -41% pour le buy &amp; hold) : on cede un peu de hausse pour ne plus subir la baisse. <strong>Gagner de l'argent en baissier reste hors de portee</strong> (long-only, pas de vente a decouvert) : l'objectif est de rester plat. Les marges evitent le va-et-vient couteux autour de la ligne de tendance ; une fenetre trop courte (~200 bougies) se fait hacher et perd. Stop-loss <strong>optionnel</strong> : la sortie normale est le retournement de tendance.</p>
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

function onAccountTypeChange(value) {
  // EF-65 (2026-09-17, demande de l'utilisateur : "selectionner les actions
  // avec une liste") - "Actions" bascule le Symbole sur une liste deroulante
  // d'actions Euronext (TOP_STOCKS) au lieu des cryptos (TOP10_SYMBOLS),
  // avec le meme mecanisme "Autre..." en texte libre pour un ticker non
  // liste. Rappelle aussi le prealable non-code (TWS/IB Gateway) - le reste
  // du formulaire (risque, strategie) ne change pas, seules les strategies
  // imposant un timeframe incompatible sont refusees cote serveur
  // (build_config).
  const isIbkr = value === "ibkr_paper";
  const hint = document.getElementById("f_account_type_hint");
  const symbolWrap = document.getElementById("f_symbol_wrap");
  symbolWrap.innerHTML = isIbkr
    ? `<label>Symbole</label>${symbolSelectHtml("f_symbol", TOP_STOCKS[0], TOP_STOCKS, "ex: RNO.PA (Renault, Euronext Paris)")}`
    : `<label>Symbole</label>${symbolSelectHtml("f_symbol", "ETH/USDT")}`;
  if (isIbkr) {
    hint.innerHTML = "Necessite TWS ou IB Gateway installe et connecte en mode <strong>PAPER</strong> (voir le manuel utilisateur) - aucun argent reel n'est engage. Strategies compatibles : &quot;Rebond de creux - journalier&quot;, &quot;Croisement de moyennes&quot;, &quot;Scalp sur creux&quot;, &quot;Buy &amp; hold&quot;.";
    hint.style.display = "block";
  } else {
    hint.style.display = "none";
  }
}

function onStrategyTypeChange(type) {
  document.getElementById("f_strategy_fields").innerHTML = strategyFieldsHtml(type);

  const isDipBounce = type === "dip_bounce_hourly" || type === "dip_bounce_minute";
  const isDipBounceDaily = type === "dip_bounce_daily";
  const isMeanDip = type === "mean_dip";
  const isSlopeDip = type === "slope_dip";
  const noStopLoss = type === "buy_and_hold";

  const timeframeSelect = document.getElementById("f_timeframe");
  const timeframeHint = document.getElementById("f_timeframe_hint");
  if (isDipBounce || isDipBounceDaily || isMeanDip || isSlopeDip) {
    timeframeSelect.value = isDipBounceDaily ? "1d" : (isMeanDip ? "5m" : (isSlopeDip ? "1m" : (type === "dip_bounce_hourly" ? "1h" : "1m")));
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
  } else if (isDipBounce || isDipBounceDaily || isSlopeDip) {
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

  // 2026-09-16 : constat empirique en testant "Creux vs moyenne" sur
  // plusieurs periodes - avec 1 seule position autorisee (defaut generique),
  // la position ouverte bloque toute nouvelle entree jusqu'a son stop-loss,
  // ce qui revient a n'ouvrir qu'un seul trade par semaine environ (la
  // strategie devient quasi inactive). Suggestion de 10 uniquement si le
  // champ est encore a sa valeur par defaut (jamais touche par l'utilisateur).
  const maxConcurrentInput = document.getElementById("f_max_concurrent_positions");
  if (isMeanDip && maxConcurrentInput.value === "1") {
    maxConcurrentInput.value = "10";
  }

  // Suggestion demandee explicitement par l'utilisateur ("on vend sur le
  // trailing a 5%") - pre-remplie uniquement si le champ est encore vide
  // (jamais touche), jamais ecrasee si l'utilisateur a deja saisi une valeur.
  const trailingInput = document.getElementById("f_trailing_stop_pct");
  if (isSlopeDip && !trailingInput.value) {
    trailingInput.value = "5";
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

// --- Onglet Manuel : panier de trading manuel en paper (EF-81) ----------------
//
// Le formulaire d'ordre n'est construit qu'UNE fois (garde sur son id) : le
// rafraichissement automatique toutes les 15 s ne doit jamais effacer un
// montant en cours de saisie. Seuls les blocs de chiffres (resume,
// positions, historique) sont redessines.
let manualSide = "buy";
let manualBookCache = null;
let manualPriceTimer = null;

async function renderManualTab() {
  const contentEl = document.getElementById("content");
  if (!document.getElementById("manual-root")) {
    contentEl.innerHTML = `<div id="manual-root">
      <h1>Trading manuel</h1>
      <p class="muted">Un panier <strong>a part</strong> : son capital est celui que tu y verses, il ne touche pas
      au panier commun des bots. Les ordres partent <strong>reellement</strong> sur le testnet Binance
      (argent fictif, prix reels), avec les memes arrondis et limites de paire que les bots.</p>
      <div id="manual-summary"></div>
      <div class="manual-layout">
        <div class="order-panel" id="manual-order-panel">${renderManualOrderForm()}</div>
        <div>
          <div id="manual-positions"></div>
          <div id="manual-orders"></div>
        </div>
      </div>
    </div>`;
    refreshManualPrice();
  }
  await refreshManualBook();
}

async function refreshManualBook() {
  try {
    const resp = await fetch(`${CONTROL_SERVER}/api/manual-book`);
    manualBookCache = await resp.json();
  } catch (e) {
    document.getElementById("manual-summary").innerHTML = investServerDownHtml();
    return;
  }
  renderManualSummary(manualBookCache);
  renderManualPositions(manualBookCache);
  renderManualOrders(manualBookCache);
}

function renderManualSummary(b) {
  const el = document.getElementById("manual-summary");
  if (!el) return;
  const pnlColor = b.pnl >= 0 ? "var(--green)" : "var(--red)";
  const pct = b.pnl_pct === null || b.pnl_pct === undefined ? "" : ` (${b.pnl_pct >= 0 ? "+" : ""}${b.pnl_pct.toFixed(2)} %)`;
  el.innerHTML = `<div class="section-block">
    <div class="grid">
      <div><div class="stat-label">Verse dans le panier</div><div class="stat-value">${b.deposited.toFixed(2)}</div></div>
      <div><div class="stat-label">Cash disponible</div><div class="stat-value">${b.cash.toFixed(2)}</div></div>
      <div><div class="stat-label">Investi (valeur)</div><div class="stat-value">${b.invested.toFixed(2)}</div></div>
      <div><div class="stat-label">Valeur totale</div><div class="stat-value">${b.value.toFixed(2)}</div></div>
      <div><div class="stat-label">Gain / perte</div><div class="stat-value" style="color:${pnlColor};">${b.pnl >= 0 ? "+" : ""}${b.pnl.toFixed(2)}${pct}</div></div>
      <div><div class="stat-label">Frais payes</div><div class="stat-value">${b.fees.toFixed(2)}</div></div>
    </div>
    <div class="invest-toolbar" style="margin-top:14px;">
      <span class="tb-label">Verser (USDT fictifs)</span>
      <input id="manual-deposit-amount" type="number" min="1" step="50" value="500" style="width:110px; padding:7px 9px;">
      <button class="primary" onclick="manualDeposit()">Verser</button>
      <span class="tb-sep"></span>
      <button onclick="manualReset()" style="border-color:var(--red); color:var(--red);">Remettre le panier a zero</button>
    </div>
    <div id="manual-msg" class="manual-msg"></div>
  </div>`;
}

function renderManualOrderForm() {
  const options = TOP10_SYMBOLS.map(s => `<option value="${s}">${s}</option>`).join("");
  return `
    <div class="side-toggle">
      <button id="manual-side-buy" class="active-buy" onclick="setManualSide('buy')">Acheter</button>
      <button id="manual-side-sell" onclick="setManualSide('sell')">Vendre</button>
    </div>
    <label>Paire
      <select id="manual-symbol" onchange="refreshManualPrice()">${options}</select>
    </label>
    <div class="live-price"><span class="px" id="manual-price">-</span><span class="sym" id="manual-price-sym">USDT</span></div>
    <label id="manual-amount-label">Montant a acheter (USDT)
      <input id="manual-amount" type="number" min="0" step="10" value="50" oninput="updateManualEstimate()">
    </label>
    <div class="quick-row" id="manual-quick">
      <button onclick="manualQuick(0.25)">25 %</button><button onclick="manualQuick(0.5)">50 %</button>
      <button onclick="manualQuick(0.75)">75 %</button><button onclick="manualQuick(1)">Tout</button>
    </div>
    <div class="order-estimate" id="manual-estimate"></div>
    <button id="manual-submit" class="submit-buy" onclick="submitManualOrder()">Acheter au marche</button>
    <p class="muted" style="font-size:11px; margin:0;">Ordre au marche sur le testnet. Frais 0,1 % comptes dans le panier.
    Le prix affiche est le dernier cours public ; l'execution reelle peut differer legerement.</p>`;
}

function setManualSide(side) {
  manualSide = side;
  const buy = side === "buy";
  document.getElementById("manual-side-buy").className = buy ? "active-buy" : "";
  document.getElementById("manual-side-sell").className = buy ? "" : "active-sell";
  document.getElementById("manual-amount-label").firstChild.textContent = buy ? "Montant a acheter (USDT)" : "Quantite a vendre";
  const input = document.getElementById("manual-amount");
  input.step = buy ? "10" : "any";
  const submit = document.getElementById("manual-submit");
  submit.className = buy ? "submit-buy" : "submit-sell";
  submit.textContent = buy ? "Acheter au marche" : "Vendre au marche";
  updateManualEstimate();
}

function manualHeld(symbol) {
  const line = ((manualBookCache || {}).positions || []).find(p => p.symbol === symbol);
  return line ? line.quantity : 0;
}

function manualQuick(fraction) {
  const symbol = document.getElementById("manual-symbol").value;
  const input = document.getElementById("manual-amount");
  if (manualSide === "buy") {
    const cash = (manualBookCache || {}).cash || 0;
    // Le frais de 0,1 % est retenu pour que "Tout" passe reellement.
    input.value = (Math.floor(cash * fraction / 1.001 * 100) / 100).toFixed(2);
  } else {
    input.value = String(manualHeld(symbol) * fraction);
  }
  updateManualEstimate();
}

async function refreshManualPrice() {
  const symbol = document.getElementById("manual-symbol").value;
  document.getElementById("manual-price-sym").textContent = symbol.split("/")[1];
  try {
    const resp = await fetch(`${CONTROL_SERVER}/api/manual-price?symbol=${encodeURIComponent(symbol)}`);
    const data = await resp.json();
    document.getElementById("manual-price").textContent = data.error ? "-" : Number(data.price).toLocaleString("fr-FR", { maximumFractionDigits: 6 });
    document.getElementById("manual-price").dataset.value = data.error ? "" : data.price;
  } catch (e) {
    document.getElementById("manual-price").textContent = "-";
  }
  updateManualEstimate();
  clearTimeout(manualPriceTimer);
  manualPriceTimer = setTimeout(refreshManualPrice, 10000);
}

function updateManualEstimate() {
  const el = document.getElementById("manual-estimate");
  if (!el) return;
  const price = parseFloat(document.getElementById("manual-price").dataset.value || "0");
  const raw = parseFloat(document.getElementById("manual-amount").value || "0");
  const symbol = document.getElementById("manual-symbol").value;
  if (!price || !raw) { el.textContent = ""; return; }
  if (manualSide === "buy") {
    el.textContent = `~ ${(raw / price).toFixed(6)} ${symbol.split("/")[0]} + ${(raw * 0.001).toFixed(2)} USDT de frais`;
  } else {
    el.textContent = `~ ${(raw * price).toFixed(2)} USDT (detenu : ${manualHeld(symbol)})`;
  }
}

async function submitManualOrder() {
  const symbol = document.getElementById("manual-symbol").value;
  const raw = parseFloat(document.getElementById("manual-amount").value || "0");
  const msg = document.getElementById("manual-msg");
  if (!raw || raw <= 0) { msg.innerHTML = '<span style="color:var(--red);">Montant ou quantite manquant.</span>'; return; }
  const what = manualSide === "buy" ? `acheter pour ${raw} USDT de ${symbol}` : `vendre ${raw} ${symbol.split("/")[0]}`;
  if (!confirm(`Passer REELLEMENT un ordre au marche pour ${what} sur le testnet Binance ?\\n\\nArgent fictif, mais l'ordre est bien envoye a l'exchange.`)) return;
  msg.innerHTML = '<span class="muted">Ordre en cours...</span>';
  document.getElementById("manual-submit").disabled = true;
  try {
    const body = manualSide === "buy" ? { symbol, side: "buy", amount: raw } : { symbol, side: "sell", quantity: raw };
    const resp = await fetch(`${CONTROL_SERVER}/api/manual-order`, {
      method: "POST", headers: { "Content-Type": "application/json" }, body: JSON.stringify(body),
    });
    const d = await resp.json();
    if (d.error) {
      msg.innerHTML = `<span style="color:var(--red);">${d.error}</span>`;
    } else if (d.status === "filled") {
      msg.innerHTML = `<span style="color:var(--green);">Execute : ${d.side === "buy" ? "achat" : "vente"} de ${d.quantity} ${symbol.split("/")[0]} a ${d.price} (frais ${d.fee.toFixed(2)})</span>`
        + (d.warnings.length ? `<br><span class="muted">${d.warnings.join(" - ")}</span>` : "");
    } else {
      msg.innerHTML = `<span style="color:var(--amber);">Non execute : ${d.reason}</span>`;
    }
  } catch (e) {
    msg.innerHTML = `<span style="color:var(--red);">Serveur de controle injoignable : ${e}</span>`;
  } finally {
    document.getElementById("manual-submit").disabled = false;
  }
  await refreshManualBook();
  updateManualEstimate();
}

async function manualSellAll(symbol) {
  if (!confirm(`Vendre TOUTE la position ${symbol} au marche sur le testnet ?`)) return;
  const msg = document.getElementById("manual-msg");
  msg.innerHTML = '<span class="muted">Vente en cours...</span>';
  try {
    const resp = await fetch(`${CONTROL_SERVER}/api/manual-order`, {
      method: "POST", headers: { "Content-Type": "application/json" },
      body: JSON.stringify({ symbol, side: "sell", quantity: "all" }),
    });
    const d = await resp.json();
    msg.innerHTML = d.error ? `<span style="color:var(--red);">${d.error}</span>`
      : d.status === "filled" ? `<span style="color:var(--green);">Vendu ${d.quantity} ${symbol.split("/")[0]} a ${d.price}</span>`
      : `<span style="color:var(--amber);">Non execute : ${d.reason}</span>`;
  } catch (e) {
    msg.innerHTML = `<span style="color:var(--red);">Serveur de controle injoignable : ${e}</span>`;
  }
  await refreshManualBook();
}

async function manualDeposit() {
  const amount = parseFloat(document.getElementById("manual-deposit-amount").value || "0");
  const msg = document.getElementById("manual-msg");
  try {
    const resp = await fetch(`${CONTROL_SERVER}/api/manual-deposit`, {
      method: "POST", headers: { "Content-Type": "application/json" }, body: JSON.stringify({ amount }),
    });
    const d = await resp.json();
    msg.innerHTML = d.error ? `<span style="color:var(--red);">${d.error}</span>` : `<span class="muted">Verse. Cash : ${d.cash.toFixed(2)} USDT.</span>`;
  } catch (e) {
    msg.innerHTML = `<span style="color:var(--red);">Serveur de controle injoignable : ${e}</span>`;
  }
  await refreshManualBook();
}

async function manualReset() {
  if (!confirm("Remettre le panier manuel a zero ?\\n\\nL'historique est sauvegarde dans un fichier .bak.\\nATTENTION : cela ne vend rien sur le testnet - vends d'abord si tu veux repartir sans position.")) return;
  const msg = document.getElementById("manual-msg");
  try {
    const resp = await fetch(`${CONTROL_SERVER}/api/manual-reset`, {
      method: "POST", headers: { "Content-Type": "application/json" }, body: "{}",
    });
    const d = await resp.json();
    msg.innerHTML = `<span class="muted">${d.message || d.error}</span>`;
  } catch (e) {
    msg.innerHTML = `<span style="color:var(--red);">Serveur de controle injoignable : ${e}</span>`;
  }
  await refreshManualBook();
}

function renderManualPositions(b) {
  const el = document.getElementById("manual-positions");
  if (!el) return;
  if (!b.positions.length) {
    el.innerHTML = `<div class="section-block"><div class="section-header"><h2>Positions</h2></div>
      <p class="muted">Aucune position. Verse du capital, choisis une paire et achete.</p></div>`;
    return;
  }
  const rows = b.positions.map(p => {
    const c = (p.pnl || 0) >= 0 ? "var(--green)" : "var(--red)";
    return `<tr>
      <td><strong>${p.symbol}</strong></td>
      <td style="text-align:right;">${p.quantity}</td>
      <td style="text-align:right;">${p.avg_price.toFixed(4)}</td>
      <td style="text-align:right;">${p.price ? p.price.toFixed(4) : "-"}</td>
      <td style="text-align:right;">${p.value ? p.value.toFixed(2) : "-"}</td>
      <td style="text-align:right; color:${c};">${p.pnl === null ? "-" : `${p.pnl >= 0 ? "+" : ""}${p.pnl.toFixed(2)} (${p.pnl_pct >= 0 ? "+" : ""}${p.pnl_pct.toFixed(2)} %)`}</td>
      <td><button onclick="manualSellAll('${p.symbol}')" style="background:var(--red); color:#fff; font-size:11.5px; padding:5px 9px;">Tout vendre</button></td>
    </tr>`;
  }).join("");
  el.innerHTML = `<div class="section-block"><div class="section-header"><h2>Positions</h2></div>
    <table class="bi"><thead><tr><th>Paire</th><th style="text-align:right;">Quantite</th><th style="text-align:right;">Prix de revient</th>
    <th style="text-align:right;">Cours</th><th style="text-align:right;">Valeur</th><th style="text-align:right;">Gain / perte</th><th></th></tr></thead>
    <tbody>${rows}</tbody></table>
    <p class="muted" style="font-size:11.5px;">Prix de revient frais inclus. Cours public rafraichi a chaque passage.</p></div>`;
}

function renderManualOrders(b) {
  const el = document.getElementById("manual-orders");
  if (!el) return;
  if (!b.orders.length) { el.innerHTML = ""; return; }
  const rows = b.orders.map(o => `<tr>
    <td class="muted">${o.ts.replace("T", " ").replace("+00:00", " UTC")}</td>
    <td><strong>${o.symbol}</strong></td>
    <td style="color:${o.side === "buy" ? "var(--green)" : "var(--red)"};">${o.side === "buy" ? "achat" : "vente"}</td>
    <td style="text-align:right;">${o.quantity}</td>
    <td style="text-align:right;">${o.price ? o.price.toFixed(4) : "-"}</td>
    <td style="text-align:right;">${o.fee.toFixed(2)}</td>
    <td>${o.status === "filled" ? '<span style="color:var(--green);">execute</span>' : `<span style="color:var(--amber);" title="${o.reason || ""}">${o.status}</span>`}</td>
  </tr>`).join("");
  el.innerHTML = `<div class="section-block"><div class="section-header"><h2>Historique des ordres</h2></div>
    <table class="bi"><thead><tr><th>Quand</th><th>Paire</th><th>Cote</th><th style="text-align:right;">Quantite</th>
    <th style="text-align:right;">Prix</th><th style="text-align:right;">Frais</th><th>Statut</th></tr></thead><tbody>${rows}</tbody></table></div>`;
}

function renderInvestContent() {
  if (currentInvestSubTab === "reglages") {
    renderInvestSettingsTab();
  } else {
    renderInvestTrackingTab();
  }
}

async function fetchInvestBots() {
  try {
    const resp = await fetch(`${CONTROL_SERVER}/api/dca-bots`);
    const data = await resp.json();
    investBotsCache = data.bots || [];
  } catch (e) {
    investBotsCache = null; // serveur injoignable
  }
  return investBotsCache;
}

function investServerDownHtml() {
  return `<div class="section-block"><p class="muted">Serveur de controle injoignable.
    Lance <code>python -m tradingbot.control_server</code> puis recharge cette page.</p></div>`;
}

// --- Investissement : visualisation des lignes (EF-78) -----------------------
//
// Palette CATEGORIELLE de 6 teintes, validee sur les cinq controles du skill
// dataviz en mode sombre (bande de luminosite, chroma, separation en vision
// des couleurs deficiente, plancher vision normale, contraste sur le fond).
// Un premier jeu choisi a l'oeil avait ECHOUE : rose et turquoise se
// confondent en deuteranopie (delta E 3,0). Ne pas remplacer ces valeurs sans
// repasser le validateur.
//
// Le vert et le rouge du theme sont volontairement ABSENTS : ils portent le
// sens gain/perte dans cette interface et ne doivent pas designer aussi une
// ligne du panier.
const INVEST_SERIES_COLORS = ["#3987e5", "#d95926", "#199e70", "#c98500", "#d55181", "#008300"];

// La couleur suit la LIGNE, jamais son rang a l'affichage : trier ou masquer
// une ligne ne doit pas repeindre les autres.
function investColorFor(bot, symbol) {
  const symbols = Object.keys(bot.config.weights).sort();
  const i = symbols.indexOf(symbol);
  return INVEST_SERIES_COLORS[(i < 0 ? 0 : i) % INVEST_SERIES_COLORS.length];
}

const INVEST_RANGES = [
  { id: 30, label: "1M" }, { id: 90, label: "3M" }, { id: 180, label: "6M" },
  { id: 365, label: "1 an" }, { id: 1825, label: "5 ans" },
];
let investRangeDays = {};      // nom du bot -> nombre de jours affiches
let investHistoryCache = {};   // "nom|jours" -> reponse du serveur
let investHistoryLoading = {};

function investRangeFor(name) {
  return investRangeDays[name] || 180;
}

async function fetchInvestHistory(name, days) {
  const key = name + "|" + days;
  if (investHistoryCache[key]) return investHistoryCache[key];
  if (investHistoryLoading[key]) return null;
  investHistoryLoading[key] = true;
  try {
    const resp = await fetch(`${CONTROL_SERVER}/api/dca-price-history?name=${encodeURIComponent(name)}&days=${days}`);
    const data = await resp.json();
    if (!data.error) investHistoryCache[key] = data;
  } catch (e) {
    // Silencieux : le graphique affiche simplement son etat "indisponible".
  } finally {
    investHistoryLoading[key] = false;
  }
  return investHistoryCache[key] || null;
}

function selectInvestRange(name, days) {
  investRangeDays[name] = days;
  renderInvestTrackingTab();
}

function investRangeSelector(name) {
  const active = investRangeFor(name);
  const buttons = INVEST_RANGES.map(r =>
    `<button class="range-btn ${r.id === active ? "active" : ""}" onclick="selectInvestRange('${name}',${r.id})">${r.label}</button>`
  ).join("");
  return `<div class="range-selector">${buttons}</div>`;
}

function niceStep(raw) {
  const mag = Math.pow(10, Math.floor(Math.log10(Math.max(raw, 1e-9))));
  const n = raw / mag;
  return (n <= 1 ? 1 : n <= 2 ? 2 : n <= 5 ? 5 : 10) * mag;
}

// Graphique COMPARATIF : toutes les lignes ramenees a 0 % a leur premier
// point. Comparer des cours bruts de 7 EUR et 400 EUR sur le meme axe
// n'apprendrait rien ; ramenes en pourcentage d'evolution, ils partagent un
// axe UNIQUE et se comparent reellement (jamais deux echelles superposees).
function investComparisonSvg(bot, history) {
  const W = 760, H = 260, padL = 46, padR = 14, padT = 14, padB = 26;
  const symbols = Object.keys(bot.config.weights).sort()
    .filter(s => (history.series[s] || {}).points && history.series[s].points.length > 1);
  if (symbols.length === 0) {
    return '<p class="muted">Aucun historique de cours disponible pour cette periode.</p>';
  }

  const normalised = {};
  let lo = Infinity, hi = -Infinity;
  symbols.forEach(s => {
    const pts = history.series[s].points;
    const base = pts[0].close;
    const vals = pts.map(pt => ({ t: pt.t, v: base ? (pt.close / base - 1) * 100 : 0 }));
    normalised[s] = vals;
    vals.forEach(o => { if (o.v < lo) lo = o.v; if (o.v > hi) hi = o.v; });
  });
  if (lo === hi) { lo -= 1; hi += 1; }
  const margin = (hi - lo) * 0.08;
  lo -= margin; hi += margin;

  const tMin = Math.min.apply(null, symbols.map(s => normalised[s][0].t));
  const tMax = Math.max.apply(null, symbols.map(s => normalised[s][normalised[s].length - 1].t));
  const x = t => padL + (tMax === tMin ? 0 : (t - tMin) / (tMax - tMin)) * (W - padL - padR);
  const y = v => padT + (1 - (v - lo) / (hi - lo)) * (H - padT - padB);

  // Graduations rondes, chacune nommant une valeur que le graphique atteint.
  const step = niceStep((hi - lo) / 4);
  const ticks = [];
  for (let v = Math.ceil(lo / step) * step; v <= hi; v += step) ticks.push(v);

  const grid = ticks.map(v => {
    const isZero = Math.abs(v) < step / 100;
    return `<line x1="${padL}" y1="${y(v).toFixed(1)}" x2="${W - padR}" y2="${y(v).toFixed(1)}"
      stroke="${isZero ? "var(--border-strong)" : "var(--border)"}" stroke-width="1" />
      <text x="${padL - 7}" y="${(y(v) + 3.5).toFixed(1)}" text-anchor="end" font-size="10"
        fill="var(--text-faint)">${v >= 0 ? "+" : ""}${Math.round(v)}%</text>`;
  }).join("");

  const lines = symbols.map(s => {
    const color = investColorFor(bot, s);
    const coords = normalised[s].map(o => `${x(o.t).toFixed(1)},${y(o.v).toFixed(1)}`).join(" ");
    const last = normalised[s][normalised[s].length - 1];
    return `<polyline points="${coords}" fill="none" stroke="${color}" stroke-width="2"
        stroke-linejoin="round" stroke-linecap="round"><title>${s} : ${last.v >= 0 ? "+" : ""}${last.v.toFixed(1)} % sur la periode</title></polyline>`;
  }).join("");

  const firstDay = new Date(tMin).toISOString().slice(0, 10);
  const lastDay = new Date(tMax).toISOString().slice(0, 10);

  const legend = symbols.map(s => {
    const last = normalised[s][normalised[s].length - 1].v;
    return `<span class="li"><span class="sw" style="background:${investColorFor(bot, s)};"></span>
      <strong>${s}</strong> <span class="val">${last >= 0 ? "+" : ""}${last.toFixed(1)} %</span></span>`;
  }).join("");

  return `<svg viewBox="0 0 ${W} ${H}" width="100%" height="${H}" role="img"
      aria-label="Evolution comparee des lignes du panier, en pourcentage depuis le debut de la periode"
      style="background:var(--surface); border:1px solid var(--border); border-radius:var(--radius-md);">
      ${grid}${lines}
      <text x="${padL}" y="${H - 8}" font-size="10" fill="var(--text-faint)">${firstDay}</text>
      <text x="${W - padR}" y="${H - 8}" font-size="10" fill="var(--text-faint)" text-anchor="end">${lastDay}</text>
    </svg>
    <div class="chart-legend">${legend}</div>
    <p class="muted" style="font-size:11.5px; margin-top:8px;">Chaque ligne part de 0 % au debut de la periode :
      c'est la seule facon de comparer sur un axe unique des cours qui vont de 7 EUR a 400 EUR.
      Survole une courbe pour son nom.</p>`;
}

// Courbe miniature d'une ligne, avec son PRIX DE REVIENT en trait tire : un
// cours de 79 EUR ne dit rien tant qu'on ne sait pas qu'on a paye 82.
function investSparkSvg(points, costBasis, color) {
  const W = 240, H = 54;
  if (!points || points.length < 2) {
    return `<div class="muted" style="font-size:11px; height:${H}px; display:flex; align-items:center;">Pas d'historique</div>`;
  }
  const closes = points.map(pt => pt.close);
  let lo = Math.min.apply(null, closes), hi = Math.max.apply(null, closes);
  if (costBasis) { lo = Math.min(lo, costBasis); hi = Math.max(hi, costBasis); }
  if (lo === hi) { lo -= 1; hi += 1; }
  const span = (hi - lo) * 1.1, mid = (hi + lo) / 2;
  lo = mid - span / 2; hi = mid + span / 2;
  const x = i => (i / (points.length - 1)) * W;
  const y = v => H - ((v - lo) / (hi - lo)) * H;

  const coords = points.map((pt, i) => `${x(i).toFixed(1)},${y(pt.close).toFixed(1)}`).join(" ");
  const area = `${x(0).toFixed(1)},${H} ${coords} ${x(points.length - 1).toFixed(1)},${H}`;
  const basisLine = costBasis
    ? `<line x1="0" y1="${y(costBasis).toFixed(1)}" x2="${W}" y2="${y(costBasis).toFixed(1)}"
        stroke="var(--text-dim)" stroke-width="1" stroke-dasharray="3 3" vector-effect="non-scaling-stroke"><title>Prix de revient ${costBasis.toFixed(2)}</title></line>`
    : "";
  const lastY = y(closes[closes.length - 1]);

  return `<svg viewBox="0 0 ${W} ${H}" width="100%" height="${H}" preserveAspectRatio="none"
      role="img" aria-label="Evolution du cours sur la periode">
      <polygon points="${area}" fill="${color}" opacity="0.13" />
      ${basisLine}
      <polyline points="${coords}" fill="none" stroke="${color}" stroke-width="1.8"
        stroke-linejoin="round" stroke-linecap="round" vector-effect="non-scaling-stroke" />
      <circle cx="${(W - 3).toFixed(1)}" cy="${lastY.toFixed(1)}" r="2.6" fill="${color}" />
    </svg>`;
}

function renderPositionCard(bot, line, history) {
  const color = investColorFor(bot, line.symbol);
  const serie = (history && history.series[line.symbol]) || {};
  const basis = (history && history.cost_basis[line.symbol]) || null;
  const costPrice = basis ? basis.avg_price : null;
  const held = line.quantity > 0;
  // Avant le premier passage du bot, sa base n'a aucun prix : on retombe sur
  // la derniere cloture du graphique, pour que la carte affiche un cours des
  // la creation du panier plutot qu'un tiret.
  const pts = serie.points || [];
  const price = line.price || (pts.length ? pts[pts.length - 1].close : null);
  const lineValue = line.value || (price && held ? price * line.quantity : 0);

  // Gain latent calcule sur le PRIX DE REVIENT reel (frais inclus), pas sur
  // le prix planifie : c'est ce que la ligne a effectivement coute.
  let gainHtml = '<span class="chg muted">-</span>';
  if (held && costPrice && price) {
    const pct = (price / costPrice - 1) * 100;
    const euros = (price - costPrice) * line.quantity;
    const c = pct >= 0 ? "var(--green)" : "var(--red)";
    gainHtml = `<span class="chg" style="color:${c};">${pct >= 0 ? "+" : ""}${pct.toFixed(2)} %
      <span style="opacity:0.75; font-weight:500;">(${euros >= 0 ? "+" : ""}${euros.toFixed(2)} EUR)</span></span>`;
  }

  const drift = line.actual_pct - line.target_pct;
  const band = bot.config.rebalance_band_pct || 5;
  const driftColor = Math.abs(drift) > band ? "var(--amber)" : "var(--text-faint)";
  const allocPct = Math.max(0, Math.min(100, line.actual_pct));

  return `<div class="pos-card ${held ? "" : "empty"}">
    <div class="pos-head">
      <span class="pos-dot" style="background:${color};"></span>
      <span class="pos-sym">${line.symbol}</span>
      <span class="pos-qty">${held ? line.quantity.toFixed(0) + " titre(s)" : "aucun titre"}</span>
    </div>
    <div class="pos-price">
      <span class="now">${price ? price.toFixed(2) : "-"}</span>
      ${gainHtml}
    </div>
    ${investSparkSvg(serie.points, costPrice, color)}
    <dl class="pos-rows">
      <dt>Prix de revient</dt><dd>${costPrice ? costPrice.toFixed(2) + " EUR" : "-"}</dd>
      <dt>Valeur de la ligne</dt><dd>${lineValue ? lineValue.toFixed(2) + " EUR" : "-"}</dd>
    </dl>
    <div class="alloc">
      <div class="alloc-track">
        <div class="alloc-fill" style="width:${allocPct.toFixed(1)}%; background:${color};"></div>
        <div class="alloc-target" style="left:calc(${Math.min(100, line.target_pct).toFixed(1)}% - 1px);"
          title="Cible ${line.target_pct.toFixed(1)} %"></div>
      </div>
      <div class="alloc-legend">
        <span>reel ${line.actual_pct.toFixed(1)} %</span>
        <span style="color:${driftColor};">${drift >= 0 ? "+" : ""}${drift.toFixed(1)} pts vs cible ${line.target_pct.toFixed(1)} %</span>
      </div>
    </div>
    <div class="pos-actions">
      <button ${held ? "" : "disabled"} onclick="sellInvestLine('${bot.name}','${line.symbol}','half')">Vendre la moitie</button>
      <button ${held ? "" : "disabled"} style="${held ? "background:var(--red); color:#fff;" : ""}"
        onclick="sellInvestLine('${bot.name}','${line.symbol}','all')">Tout vendre</button>
    </div>
  </div>`;
}

function renderInvestToolbar(bot) {
  const monthly = bot.config.monthly_contribution;
  return `<div class="invest-toolbar">
    <span class="tb-label">Plafond mensuel</span>
    <button class="step-btn" onclick="stepInvestContribution('${bot.name}',-50)" title="Diminuer de 50 EUR">&minus;</button>
    <span class="tb-value">${monthly.toFixed(0)} EUR</span>
    <button class="step-btn" onclick="stepInvestContribution('${bot.name}',50)" title="Augmenter de 50 EUR">+</button>
    <button onclick="promptInvestContribution('${bot.name}')">Montant exact...</button>
    <span class="tb-sep"></span>
    <button onclick="resetInvestBasket('${bot.name}')" style="border-color:var(--red); color:var(--red);">Remettre le panier a zero</button>
  </div>
  <p class="muted" style="font-size:11.5px; margin-top:6px;">Le plafond s'applique au prochain versement.
    Un ordre coute <strong>3 EUR minimum</strong> chez le courtier : sur un versement reparti sur plusieurs
    lignes, les frais montent vite. Verser plus, moins souvent, les dilue.</p>`;
}

async function sellInvestLine(name, symbol, mode) {
  const bot = (investBotsCache || []).find(b => b.name === name);
  const line = bot ? bot.lines.find(l => l.symbol === symbol) : null;
  if (!line || line.quantity <= 0) return;
  const quantity = mode === "half" ? Math.floor(line.quantity / 2) : Math.floor(line.quantity);
  if (quantity < 1) {
    alert(symbol + " : une seule action detenue, vendre la moitie est impossible. Utilise \\"Tout vendre\\".");
    return;
  }
  const ok = confirm(
    "Vendre REELLEMENT " + quantity + " " + symbol + " sur le compte paper ?\\n\\n" +
    "Argent fictif, mais l'ordre part vraiment chez Interactive Brokers et sera enregistre.\\n" +
    "Hors des heures d'ouverture de la place, l'ordre sera refuse.\\n\\n" +
    "Vendre ne rend PAS le versement du mois a nouveau disponible."
  );
  if (!ok) return;

  const target = document.getElementById("dca_report_" + name);
  if (target) target.innerHTML = '<p class="muted">Vente en cours...</p>';
  const lines = {};
  lines[symbol] = quantity;
  try {
    const resp = await fetch(`${CONTROL_SERVER}/api/dca-sell`, {
      method: "POST", headers: { "Content-Type": "application/json" },
      body: JSON.stringify({ name, lines }),
    });
    const data = await resp.json();
    if (target) {
      target.innerHTML = data.error
        ? `<p style="color:var(--red);">${data.error}</p>`
        : `<pre class="dca-pre">${data.report}</pre>`;
    }
    if (!data.error) renderInvestTrackingTab();
  } catch (e) {
    if (target) target.innerHTML = `<p style="color:var(--red);">Serveur de controle injoignable : ${e}</p>`;
  }
}

async function resetInvestBasket(name) {
  const ok = confirm(
    'Remettre a zero le registre du bot "' + name + '" ?\\n\\n' +
    "Efface ses positions, ses ordres et ses versements enregistres - le versement du mois redevient disponible.\\n" +
    "L'historique est SAUVEGARDE dans un fichier .bak, rien n'est perdu definitivement.\\n\\n" +
    "ATTENTION : cela ne VEND RIEN. Les titres restent chez le courtier, et le bot refusera de passer\\n" +
    "des ordres tant que l'ecart de positions n'est pas resorbe. Vends d'abord."
  );
  if (!ok) return;
  const target = document.getElementById("dca_report_" + name);
  try {
    const resp = await fetch(`${CONTROL_SERVER}/api/dca-reset`, {
      method: "POST", headers: { "Content-Type": "application/json" },
      body: JSON.stringify({ name }),
    });
    const data = await resp.json();
    if (target) {
      target.innerHTML = data.error
        ? `<p style="color:var(--red);">${data.error}</p>`
        : `<p class="muted">${data.message}</p>`;
    }
    if (!data.error) { investHistoryCache = {}; renderInvestTrackingTab(); }
  } catch (e) {
    if (target) target.innerHTML = `<p style="color:var(--red);">Serveur de controle injoignable : ${e}</p>`;
  }
}

function stepInvestContribution(name, delta) {
  const bot = (investBotsCache || []).find(b => b.name === name);
  if (!bot) return;
  const next = bot.config.monthly_contribution + delta;
  if (next < 50) {
    alert("En dessous de 50 EUR par mois, les 3 EUR de frais par ordre depassent 6 % du versement.\\n" +
          "Passe par \\"Montant exact...\\" si tu veux quand meme descendre plus bas.");
    return;
  }
  applyInvestContribution(name, next);
}

function promptInvestContribution(name) {
  const bot = (investBotsCache || []).find(b => b.name === name);
  if (!bot) return;
  const raw = prompt("Versement mensuel, en euros :", bot.config.monthly_contribution.toFixed(0));
  if (raw === null) return;
  const value = parseFloat(String(raw).replace(",", "."));
  if (!isFinite(value) || value <= 0) { alert("Montant invalide."); return; }
  applyInvestContribution(name, value);
}

async function applyInvestContribution(name, amount) {
  const target = document.getElementById("dca_report_" + name);
  try {
    const resp = await fetch(`${CONTROL_SERVER}/api/dca-contribution`, {
      method: "POST", headers: { "Content-Type": "application/json" },
      body: JSON.stringify({ name, monthly_contribution: amount }),
    });
    const data = await resp.json();
    if (data.error) {
      if (target) target.innerHTML = `<p style="color:var(--red);">${data.error}</p>`;
      return;
    }
    investBotsCache = [];           // la config a change : on la rechargera
    renderInvestTrackingTab();
  } catch (e) {
    if (target) target.innerHTML = `<p style="color:var(--red);">Serveur de controle injoignable : ${e}</p>`;
  }
}

function renderInvestLinesTable(bot) {
  const rows = bot.lines.map(line => {
    const drift = line.actual_pct - line.target_pct;
    const driftColor = Math.abs(drift) > (bot.config.rebalance_band_pct || 5) ? "var(--red)" : "var(--muted)";
    return `<tr>
      <td><strong>${line.symbol}</strong></td>
      <td style="text-align:right;">${line.quantity ? line.quantity.toFixed(0) : "-"}</td>
      <td style="text-align:right;">${line.price ? line.price.toFixed(2) : "-"}</td>
      <td style="text-align:right;">${line.value ? line.value.toFixed(2) : "-"}</td>
      <td style="text-align:right;">${line.actual_pct.toFixed(1)} %</td>
      <td style="text-align:right;" class="muted">${line.target_pct.toFixed(1)} %</td>
      <td style="text-align:right; color:${driftColor};">${drift >= 0 ? "+" : ""}${drift.toFixed(1)} pts</td>
    </tr>`;
  }).join("");
  return `<table class="bi">
    <thead><tr>
      <th>Ligne</th><th style="text-align:right;">Titres</th><th style="text-align:right;">Cours</th>
      <th style="text-align:right;">Valeur</th><th style="text-align:right;">Reel</th>
      <th style="text-align:right;">Cible</th><th style="text-align:right;">Ecart</th>
    </tr></thead><tbody>${rows}</tbody></table>`;
}

function renderInvestBotCard(bot, history) {
  const gain = bot.value - bot.total_invested;
  const gainColor = gain >= 0 ? "var(--green)" : "var(--red)";
  const rate = bot.money_weighted_return_pct === null || bot.money_weighted_return_pct === undefined
    ? "-" : `${bot.money_weighted_return_pct >= 0 ? "+" : ""}${bot.money_weighted_return_pct.toFixed(2)} %/an`;

  // Un bot qui n'a jamais tourne n'a ni position ni prix de revient - mais le
  // cours de ses lignes existe deja, et c'est justement ce qu'on veut voir
  // AVANT d'engager le premier versement.
  if (!bot.exists) {
    return `<div class="section-block">
      <h2>${bot.name}</h2>
      <p class="muted">Ce bot n'a encore jamais tourne : aucune position, aucun versement consomme.
      Le graphique ci-dessous montre deja le cours de ses lignes. Utilise &quot;Simuler le passage du jour&quot;
      pour voir ce qu'il acheterait, sans rien engager.</p>
      ${renderInvestToolbar(bot)}
      ${investRangeSelector(bot.name)}
      ${history ? investComparisonSvg(bot, history) : '<p class="muted">Chargement des cours...</p>'}
      <div class="pos-grid">${bot.lines.map(l => renderPositionCard(bot, l, history)).join("")}</div>
      ${renderInvestActions(bot)}
      <div id="dca_report_${bot.name}" class="dca-report"></div>
    </div>`;
  }

  return `<div class="section-block">
    <h2>${bot.name}</h2>
    <div class="grid">
      <div><div class="stat-label">Total verse</div><div class="stat-value">${bot.total_invested.toFixed(2)}</div></div>
      <div><div class="stat-label">Valeur</div><div class="stat-value">${bot.value.toFixed(2)}</div></div>
      <div><div class="stat-label">Gain</div><div class="stat-value" style="color:${gainColor};">${gain >= 0 ? "+" : ""}${gain.toFixed(2)}</div></div>
      <div><div class="stat-label">Rendement / an</div><div class="stat-value">${rate}</div></div>
      <div><div class="stat-label">Baisse max subie</div><div class="stat-value" style="color:var(--red);">-${bot.max_drawdown_pct.toFixed(2)} %</div></div>
      <div><div class="stat-label">Frais payes</div><div class="stat-value">${bot.total_fees.toFixed(2)}</div></div>
    </div>
    <p class="muted" style="margin-top:10px;">
      ${bot.contributions} versement(s) | ${bot.orders} ordre(s) | liquidites en attente : ${bot.cash.toFixed(2)}
      ${bot.last_rebalance_day ? ` | dernier rééquilibrage : ${bot.last_rebalance_day}` : " | aucun rééquilibrage a ce jour"}
    </p>
    <p class="muted">
      Valorisation calculee avec les derniers cours connus${bot.prices_as_of ? ` (${bot.prices_as_of})` : ""},
      pas en direct : ce bot n'agit qu'une fois par mois. Clique sur &quot;Simuler&quot; pour une photo aux cours du jour.
    </p>
    ${renderInvestToolbar(bot)}
    ${investRangeSelector(bot.name)}
    ${history ? investComparisonSvg(bot, history) : '<p class="muted">Chargement des cours...</p>'}
    <div class="pos-grid">${bot.lines.map(l => renderPositionCard(bot, l, history)).join("")}</div>
    <details style="margin-top:16px;">
      <summary class="muted" style="cursor:pointer; font-size:12px;">Tableau detaille des lignes</summary>
      ${renderInvestLinesTable(bot)}
    </details>
    ${renderInvestActions(bot)}
    <div id="dca_report_${bot.name}" class="dca-report"></div>
  </div>`;
}

function renderInvestActions(bot) {
  return `<div style="display:flex; gap:10px; flex-wrap:wrap; margin-top:14px; align-items:center;">
    <button class="primary" onclick="runDcaBot('${bot.name}', false)">Simuler le passage du jour</button>
    <button onclick="runDcaBot('${bot.name}', true)" style="background:var(--red); color:#fff;">Executer reellement (compte paper)</button>
    <span class="muted" style="font-size:12px;">La simulation n'envoie rien et n'enregistre rien.</span>
  </div>`;
}

async function runDcaBot(name, execute) {
  const target = document.getElementById(`dca_report_${name}`);
  if (execute) {
    const ok = confirm(
      `Passer REELLEMENT les ordres du bot "${name}" sur le compte paper Interactive Brokers ?\\n\\n` +
      "Argent fictif, mais le versement du mois sera consomme et enregistre.\\n" +
      "TWS ou IB Gateway doit etre lance et connecte en mode PAPER."
    );
    if (!ok) return;
  }
  target.innerHTML = '<p class="muted">Passage en cours...</p>';
  try {
    const resp = await fetch(`${CONTROL_SERVER}/api/dca-run`, {
      method: "POST",
      headers: { "Content-Type": "application/json" },
      body: JSON.stringify({ name, execute }),
    });
    const data = await resp.json();
    if (data.error) {
      target.innerHTML = `<p style="color:var(--red);">${data.error}</p>`;
      return;
    }
    lastDcaReports[name] = data.report;
    target.innerHTML = `<pre class="dca-pre">${data.report}</pre>`;
    if (execute) renderInvestTrackingTab();
  } catch (e) {
    target.innerHTML = `<p style="color:var(--red);">Serveur de controle injoignable : ${e}</p>`;
  }
}

function reinjectDcaReports() {
  Object.entries(lastDcaReports).forEach(([name, report]) => {
    const target = document.getElementById(`dca_report_${name}`);
    if (target && !target.innerHTML) target.innerHTML = `<pre class="dca-pre">${report}</pre>`;
  });
}

async function renderInvestTrackingTab() {
  const contentEl = document.getElementById("content");
  // Le "Chargement..." ne s'affiche qu'au premier rendu : sur le
  // rafraichissement automatique (15 s), le faire clignoterait a chaque fois.
  if (!document.getElementById("invest-root")) {
    contentEl.innerHTML = '<div id="invest-root"><h1>Investissement regulier</h1><p class="muted">Chargement...</p></div>';
  }
  const bots = await fetchInvestBots();
  if (bots === null) {
    contentEl.innerHTML = '<div id="invest-root"><h1>Investissement regulier</h1>' + investServerDownHtml() + "</div>";
    return;
  }
  const intro = `<h1>Investissement regulier</h1>
    <p class="muted">Ces bots versent une somme fixe chaque mois sur une allocation cible et ne vendent
    jamais sur une baisse (aucun stop-loss, volontairement). Ils ne cherchent pas a predire le marche :
    aucune strategie testee dans ce projet n'a battu un panier diversifie de facon reproductible.
    Argent fictif uniquement (compte paper Interactive Brokers).</p>`;
  // L'historique est charge AVANT de dessiner, et mis en cache par (bot,
  // periode) : le rafraichissement automatique toutes les 15 s ne doit pas
  // rappeler Yahoo Finance a chaque passage.
  const histories = {};
  for (const bot of bots) {
    histories[bot.name] = await fetchInvestHistory(bot.name, investRangeFor(bot.name));
  }
  const body = bots.length === 0
    ? `<div class="section-block"><p class="muted">Aucun bot d'investissement configure. Va dans le sous-onglet
      <strong>Reglages</strong> pour en creer un.</p></div>`
    : bots.map(bot => renderInvestBotCard(bot, histories[bot.name])).join("");
  contentEl.innerHTML = `<div id="invest-root">${intro}${body}</div>`;
  reinjectDcaReports();
}

function renderInvestWeightRows(weights) {
  const entries = Object.entries(weights || {});
  if (entries.length === 0) entries.push(["", 1]);
  return entries.map(([symbol, weight], i) => `
    <div class="dca-weight-row" style="display:flex; gap:8px; margin-bottom:6px; align-items:center;">
      <input type="text" class="dca-symbol" value="${symbol}" placeholder="ex: TTE.PA" style="flex:2;">
      <input type="number" class="dca-weight" value="${weight}" min="0" step="any" placeholder="poids" style="flex:1;">
      <button onclick="this.closest('.dca-weight-row').remove()" title="Retirer cette ligne">✕</button>
    </div>`).join("");
}

async function renderInvestSettingsTab(force) {
  const contentEl = document.getElementById("content");
  // Le rafraichissement automatique (15 s) rappelle cette fonction : sans ce
  // garde il reconstruirait le formulaire et effacerait une allocation en
  // cours de saisie. Meme protection que "supervision-root"/"bt_run_btn"
  // ailleurs dans ce dashboard.
  if (!force && document.getElementById("dca-settings-root")) return;
  contentEl.innerHTML = '<div id="dca-settings-root"><h1>Reglages</h1><p class="muted">Chargement...</p></div>';
  const bots = await fetchInvestBots();
  if (bots === null) {
    contentEl.innerHTML = '<div id="dca-settings-root"><h1>Reglages</h1>' + investServerDownHtml() + "</div>";
    return;
  }
  const existing = bots.map(b => b.config);
  const selected = existing.find(c => c.name === currentInvestBot) || null;
  const cfg = selected || {
    name: "", weights: { "TTE.PA": 1, "ORA.PA": 1, "GLE.PA": 1 },
    monthly_contribution: 200, rebalance_band_pct: 5, min_rebalance_interval_days: 90,
    min_order_value: 50, fee_pct: 0.001, fee_fixed: 3.0,
    follow_drift_on_contribution: true, ibkr_host: "127.0.0.1", ibkr_port: 7497, ibkr_client_id: 30,
  };

  contentEl.innerHTML = `<div id="dca-settings-root"><h1>Reglages</h1>
  <div class="section-block">
    <label>Bot a modifier</label>
    <select id="dca_pick" onchange="currentInvestBot = this.value || null; renderInvestSettingsTab(true);">
      <option value="">+ Nouveau bot</option>
      ${existing.map(c => `<option value="${c.name}" ${c.name === cfg.name ? "selected" : ""}>${c.name}</option>`).join("")}
    </select>
  </div>

  <div class="section-block">
    <h2>Allocation cible</h2>
    <p class="muted">Les poids sont relatifs : 1/1/1 donne trois lignes egales. C'est le choix qui pese
    le PLUS lourd sur le resultat, bien plus que les reglages ci-dessous. Le panier propose par defaut
    est tres concentre (grandes capitalisations Euronext) et a subi une baisse de 50 % sur la periode
    mesuree - a remplacer par le tien.</p>
    <div id="dca_weights">${renderInvestWeightRows(cfg.weights)}</div>
    <button onclick="document.getElementById('dca_weights').insertAdjacentHTML('beforeend', renderInvestWeightRows({'': 1}))">+ Ajouter une ligne</button>
  </div>

  <div class="section-block">
    <h2>Versements</h2>
    <div class="form-grid">
      <div><label>Nom du bot</label><input type="text" id="dca_name" value="${cfg.name}" placeholder="ex: mon_epargne" ${selected ? "readonly" : ""}></div>
      <div><label>Versement mensuel</label><input type="number" id="dca_monthly" value="${cfg.monthly_contribution}" min="0" step="any"></div>
      <div><label>Ordre minimum</label><input type="number" id="dca_min_order" value="${cfg.min_order_value}" min="0" step="any">
        <span class="adv-hint">En dessous, les frais mangent l'operation : le cash attend le mois suivant.</span></div>
      <div><label>Repartition du versement</label>
        <select id="dca_follow_drift">
          <option value="true" ${cfg.follow_drift_on_contribution ? "selected" : ""}>Concentrer sur les lignes en retard (recommande pour de petits versements)</option>
          <option value="false" ${!cfg.follow_drift_on_contribution ? "selected" : ""}>Repartir selon les poids cibles</option>
        </select>
        <span class="adv-hint">Rendement equivalent (mesure sur 6 periodes). Mais repartir 200 EUR sur 6 lignes
        fait 33 EUR par ligne, souvent moins que le prix d'une action : l'argent dort.</span></div>
    </div>
  </div>

  <div class="section-block">
    <h2>Retour a l'allocation cible</h2>
    <div class="form-grid">
      <div><label>Bande de tolerance (points de %)</label><input type="number" id="dca_band" value="${cfg.rebalance_band_pct === null ? "" : cfg.rebalance_band_pct}" min="0" step="any">
        <span class="adv-hint">Vide = ne jamais vendre pour rééquilibrer.</span></div>
      <div><label>Intervalle minimum (jours)</label><input type="number" id="dca_interval" value="${cfg.min_rebalance_interval_days}" min="1" step="1">
        <span class="adv-hint">90 = trimestriel. Sans ce plafond, le bot rééquilibre tous les jours et brule les frais.</span></div>
    </div>
  </div>

  <div class="section-block">
    <h2>Frais et courtier</h2>
    <div class="form-grid">
      <div><label>Frais en % par ordre</label><input type="number" id="dca_fee_pct" value="${cfg.fee_pct * 100}" min="0" step="any"></div>
      <div><label>Frais MINIMUM par ordre (EUR)</label><input type="number" id="dca_fee_fixed" value="${cfg.fee_fixed}" min="0" step="any">
        <span class="adv-hint">3,00 EUR chez IBKR sur Euronext Paris, MESURE sur le compte reel le 2026-09-18 (et non estime). C'est lui qui decide tout pour de petits versements : sur un ordre de 200 EUR, il fait 1,5 %.</span></div>
      <div><label>Hote IBKR</label><input type="text" id="dca_host" value="${cfg.ibkr_host}"></div>
      <div><label>Port IBKR</label>
        <select id="dca_port">
          <option value="7497" ${cfg.ibkr_port === 7497 ? "selected" : ""}>7497 - TWS paper</option>
          <option value="4002" ${cfg.ibkr_port === 4002 ? "selected" : ""}>4002 - IB Gateway paper</option>
        </select>
        <span class="adv-hint">Les ports du compte REEL (7496/4001) sont refuses par le code.</span></div>
    </div>
  </div>

  <div class="section-block">
    <button class="primary" onclick="saveDcaBot()">${selected ? "Enregistrer les modifications" : "Creer le bot"}</button>
    ${selected ? `<button onclick="deleteDcaBot('${cfg.name}')" style="background:var(--red); color:#fff; margin-left:10px;">Supprimer</button>` : ""}
    <p class="muted" id="dca_save_status"></p>
  </div></div>`;
}

function collectDcaWeights() {
  const weights = {};
  document.querySelectorAll("#dca_weights .dca-weight-row").forEach(row => {
    const symbol = row.querySelector(".dca-symbol").value.trim().toUpperCase();
    const weight = parseFloat(row.querySelector(".dca-weight").value);
    if (symbol && weight > 0) weights[symbol] = weight;
  });
  return weights;
}

async function saveDcaBot() {
  const statusEl = document.getElementById("dca_save_status");
  const band = document.getElementById("dca_band").value.trim();
  const payload = {
    name: document.getElementById("dca_name").value.trim(),
    weights: collectDcaWeights(),
    monthly_contribution: parseFloat(document.getElementById("dca_monthly").value),
    rebalance_band_pct: band === "" ? null : parseFloat(band),
    min_rebalance_interval_days: parseInt(document.getElementById("dca_interval").value, 10),
    min_order_value: parseFloat(document.getElementById("dca_min_order").value),
    fee_pct: parseFloat(document.getElementById("dca_fee_pct").value) / 100,
    fee_fixed: parseFloat(document.getElementById("dca_fee_fixed").value),
    follow_drift_on_contribution: document.getElementById("dca_follow_drift").value === "true",
    ibkr_host: document.getElementById("dca_host").value.trim(),
    ibkr_port: parseInt(document.getElementById("dca_port").value, 10),
  };
  statusEl.textContent = "Enregistrement...";
  try {
    const resp = await fetch(`${CONTROL_SERVER}/api/dca-save`, {
      method: "POST",
      headers: { "Content-Type": "application/json" },
      body: JSON.stringify(payload),
    });
    const data = await resp.json();
    if (data.error) {
      statusEl.innerHTML = `<span style="color:var(--red);">${data.error}</span>`;
      return;
    }
    statusEl.innerHTML = `<span style="color:var(--green);">Enregistre. Va dans &quot;Suivi&quot; pour le simuler.</span>`;
    currentInvestBot = data.name;
    renderInvestSettingsTab(true);
  } catch (e) {
    statusEl.innerHTML = `<span style="color:var(--red);">Serveur injoignable : ${e}</span>`;
  }
}

async function deleteDcaBot(name) {
  if (!confirm(`Supprimer le bot d'investissement "${name}" ?\\n\\nSon historique de versements et d'ordres est CONSERVE dans data/, seule la configuration est retiree.`)) return;
  const resp = await fetch(`${CONTROL_SERVER}/api/dca-delete`, {
    method: "POST",
    headers: { "Content-Type": "application/json" },
    body: JSON.stringify({ name }),
  });
  const data = await resp.json();
  if (data.error) {
    document.getElementById("dca_save_status").innerHTML = `<span style="color:var(--red);">${data.error}</span>`;
    return;
  }
  currentInvestBot = null;
  renderInvestSettingsTab(true);
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
        <div class="field"><label>Type de compte</label>
          <select id="f_account_type" onchange="onAccountTypeChange(this.value)">
            <option value="crypto">Crypto (testnet Binance)</option>
            <option value="ibkr_paper">Actions (paper trading Interactive Brokers)</option>
          </select>
          <div id="f_account_type_hint" class="muted" style="font-size:11px; margin-top:4px; display:none;"></div>
        </div>
        <div class="field" id="f_symbol_wrap"><label>Symbole</label>${symbolSelectHtml("f_symbol", "ETH/USDT")}</div>
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
            <option value="dip_bounce_daily">Rebond de creux - journalier (actions)</option>
            <option value="mean_dip">Creux vs moyenne (5 min, sans verrou)</option>
            <option value="slope_dip">Detecteur de pente (1 min, trailing 5%)</option>
            <option value="trend_regime">Regime de tendance (investi en hausse, liquidites en baisse)</option>
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
  // strategies/dip_bounce.py, agnostique du timeframe) mais 3 presets cote
  // formulaire - determine par le timeframe (1d = actions IBKR, sinon la
  // fenetre : 24 = horaire, 60 = minute).
  if (cfg.strategy.type === "dip_bounce") {
    if (cfg.timeframe === "1d") return "dip_bounce_daily";
    return cfg.strategy.trend_ma_period === 60 ? "dip_bounce_minute" : "dip_bounce_hourly";
  }
  return cfg.strategy.type;
}

function fillFormWithConfig(name, cfg) {
  editingBotName = name;
  const formType = formStrategyTypeFor(cfg);
  const accountType = cfg.exchange === "ibkr_paper" ? "ibkr_paper" : "crypto";
  document.getElementById("f_name").value = cfg.name;
  document.getElementById("f_account_type").value = accountType;
  onAccountTypeChange(accountType);  // pose le hint + reconstruit la liste de symboles (actions ou crypto)
  setSymbolValue("f_symbol", cfg.symbol, accountType === "ibkr_paper" ? TOP_STOCKS : TOP10_SYMBOLS);
  document.getElementById("f_timeframe").value = cfg.timeframe;
  document.getElementById("f_strategy_type").value = formType;
  onStrategyTypeChange(formType);  // pose aussi les champs + verrouille timeframe/stop-loss si besoin

  if (cfg.strategy.type === "sma_cross") {
    document.getElementById("f_short_window").value = cfg.strategy.short_window;
    document.getElementById("f_long_window").value = cfg.strategy.long_window;
  } else if (cfg.strategy.type === "scalp_dip") {
    document.getElementById("f_lookback").value = cfg.strategy.lookback;
    document.getElementById("f_dip_threshold_pct").value = cfg.strategy.dip_threshold_pct * 100;
  } else if (formType === "dip_bounce_daily") {
    document.getElementById("f_trend_ma_period").value = cfg.strategy.trend_ma_period;
    document.getElementById("f_dip_threshold_pct").value = cfg.strategy.dip_threshold_pct * 100;
  } else if (cfg.strategy.type === "dip_bounce") {
    document.getElementById("f_dip_threshold_pct").value = cfg.strategy.dip_threshold_pct * 100;
    document.getElementById("f_profit_lock_arm_pct").value = (cfg.risk.profit_lock_arm_pct ?? 0.005) * 100;
    document.getElementById("f_profit_lock_trigger_pct").value = (cfg.risk.profit_lock_trigger_pct ?? 0.0043) * 100;
    document.getElementById("f_force_trade_after_hours").value = cfg.strategy.force_trade_after_hours ?? 0;
  } else if (cfg.strategy.type === "mean_dip") {
    document.getElementById("f_window").value = cfg.strategy.window;
    document.getElementById("f_num_std").value = cfg.strategy.num_std;
  } else if (cfg.strategy.type === "trend_regime") {
    document.getElementById("f_ema_period").value = cfg.strategy.ema_period;
    document.getElementById("f_entry_buffer_pct").value = (cfg.strategy.entry_buffer_pct * 100).toFixed(2);
    document.getElementById("f_exit_buffer_pct").value = (cfg.strategy.exit_buffer_pct * 100).toFixed(2);
  } else if (cfg.strategy.type === "slope_dip") {
    document.getElementById("f_slope_threshold_pct").value = cfg.strategy.slope_threshold_pct * 100;
    document.getElementById("f_candles_window").value = cfg.strategy.candles_window;
    document.getElementById("f_one_buy_per_slope").checked = !!cfg.strategy.one_buy_per_slope;
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
    account_type: document.getElementById("f_account_type").value,
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
  } else if (strategyType === "dip_bounce_daily") {
    payload.trend_ma_period = document.getElementById("f_trend_ma_period").value;
    payload.dip_threshold_pct = document.getElementById("f_dip_threshold_pct").value / 100;
  } else if (strategyType === "mean_dip") {
    payload.window = document.getElementById("f_window").value;
    payload.num_std = document.getElementById("f_num_std").value;
  } else if (strategyType === "slope_dip") {
    payload.slope_threshold_pct = document.getElementById("f_slope_threshold_pct").value / 100;
    payload.candles_window = document.getElementById("f_candles_window").value;
    payload.one_buy_per_slope = document.getElementById("f_one_buy_per_slope").checked;
  } else if (strategyType === "trend_regime") {
    payload.ema_period = document.getElementById("f_ema_period").value;
    payload.entry_buffer_pct = document.getElementById("f_entry_buffer_pct").value / 100;
    payload.exit_buffer_pct = document.getElementById("f_exit_buffer_pct").value / 100;
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
    <a href="${CONTROL_SERVER}/trading.html?bot=${encodeURIComponent(currentBotName)}" target="_blank" rel="noopener" style="margin-left:8px; font-size:12px; font-weight:600;">Ouvrir l'espace de trading</a>
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
  drawPendingBotChart();
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
  // Meme constat empirique que pour le formulaire de creation (2026-09-16) :
  // "Creux vs moyenne" a besoin de plusieurs positions simultanees pour
  // trader normalement, sinon une seule position bloque tout le reste.
  const maxConcurrentInput = document.getElementById("bt_max_concurrent_positions");
  if (key === "mean_dip" && maxConcurrentInput.value === "1") {
    maxConcurrentInput.value = "10";
  }
  // Suggestion demandee explicitement par l'utilisateur pour "Detecteur de
  // pente" ("on vend sur le trailing a 5%") - pre-remplie seulement si vide.
  const trailingInputBt = document.getElementById("bt_trailing_stop_pct");
  if (key === "slope_dip" && trailingInputBt && !trailingInputBt.value) {
    trailingInputBt.value = "5";
  }
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
      if (data.chart) {
        renderBacktestChart(data.chart);
      }
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

let currentBacktestChartData = null;  // EF-60 : donnees brutes (bougies + trades) du dernier backtest, reutilisees a chaque changement de zoom sans re-appeler le serveur
let chartSlopeSelection = { a: null, b: null };  // EF-61 : 2 bougies cliquees pour mesurer la pente entre elles
let lastChartLayout = null;  // dernieres bougies affichees + fonctions x()/y() en cours, pour convertir un clic en bougie

function renderBacktestChart(chart) {
  currentBacktestChartData = chart;
  chartSlopeSelection = { a: null, b: null };
  const reportWrap = document.getElementById("bt_report_wrap");
  const chartHtml = `
    <div class="section-block" style="margin-top:20px;">
      <h2>Graphique (prix + achats/ventes)</h2>
      <div class="form-grid" style="grid-template-columns: repeat(3, 1fr); align-items:end; margin-bottom:10px;">
        <div class="field"><label>Debut de la fenetre (%)</label><input id="chart_zoom_from" type="range" min="0" max="99" value="0" oninput="updateBacktestChartView()"></div>
        <div class="field"><label>Fin de la fenetre (%)</label><input id="chart_zoom_to" type="range" min="1" max="100" value="100" oninput="updateBacktestChartView()"></div>
        <div class="field"><label style="display:flex; align-items:center; gap:6px; font-weight:400;"><input id="chart_show_candles" type="checkbox" checked onchange="updateBacktestChartView()"> Afficher les bougies (sinon courbe)</label></div>
      </div>
      <canvas id="bt_chart_canvas" width="1100" height="380" style="width:100%; height:380px; display:block; cursor:crosshair; background:var(--surface-2); border:1px solid var(--border); border-radius:var(--radius-md);"></canvas>
      <p class="muted" id="chart_zoom_label" style="font-size:11px; margin-top:6px;"></p>
      <p class="muted" style="font-size:11px;">Triangle vert = achat, triangle rouge = vente, cercle = position encore ouverte a la fin de la periode. Bougies regroupees si necessaire pour rester lisible (voir le nombre affiche ci-dessus).</p>
      <p id="chart_slope_result" style="font-size:12.5px; margin-top:8px; padding:9px 12px; background:var(--surface-2); border:1px solid var(--border); border-radius:var(--radius-md);">Clique sur une bougie, puis sur une 2e, pour calculer la pente entre les deux.</p>
    </div>`;
  reportWrap.insertAdjacentHTML("beforeend", chartHtml);
  document.getElementById("bt_chart_canvas").addEventListener("click", handleChartCandleClick);
  updateBacktestChartView();
}

function handleChartCandleClick(evt) {
  if (!lastChartLayout) return;
  const rect = evt.target.getBoundingClientRect();
  const clickX = evt.clientX - rect.left;
  const { candles, minT, maxT, padL, plotW } = lastChartLayout;
  if (clickX < padL || clickX > padL + plotW) return;
  const spanT = Math.max(1, maxT - minT);
  const targetT = minT + ((clickX - padL) / plotW) * spanT;
  let nearest = candles[0];
  let bestDiff = Infinity;
  for (const c of candles) {
    const diff = Math.abs(c.t - targetT);
    if (diff < bestDiff) { bestDiff = diff; nearest = c; }
  }
  if (!chartSlopeSelection.a || chartSlopeSelection.b) {
    chartSlopeSelection = { a: nearest, b: null };
  } else {
    chartSlopeSelection.b = nearest;
  }
  updateChartSlopeResultText();
  updateBacktestChartView();
}

function fmtChartTimestamp(t) {
  return new Date(t).toISOString().slice(0, 16).replace("T", " ");
}

function updateChartSlopeResultText() {
  const el = document.getElementById("chart_slope_result");
  if (!el) return;
  const { a, b } = chartSlopeSelection;
  if (!a) {
    el.textContent = "Clique sur une bougie, puis sur une 2e, pour calculer la pente entre les deux.";
    return;
  }
  if (!b) {
    el.innerHTML = `Bougie A : <strong>${fmtChartTimestamp(a.t)}</strong>, cloture <strong>${a.c.toFixed(2)}</strong> — clique une 2e bougie pour calculer la pente.`;
    return;
  }
  const [first, second] = a.t <= b.t ? [a, b] : [b, a];
  const pct = ((second.c - first.c) / first.c) * 100;
  const sign = pct >= 0 ? "+" : "";
  const color = pct >= 0 ? "var(--green)" : "var(--red)";
  el.innerHTML = `Pente de <strong>${fmtChartTimestamp(first.t)}</strong> (${first.c.toFixed(2)}) a <strong>${fmtChartTimestamp(second.t)}</strong> (${second.c.toFixed(2)}) : <strong style="color:${color};">${sign}${pct.toFixed(3)} %</strong> — clique une nouvelle bougie pour recommencer une mesure.`;
}

function updateBacktestChartView() {
  if (!currentBacktestChartData) return;
  const fromEl = document.getElementById("chart_zoom_from");
  const toEl = document.getElementById("chart_zoom_to");
  const showCandles = document.getElementById("chart_show_candles").checked;
  const fromPct = Number(fromEl.value);
  const toPct = Math.max(Number(toEl.value), fromPct + 1);
  const all = currentBacktestChartData.candles;
  const n = all.length;
  const startIdx = Math.floor((fromPct / 100) * n);
  const endIdx = Math.min(n, Math.max(startIdx + 2, Math.ceil((toPct / 100) * n)));
  const visible = all.slice(startIdx, endIdx);
  drawBacktestCandlestickChart(visible, currentBacktestChartData.closed_trades, currentBacktestChartData.open_positions, showCandles);
  const label = document.getElementById("chart_zoom_label");
  if (label) label.textContent = `${visible.length} bougies affichees sur ${n} au total (fenetre ${fromPct}% - ${toPct}%)`;
}

function drawBacktestCandlestickChart(candles, closedTrades, openPositions, showCandles, canvasId = "bt_chart_canvas") {
  // EF-84 : meme dessin pour les tests ET pour le graphique des bots - le
  // canvas cible est un parametre ; la mesure de pente au clic reste propre
  // au graphique des tests.
  const isBacktest = canvasId === "bt_chart_canvas";
  const canvas = document.getElementById(canvasId);
  if (!canvas || !candles || candles.length === 0) return;
  const dpr = window.devicePixelRatio || 1;
  const cssWidth = canvas.clientWidth || 1100;
  canvas.width = cssWidth * dpr;
  const cssHeight = canvas.clientHeight || 380;
  canvas.height = cssHeight * dpr;
  const ctx = canvas.getContext("2d");
  ctx.setTransform(dpr, 0, 0, dpr, 0, 0);
  const w = cssWidth, h = cssHeight;
  ctx.clearRect(0, 0, w, h);

  const padL = 58, padR = 12, padT = 12, padB = 22;
  const plotW = w - padL - padR, plotH = h - padT - padB;
  const minP = Math.min(...candles.map(c => c.l));
  const maxP = Math.max(...candles.map(c => c.h));
  const pricePad = (maxP - minP) * 0.06 || 1;
  const lo = minP - pricePad, hi = maxP + pricePad;
  const minT = candles[0].t, maxT = candles[candles.length - 1].t;
  const spanT = Math.max(1, maxT - minT);
  const x = t => padL + ((t - minT) / spanT) * plotW;
  const y = p => padT + (1 - (p - lo) / (hi - lo)) * plotH;

  const styles = getComputedStyle(document.documentElement);
  const gridColor = (styles.getPropertyValue("--border") || "#333").trim();
  const inkColor = (styles.getPropertyValue("--text-dim") || "#888").trim();
  const lineColor = (styles.getPropertyValue("--accent") || "#5b8def").trim();
  const upColor = (styles.getPropertyValue("--green") || "#2fd699").trim();
  const downColor = (styles.getPropertyValue("--red") || "#ff6b6b").trim();

  ctx.strokeStyle = gridColor;
  ctx.fillStyle = inkColor;
  ctx.font = "10px monospace";
  ctx.lineWidth = 1;
  for (let s = 0; s <= 4; s++) {
    const price = lo + (hi - lo) * (s / 4);
    const yy = y(price);
    ctx.beginPath(); ctx.moveTo(padL, yy); ctx.lineTo(w - padR, yy); ctx.stroke();
    ctx.fillText(price.toFixed(2), 4, yy + 3);
  }
  for (let s = 0; s <= 4; s++) {
    const t = minT + spanT * (s / 4);
    const xx = x(t);
    const label = new Date(t).toISOString().slice(0, 16).replace("T", " ");
    ctx.fillText(label, Math.min(Math.max(xx - 40, padL), w - padR - 80), h - 6);
  }

  if (showCandles) {
    const candleW = Math.max(1, Math.min(10, (plotW / candles.length) * 0.7));
    candles.forEach(c => {
      const xx = x(c.t);
      const color = c.c >= c.o ? upColor : downColor;
      ctx.strokeStyle = color;
      ctx.fillStyle = color;
      ctx.beginPath(); ctx.moveTo(xx, y(c.h)); ctx.lineTo(xx, y(c.l)); ctx.stroke();
      const yOpen = y(c.o), yClose = y(c.c);
      const bodyTop = Math.min(yOpen, yClose), bodyH = Math.max(1, Math.abs(yOpen - yClose));
      ctx.fillRect(xx - candleW / 2, bodyTop, candleW, bodyH);
    });
  } else {
    ctx.strokeStyle = lineColor;
    ctx.lineWidth = 1.5;
    ctx.beginPath();
    candles.forEach((c, i) => {
      const xx = x(c.t), yy = y(c.c);
      if (i === 0) ctx.moveTo(xx, yy); else ctx.lineTo(xx, yy);
    });
    ctx.stroke();
  }

  function triangleUp(xx, yy, color) {
    ctx.fillStyle = color;
    ctx.beginPath(); ctx.moveTo(xx, yy - 7); ctx.lineTo(xx + 5, yy + 2); ctx.lineTo(xx - 5, yy + 2); ctx.closePath(); ctx.fill();
  }
  function triangleDown(xx, yy, color) {
    ctx.fillStyle = color;
    ctx.beginPath(); ctx.moveTo(xx, yy + 7); ctx.lineTo(xx + 5, yy - 2); ctx.lineTo(xx - 5, yy - 2); ctx.closePath(); ctx.fill();
  }
  (closedTrades || []).forEach(t => {
    if (t.buy_t >= minT && t.buy_t <= maxT) triangleUp(x(t.buy_t), y(t.buy_p), upColor);
    if (t.sell_t >= minT && t.sell_t <= maxT) triangleDown(x(t.sell_t), y(t.sell_p), downColor);
  });
  (openPositions || []).forEach(p => {
    if (p.buy_t >= minT && p.buy_t <= maxT) {
      triangleUp(x(p.buy_t), y(p.buy_p), upColor);
      ctx.strokeStyle = inkColor;
      ctx.lineWidth = 1.3;
      ctx.beginPath(); ctx.arc(x(p.buy_t), y(p.buy_p), 9, 0, 2 * Math.PI); ctx.stroke();
    }
  });

  if (!isBacktest) return;
  lastChartLayout = { candles, x, y, minT, maxT, padL, padR, plotW };

  // EF-61 : 2 bougies cliquees pour mesurer la pente - dessine les 2 points
  // (s'ils sont dans la fenetre visible actuelle) et le segment entre eux.
  const accentColor = (styles.getPropertyValue("--accent") || "#5b8def").trim();
  function drawSelectionDot(xx, yy) {
    ctx.fillStyle = accentColor;
    ctx.strokeStyle = "#fff";
    ctx.lineWidth = 1.5;
    ctx.beginPath(); ctx.arc(xx, yy, 5, 0, 2 * Math.PI); ctx.fill(); ctx.stroke();
  }
  if (chartSlopeSelection.a && chartSlopeSelection.a.t >= minT && chartSlopeSelection.a.t <= maxT) {
    const ax = x(chartSlopeSelection.a.t), ay = y(chartSlopeSelection.a.c);
    if (chartSlopeSelection.b && chartSlopeSelection.b.t >= minT && chartSlopeSelection.b.t <= maxT) {
      const bx = x(chartSlopeSelection.b.t), by = y(chartSlopeSelection.b.c);
      ctx.strokeStyle = accentColor;
      ctx.lineWidth = 1.5;
      ctx.setLineDash([5, 4]);
      ctx.beginPath(); ctx.moveTo(ax, ay); ctx.lineTo(bx, by); ctx.stroke();
      ctx.setLineDash([]);
      drawSelectionDot(bx, by);
    }
    drawSelectionDot(ax, ay);
  }
}

function exportBacktestToNewBot() {
  // Reprend les reglages actuels du formulaire Test/Backtest et les reporte
  // dans le formulaire de Creation (§5.1/5.2), demande de l'utilisateur pour
  // ne pas avoir a retaper a la main une config qui a donne un bon resultat
  // en test. Les cles de strategie backtest/creation sont deja identiques
  // (sma_cross, scalp_dip, dip_bounce_hourly/minute, mean_dip, buy_and_hold) -
  // seuls mean_reversion/market_making n'ont pas d'equivalent creable (bouton
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
  } else if (strategyKey === "mean_dip") {
    exported.window = val("bt_p_window");
    exported.numStd = val("bt_p_num_std");
  } else if (strategyKey === "slope_dip") {
    exported.slopeThresholdPct = val("bt_p_slope_threshold_pct");
    exported.candlesWindow = val("bt_p_candles_window");
    exported.oneBuyPerSlope = val("bt_p_one_buy_per_slope");
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
  } else if (strategyKey === "mean_dip") {
    if (exported.window) document.getElementById("f_window").value = exported.window;
    if (exported.numStd) document.getElementById("f_num_std").value = exported.numStd;
  } else if (strategyKey === "slope_dip") {
    if (exported.slopeThresholdPct) document.getElementById("f_slope_threshold_pct").value = exported.slopeThresholdPct;
    if (exported.candlesWindow) document.getElementById("f_candles_window").value = exported.candlesWindow;
    document.getElementById("f_one_buy_per_slope").checked = exported.oneBuyPerSlope === "1";
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
