"""Read the seven fields from a document's text without calling a model.

The documents are mostly "Label: value" lines, and the reader renders
spreadsheet rows as "Label | value" so they arrive in the same shape. Mapping
a label to a field is a lookup, not reasoning -- so do it locally, for free,
deterministically, and keep the model for the documents this cannot handle.

Labels are normalised before lookup: parenthetical qualifiers and non-ASCII
characters are stripped, which lets one entry cover "Gross Wt (kgs)",
"Gross Weight (KG)" and the bilingual "Gross Weight毛重(KGS)".
"""
from __future__ import annotations

import re
import unicodedata

from sdoc.schemas import ExtractedField

# canonical field -> normalised labels that mean it
LABEL_ALIASES = {
    "shipper": {"shipper", "shipper exporter", "exporter", "consignor",
                "shipper name"},
    "consignee": {"consignee", "to the order of", "consigned to",
                  "consignee name", "order of"},
    "notify_party": {"notify", "notify party", "notify address",
                     "also notify", "notify party intermediate consignee"},
    "port_of_loading": {"port of loading", "pol", "load port", "loading port",
                        "port of load"},
    "port_of_discharge": {"port of discharge", "pod", "discharge port",
                          "discharging port", "destination port"},
    "container_count": {"total containers", "container count", "containers",
                        "no of containers", "number of containers",
                        "no of containers or packages", "container qty"},
    "gross_weight_kg": {"gross wt", "gross weight", "total gross weight",
                        "gross wt kgs", "gross weight kgs"},
}

_LABEL_TO_FIELD = {label: name
                   for name, labels in LABEL_ALIASES.items()
                   for label in labels}

# Fallback for labels we have not seen literally -- PDF and DOCX layouts
# invent their own wording. ORDER MATTERS: "Notify Party/Intermediate
# Consignee" contains "consignee", so notify must be tested first.
_KEYWORD_RULES = [
    ("notify_party", lambda l: "notify" in l),
    ("shipper", lambda l: "shipper" in l or "exporter" in l or "consignor" in l),
    ("consignee", lambda l: "consignee" in l or "order of" in l),
    ("container_count", lambda l: "container" in l),
    ("port_of_loading", lambda l: "loading" in l or "load port" in l),
    ("port_of_discharge", lambda l: "discharge" in l or "destination port" in l),
    # "gross" guards against Net Weight, which is a different figure.
    ("gross_weight_kg", lambda l: "gross" in l and ("weight" in l or "wt" in l)),
]

# "Label: value" or the spreadsheet rendering "Label | value"
LABEL_LINE = re.compile(r"^(?P<label>[^:|]{1,60})\s*[:|]\s*(?P<value>.*)$")

# Values that mean "not filled in" rather than an actual value.
BLANK_VALUES = {"", "-", "--", "n/a", "na", "tba", "tbc", "???", "____",
                "_______", "none", "nil"}

# A ruled blank line is drawn to whatever width fits, so listing placeholder
# strings literally misses every length nobody happened to write down --
# "___" and "________" are the same empty box. Judge by the characters.
_BLANK_CHARS = set("_-?.—– ")


def is_blank(value: str) -> bool:
    """True when a printed value means "not filled in"."""
    text = (value or "").strip()
    if text.lower() in BLANK_VALUES:
        return True
    return bool(text) and set(text) <= _BLANK_CHARS


def normalise_label(label: str) -> str:
    text = unicodedata.normalize("NFKD", label)
    text = "".join(ch for ch in text if ord(ch) < 128)   # drop CJK etc.
    text = re.sub(r"\([^)]*\)", " ", text)               # drop (POL), (kgs)
    text = re.sub(r"[^a-z0-9\s]", " ", text.lower())
    return re.sub(r"\s+", " ", text).strip()


def field_for_label(label: str):
    key = normalise_label(label)
    if not key:
        return None
    if key in _LABEL_TO_FIELD:
        return _LABEL_TO_FIELD[key]
    for name, matches in _KEYWORD_RULES:
        if matches(key):
            return name
    return None


def extract(doc) -> dict:
    """DocumentExtract -> {field_name: ExtractedField}.

    Only the value on the label line is taken. Indented continuation lines are
    address detail that both documents repeat identically -- including them
    adds noise without adding signal.
    """
    found = {}
    if not doc or not doc.text:
        return found

    for line in doc.text.splitlines():
        if line.startswith((" ", "\t")):      # continuation / address line
            continue

        match = LABEL_LINE.match(line)
        if not match:
            continue

        name = field_for_label(match.group("label"))
        if not name or name in found:          # unknown, or already have it
            continue

        value = match.group("value").strip()
        if is_blank(value):
            continue                           # blank is missing, not a value

        found[name] = ExtractedField(
            field=name,
            raw_value=value,
            confidence=0.95,                   # an exact label match is certain
            label_found=match.group("label").strip(),
            snippet=line.strip(),
        )

    return found


def count(doc) -> int:
    """How many of the seven fields this document yields. Used to decide
    whether a document needs the model."""
    return len(extract(doc))


# --- compatibility layer for the review app -------------------------------
#
# web/app.py and the tests need a slightly wider surface than the pipeline
# does: a text-in, dict-out helper and extractor objects with the same
# __call__ shape as GeminiExtractor. All of it is built on extract() above,
# so this repo has one label table rather than two.
#
# extract_fields() adds one thing extract() deliberately does not: a second
# pass over lines whose separator was lost in PDF conversion, such as
# "Port of Loading NHAVA SHEVA, INDIA". It only fills fields the first pass
# missed. The pipeline does not use it -- HybridExtractor sends those
# documents to the model instead, which is the stronger reading.

from sdoc.schemas import DocumentExtract          # noqa: E402

# Longest label first, so "shipper exporter" is tried before "shipper".
_PREFIX_RULES = [
    (field, re.compile(r"^\s*" + r"\s+".join(map(re.escape, label.split()))
                       + r"\b[ \t]+(?P<value>\S.*)$", re.I))
    for label, field in sorted(_LABEL_TO_FIELD.items(),
                               key=lambda kv: -len(kv[0]))
]


def _extract_separatorless(text: str, already: dict) -> dict:
    """Fill fields from lines a PDF stripped the colon out of."""
    found = {}
    for line in text.splitlines():
        if not line.strip() or line.startswith((" ", "\t")):
            continue
        if ":" in line or "|" in line:
            continue                       # pass one already had its chance
        ascii_line = "".join(c for c in line if ord(c) < 128)
        for field, pattern in _PREFIX_RULES:
            if field in already or field in found:
                continue
            hit = pattern.match(ascii_line)
            if hit:
                value = hit.group("value").strip()
                if not is_blank(value):
                    found[field] = ExtractedField(
                        field=field, raw_value=value, confidence=0.75,
                        label_found=None, snippet=line.strip())
                break
    return found


def extract_fields(text: str) -> dict:
    """Plain text -> {field: {"value", "label", "confidence"}}.

    A blank or placeholder value yields no entry at all, matching extract():
    a field that is not there is missing, which is not the same as a value.
    """
    doc = DocumentExtract(path="<text>", doc_role="UNKNOWN")
    doc.text = text or ""
    fields = extract(doc)
    fields.update(_extract_separatorless(doc.text, fields))
    return {name: {"value": f.raw_value, "label": f.label_found,
                   "confidence": f.confidence}
            for name, f in fields.items()}


class LabelExtractor:
    """Offline drop-in for GeminiExtractor. No key, no network, no quota."""

    name = "labels"

    def __call__(self, *docs) -> dict:
        result = {}
        for doc in docs:
            if doc is None or not doc.read_ok or not doc.text:
                continue
            fields = extract(doc)
            fields.update(_extract_separatorless(doc.text, fields))
            result[doc.path] = fields
        return result


class ChainExtractor:
    """Try each extractor in turn; keep the first that answers per document."""

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
