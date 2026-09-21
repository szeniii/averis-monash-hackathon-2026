"""Human-in-the-loop review interface.

The gate escalates the cases it cannot decide. Until a person can see those
cases and act on them, the escalation is just a label in a JSON file. This
serves the queue, the evidence behind each case, and the confirm/correct
actions that feed back into the report.

    python scripts/serve_review.py          # then open http://localhost:8000

Reads results.json (full pipeline output) and review_decisions.json (human
judgements). Writes only the latter -- re-running the pipeline never destroys
a review.
"""
from __future__ import annotations

import json
from pathlib import Path

from fastapi import FastAPI, HTTPException
from fastapi.responses import FileResponse
from fastapi.staticfiles import StaticFiles
from pydantic import BaseModel

from sdoc import results_io
from sdoc.documents import reader
from sdoc.loader import Inbox
from sdoc.review.apply import apply_all, apply_decision
from sdoc.review.store import ReviewStore
from sdoc.schemas import FIELDS

DATA_SOURCE = "data"
RESULTS_PATH = "results.json"
STATIC_DIR = Path(__file__).parent / "static"

app = FastAPI(title="Shipping Document Verification — Review")

_inbox = Inbox(DATA_SOURCE)
_store = ReviewStore()
_results = {}
_emails = {}


def _load_state() -> None:
    """Load pipeline output and the inbox into memory.

    The dataset is not committed, so on a deployed host data/ is usually
    absent. results.json alone is enough to review cases -- it carries the
    comparisons and the escalation reasons. Only the email body and the
    source-document viewer need the raw inbox, so its absence degrades those
    two panels rather than stopping the server from starting.
    """
    global _results, _emails
    _results = results_io.load(RESULTS_PATH) if results_io.exists(RESULTS_PATH) else {}
    try:
        _emails = {e["email_id"]: e for e in _inbox.emails()}
    except Exception:                                     # noqa: BLE001
        _emails = {}


_load_state()


# --------------------------------------------------------------------------
# request bodies
# --------------------------------------------------------------------------
class ReviewBody(BaseModel):
    decision: str                      # "confirm" | "correct"
    status: str | None = None          # required when correcting
    review_reason: str | None = None
    defect_fields: list[str] = []
    note: str = ""
    reviewer: str = "reviewer"


# --------------------------------------------------------------------------
# helpers
# --------------------------------------------------------------------------
def _summary(email_id: str, case) -> dict:
    email = _emails.get(email_id, {})
    decision = _store.get(email_id)
    return {
        "email_id": email_id,
        "subject": email.get("subject", ""),
        "from": email.get("from", ""),
        "category": case.category.value,
        "status": case.status.value,
        "review_reason": case.review_reason.value if case.review_reason else None,
        "escalation_detail": case.escalation_detail,
        "defect_fields": case.defect_fields,
        "reviewed": decision is not None,
        "decision": decision["decision"] if decision else None,
    }


def _case_or_404(email_id: str):
    case = _results.get(email_id)
    if case is None:
        raise HTTPException(404, f"{email_id} not found — has the pipeline run?")
    return case


# --------------------------------------------------------------------------
# endpoints
# --------------------------------------------------------------------------
@app.get("/api/stats")
def stats():
    pending = [eid for eid, c in _results.items()
               if c.status.value == "NEEDS_REVIEW" and _store.get(eid) is None]
    by_reason = {}
    for eid in pending:
        reason = _results[eid].review_reason
        key = reason.value if reason else "unspecified"
        by_reason[key] = by_reason.get(key, 0) + 1

    return {
        "total_cases": len(_results),
        "needs_review": sum(1 for c in _results.values()
                            if c.status.value == "NEEDS_REVIEW"),
        "pending": len(pending),
        "reviewed": _store.count(),
        "mismatches": sum(1 for c in _results.values() if c.has_defect),
        "pending_by_reason": by_reason,
        "pipeline_has_run": bool(_results),
    }


@app.get("/api/cases")
def list_cases(queue: str = "pending"):
    """queue: pending | reviewed | mismatch | all"""
    rows = []
    for email_id, case in _results.items():
        decision = _store.get(email_id)
        needs = case.status.value == "NEEDS_REVIEW"

        if queue == "pending" and not (needs and decision is None):
            continue
        if queue == "reviewed" and decision is None:
            continue
        if queue == "mismatch" and not case.has_defect:
            continue

        rows.append(_summary(email_id, case))

    rows.sort(key=lambda r: r["email_id"])
    return {"queue": queue, "count": len(rows), "cases": rows}


@app.get("/api/cases/{email_id}")
def get_case(email_id: str):
    """Everything a reviewer needs: the email, the seven fields, the reason."""
    case = _case_or_404(email_id)
    email = _emails.get(email_id, {})
    decision = _store.get(email_id)

    by_field = {c.field: c for c in case.comparisons}
    comparisons = []
    for name in FIELDS:
        comparison = by_field.get(name)
        if comparison is None:
            comparisons.append({
                "field": name, "status": "missing",
                "si_value": None, "bl_value": None,
                "si_label": None, "bl_label": None,
                "si_confidence": None, "bl_confidence": None,
                "reason": "field not extracted",
            })
            continue
        comparisons.append({
            "field": name,
            "status": comparison.status.value,
            "si_value": comparison.si.raw_value if comparison.si else None,
            "bl_value": comparison.bl.raw_value if comparison.bl else None,
            "si_label": comparison.si.label_found if comparison.si else None,
            "bl_label": comparison.bl.label_found if comparison.bl else None,
            "si_confidence": comparison.si.confidence if comparison.si else None,
            "bl_confidence": comparison.bl.confidence if comparison.bl else None,
            "reason": comparison.reason,
        })

    effective = apply_decision(case, decision) if decision else case

    return {
        "email_id": email_id,
        "subject": email.get("subject", ""),
        "from": email.get("from", ""),
        "body": email.get("body", ""),
        "attachments": email.get("attachments", []),
        "category": case.category.value,
        "category_confidence": case.category_confidence,
        "decided_by": case.decided_by,
        "pipeline": {
            "status": case.status.value,
            "review_reason": case.review_reason.value if case.review_reason else None,
            "escalation_detail": case.escalation_detail,
            "defect_fields": case.defect_fields,
        },
        "effective": {
            "status": effective.status.value,
            "review_reason": (effective.review_reason.value
                              if effective.review_reason else None),
            "defect_fields": effective.defect_fields,
            "human_reviewed": effective.human_reviewed,
        },
        "comparisons": comparisons,
        "review": decision,
    }


@app.get("/api/cases/{email_id}/documents")
def get_documents(email_id: str):
    """The raw SI and BL text, so a reviewer can check the machine's reading."""
    email = _emails.get(email_id)
    if email is None:
        # No inbox on this host -- the case itself is still reviewable.
        return {"email_id": email_id, "documents": [],
                "note": "source documents are not available on this deployment"}

    documents = []
    for path in email.get("attachments", []):
        doc = reader.read(_inbox, path)
        documents.append({
            "path": path,
            "role": doc.doc_role,
            "doc_type_detected": doc.doc_type_detected,
            "read_method": doc.read_method,
            "read_ok": doc.read_ok,
            "read_error": doc.read_error,
            "text": doc.text[:20000],
        })
    return {"email_id": email_id, "documents": documents}


@app.post("/api/cases/{email_id}/review")
def review_case(email_id: str, body: ReviewBody):
    """Confirm or correct a case. This is what updates the report."""
    case = _case_or_404(email_id)
    try:
        _store.record(
            email_id,
            body.decision,
            status=body.status,
            review_reason=body.review_reason,
            defect_fields=body.defect_fields,
            note=body.note,
            reviewer=body.reviewer,
        )
    except ValueError as exc:
        raise HTTPException(400, str(exc))

    updated = apply_decision(case, _store.get(email_id))
    return {
        "email_id": email_id,
        "status": updated.status.value,
        "review_reason": (updated.review_reason.value
                          if updated.review_reason else None),
        "defect_fields": updated.defect_fields,
        "human_reviewed": updated.human_reviewed,
    }


@app.delete("/api/cases/{email_id}/review")
def undo_review(email_id: str):
    """Put a case back in the queue."""
    return {"email_id": email_id, "cleared": _store.clear(email_id)}


@app.post("/api/export")
def export_submission(path: str = "submission.json"):
    """Rewrite submission.json with every human decision applied."""
    if not _results:
        raise HTTPException(400, "no results loaded — run the pipeline first")

    merged = apply_all(_results, _store)
    payload = {eid: case.to_submission() for eid, case in merged.items()}
    Path(path).write_text(json.dumps(payload, indent=2))

    changed = sum(1 for eid, case in merged.items()
                  if case.to_submission() != _results[eid].to_submission())
    return {
        "path": path,
        "entries": len(payload),
        "reviews_applied": _store.count(),
        "entries_changed": changed,
    }


@app.post("/api/reload")
def reload_state():
    """Pick up a fresh pipeline run without restarting the server."""
    _load_state()
    return {"reloaded": True, "cases": len(_results)}


@app.get("/")
def index():
    return FileResponse(STATIC_DIR / "index.html")


app.mount("/static", StaticFiles(directory=STATIC_DIR), name="static")
