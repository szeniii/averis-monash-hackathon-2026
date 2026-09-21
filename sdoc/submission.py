"""Turn CaseResults into the JSON the scoring server expects.

The submission format is a boundary concern: it is produced here and nowhere
else, so the rest of the pipeline is free to model the problem however it
likes.
"""
from __future__ import annotations

import json


def build(results: dict) -> dict:
    """{email_id: CaseResult} -> {email_id: {...}}"""
    return {eid: case.to_submission() for eid, case in results.items()}


def write(results: dict, path: str = "submission.json") -> str:
    data = build(results)
    with open(path, "w", encoding="utf-8") as fh:
        json.dump(data, fh, indent=2)
    return path


def check(submission: dict, sample: dict) -> list:
    """Verify every email_id is present with the right keys. -> problems."""
    problems = []
    missing = set(sample) - set(submission)
    extra = set(submission) - set(sample)
    if missing:
        problems.append(f"{len(missing)} email_ids missing, e.g. {sorted(missing)[:3]}")
    if extra:
        problems.append(f"{len(extra)} unexpected email_ids, e.g. {sorted(extra)[:3]}")
    required = {"category", "status", "review_reason", "defect_fields", "has_defect"}
    for eid, entry in list(submission.items())[:600]:
        absent = required - set(entry)
        if absent:
            problems.append(f"{eid} missing keys: {sorted(absent)}")
            break
    return problems
