"""Where human review decisions live.

The pipeline's verdict and a human's verdict are kept apart on purpose. The
pipeline can be re-run at any time -- new prompt, new thresholds, new model --
and the reviews must survive that. So decisions are stored against email_id
in their own file and replayed over whatever the pipeline last produced.

Two decisions exist:

  confirm  the reviewer agrees with the gate; the case leaves the queue with
           the pipeline's own verdict, now marked human_reviewed.
  correct  the reviewer overrides it, supplying the true status and, for a
           mismatch, the fields that actually differ.

An audit trail matters more than it looks: "who decided this and why" is the
first question anyone asks about an automated check that got something wrong.
"""
from __future__ import annotations

import json
from datetime import datetime, timezone
from pathlib import Path

DEFAULT_PATH = "review_decisions.json"

VALID_DECISIONS = {"confirm", "correct"}
VALID_STATUSES = {"OK", "MISMATCH", "NEEDS_REVIEW"}
VALID_REASONS = {"wrong_doc_type", "missing_attachment",
                 "unreadable", "missing_value"}


class ReviewStore:
    """Append-only-ish JSON store of review decisions, keyed by email_id."""

    def __init__(self, path: str = DEFAULT_PATH):
        self.path = Path(path)
        self._decisions = {}
        if self.path.exists():
            try:
                self._decisions = json.loads(self.path.read_text())
            except json.JSONDecodeError:
                # A corrupt file must not stop the reviewer working. Keep the
                # broken copy for inspection rather than overwriting it.
                self.path.rename(self.path.with_suffix(".corrupt.json"))
                self._decisions = {}

    # -- read ------------------------------------------------------------
    def get(self, email_id: str):
        return self._decisions.get(email_id)

    def all(self) -> dict:
        return dict(self._decisions)

    def count(self) -> int:
        return len(self._decisions)

    def reviewed_ids(self) -> set:
        return set(self._decisions)

    # -- write -----------------------------------------------------------
    def record(self, email_id: str, decision: str, *, status=None,
               review_reason=None, defect_fields=None, note="",
               reviewer="reviewer") -> dict:
        """Store one decision. Raises ValueError on an invalid combination."""
        if decision not in VALID_DECISIONS:
            raise ValueError(f"decision must be one of {sorted(VALID_DECISIONS)}")

        if decision == "correct":
            if status not in VALID_STATUSES:
                raise ValueError(f"status must be one of {sorted(VALID_STATUSES)}")
            if status == "MISMATCH" and not defect_fields:
                raise ValueError(
                    "a corrected MISMATCH must name the fields that differ")
            if status == "NEEDS_REVIEW" and review_reason not in VALID_REASONS:
                raise ValueError(
                    f"NEEDS_REVIEW needs a reason: {sorted(VALID_REASONS)}")
            if status != "MISMATCH":
                defect_fields = []
            if status != "NEEDS_REVIEW":
                review_reason = None

        entry = {
            "email_id": email_id,
            "decision": decision,
            "status": status,
            "review_reason": review_reason,
            "defect_fields": list(defect_fields or []),
            "note": note,
            "reviewer": reviewer,
            "decided_at": datetime.now(timezone.utc).isoformat(timespec="seconds"),
        }
        self._decisions[email_id] = entry
        self._save()
        return entry

    def clear(self, email_id: str) -> bool:
        """Undo a review, putting the case back in the queue."""
        if email_id in self._decisions:
            del self._decisions[email_id]
            self._save()
            return True
        return False

    def _save(self) -> None:
        # Write to a temporary file then replace, so an interrupted save
        # cannot leave a half-written file behind.
        tmp = self.path.with_suffix(".tmp")
        tmp.write_text(json.dumps(self._decisions, indent=2))
        tmp.replace(self.path)
