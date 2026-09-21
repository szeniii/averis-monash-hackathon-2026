"""Stage 3: compare the SI and BL values for each of the seven fields.

No AI here, on purpose. The model reads the documents; this module decides.
That makes every flag reproducible and explainable -- which is what a
document-verification tool actually needs, and it removes any chance of a
hallucinated discrepancy.

The SI is the reference. The BL is checked against it.
"""
from __future__ import annotations

from sdoc.compare.normalize import normalize, party_similarity
from sdoc.schemas import FIELDS, FieldComparison, FieldStatus

# Party names: above HIGH it's the same company, below LOW it's a different
# one, and the band in between is genuinely uncertain -> escalate.
PARTY_SAME = 0.95
PARTY_DIFFERENT = 0.70
PARTY_FIELDS = {"shipper", "consignee", "notify_party"}

WEIGHT_TOLERANCE_KG = 0.5


def _compare_one(field_name, si_field, bl_field) -> FieldComparison:
    cmp = FieldComparison(field=field_name, si=si_field, bl=bl_field)

    # Absent from a document entirely, or present but blank (N/A, ____).
    si_missing = si_field is None or si_field.raw_value is None
    bl_missing = bl_field is None or bl_field.raw_value is None
    if si_missing or bl_missing:
        cmp.status = FieldStatus.MISSING
        which = "SI" if si_missing else "BL"
        if si_missing and bl_missing:
            which = "both documents"
        cmp.reason = f"{field_name} not provided in {which}"
        return cmp

    si_value = normalize(field_name, si_field.raw_value)
    bl_value = normalize(field_name, bl_field.raw_value)
    si_field.normalized_value = str(si_value) if si_value is not None else None
    bl_field.normalized_value = str(bl_value) if bl_value is not None else None

    # Normalisation itself failed -- we read characters but cannot interpret
    # them. Not a discrepancy; a reading problem.
    if si_value is None or bl_value is None:
        cmp.status = FieldStatus.UNREADABLE
        cmp.reason = f"could not interpret {field_name} value"
        return cmp

    if field_name == "gross_weight_kg":
        cmp.status = (FieldStatus.MATCH
                      if abs(si_value - bl_value) <= WEIGHT_TOLERANCE_KG
                      else FieldStatus.MISMATCH)
        return cmp

    if field_name in PARTY_FIELDS:
        if si_value == bl_value:
            cmp.status = FieldStatus.MATCH
            return cmp
        score = party_similarity(si_value, bl_value)
        if score >= PARTY_SAME:
            cmp.status = FieldStatus.MATCH
        elif score <= PARTY_DIFFERENT:
            cmp.status = FieldStatus.MISMATCH
        else:
            cmp.status = FieldStatus.UNREADABLE   # uncertain -> human decides
            cmp.reason = (f"{field_name} names are {score:.0%} similar - "
                          f"too close to call automatically")
        return cmp

    cmp.status = (FieldStatus.MATCH if si_value == bl_value
                  else FieldStatus.MISMATCH)
    return cmp


def compare(si_fields: dict, bl_fields: dict) -> list:
    """-> list[FieldComparison], one per field, always all seven, in order."""
    return [_compare_one(name, si_fields.get(name), bl_fields.get(name))
            for name in FIELDS]
