"""Persist full CaseResults to disk and read them back.

submission.json is deliberately narrow -- five keys the scorer reads. That is
not enough to review a case: a human needs the SI value, the BL value, the
label each was found under and why the gate escalated.

This module round-trips the whole CaseResult so the review interface can be a
separate process from the pipeline. Without it the evidence dies with the
Python process that produced it.
"""
from __future__ import annotations

import json
from pathlib import Path

from sdoc.schemas import (CaseResult, Category, ExtractedField,
                          FieldComparison, FieldStatus, ReviewReason, Status)

DEFAULT_PATH = "results.json"


# --------------------------------------------------------------------------
# dump
# --------------------------------------------------------------------------
def _field_to_dict(field: ExtractedField | None):
    if field is None:
        return None
    return {
        "field": field.field,
        "raw_value": field.raw_value,
        "normalized_value": field.normalized_value,
        "confidence": field.confidence,
        "label_found": field.label_found,
        "snippet": field.snippet,
    }


def _comparison_to_dict(comparison: FieldComparison) -> dict:
    return {
        "field": comparison.field,
        "si": _field_to_dict(comparison.si),
        "bl": _field_to_dict(comparison.bl),
        "status": comparison.status.value,
        "reason": comparison.reason,
    }


def case_to_dict(case: CaseResult) -> dict:
    return {
        "email_id": case.email_id,
        "category": case.category.value,
        "category_confidence": case.category_confidence,
        "decided_by": case.decided_by,
        "status": case.status.value,
        "review_reason": case.review_reason.value if case.review_reason else None,
        "escalation_detail": case.escalation_detail,
        "human_reviewed": case.human_reviewed,
        "comparisons": [_comparison_to_dict(c) for c in case.comparisons],
    }


def dump(results, path: str = DEFAULT_PATH) -> str:
    """results is {email_id: CaseResult} or a list of CaseResult."""
    cases = results.values() if isinstance(results, dict) else results
    payload = {case.email_id: case_to_dict(case) for case in cases}
    Path(path).write_text(json.dumps(payload, indent=2))
    return path


# --------------------------------------------------------------------------
# load
# --------------------------------------------------------------------------
def _field_from_dict(data):
    if data is None:
        return None
    return ExtractedField(
        field=data.get("field", ""),
        raw_value=data.get("raw_value"),
        normalized_value=data.get("normalized_value"),
        confidence=data.get("confidence", 0.0),
        label_found=data.get("label_found"),
        snippet=data.get("snippet"),
    )


def case_from_dict(data: dict) -> CaseResult:
    case = CaseResult(
        email_id=data["email_id"],
        category=Category(data["category"]),
        category_confidence=data.get("category_confidence", 0.0),
        decided_by=data.get("decided_by"),
        status=Status(data["status"]),
        review_reason=(ReviewReason(data["review_reason"])
                       if data.get("review_reason") else None),
        escalation_detail=data.get("escalation_detail"),
        human_reviewed=data.get("human_reviewed", False),
    )
    case.comparisons = [
        FieldComparison(
            field=c["field"],
            si=_field_from_dict(c.get("si")),
            bl=_field_from_dict(c.get("bl")),
            status=FieldStatus(c["status"]),
            reason=c.get("reason"),
        )
        for c in data.get("comparisons", [])
    ]
    return case


def load(path: str = DEFAULT_PATH) -> dict:
    """-> {email_id: CaseResult}"""
    raw = json.loads(Path(path).read_text())
    return {eid: case_from_dict(data) for eid, data in raw.items()}


def exists(path: str = DEFAULT_PATH) -> bool:
    return Path(path).exists()
