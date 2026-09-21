"""Turn two differently-written values into a form that can be compared.

This module is where accuracy comes from. Compare RAW strings and
'22,000 KG' != '22000' becomes a false alarm; the scoring punishes those as
hard as a missed defect.

Rule: normalise, then compare exactly. Never fuzzy-match raw text.
"""
from __future__ import annotations

import re
from difflib import SequenceMatcher

# Company suffixes that mean the same thing written different ways.
SUFFIX_MAP = {
    "limited": "ltd", "incorporated": "inc", "corporation": "corp",
    "company": "co", "private": "pvt", "public limited company": "plc",
    "sendirian berhad": "sdn bhd", "pte ltd": "pte ltd",
    "gesellschaft mit beschrankter haftung": "gmbh",
}
NOISE_WORDS = {"the", "messrs", "m s"}

# tonne / pound -> kilogram
WEIGHT_UNITS = {
    "kg": 1.0, "kgs": 1.0, "kgm": 1.0, "kilogram": 1.0, "kilograms": 1.0,
    "mt": 1000.0, "ton": 1000.0, "tons": 1000.0, "tonne": 1000.0,
    "tonnes": 1000.0, "metricton": 1000.0,
    "lb": 0.45359237, "lbs": 0.45359237, "pound": 0.45359237,
}

WEIGHT_TOLERANCE_KG = 0.5   # rounding only, not a real difference


def _squash(text: str) -> str:
    text = text.upper()
    text = re.sub(r"[^A-Z0-9 ]+", " ", text)
    return re.sub(r"\s+", " ", text).strip()


def party(value):
    """Company name -> canonical form. 'Acme Corp. Ltd' -> 'ACME CORP LTD'."""
    if not value:
        return None
    text = value.lower()
    for long_form, short in SUFFIX_MAP.items():
        text = re.sub(r"\b" + re.escape(long_form) + r"\b", short, text)
    text = _squash(text)
    tokens = [t for t in text.split() if t.lower() not in NOISE_WORDS]
    return " ".join(tokens) or None


def party_similarity(a, b) -> float:
    """0..1. Used only for the uncertain middle band -- see comparator."""
    if not a or not b:
        return 0.0
    ta, tb = set(a.split()), set(b.split())
    if not ta or not tb:
        return 0.0
    jaccard = len(ta & tb) / len(ta | tb)
    seq = SequenceMatcher(None, a, b).ratio()
    return max(jaccard, seq)


def port(value):
    """Port name -> canonical form.

    'NHAVA SHEVA, INDIA (INNSA)' and 'NHAVA SHEVA, INDIA' both become
    'NHAVA SHEVA INDIA', so the presence of a UN/LOCODE on one side only
    does not read as a discrepancy.
    """
    if not value:
        return None
    text = re.sub(r"\([^)]*\)", " ", value)   # drop bracketed codes
    text = _squash(text)
    text = re.sub(r"\bPORT OF\b", " ", text)
    return re.sub(r"\s+", " ", text).strip() or None


def container_count(value):
    """'6 x 40\\'HC' -> 6 ; 'TEN (10) CONTAINERS' -> 10 ; '3' -> 3."""
    if not value:
        return None
    m = re.search(r"\((\d+)\)", value)        # 'TEN (10)' -- digits win
    if m:
        return int(m.group(1))
    m = re.match(r"\s*(\d+)\s*[xX*]", value)  # '6 x 40HC'
    if m:
        return int(m.group(1))
    m = re.search(r"\d+", value)
    return int(m.group(0)) if m else None


def gross_weight_kg(value):
    """'22,000 KG' / '22000' / '22 MT' -> 22000.0 kilograms."""
    if not value:
        return None
    text = value.replace(",", "")
    m = re.search(r"(\d+(?:\.\d+)?)", text)
    if not m:
        return None
    amount = float(m.group(1))
    tail = text[m.end():].lower()
    unit = re.sub(r"[^a-z]", "", tail.split()[0]) if tail.split() else ""
    return round(amount * WEIGHT_UNITS.get(unit, 1.0), 3)


# field name -> normaliser
NORMALISERS = {
    "shipper": party,
    "consignee": party,
    "notify_party": party,
    "port_of_loading": port,
    "port_of_discharge": port,
    "container_count": container_count,
    "gross_weight_kg": gross_weight_kg,
}


def normalize(field_name: str, value):
    fn = NORMALISERS.get(field_name)
    return fn(value) if fn else (value.strip().upper() if value else None)
