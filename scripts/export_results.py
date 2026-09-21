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
                        help="skip Gemini entirely; makes no API calls")
    parser.add_argument("--rules-classify", action="store_true",
                        help="classify with rules only, spend every API "
                             "request on reading documents")
    parser.add_argument("--group", type=int, default=120,
                        help="documents per extraction request (default 10). "
                             "Higher spends fewer requests; lower is safer "
                             "if large prompts fail.")
    parser.add_argument("--results", default="results.json")
    parser.add_argument("--submission", default="submission.json")
    args = parser.parse_args()

    inbox = Inbox(args.source)
    emails = inbox.emails()
    print(f"{len(emails)} emails from {args.source}\n")

    # An empty source is a setup mistake, not a result. Running on it used to
    # write {} over results.json, which is how a good file was lost once.
    if not emails:
        print(f"! no emails found in {args.source!r} - nothing to do.")
        print(f"  Expected {args.source}/inbox/ to hold the email records.")
        print("  Set the dataset up first:  bash scripts/setup_data.sh")
        return 1

    classifier = extractor = None

    if args.no_llm:
        # Local parsing still reads most of this corpus, so "no API" should
        # not mean "no extraction". Without this the run compares nothing and
        # every case escalates as unreadable.
        from sdoc.extract.hybrid import HybridExtractor
        print("1. classifying (rules only, no API calls)")
        extractor = HybridExtractor(None)
    elif args.rules_classify:
        # The rule classifier scores 0.947 macro-F1 on this inbox, and
        # stage 1 is 30% of the score. Field extraction feeds end-to-end,
        # which is 50% -- and it cannot run at all without the API. When
        # requests are scarce, every one of them belongs to extraction.
        from sdoc.extract.hybrid import HybridExtractor
        from sdoc.extract.llm import GeminiExtractor
        print("1. classifying (rules only - saving quota for extraction)")
        extractor = HybridExtractor(GeminiExtractor())
    else:
        from sdoc.classify.llm import GeminiClassifier
        from sdoc.extract.llm import GeminiExtractor
        print("1. classifying")
        from sdoc.extract.hybrid import HybridExtractor
        classifier = GeminiClassifier()
        classifier.warm(emails)
        extractor = HybridExtractor(GeminiExtractor())

    # Read every document up front, several per request. The per-email loop
    # below then runs entirely from the extractor's cache and makes no calls
    # of its own -- ~26 requests instead of ~126.
    if extractor is not None:
        from sdoc.extract import warm
        print("\n2. reading documents")
        warm.warm(inbox, emails, extractor, group_size=args.group)

    if extractor is not None and hasattr(extractor, "summary"):
        print(f"  {extractor.summary()}")

    print("\n3. comparing")
    results = pipeline.run_all(inbox, classifier=classifier, extractor=extractor)

    if not results:
        print(f"\n! the pipeline produced no results - refusing to overwrite "
              f"{args.results} and {args.submission}.")
        return 1

    print("\n4. writing output")
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
    print("Review them in the app:  uvicorn web.app:app")


if __name__ == "__main__":
    sys.exit(main() or 0)
