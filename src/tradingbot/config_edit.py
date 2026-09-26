"""Modification ciblee des reglages de risque d'un bot (EF-89).

Le panneau de reglages de la page Trading change stop-loss, trailing stop,
objectif... Reecrire le YAML via `yaml.safe_dump` EFFACERAIT tous les
commentaires - or ceux des configs expliquent le pourquoi des reglages
("volontairement aucun stop-loss : mesure deux fois comme perdant"). On
remplace donc uniquement les lignes `  cle: valeur` du bloc `risk:`, en
conservant les commentaires, l'ordre et le reste du fichier. Une cle absente
est ajoutee a la fin du bloc.
"""

from __future__ import annotations

import re

# Reglages modifiables depuis la page, et leurs bornes. Les pourcentages sont
# des FRACTIONS (0.08 = 8 %). None = protection desactivee.
EDITABLE_RISK_KEYS = {
    "stop_loss_pct": (0.0, 0.99),
    "take_profit_pct": (0.0, 10.0),
    "trailing_stop_pct": (0.0, 0.99),
    "profit_lock_arm_pct": (0.0, 10.0),
    "profit_lock_trigger_pct": (-0.99, 10.0),
    "max_daily_loss_pct": (0.0, 0.99),
    "max_concurrent_positions": (1, 20),
}
NULLABLE = {"stop_loss_pct", "take_profit_pct", "trailing_stop_pct", "profit_lock_arm_pct", "profit_lock_trigger_pct"}


def validate_risk_updates(updates: dict) -> dict:
    """Controle et normalise les valeurs recues. Leve ValueError avec un
    message lisible - jamais de valeur hors bornes ecrite dans une config."""
    clean = {}
    for key, value in updates.items():
        if key not in EDITABLE_RISK_KEYS:
            raise ValueError(f"reglage non modifiable ici : {key}")
        low, high = EDITABLE_RISK_KEYS[key]
        if value is None or value == "":
            if key not in NULLABLE:
                raise ValueError(f"{key} ne peut pas etre desactive")
            clean[key] = None
            continue
        if key == "max_concurrent_positions":
            if isinstance(value, bool) or int(value) != float(value):
                raise ValueError("max_concurrent_positions doit etre un nombre entier")
            number = int(value)
        else:
            number = float(value)
        # Nombre de positions : bornes incluses. Pourcentages : strictement
        # au-dessus du minimum (un stop-loss a 0 % vendrait au premier tick).
        in_range = low <= number <= high if key == "max_concurrent_positions" else low < number <= high
        if not in_range:
            raise ValueError(f"{key} hors bornes ({low} - {high}) : {value}")
        clean[key] = number
    arm, trig = clean.get("profit_lock_arm_pct"), clean.get("profit_lock_trigger_pct")
    if arm is not None and trig is not None and trig >= arm:
        raise ValueError("le verrou de gain doit vendre SOUS son seuil d'armement (declenchement < armement)")
    return clean


def _format(value) -> str:
    if value is None:
        return "null"
    if isinstance(value, int) and not isinstance(value, bool):
        return str(value)
    return repr(float(value))


def update_risk_block(text: str, updates: dict) -> str:
    """Remplace les valeurs de `updates` dans le bloc `risk:` de `text`, sans
    toucher a rien d'autre (commentaires compris). Leve ValueError s'il n'y a
    pas de bloc `risk:`."""
    lines = text.splitlines()
    try:
        start = next(i for i, line in enumerate(lines) if re.match(r"^risk:\s*(#.*)?$", line))
    except StopIteration:
        raise ValueError("bloc 'risk:' introuvable dans la config")
    end = start + 1
    while end < len(lines) and (lines[end].startswith((" ", "\t")) or not lines[end].strip()):
        end += 1
    # Ne pas avaler les lignes vides qui separent du bloc suivant.
    last_content = end
    while last_content > start + 1 and not lines[last_content - 1].strip():
        last_content -= 1

    remaining = dict(updates)
    for i in range(start + 1, last_content):
        match = re.match(r"^(\s+)([A-Za-z_]\w*)(\s*):(\s*)([^#]*?)(\s*)(#.*)?$", lines[i])
        if not match or match.group(2) not in remaining:
            continue
        indent, key, sp1, sp2, _old, sp3, comment = match.groups()
        lines[i] = f"{indent}{key}{sp1}:{sp2 or ' '}{_format(remaining.pop(key))}{(sp3 or ' ') + comment if comment else ''}"

    if remaining:
        indent = "  "
        for i in range(start + 1, last_content):
            m = re.match(r"^(\s+)\w", lines[i])
            if m:
                indent = m.group(1)
                break
        added = [f"{indent}{key}: {_format(value)}" for key, value in remaining.items()]
        lines[last_content:last_content] = added

    result = "\n".join(lines)
    return result + ("\n" if text.endswith("\n") else "")
