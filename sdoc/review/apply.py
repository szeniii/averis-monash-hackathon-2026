"""Replay human decisions over the pipeline's results.

This is the "report updates" half of the use case: once a person confirms or
corrects a case, the report and the submission must reflect their judgement,
not the machine's original guess.

Kept as a pure function over a copy so the pipeline output is never mutated
in place -- you can always see what the system said before a human touched it.
"""
from __future__ import annotations

import copy

from sdoc.schemas import (CaseResult, FieldComparison, FieldStatus,
                          ReviewReason, Status)


def apply_decision(case: CaseResult, decision: dict) -> CaseResult:
    """Return a new CaseResult with the reviewer's judgement applied."""
    if not decision:
        return case

    reviewed = copy.deepcopy(case)
    reviewed.human_reviewed = True

    if decision.get("decision") == "confirm":
        # The reviewer agreed. The verdict stands; it is simply no longer
        # waiting on anybody.
        note = decision.get("note")
        if note:
            reviewed.escalation_detail = (
                f"{reviewed.escalation_detail or ''} | confirmed: {note}".strip(" |"))
        return reviewed

    # --- correct ---------------------------------------------------------
    status = decision.get("status")
    if status:
        reviewed.status = Status(status)

    if reviewed.status is Status.NEEDS_REVIEW:
        reason = decision.get("review_reason")
        reviewed.review_reason = ReviewReason(reason) if reason else None
    else:
        reviewed.review_reason = None

    if reviewed.status is Status.MISMATCH:
        _force_defect_fields(reviewed, decision.get("defect_fields") or [])
    elif reviewed.status is Status.OK:
        # Nothing differs: every field that was flagged is now a match.
        for comparison in reviewed.comparisons:
            comparison.status = FieldStatus.MATCH

    who = decision.get("reviewer", "reviewer")
    note = decision.get("note", "")
    reviewed.escalation_detail = (
        f"corrected by {who}" + (f": {note}" if note else ""))
    return reviewed


def _force_defect_fields(case: CaseResult, fields: list) -> None:
    """Make the comparison list agree with the reviewer's chosen fields.

    CaseResult.defect_fields is derived from per-field statuses, so setting
    the status is what actually changes the submission. Fields the reviewer
    did not name become MATCH; named fields become MISMATCH, and one is
    created if the pipeline never produced a row for it.
    """
    wanted = set(fields)
    seen = set()

    for comparison in case.comparisons:
        seen.add(comparison.field)
        comparison.status = (FieldStatus.MISMATCH
                             if comparison.field in wanted
                             else FieldStatus.MATCH)

    for name in wanted - seen:
        case.comparisons.append(
            FieldComparison(field=name, status=FieldStatus.MISMATCH,
                            reason="added by human reviewer"))


def apply_all(results: dict, store) -> dict:
    """{email_id: CaseResult} + ReviewStore -> {email_id: CaseResult}."""
    return {
        email_id: apply_decision(case, store.get(email_id))
        for email_id, case in results.items()
    }
