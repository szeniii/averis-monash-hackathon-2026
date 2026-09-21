"""Shared data contract for the SDOC pipeline.

Every stage imports from here. Treat changes as breaking and tell the team.

The vocabulary (categories, statuses, review reasons) is fixed by the
organisers' sample_submission.json -- do not invent new values.
"""
from __future__ import annotations

from dataclasses import dataclass, field
from enum import Enum
from typing import Optional

# The seven fields compared between the SI and the BL, in report order.
FIELDS = [
    "shipper",
    "consignee",
    "notify_party",
    "port_of_loading",
    "port_of_discharge",
    "container_count",
    "gross_weight_kg",
]


class Category(str, Enum):
    """What kind of email this is. Exactly one per email."""
    BL_COMPARISON = "BL_COMPARISON"
    SI_REQUEST = "SI_REQUEST"
    INVOICE_QUERY = "INVOICE_QUERY"
    GENERAL = "GENERAL"
    SPAM = "SPAM"


class Status(str, Enum):
    """Headline outcome for a comparison request."""
    OK = "OK"                      # compared cleanly, all seven agree
    MISMATCH = "MISMATCH"          # compared cleanly, at least one differs
    NEEDS_REVIEW = "NEEDS_REVIEW"  # could not compare -> escalate to a human


class ReviewReason(str, Enum):
    """Why a case was escalated. Required when status is NEEDS_REVIEW."""
    WRONG_DOC_TYPE = "wrong_doc_type"          # the "BL" is an invoice, etc.
    MISSING_ATTACHMENT = "missing_attachment"  # no BL to compare against
    UNREADABLE = "unreadable"                  # scan / empty / corrupt file
    MISSING_VALUE = "missing_value"            # field blank: N/A, ???, ____


class FieldStatus(str, Enum):
    """Per-field outcome.

    The four-way split is the heart of the design: a value we could not read
    is NOT a discrepancy. Collapsing UNREADABLE/MISSING into MISMATCH is how
    you generate false alarms, which the scoring punishes.
    """
    MATCH = "match"
    MISMATCH = "mismatch"
    UNREADABLE = "unreadable"
    MISSING = "missing"


@dataclass
class ExtractedField:
    """One field pulled out of one document."""
    field: str
    raw_value: Optional[str] = None         # exactly as printed in the doc
    normalized_value: Optional[str] = None  # canonical form used to compare
    confidence: float = 0.0
    label_found: Optional[str] = None       # the label text we matched on
    snippet: Optional[str] = None           # evidence shown to a human


@dataclass
class DocumentExtract:
    """Everything we got out of one attachment."""
    path: str
    doc_role: str = "UNKNOWN"          # "SI" | "BL" | "UNKNOWN"
    doc_type_detected: Optional[str] = None  # e.g. "COMMERCIAL INVOICE"
    read_method: str = "plain_text"    # plain_text | pdf | docx | xlsx | vision
    read_ok: bool = True
    read_error: Optional[str] = None
    text: str = ""
    fields: dict = field(default_factory=dict)  # name -> ExtractedField


@dataclass
class FieldComparison:
    """The SI value and the BL value for one field, and the verdict."""
    field: str
    si: Optional[ExtractedField] = None
    bl: Optional[ExtractedField] = None
    status: FieldStatus = FieldStatus.MISSING
    reason: Optional[str] = None


@dataclass
class CaseResult:
    """The full result for one email. Serialises to one submission entry."""
    email_id: str
    category: Category = Category.GENERAL
    category_confidence: float = 0.0
    decided_by: Optional[str] = None       # "rule" | "llm" -- diagnostic only
    status: Status = Status.OK
    review_reason: Optional[ReviewReason] = None
    comparisons: list = field(default_factory=list)  # list[FieldComparison]
    escalation_detail: Optional[str] = None
    human_reviewed: bool = False

    @property
    def defect_fields(self) -> list:
        if self.status is not Status.MISMATCH:
            return []
        return [c.field for c in self.comparisons
                if c.status is FieldStatus.MISMATCH]

    @property
    def has_defect(self) -> bool:
        return self.status is Status.MISMATCH

    def to_submission(self) -> dict:
        """The exact shape the scoring server expects."""
        return {
            "category": self.category.value,
            "status": self.status.value,
            "review_reason": self.review_reason.value if self.review_reason else None,
            "defect_fields": self.defect_fields,
            "has_defect": self.has_defect,
            "decided_by": self.decided_by,
        }
