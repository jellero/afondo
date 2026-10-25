"""Conservative numeric and temporal context checks, not truth judgments.

Given a verbatim claim and a cited source excerpt, identify only explicit,
auditable differences. No mismatch is promoted to "false" or "out of context":
denominators, populations and measurement methods still require a human.
"""
from __future__ import annotations

from decimal import Decimal, InvalidOperation
import re

NUMBER = re.compile(
    r"(?<![\w])(-?\d+(?:[.,]\d+)?)(?:\s*)(%|percento|percent|per cento|"
    r"euro|€|usd|\$|milioni|milione|miliardi|miliardo|million|billion)?(?!\w)",
    re.IGNORECASE,
)
YEAR = re.compile(r"\b(?:19|20)\d{2}\b")


def _numbers(text: str) -> set[tuple[str, str]]:
    values: set[tuple[str, str]] = set()
    for match in NUMBER.finditer(text):
        raw, unit = match.group(1), (match.group(2) or "").lower().strip()
        # Years are compared separately, not counted as generic quantities.
        if not unit and re.fullmatch(r"(?:19|20)\d{2}", raw):
            continue
        try:
            if "," in raw and "." not in raw:
                value = Decimal(raw.replace(",", "."))
            else:
                value = Decimal(raw)
        except InvalidOperation:
            continue
        if unit in ("percento", "percent", "per cento"):
            unit = "%"
        if unit in ("€", "euro"):
            unit = "eur"
        if unit in ("$", "usd"):
            unit = "usd"
        if unit in ("milione", "milioni", "million"):
            unit = "millions"
        if unit in ("miliardo", "miliardi", "billion"):
            unit = "billions"
        if unit:
            values.add((format(value, "f"), unit))
    return values


def context_signals(claim: str, excerpt: str) -> list[dict]:
    """Warnings about literal numbers/dates only, without semantic inference."""
    signals = []
    claim_years, source_years = set(YEAR.findall(claim)), set(YEAR.findall(excerpt))
    if claim_years and source_years and not (claim_years & source_years):
        signals.append({
            "code": "different_explicit_years",
            "level": "review",
            "claim_values": sorted(claim_years),
            "source_values": sorted(source_years),
            "message": "Anni espliciti differenti: verificare il periodo e la base del confronto.",
        })
    cn, sn = _numbers(claim), _numbers(excerpt)
    by_unit_claim = {u: {v for v, unit in cn if unit == u} for _, u in cn}
    by_unit_source = {u: {v for v, unit in sn if unit == u} for _, u in sn}
    for unit in sorted(set(by_unit_claim) & set(by_unit_source)):
        if by_unit_claim[unit].isdisjoint(by_unit_source[unit]):
            signals.append({
                "code": "different_explicit_quantity",
                "level": "review",
                "unit": unit,
                "claim_values": sorted(by_unit_claim[unit]),
                "source_values": sorted(by_unit_source[unit]),
                "message": (
                    "Quantità esplicite differenti con unità simile: confrontare "
                    "popolazione, intervallo, denominatore e metodologia."
                ),
            })
    return signals
