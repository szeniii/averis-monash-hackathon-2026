"""Stage 2: read the seven shipment fields out of a document with Gemini.

A lookup table of label spellings only works while the labels are ones you
listed. Here the SI and BL name the same field differently on every pair, and
a third of the documents are PDF, Word or Excel whose text comes out as
fragmented table cells rather than "Label: value" lines. Reading meaning is
the job, so the model does it.

Two rules the prompt enforces, both of which protect the comparison:

* Each document is read INDEPENDENTLY. Showing the model an SI and a BL and
  asking for both at once invites it to reconcile them - quietly "fixing" a
  consignee that genuinely differs, which is the exact defect we exist to
  find. They travel in one request for speed, never as one task.

* Values come back EXACTLY as printed. Tidying "22,000 KG" into 22000 is
  sdoc.compare.normalize's job, and keeping the raw string means a human
  reviewing an escalation sees what the document actually said.

Setup:  pip install google-genai   +   GEMINI_API_KEY in the environment
"""
from __future__ import annotations

import json
import os
import pathlib
import time

from sdoc.schemas import ExtractedField, FIELDS

# .strip(): `set GEMINI_MODEL=x ` on Windows keeps the trailing
# space, and the API rejects the name as a bad format.
MODEL = os.environ.get("GEMINI_MODEL", "gemini-3.6-flash").strip()
CACHE_PATH = pathlib.Path(".cache/extract.json")
MAX_CHARS = 6000          # a shipping document is far shorter than this
MAX_RETRIES = 4           # a rate limit is temporary, not fatal
BASE_DELAY = 2.0          # seconds, doubled each retry
MIN_INTERVAL = 0.6        # seconds between calls, to stay under the RPM cap

SYSTEM_PROMPT = """\
You read shipping documents and report seven fields from each.

The documents are Shipping Instructions (SI) and draft Bills of Lading (BL).
The same field is labelled differently from document to document - "Port of
Loading", "Load Port" and "POL" are the same field; "Consignee", "Consignee
(Non-Negotiable)" and "To the Order of" are the same field; "Gross Weight
(KG)", "Gross Wt (kgs)" and bilingual variants are the same field. Identify
fields by meaning, not by the label text.

The seven fields:
  shipper             the exporter / consignor - COMPANY NAME ONLY
  consignee           who receives the cargo - COMPANY NAME ONLY
  notify_party        who is notified on arrival - COMPANY NAME ONLY
  port_of_loading     where the cargo is loaded
  port_of_discharge   where the cargo is discharged
  container_count     number of containers
  gross_weight_kg     total gross weight

Rules, in order of importance:

1. Read each document on its own. Documents in the same request are unrelated
   tasks. NEVER let a value in one document influence what you report for
   another, even when they look like a pair. Reporting what you think the
   value "should" be destroys the purpose of this system.

2. Report the value EXACTLY as printed, including commas, units and case:
   "131,058 KG", "6 x 40'HC", "NHAVA SHEVA, INDIA (INNSA)". Do not convert,
   round, expand or tidy anything.

3. Party fields are the COMPANY NAME ONLY. The address block printed beneath
   a party name is not part of the value - leave it out.

4. If a field is absent, or printed as a blank placeholder (N/A, NA, ???,
   ____, TBA, TBC, -), set present=false and value=null. A blank is missing
   information, not a value. Never guess, never infer from context, never
   copy from elsewhere in the document.

5. Do not confuse gross weight with net weight or tare weight. Only gross.

6. container_count is the number of containers. From "6 x 40'HC" the field
   value is the whole printed string "6 x 40'HC" - do not reduce it.

7. label_in_document is the label text you matched, copied verbatim, or null
   if the value was not labelled.

8. confidence 0.0-1.0 is how certain you are this is that field's value.
   Use below 0.5 when the text is garbled or the layout is ambiguous. Low
   confidence sends the case to a human, which is the correct outcome when
   you are unsure - do not inflate it."""

_FIELD_ITEM = {
    "type": "object",
    "properties": {
        "name": {"type": "string", "enum": [
            "shipper", "consignee", "notify_party", "port_of_loading",
            "port_of_discharge", "container_count", "gross_weight_kg"]},
        "value": {"type": "string", "nullable": True},
        "label_in_document": {"type": "string", "nullable": True},
        "present": {"type": "boolean"},
        "confidence": {"type": "number"},
    },
    "required": ["name", "present", "confidence"],
}

RESPONSE_SCHEMA = {
    "type": "object",
    "properties": {
        "documents": {
            "type": "array",
            "items": {
                "type": "object",
                "properties": {
                    "path": {"type": "string"},
                    "fields": {"type": "array", "items": _FIELD_ITEM},
                },
                "required": ["path", "fields"],
            },
        }
    },
    "required": ["documents"],
}


def _load_cache() -> dict:
    if CACHE_PATH.exists():
        try:
            return json.loads(CACHE_PATH.read_text())
        except Exception:
            return {}
    return {}


def _save_cache(cache: dict) -> None:
    CACHE_PATH.parent.mkdir(parents=True, exist_ok=True)
    CACHE_PATH.write_text(json.dumps(cache, indent=2))


def _render(doc) -> str:
    return (f"<document path=\"{doc.path}\" kind=\"{doc.doc_role}\">\n"
            f"{doc.text[:MAX_CHARS]}\n</document>")


class GeminiExtractor:
    """Reads the seven fields out of DocumentExtract objects.

        extractor = GeminiExtractor()
        fields = extractor(si_doc, bl_doc)[si_doc.path]
    """

    def __init__(self, api_key: str | None = None, model: str = MODEL):
        self.model = model
        self.cache = _load_cache()
        self._client = None
        self._warned = False
        self._consecutive_failures = 0
        self._last_call = 0.0
        self._key = api_key or os.environ.get("GEMINI_API_KEY")

    def _client_or_none(self):
        if self._client is not None:
            return self._client
        if not self._key:
            if not self._warned:
                self._warned = True
                print("  ! GEMINI_API_KEY is not set - fields cannot be read.\n"
                      "    Windows:  set GEMINI_API_KEY=your-key-here")
            return None
        try:
            from google import genai
            self._client = genai.Client(api_key=self._key)
        except ImportError:
            if not self._warned:
                self._warned = True
                print("  ! google-genai is not installed.\n"
                      "    Run:  python -m pip install google-genai")
            return None
        except Exception as exc:
            if not self._warned:
                self._warned = True
                print(f"  ! Gemini unavailable ({exc})")
            return None
        return self._client

    def _ask(self, docs: list) -> dict:
        """-> {path: {field_name: {...}}} for the documents actually answered.

        Returns {} on failure. The caller must NOT cache that: an empty
        answer from a rate limit is not a fact about the document.
        """
        if self._consecutive_failures >= 6:
            return {}                       # the API is properly down
        client = self._client_or_none()
        if client is None:
            return {}

        from google.genai import types

        # stay under the requests-per-minute cap
        gap = time.time() - self._last_call
        if gap < MIN_INTERVAL:
            time.sleep(MIN_INTERVAL - gap)

        payload = None
        for attempt in range(MAX_RETRIES):
            try:
                response = client.models.generate_content(
                    model=self.model,
                    contents="\n\n".join(_render(d) for d in docs),
                    config=types.GenerateContentConfig(
                        system_instruction=SYSTEM_PROMPT,
                        response_mime_type="application/json",
                        response_schema=RESPONSE_SCHEMA,
                        temperature=0.0,
                    ),
                )
                self._last_call = time.time()
                payload = json.loads(response.text)
                self._consecutive_failures = 0
                break
            except Exception as exc:
                self._last_call = time.time()
                message = str(exc)
                transient = any(t in message for t in
                                ("429", "RESOURCE_EXHAUSTED", "503", "500",
                                 "UNAVAILABLE", "DEADLINE", "timeout", "Timeout"))
                if transient and attempt < MAX_RETRIES - 1:
                    wait = BASE_DELAY * (2 ** attempt)
                    print(f"    rate limited, waiting {wait:.0f}s "
                          f"(attempt {attempt + 2}/{MAX_RETRIES})")
                    time.sleep(wait)
                    continue
                self._consecutive_failures += 1
                if self._consecutive_failures <= 3:
                    print(f"  ! extraction failed: {message[:160]}")
                return {}

        if payload is None:
            return {}

        out = {}
        for entry in payload.get("documents", []):
            path = entry.get("path")
            if not path:
                continue
            fields = {}
            for row in entry.get("fields", []):
                name = row.get("name")
                if name not in FIELDS:
                    continue
                present = bool(row.get("present")) and row.get("value") not in (None, "")
                fields[name] = {
                    "value": row.get("value") if present else None,
                    "label": row.get("label_in_document"),
                    "confidence": float(row.get("confidence", 0.0)) if present else 0.0,
                }
            if fields:                      # never record an empty answer
                out[path] = fields
        return out

    def __call__(self, *docs) -> dict:
        """Read one or more documents. -> {path: {field: ExtractedField}}"""
        docs = [d for d in docs if d is not None and d.read_ok and d.text]
        if not docs:
            return {}

        pending = [d for d in docs if d.path not in self.cache]
        if pending:
            answered = self._ask(pending)
            if answered:
                # Only real answers are cached. A failed call leaves the
                # document uncached so the next run retries it, instead of
                # recording a rate limit as "this document has no fields".
                self.cache.update(answered)
                _save_cache(self.cache)

        result = {}
        for d in docs:
            raw = self.cache.get(d.path) or {}
            fields = {}
            for name, item in raw.items():
                fields[name] = ExtractedField(
                    field=name,
                    raw_value=item.get("value"),
                    normalized_value=None,
                    confidence=item.get("confidence", 0.0),
                    label_found=item.get("label"),
                    snippet=(f"{item.get('label')}: {item.get('value')}"
                             if item.get("value") else None),
                )
            result[d.path] = fields
        return result
