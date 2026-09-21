"""Stage 1 (rules): classify an email from its subject and body.

Deliberately cheap and deterministic. It handles the clearly-signposted
emails so the LLM only sees the ambiguous ones -- fewer API calls, faster
runs, and every rule decision is explainable.

Returns (Category, confidence, "rule") or (None, 0.0, None) when unsure,
in which case the caller should fall back to the LLM classifier.

TUNE THIS by reading real emails:
    python scripts/peek.py 40
Add patterns you see. Do not tune it against ground_truth.json.
"""
from __future__ import annotations

import re

from sdoc.schemas import Category

# --- spam: consumer-scam language that never appears in shipping ops -------
SPAM_PATTERNS = [
    r"\bcongratulation", r"\byou have won\b", r"\bprize\b", r"\blottery\b",
    r"\bclaim your\b", r"\bgift card\b", r"\bcrypto", r"\bbitcoin\b",
    r"mailbox (is )?full", r"storage (is )?full", r"verify your (account|password)",
    r"account (has been )?suspend", r"click (here|the link) (to|below)",
    r"unclaimed (parcel|package)", r"(customs|delivery) fee of",
    r"\burgent(ly)? (wire|transfer)\b", r"\bunsubscribe\b.*\bwinner\b",
]

# --- invoice / billing queries --------------------------------------------
INVOICE_PATTERNS = [
    r"\binvoice\b", r"\bbilling\b", r"\bdebit note\b", r"\bcredit note\b",
    r"local charges", r"\bthc\b", r"d\s*&\s*d charges", r"demurrage",
    r"detention charge", r"total freight", r"\bmissing gr\b",
    r"cancel invoice", r"\bpayment\b.*\boutstanding\b", r"\bstatement of account\b",
]

# --- requests to PREPARE a new SI (no comparison wanted) ------------------
SI_REQUEST_PATTERNS = [
    r"\brequest si\b", r"\bcust si\b", r"\bsi needed\b", r"\bneed si\b",
    r"\bsend (us )?the si\b", r"\bprepare (the )?si\b",
    r"\bshipping instruction\b.*\b(request|needed|please (send|prepare))\b",
    r"^si\s*[-_]", r"\bsi submission\b", r"\bkindly submit si\b",
]

# --- document comparison requests -----------------------------------------
BL_COMPARISON_PATTERNS = [
    r"to confirm docs", r"\bconfirm (the )?docs\b",
    r"request bl draft", r"\bdraft bl\b", r"\bbl draft\b",
    r"\bcompare\b.*\b(si|bl)\b", r"\b(si|bl)\b.*\bcompare\b",
    r"check (the )?(details|si|bl|draft)", r"\bverify (the )?(si|bl|draft)\b",
    r"\bamend(ment)?\b.*\bbl\b", r"\bbl\b.*\bamend",
    r"attached are the si and", r"\bsi and (the )?draft bl\b",
]

# --- operational noise: notifications, reports, HR ------------------------
GENERAL_PATTERNS = [
    r"update summary", r"berthing report", r"\bsla\b", r"_rpa_",
    r"out of office", r"public holiday", r"\bholiday notice\b",
    r"system maintenance", r"\bweekly report\b", r"\bmeeting\b",
    r"\bvessel schedule\b", r"\breminder\b.*\bdeadline\b",
]

_ORDER = [
    (Category.SPAM, SPAM_PATTERNS, 0.95),
    (Category.BL_COMPARISON, BL_COMPARISON_PATTERNS, 0.90),
    (Category.SI_REQUEST, SI_REQUEST_PATTERNS, 0.88),
    (Category.INVOICE_QUERY, INVOICE_PATTERNS, 0.88),
    (Category.GENERAL, GENERAL_PATTERNS, 0.80),
]


def _body_without_thread(body: str) -> str:
    """Drop quoted/forwarded history.

    Bodies contain forwarded threads and signatures. Classifying on the whole
    blob means an old quoted invoice query can outvote the actual request.
    We keep everything above the first forward marker.
    """
    markers = [
        r"\n_{5,}", r"\nFrom:\s", r"\n-{3,}\s*Original Message",
        r"\nOn .{0,60}wrote:", r"\n>{1,}\s",
    ]
    cut = len(body)
    for m in markers:
        hit = re.search(m, body)
        if hit:
            cut = min(cut, hit.start())
    return body[:cut]


def classify(email: dict):
    """-> (Category | None, confidence, "rule" | None)"""
    subject = (email.get("subject") or "").lower()
    body = _body_without_thread(email.get("body") or "").lower()
    has_attachments = bool(email.get("attachments"))

    # Subject carries the strongest signal; weight it by checking it first.
    for scope, weight in ((subject, 1.0), (body, 0.92)):
        for category, patterns, base in _ORDER:
            for pattern in patterns:
                if re.search(pattern, scope):
                    conf = base * weight
                    # An SI+BL pair attached is near-proof of a comparison.
                    if has_attachments and category is not Category.BL_COMPARISON:
                        conf *= 0.75
                    return category, conf, "rule"

    # No pattern hit. Attachments alone still imply a comparison request.
    if has_attachments:
        return Category.BL_COMPARISON, 0.60, "rule"

    return None, 0.0, None
