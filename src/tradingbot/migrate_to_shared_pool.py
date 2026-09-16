"""Migration one-off : bascule des bots existants (capital isole par
instance) vers le panier de capital commun (STC section 3.5 revisee).

A executer UNE SEULE FOIS, tous les bots etant arretes (ils partagent tous
le meme fichier `data/shared_pool.db`, et cette migration part du principe
qu'aucun ordre n'est en cours pendant qu'elle calcule le cash de chacun).

Pour chaque config/*.yml ayant un `capital_allocated` et un
`data/{name}.db` correspondant, on recalcule le cash reel de ce bot a
l'instant du gel (meme formule que l'ancien `compute_restored_cash` de
run_paper.py : capital_allocated + realized_pnl - argent immobilise dans
les positions encore ouvertes), puis on seede le panier commun a la SOMME
de ces cash individuels - pas a la somme brute des `capital_allocated`
nominaux, puisque l'argent deja immobilise dans une position ouverte n'est
pas disponible pour un nouvel achat (il reintegrera le panier
naturellement quand cette position sera revendue).

Usage:
    python -m tradingbot.migrate_to_shared_pool
"""

from pathlib import Path

import yaml

from tradingbot.reporting.logger import TradeLogger
from tradingbot.run_paper import compute_restored_cash
from tradingbot.shared_pool import SharedPool

CONFIG_DIR = Path("config")


def compute_bot_state(config_path: Path) -> dict | None:
    with open(config_path, encoding="utf-8") as f:
        config = yaml.safe_load(f)

    capital_allocated = config.get("capital_allocated")
    instance_name = config.get("name")
    if capital_allocated is None or instance_name is None:
        return None

    db_path = Path("data") / f"{instance_name}.db"
    if not db_path.exists():
        # Bot configure mais jamais lance : rien a migrer, son plafond de
        # base sera simplement utilise tel quel des son premier demarrage.
        print(f"  {instance_name} : pas de {db_path}, jamais lance - ignore (base_cap={capital_allocated} reste pris tel quel).")
        return None

    logger = TradeLogger(instance_name)
    trade_history = logger.load_closed_trades()
    positions = logger.load_open_positions()
    logger.close()

    realized_pnl = sum(t["pnl"] for t in trade_history)
    cash = compute_restored_cash(capital_allocated, realized_pnl, positions)
    tied_up = sum(p.quantity * p.avg_entry_price + p.entry_fee for p in positions)

    print(
        f"  {instance_name} : base_cap={capital_allocated:.2f}, realized_pnl={realized_pnl:+.2f}, "
        f"immobilise={tied_up:.2f} -> cash={cash:.2f} ({len(trade_history)} trades clotures)"
    )
    return {
        "instance_name": instance_name,
        "cash": cash,
        "base_cap": capital_allocated,
        "trade_count": len(trade_history),
    }


def main() -> None:
    print("Migration vers le panier de capital commun.")
    print("IMPORTANT : tous les bots doivent etre arretes avant de continuer.\n")

    config_paths = sorted(CONFIG_DIR.glob("*.yml"))
    if not config_paths:
        print(f"Aucune config trouvee dans {CONFIG_DIR}/.")
        return

    per_bot = []
    for config_path in config_paths:
        state = compute_bot_state(config_path)
        if state is not None:
            per_bot.append(state)

    if not per_bot:
        print("\nAucun bot avec un historique existant - rien a migrer.")
        return

    total_cash = sum(b["cash"] for b in per_bot)
    print(f"\nTotal du panier commun a initialiser : {total_cash:.2f} (somme du cash reel de {len(per_bot)} bot(s))")

    pool = SharedPool()
    try:
        pool.seed_migration(per_bot)
    except RuntimeError as exc:
        print(f"\nMigration annulee : {exc}")
        return
    finally:
        pool.close()

    print("\nPanier commun initialise dans data/shared_pool.db.")
    print("Vous pouvez maintenant relancer les bots avec le nouveau code.")


if __name__ == "__main__":
    main()
