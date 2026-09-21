"""Stage 1 (AI): classify emails with Gemini.

Why a model rather than keywords: subjects in this inbox are coded strings
like "AFEMY - CONAKRY_GUINEA - MONTER(MCLSIN6123859) - 5RCY-68239", some are
deliberately misleading, and the real request is often buried under a
forwarded thread and a signature block. Reading intent is the job.

Design notes
------------
* Batched. 520 emails one-per-call is slow and burns rate limit; we send
  BATCH_SIZE at a time and ask for one row back per email.
* Structured output. The model is constrained to a JSON schema, so we get
  a parseable answer instead of prose we have to regex.
* Cached to disk. Re-running the pipeline while you tune later stages must
  not re-pay for classification. Delete .cache/classify.json to force a
  fresh run.
* Fails soft. If the API errors, the caller falls back to the rule
  classifier rather than losing the whole run.

Setup
-----
    pip install google-genai python-dotenv
    echo GEMINI_API_KEY=your-key-here > .env
"""
from __future__ import annotations

import json
import os
import pathlib
import re
import time

from sdoc.schemas import Category

# .strip(): `set GEMINI_MODEL=x ` on Windows keeps the trailing
# space, and the API rejects the name as a bad format.
MODEL = os.environ.get("GEMINI_MODEL", "gemini-3.6-flash").strip()
# 60: the free tier allows 20 requests per day PER MODEL, and
# 520 emails at 60 the inbox classifies in 9 calls, leaving room for extraction.
BATCH_SIZE = 60
CACHE_PATH = pathlib.Path(".cache/classify.json")

# A 503 ("high demand") or a 429 clears on its own; a bad key never will.
# Retrying the first and latching on the second is the whole distinction.
MAX_RETRIES = 3

# Checked FIRST, because a quota error's body contains a retry delay like
# "4.926294033s" -- and a bare substring search for "403" finds one inside
# that float. Transient always wins.
TRANSIENT_MARKERS = ("RESOURCE_EXHAUSTED", "UNAVAILABLE", "DEADLINE",
                     "INTERNAL", "timeout", "429", "500", "503")

PERMANENT_MARKERS = ("UNAUTHENTICATED", "PERMISSION_DENIED",
                     "API_KEY_INVALID", "NOT_FOUND", "INVALID_ARGUMENT")


def _is_permanent(exc: Exception) -> bool:
    """True when retrying cannot possibly help (bad key, bad model name)."""
    message = str(exc)
    if any(marker.lower() in message.lower() for marker in TRANSIENT_MARKERS):
        return False
    # Status names, not bare numbers -- numbers appear in retry delays.
    return any(marker in message for marker in PERMANENT_MARKERS)

SYSTEM_PROMPT = """\
You are triaging the inbox of a shipping documentation team at a paper
exporter. Assign each email exactly one category.

BL_COMPARISON - the sender wants an SI checked against a draft Bill of
  Lading, or wants a draft BL verified, confirmed or amended. Phrases like
  "to confirm docs", "please check the details", "compare the SI and draft
  BL", "draft BL for your confirmation". Also use this when the sender asks
  for a draft BL to be produced for a shipment.

SI_REQUEST - the sender is asking for a Shipping Instruction to be prepared,
  submitted or sent. The subject often starts with "SI -" or contains
  "REQUEST SI", "CUST SI", "SI NEEDED".

INVOICE_QUERY - anything about money: invoices, billing, local charges, THC,
  demurrage and detention, freight amounts, credit or debit notes,
  cancelling or correcting an invoice.

GENERAL - internal operational traffic that needs no document action:
  status summaries, berthing reports, vessel schedules, system or bot
  notices, SLA reminders, HR and holiday announcements, plain acknowledgements.

SPAM - unsolicited commercial or fraudulent mail: prizes, lotteries,
  parcel-fee scams, mailbox-full phishing, crypto offers.

Rules:
- Judge by the NEWEST message. Ignore quoted or forwarded history below
  markers like "From:", "________" or ">".
- Ignore signature blocks, disclaimers and external-sender warning banners.
- The subject line can be misleading. If the subject and the body disagree,
  trust the body.
- Attachments named _SI and _BL are strong evidence of BL_COMPARISON, but an
  email with no attachments can still be BL_COMPARISON.
- confidence is 0.0-1.0: how sure you are. Use below 0.6 when genuinely torn.

Return one object per email, in the same order you received them."""

RESPONSE_SCHEMA = {
    "type": "object",
    "properties": {
        "results": {
            "type": "array",
            "items": {
                "type": "object",
                "properties": {
                    "email_id": {"type": "string"},
                    "category": {
                        "type": "string",
                        "enum": [c.value for c in Category],
                    },
                    "confidence": {"type": "number"},
                    "reason": {"type": "string"},
                },
                "required": ["email_id", "category", "confidence"],
            },
        }
    },
    "required": ["results"],
}


def _trim_body(body: str, limit: int = 1200) -> str:
    """Keep the newest message only, and cap its length.

    Sending whole forwarded chains wastes tokens and buries the signal.
    """
    for marker in (r"\n_{5,}", r"\nFrom:\s", r"\n-{3,}\s*Original Message",
                   r"\nOn .{0,60}wrote:", r"\n>{1,}\s"):
        hit = re.search(marker, body)
        if hit:
            body = body[:hit.start()]
            break
    return body.strip()[:limit]


def _render(email: dict) -> str:
    names = [a.split("/")[-1] for a in (email.get("attachments") or [])]
    return (
        f"<email id=\"{email['email_id']}\">\n"
        f"from: {email.get('from', '')}\n"
        f"subject: {email.get('subject', '')}\n"
        f"attachments: {', '.join(names) if names else 'none'}\n"
        f"body:\n{_trim_body(email.get('body') or '')}\n"
        f"</email>"
    )


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


class GeminiClassifier:
    """Callable that classifies a whole inbox, then answers per email.

    Usage:
        clf = GeminiClassifier()
        clf.warm(inbox.emails())        # one pass, batched + cached
        category, confidence, by = clf(email)
    """

    def __init__(self, api_key: str | None = None, model: str = MODEL):
        self.model = model
        self.cache = _load_cache()
        self._client = None
        self._warned = False
        self._failed = False
        self._key = api_key or os.environ.get("GEMINI_API_KEY")

    # -- lazy so importing this module never requires the SDK -------------
    def _client_or_none(self):
        if self._client is not None:
            return self._client
        if not self._key:
            if not self._warned:
                self._warned = True
                print("  ! GEMINI_API_KEY is not set - no classification "
                      "will happen.\n"
                      "    Windows:  set GEMINI_API_KEY=your-key-here\n"
                      "    (only applies to the window you type it in)")
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

    def _classify_batch(self, emails: list, attempt: int = 0) -> dict:
        # _failed is only ever set by an error retrying cannot fix, so
        # stopping here does not throw away recoverable work.
        if self._failed:
            return {}
        client = self._client_or_none()
        if client is None:
            return {}

        from google.genai import types

        prompt = "\n\n".join(_render(e) for e in emails)
        try:
            response = client.models.generate_content(
                model=self.model,
                contents=prompt,
                config=types.GenerateContentConfig(
                    system_instruction=SYSTEM_PROMPT,
                    response_mime_type="application/json",
                    response_schema=RESPONSE_SCHEMA,
                    temperature=0.0,      # same input -> same answer
                ),
            )
            payload = json.loads(response.text)
        except Exception as exc:
            # Bad key or bad model name: every further call fails the same
            # way, so stop the whole run rather than hammering the API.
            if _is_permanent(exc):
                if not self._failed:
                    self._failed = True
                    print(f"  ! Gemini unavailable, not retrying: {exc}")
                    print("    Everything falls back to the rule classifier.")
                return {}

            # Transient (503 high demand, 429 rate limit, network blip).
            # Back off and try this batch again.
            if attempt < MAX_RETRIES:
                delay = 2 ** attempt
                print(f"    retrying in {delay}s ({exc.__class__.__name__})")
                time.sleep(delay)
                return self._classify_batch(emails, attempt + 1)

            # Out of retries. Give up on THIS batch only -- the next one
            # still gets its own attempts, and the cache means a re-run
            # picks up exactly what is missing.
            print(f"  ! batch of {len(emails)} failed after "
                  f"{MAX_RETRIES} retries: {exc}")
            return {}

        out = {}
        for row in payload.get("results", []):
            try:
                out[row["email_id"]] = {
                    "category": Category(row["category"]).value,
                    "confidence": float(row.get("confidence", 0.5)),
                    "reason": row.get("reason", ""),
                }
            except (KeyError, ValueError):
                continue
        return out

    def warm(self, emails: list) -> None:
        """Classify everything not already cached. Call once before run_all."""
        todo = [e for e in emails if e["email_id"] not in self.cache]
        if not todo:
            print(f"  classification: all {len(emails)} cached")
            return
        print(f"  classification: {len(todo)} to do "
              f"({len(emails) - len(todo)} cached), batches of {BATCH_SIZE}")
        for i in range(0, len(todo), BATCH_SIZE):
            batch = todo[i:i + BATCH_SIZE]
            self.cache.update(self._classify_batch(batch))
            print(f"    {min(i + BATCH_SIZE, len(todo))}/{len(todo)}")
            _save_cache(self.cache)

    def __call__(self, email: dict):
        """-> (Category, confidence, "llm") or (None, 0.0, None) if unknown."""
        hit = self.cache.get(email["email_id"])
        if hit is None:
            hit = self._classify_batch([email]).get(email["email_id"])
            if hit:
                self.cache[email["email_id"]] = hit
                _save_cache(self.cache)
        if hit is None:
            return None, 0.0, None
        return Category(hit["category"]), hit["confidence"], "llm"
