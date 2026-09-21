#!/usr/bin/env python3
"""Run the pipeline and save the FULL results, not just the submission.

    python scripts/export_results.py            # uses data/
    python scripts/export_results.py --no-llm   # rules only, no API calls

submission.json keeps only the five scored keys, which is not enough to
review anything. This writes results.json with the per-field comparisons,
the labels each value was found under and the escalation detail -- the
evidence a human needs to confirm or correct a case.
"""
import argparse
import pathlib
import sys
from collections import Counter

sys.path.insert(0, str(pathlib.Path(__file__).resolve().parent.parent))

from sdoc import pipeline, results_io, submission   # noqa: E402
from sdoc.loader import Inbox                       # noqa: E402


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument("source", nargs="?", default="data")
    parser.add_argument("--no-llm", action="store_true",
                        help="skip Gemini; rules only, makes no API calls")
    parser.add_argument("--results", default="results.json")
    parser.add_argument("--submission", default="submission.json")
    args = parser.parse_args()

    inbox = Inbox(args.source)
    emails = inbox.emails()
    print(f"{len(emails)} emails from {args.source}\n")

    classifier = extractor = None
    if not args.no_llm:
        from sdoc.classify.llm import GeminiClassifier
        from sdoc.extract.llm import GeminiExtractor
        print("1. classifying")
        classifier = GeminiClassifier()
        classifier.warm(emails)
        extractor = GeminiExtractor()
    else:
        print("1. classifying (rules only)")

    print("\n2. reading documents and comparing")
    results = pipeline.run_all(inbox, classifier=classifier, extractor=extractor)

    print("\n3. writing output")
    results_io.dump(results, args.results)
    submission.write(results, args.submission)
    print(f"   {args.results}     (full evidence, for the review interface)")
    print(f"   {args.submission}  (five scored keys, for the scorer)")

    statuses = Counter(case.status.value for case in results.values())
    reasons = Counter(case.review_reason.value for case in results.values()
                      if case.review_reason)
    print(f"\n   statuses       {dict(statuses)}")
    print(f"   review reasons {dict(reasons)}")
    print(f"\n{statuses.get('NEEDS_REVIEW', 0)} cases are waiting for a human.")
    print("Review them:  python scripts/serve_review.py")


if __name__ == "__main__":
    main()
