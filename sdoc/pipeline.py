"""Stage orchestration: one email in, one CaseResult out.

    email -> classify -> (if comparison) read attachments -> extract
          -> compare -> decide -> CaseResult

Each stage is swappable. Passing a `classifier` lets you drop an LLM in
without touching anything else here.
"""
from __future__ import annotations

from sdoc.classify import rules
from sdoc.compare.comparator import compare
from sdoc.decide.gate import decide
from sdoc.documents import reader
from sdoc.schemas import CaseResult, Category, Status


def _pick(docs, role):
    for d in docs:
        if d.doc_role == role:
            return d
    return None


def process_email(inbox, email: dict, classifier=None,
                  extractor=None) -> CaseResult:
    case = CaseResult(email_id=email["email_id"])

    # --- stage 1: what kind of email is this? -----------------------------
    # The model leads: subjects here are coded strings and some are
    # deliberately misleading, so intent has to be read rather than matched.
    # The rule classifier stays as an emergency net -- a rate limit or an
    # outage should degrade the run, not end it.
    category, confidence, decided_by = None, 0.0, None
    if classifier is not None:
        category, confidence, decided_by = classifier(email)
    if category is None:
        category, confidence, decided_by = rules.classify(email)
    if category is None:
        category, confidence, decided_by = Category.GENERAL, 0.3, "fallback"

    case.category = category
    case.category_confidence = confidence
    case.decided_by = decided_by

    # Only comparison requests go further. Everything else is OK by
    # definition -- there is nothing to compare.
    if category is not Category.BL_COMPARISON:
        case.status = Status.OK
        return case

    attachments = email.get("attachments") or []

    # A comparison request with nothing attached is only an escalation when
    # the sender believed they attached something. "Please send me the draft
    # BL" is a normal request with nothing to compare.
    if not attachments:
        body = (email.get("body") or "").lower()
        claims_attachment = any(k in body for k in (
            "attach", "enclosed", "dropped", "herewith", "as per attached"))
        if claims_attachment:
            from sdoc.schemas import ReviewReason
            case.status = Status.NEEDS_REVIEW
            case.review_reason = ReviewReason.MISSING_ATTACHMENT
            case.escalation_detail = (
                "the email refers to attachments but none are present")
        else:
            case.status = Status.OK
        return case

    # --- stage 2: read the documents and pull the seven fields ------------
    docs = [reader.read(inbox, path) for path in attachments]
    if extractor is not None:
        # One request per email: the SI and BL travel together for speed, but
        # the prompt reads them as independent tasks so neither can influence
        # the other's values.
        read_fields = extractor(*docs)
        for doc in docs:
            doc.fields = read_fields.get(doc.path, {})

    si_doc, bl_doc = _pick(docs, "SI"), _pick(docs, "BL")
    # Filenames usually say which is which; fall back to the text itself.
    if si_doc is None or bl_doc is None:
        for doc in docs:
            if doc.doc_type_detected == "SHIPPING_INSTRUCTION" and si_doc is None:
                si_doc = doc
            elif doc.doc_type_detected == "BILL_OF_LADING" and bl_doc is None:
                bl_doc = doc

    # --- stage 3: compare -------------------------------------------------
    if si_doc is not None and bl_doc is not None:
        case.comparisons = compare(si_doc.fields, bl_doc.fields)

    # --- stage 4: report or escalate --------------------------------------
    return decide(case, si_doc, bl_doc)


def run_all(inbox, classifier=None, extractor=None, progress=True) -> dict:
    """Process every email. -> {email_id: CaseResult}"""
    emails = inbox.emails()
    results = {}
    for i, email in enumerate(emails, 1):
        try:
            results[email["email_id"]] = process_email(
                inbox, email, classifier, extractor)
        except Exception as exc:
            # A crash on one email must never lose the other 519. Failures
            # are visible, and the case goes to a human.
            from sdoc.schemas import ReviewReason
            case = CaseResult(email_id=email["email_id"],
                              category=Category.BL_COMPARISON)
            case.status = Status.NEEDS_REVIEW
            case.review_reason = ReviewReason.UNREADABLE
            case.escalation_detail = f"processing error: {exc}"
            results[email["email_id"]] = case
        if progress and i % 50 == 0:
            print(f"  ... {i}/{len(emails)}")
    return results
