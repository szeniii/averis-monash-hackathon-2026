"""HTTP service around the SDOC pipeline.

    uvicorn web.app:app --reload        # http://localhost:8000

What it exposes is the part of the use case a score cannot show: the
seven-field report side by side, and a review queue where a person confirms
or corrects a case the system would not decide on its own.

The comparison and decision stages are pure Python, so everything here works
with no API key. Setting GEMINI_API_KEY upgrades stage 2 from label matching
to model reading; the chain falls back per document, never as a whole run.
"""
from __future__ import annotations

import os
import pathlib
import sys
import uuid
from datetime import datetime, timezone

from fastapi import FastAPI, File, HTTPException, UploadFile
from fastapi.responses import FileResponse
from fastapi.staticfiles import StaticFiles
from pydantic import BaseModel

sys.path.insert(0, str(pathlib.Path(__file__).resolve().parent.parent))

from sdoc.config import describe, load_env                      # noqa: E402

load_env()   # GEMINI_API_KEY from .env, unless the host already set it

from sdoc.compare.comparator import compare                      # noqa: E402
from sdoc.decide.gate import decide                              # noqa: E402
from sdoc.documents import reader                                # noqa: E402
from sdoc.extract.labels import ChainExtractor, LabelExtractor   # noqa: E402
from sdoc.schemas import (CaseResult, Category, DocumentExtract,  # noqa: E402
                          ExtractedField, FIELDS)
from web import demo_cases                                       # noqa: E402

STATIC = pathlib.Path(__file__).resolve().parent / "static"
MAX_UPLOAD_BYTES = 2 * 1024 * 1024

app = FastAPI(title="Shipping Document Verification",
              description="SI vs draft BL comparison with human review",
              version="0.1.0")


# --- extraction engine ----------------------------------------------------

def _build_extractor():
    """Gemini when a key is present, label matching either way."""
    labels = LabelExtractor()
    if not os.environ.get("GEMINI_API_KEY"):
        return labels, "labels"
    try:
        from sdoc.extract.llm import GeminiExtractor
        return ChainExtractor(GeminiExtractor(), labels), "gemini+labels"
    except Exception:
        return labels, "labels"


EXTRACTOR, ENGINE = _build_extractor()
print(f"  extraction: {describe()}")

# Review queue. In-memory on purpose: this is a demonstration surface, and
# a restart losing the queue is the correct trade for having no database.
CASES: dict = {}


# --- request bodies -------------------------------------------------------

class ComparePayload(BaseModel):
    si_text: str = ""
    bl_text: str = ""
    si_name: str = "pasted_SI.txt"
    bl_name: str = "pasted_BL.txt"


class ResolvePayload(BaseModel):
    field: str
    si_value: str | None = None
    bl_value: str | None = None


# --- helpers --------------------------------------------------------------

class _MemoryInbox:
    """Just enough of the Inbox interface for reader.read()."""

    def __init__(self, blobs: dict):
        self.blobs = blobs

    def read_bytes(self, path: str) -> bytes:
        return self.blobs[path]


def _doc_from_text(path: str, text: str, role: str) -> DocumentExtract:
    doc = DocumentExtract(path=path, doc_role=role, read_method="plain_text")
    doc.text = text or ""
    if len(doc.text.strip()) < reader.MIN_USEFUL_CHARS:
        doc.read_ok = False
        doc.read_error = (f"only {len(doc.text.strip())} characters of text "
                          f"- nothing usable to compare")
        return doc
    doc.doc_type_detected = reader._detect_doc_type(doc.text)
    return doc


def _serialise(case: CaseResult, si_doc, bl_doc) -> dict:
    rows = []
    for cmp in case.comparisons:
        rows.append({
            "field": cmp.field,
            "status": cmp.status.value,
            "reason": cmp.reason,
            "si_raw": cmp.si.raw_value if cmp.si else None,
            "si_label": cmp.si.label_found if cmp.si else None,
            "si_normalized": cmp.si.normalized_value if cmp.si else None,
            "bl_raw": cmp.bl.raw_value if cmp.bl else None,
            "bl_label": cmp.bl.label_found if cmp.bl else None,
            "bl_normalized": cmp.bl.normalized_value if cmp.bl else None,
        })
    return {
        "case_id": case.email_id,
        "status": case.status.value,
        "review_reason": case.review_reason.value if case.review_reason else None,
        "escalation_detail": case.escalation_detail,
        "has_defect": case.has_defect,
        "defect_fields": case.defect_fields,
        "human_reviewed": case.human_reviewed,
        "engine": ENGINE,
        "documents": [
            {"role": "SI", "path": si_doc.path if si_doc else None,
             "read_ok": si_doc.read_ok if si_doc else False,
             "read_error": si_doc.read_error if si_doc else "not supplied",
             "doc_type_detected": si_doc.doc_type_detected if si_doc else None,
             "read_method": si_doc.read_method if si_doc else None},
            {"role": "BL", "path": bl_doc.path if bl_doc else None,
             "read_ok": bl_doc.read_ok if bl_doc else False,
             "read_error": bl_doc.read_error if bl_doc else "not supplied",
             "doc_type_detected": bl_doc.doc_type_detected if bl_doc else None,
             "read_method": bl_doc.read_method if bl_doc else None},
        ],
        "fields": rows,
    }


def _run(si_doc, bl_doc, case_id: str | None = None) -> dict:
    """Extract, compare, decide, and file the case in the review queue."""
    case_id = case_id or f"case_{uuid.uuid4().hex[:8]}"
    case = CaseResult(email_id=case_id, category=Category.BL_COMPARISON)

    read_fields = EXTRACTOR(si_doc, bl_doc) or {}
    for doc in (si_doc, bl_doc):
        if doc is not None:
            doc.fields = read_fields.get(doc.path, {})

    if si_doc is not None and bl_doc is not None:
        case.comparisons = compare(si_doc.fields, bl_doc.fields)

    decide(case, si_doc, bl_doc)

    CASES[case_id] = {
        "case": case,
        "si_doc": si_doc,
        "bl_doc": bl_doc,
        "created_at": datetime.now(timezone.utc).isoformat(timespec="seconds"),
        "corrections": [],
    }
    return _serialise(case, si_doc, bl_doc)


# --- routes ---------------------------------------------------------------

@app.get("/health")
def health():
    return {"ok": True, "engine": ENGINE, "cases_held": len(CASES),
            "gemini_key_present": bool(os.environ.get("GEMINI_API_KEY")),
            "fields": FIELDS}


@app.get("/api/demo")
def demo_listing():
    return {"cases": demo_cases.listing()}


@app.post("/api/demo/{demo_id}")
def run_demo(demo_id: str):
    case = demo_cases.BY_ID.get(demo_id)
    if case is None:
        raise HTTPException(404, f"no demo case called {demo_id!r}")
    return _run(_doc_from_text(f"{demo_id}_SI.txt", case["si"], "SI"),
                _doc_from_text(f"{demo_id}_BL.txt", case["bl"], "BL"))


@app.post("/api/compare")
def compare_text(payload: ComparePayload):
    if not payload.si_text.strip() and not payload.bl_text.strip():
        raise HTTPException(400, "paste an SI and a BL to compare")
    si = _doc_from_text(payload.si_name, payload.si_text, "SI") \
        if payload.si_text.strip() else None
    bl = _doc_from_text(payload.bl_name, payload.bl_text, "BL") \
        if payload.bl_text.strip() else None
    return _run(si, bl)


@app.post("/api/compare/upload")
async def compare_upload(si_file: UploadFile | None = File(None),
                         bl_file: UploadFile | None = File(None)):
    if si_file is None and bl_file is None:
        raise HTTPException(400, "attach an SI, a BL, or both")

    blobs, docs = {}, {}
    for role, upload in (("SI", si_file), ("BL", bl_file)):
        if upload is None:
            docs[role] = None
            continue
        data = await upload.read()
        if len(data) > MAX_UPLOAD_BYTES:
            raise HTTPException(
                413, f"{upload.filename} is larger than the 2 MB limit")
        name = upload.filename or f"upload_{role}.txt"
        # The reader picks its parser from the extension, and the role from
        # the _SI / _BL marker, so the stored name carries both.
        stem, dot, ext = name.rpartition(".")
        path = f"{stem or name}_{role}.{ext or 'txt'}"
        blobs[path] = data
        docs[role] = path

    inbox = _MemoryInbox(blobs)
    si = reader.read(inbox, docs["SI"]) if docs.get("SI") else None
    bl = reader.read(inbox, docs["BL"]) if docs.get("BL") else None
    return _run(si, bl)


@app.get("/api/cases")
def list_cases():
    out = []
    for case_id, entry in sorted(CASES.items(),
                                 key=lambda kv: kv[1]["created_at"],
                                 reverse=True):
        case = entry["case"]
        out.append({
            "case_id": case_id,
            "status": case.status.value,
            "review_reason": case.review_reason.value if case.review_reason else None,
            "escalation_detail": case.escalation_detail,
            "defect_fields": case.defect_fields,
            "human_reviewed": case.human_reviewed,
            "corrections": len(entry["corrections"]),
            "created_at": entry["created_at"],
        })
    return {"cases": out,
            "open": sum(1 for c in out
                        if c["status"] == "NEEDS_REVIEW"
                        and not c["human_reviewed"])}


@app.get("/api/cases/{case_id}")
def get_case(case_id: str):
    entry = CASES.get(case_id)
    if entry is None:
        raise HTTPException(404, f"no case called {case_id!r}")
    payload = _serialise(entry["case"], entry["si_doc"], entry["bl_doc"])
    payload["corrections"] = entry["corrections"]
    return payload


@app.post("/api/cases/{case_id}/resolve")
def resolve_case(case_id: str, payload: ResolvePayload):
    """A person supplies the value the system could not read, and the case
    is decided again from the corrected evidence."""
    entry = CASES.get(case_id)
    if entry is None:
        raise HTTPException(404, f"no case called {case_id!r}")
    if payload.field not in FIELDS:
        raise HTTPException(400, f"{payload.field!r} is not one of the seven")

    si_doc, bl_doc = entry["si_doc"], entry["bl_doc"]
    if si_doc is None or bl_doc is None:
        raise HTTPException(409, "this case has no pair of documents to correct")

    for doc, value in ((si_doc, payload.si_value), (bl_doc, payload.bl_value)):
        if value is None:
            continue
        doc.fields[payload.field] = ExtractedField(
            field=payload.field, raw_value=value.strip() or None,
            confidence=1.0, label_found="entered by reviewer",
            snippet=f"reviewer: {value.strip()}")

    entry["corrections"].append({
        "field": payload.field,
        "si_value": payload.si_value,
        "bl_value": payload.bl_value,
        "at": datetime.now(timezone.utc).isoformat(timespec="seconds"),
    })

    case = CaseResult(email_id=case_id, category=Category.BL_COMPARISON)
    case.human_reviewed = True
    case.comparisons = compare(si_doc.fields, bl_doc.fields)
    decide(case, si_doc, bl_doc)
    entry["case"] = case

    payload_out = _serialise(case, si_doc, bl_doc)
    payload_out["corrections"] = entry["corrections"]
    return payload_out


@app.post("/api/cases/{case_id}/confirm")
def confirm_case(case_id: str):
    """A person accepts the result as it stands and closes the case."""
    entry = CASES.get(case_id)
    if entry is None:
        raise HTTPException(404, f"no case called {case_id!r}")
    entry["case"].human_reviewed = True
    return _serialise(entry["case"], entry["si_doc"], entry["bl_doc"])


@app.get("/")
def index():
    return FileResponse(STATIC / "index.html")


app.mount("/static", StaticFiles(directory=STATIC), name="static")
