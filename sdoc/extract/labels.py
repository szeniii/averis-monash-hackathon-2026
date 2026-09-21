"""Stage 2 (offline): read the seven fields by matching label text.

The Gemini extractor reads meaning and handles layouts nobody listed in
advance. This one only knows the labels it was told about -- but it needs no
API key, no network and no quota, and it is deterministic, so the pipeline
has a floor to stand on when the key is missing or the API is down.

Same callable contract as GeminiExtractor:

    extractor = LabelExtractor()
    fields = extractor(si_doc, bl_doc)[si_doc.path]

Three layouts appear in the dataset and all three are handled:

    Port of Loading (POL): SINGAPORE          .txt and .pdf with colons
    PORT OF LOADING (装货港) | SINGAPORE       .xlsx rows and Word tables
    Port of Loading SINGAPORE                 .pdf where the colon is lost

The label itself varies more than the value does. "Shipper (Principal or
Seller) (发货人)", "SHIPPER" and "Shipper/Exporter" are one field, so the
label is reduced to a canonical form -- non-ASCII dropped, bracketed asides
removed -- before any rule is tested.

Values come back EXACTLY as printed, for the same reason the LLM prompt
insists on it: normalising is sdoc.compare.normalize's job, and a human
reviewing an escalation needs to see what the document actually said.
"""
from __future__ import annotations

import re

from sdoc.schemas import ExtractedField

# Canonical label -> field, most specific first. Order matters twice over:
# "notify party/intermediate consignee" must be read as notify_party rather
# than consignee, and "shipper/exporter" must be tried before "shipper".
LABEL_RULES = [
    ("notify_party", r"notify party\s*/\s*intermediate consignee"),
    ("notify_party", r"notify party"),
    ("notify_party", r"notify"),

    ("consignee", r"to the order of"),
    ("consignee", r"consignee"),

    ("shipper", r"shipper\s*/\s*exporter"),
    ("shipper", r"shipper"),
    ("shipper", r"exporter"),

    ("port_of_loading", r"port of loading"),
    ("port_of_loading", r"load(?:ing)? port"),
    ("port_of_loading", r"pol"),

    ("port_of_discharge", r"port of discharge"),
    ("port_of_discharge", r"discharge port"),
    ("port_of_discharge", r"pod"),

    ("container_count", r"(?:no|number) of containers(?: or packages)?"),
    ("container_count", r"total containers"),
    ("container_count", r"container count"),

    # "net weight" and "tare weight" deliberately have no rule. Reading one
    # of those as the gross weight is the classic way to invent a defect.
    ("gross_weight_kg", r"gross w(?:eigh)?t"),
]

# Anchored, for "Label: value" and "Label | value" where the split is known.
_EXACT = [(field, re.compile(r"^" + pattern + r"$", re.I))
          for field, pattern in LABEL_RULES]

# Prefix-anchored with a word boundary, for lines that lost their separator.
# The boundary keeps "pol" from matching "Port of Loading ...".
_PREFIX = [(field, re.compile(r"^(" + pattern + r")\b[ \t]+(.+)$", re.I))
           for field, pattern in LABEL_RULES]

# A printed blank is missing information, not a value.
PLACEHOLDERS = {"n/a", "na", "n.a.", "none", "nil", "tba", "tbc", "tbd",
                "unknown", "x", "xx", "xxx"}

_SPLIT = re.compile(r"\s*[:|]\s*")
_BRACKETED = re.compile(r"\([^)]*\)")


def _canonical(label: str) -> str:
    """'Shipper (Principal or Seller) (发货人)' -> 'shipper'."""
    label = re.sub(r"[^\x00-\x7F]+", "", label)   # drop the bilingual half
    label = _BRACKETED.sub(" ", label)            # drop bracketed asides
    label = label.replace(".", " ").replace("_", " ").replace("*", " ")
    label = re.sub(r"[^a-zA-Z0-9/\s]+", " ", label)
    return re.sub(r"\s+", " ", label).strip().lower()


def _is_placeholder(value: str) -> bool:
    squashed = re.sub(r"[\s_.]+", "", value.strip().lower())
    if not squashed:
        return True
    if value.strip().lower() in PLACEHOLDERS:
        return True
    return set(squashed) <= {"_", "-", "?", ".", "/"}


def _record(found: dict, field: str, label: str, value: str) -> None:
    if field in found:
        return                     # first occurrence wins; headers sit at top
    value = value.strip()
    if _is_placeholder(value):
        found[field] = {"value": None, "label": label.strip(),
                        "confidence": 0.0}
    else:
        found[field] = {"value": value, "label": label.strip(),
                        "confidence": 0.85}


def _match_exact(label: str):
    for field, pattern in _EXACT:
        if pattern.match(label):
            return field
    return None


def extract_fields(text: str) -> dict:
    """Pull the seven fields out of one document's text. -> {field: dict}"""
    found = {}
    lines = text.splitlines()

    # Pass 1: a real separator is present, so the split is unambiguous.
    for line in lines:
        if not line.strip() or line[:1].isspace():
            # Indented continuation lines are the address block printed under
            # a party name. The name is the value; the address is not.
            continue
        parts = _SPLIT.split(line.strip(), maxsplit=1)
        if len(parts) != 2:
            continue
        field = _match_exact(_canonical(parts[0]))
        if field is None:
            continue
        # An xlsx row can carry trailing cells; the value is the next one.
        _record(found, field, parts[0], _SPLIT.split(parts[1], maxsplit=1)[0])

    # Pass 2: fill only what is still missing, from lines where the separator
    # was lost in conversion ("Port of Loading NHAVA SHEVA, INDIA"). Run last
    # so a properly delimited line always wins over a guessed split.
    for line in lines:
        if not line.strip() or line[:1].isspace():
            continue
        if _SPLIT.search(line):
            continue
        stripped = re.sub(r"[^\x00-\x7F]+", "", line).strip()
        for field, pattern in _PREFIX:
            if field in found:
                continue
            hit = pattern.match(stripped)
            if hit:
                _record(found, field, hit.group(1), hit.group(2))
                break

    return found


class LabelExtractor:
    """Offline drop-in for GeminiExtractor. No key, no network, no quota."""

    name = "labels"

    def __call__(self, *docs) -> dict:
        result = {}
        for doc in docs:
            if doc is None or not doc.read_ok or not doc.text:
                continue
            fields = {}
            for name, item in extract_fields(doc.text).items():
                fields[name] = ExtractedField(
                    field=name,
                    raw_value=item["value"],
                    confidence=item["confidence"],
                    label_found=item["label"],
                    snippet=(f"{item['label']}: {item['value']}"
                             if item["value"] else None),
                )
            result[doc.path] = fields
        return result


class ChainExtractor:
    """Try each extractor in turn; keep the first that answers for a document.

    Gemini first, labels second, is the useful order: the model handles the
    layouts nobody listed, and the label reader catches everything it could
    not answer because the key was missing or the quota ran out.
    """

    def __init__(self, *extractors):
        self.extractors = [e for e in extractors if e is not None]

    def __call__(self, *docs) -> dict:
        merged = {}
        remaining = [d for d in docs if d is not None]
        for extractor in self.extractors:
            if not remaining:
                break
            answered = extractor(*remaining) or {}
            for path, fields in answered.items():
                if fields and path not in merged:
                    merged[path] = fields
            remaining = [d for d in remaining if d.path not in merged]
        return merged
