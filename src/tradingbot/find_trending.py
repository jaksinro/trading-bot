"""Outil de decouverte : liste les cryptos les plus 'tendance' du moment sur
Binance (plus fortes hausses/baisses et plus forts volumes sur 24h), pour
aider a choisir la PROCHAINE devise a tester (STB section 3.1 : le choix du
marche pilote peut evoluer). Ne lance rien tout seul : affiche juste un
rapport et un squelette de config pret a copier.

Usage:
    python -m tradingbot.find_trending
"""

import sys

import ccxt

QUOTE = "USDT"
TOP_N = 10


def fetch_usdt_tickers() -> list[dict]:
    exchange = ccxt.binance()
    tickers = exchange.fetch_tickers()
    return [
        t for symbol, t in tickers.items()
        if symbol.endswith(f"/{QUOTE}") and t.get("percentage") is not None and t.get("quoteVolume")
    ]


def print_ranking(title: str, tickers: list[dict]) -> None:
    print(f"\n{title}")
    print("-" * len(title))
    for t in tickers[:TOP_N]:
        change = t["percentage"]
        volume = t["quoteVolume"]
        print(f"  {t['symbol']:<14} {change:+7.2f} %   volume 24h: {volume:,.0f} {QUOTE}")


def suggest_config_snippet(symbol: str) -> str:
    name = symbol.replace("/", "_").lower()
    return f"""
Squelette de config pour tester "{symbol}" (a adapter/valider avant de lancer) :

  name: {name}_v1
  exchange: binance
  symbol: {symbol}
  timeframe: 1h
  warmup_candles: 50
  flatten_on_start: true
  capital_allocated: 200   # budget virtuel isole, a ajuster

  strategy:
    type: sma_cross
    short_window: 10
    long_window: 30

  risk:
    max_position_size_pct: 0.10
    stop_loss_pct: 0.02
    take_profit_pct: null
    max_daily_loss_pct: 0.05

  backtest:
    starting_capital: 1000
    since: "2026-09-01T00:00:00Z"
"""


def main() -> None:
    print(f"Recuperation des donnees de marche Binance ({QUOTE})...")
    tickers = fetch_usdt_tickers()

    gainers = sorted(tickers, key=lambda t: t["percentage"], reverse=True)
    losers = sorted(tickers, key=lambda t: t["percentage"])
    most_active = sorted(tickers, key=lambda t: t["quoteVolume"], reverse=True)

    print_ranking(f"Top {TOP_N} hausses (24h)", gainers)
    print_ranking(f"Top {TOP_N} baisses (24h)", losers)
    print_ranking(f"Top {TOP_N} volumes (24h)", most_active)

    if gainers:
        top_symbol = gainers[0]["symbol"]
        print(f"\nAvertissement : une forte hausse recente ne garantit rien pour la suite")
        print(f"(momentum peut se retourner). A utiliser comme point de depart de recherche,")
        print(f"pas comme signal d'achat.")
        print(suggest_config_snippet(top_symbol))


if __name__ == "__main__":
    try:
        main()
    except Exception as e:
        print(f"Erreur lors de la recuperation des donnees : {e}", file=sys.stderr)
        sys.exit(1)
