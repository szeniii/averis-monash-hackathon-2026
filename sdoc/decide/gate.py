"""The decision gate: report a result, or escalate to a human.

This is the component the use case cares most about -- "when it cannot
complete the task on its own, escalate to a person with the relevant context,
rather than guessing or failing silently."

It is ordinary code, not AI. It consumes the per-field verdicts and decides
between OK, MISMATCH and NEEDS_REVIEW. Escalation order matters: the most
fundamental problem wins, so a missing BL is reported as missing_attachment
rather than as seven missing fields.
"""
from __future__ import annotations

from sdoc.schemas import (CaseResult, FieldStatus, ReviewReason, Status)

MIN_FIELDS_FOR_CONFIDENT_COMPARE = 5  # of 7


def decide(case: CaseResult, si_doc=None, bl_doc=None) -> CaseResult:
    """Set case.status / review_reason / escalation_detail. Returns the case."""

    # 1. No document to compare against.
    if si_doc is None or bl_doc is None:
        which = "SI" if si_doc is None else "BL"
        if si_doc is None and bl_doc is None:
            which = "SI and BL"
        return _escalate(case, ReviewReason.MISSING_ATTACHMENT,
                         f"{which} attachment not present on the email")

    # 2. An attachment is the wrong kind of document (an invoice, say).
    for doc in (si_doc, bl_doc):
        detected = doc.doc_type_detected
        if detected in {"COMMERCIAL_INVOICE", "PACKING_LIST",
                        "CERTIFICATE_OF_ORIGIN", "DEBIT_NOTE"}:
            return _escalate(
                case, ReviewReason.WRONG_DOC_TYPE,
                f"{doc.path} is a {detected.replace('_', ' ').title()}, "
                f"not a {doc.doc_role or 'shipping document'}")

    # 3. A file we could not read at all (scan, empty, corrupt).
    for doc in (si_doc, bl_doc):
        if not doc.read_ok:
            return _escalate(case, ReviewReason.UNREADABLE,
                             f"{doc.path}: {doc.read_error}")

    comparisons = case.comparisons

    # 4. Too little of the document came through to judge it.
    usable = sum(1 for c in comparisons
                 if c.status in (FieldStatus.MATCH, FieldStatus.MISMATCH))
    if usable < MIN_FIELDS_FOR_CONFIDENT_COMPARE:
        return _escalate(
            case, ReviewReason.UNREADABLE,
            f"only {usable} of 7 fields could be compared - "
            f"the documents did not parse cleanly")

    # 5. A value is blank in one document. Blank is uncertainty, NOT a
    #    discrepancy -- this is the single most important rule here.
    blank = [c.field for c in comparisons if c.status is FieldStatus.MISSING]
    if blank:
        return _escalate(case, ReviewReason.MISSING_VALUE,
                         "blank or missing in one document: " + ", ".join(blank))

    # 6. A value we read but could not confidently interpret or match.
    unclear = [c for c in comparisons if c.status is FieldStatus.UNREADABLE]
    if unclear:
        return _escalate(
            case, ReviewReason.UNREADABLE,
            "; ".join(c.reason or f"{c.field} unclear" for c in unclear))

    # 7. All seven compared cleanly.
    mismatched = [c.field for c in comparisons
                  if c.status is FieldStatus.MISMATCH]
    case.status = Status.MISMATCH if mismatched else Status.OK
    case.review_reason = None
    case.escalation_detail = None
    return case


def _escalate(case: CaseResult, reason: ReviewReason, detail: str) -> CaseResult:
    case.status = Status.NEEDS_REVIEW
    case.review_reason = reason
    case.escalation_detail = detail
    return case
