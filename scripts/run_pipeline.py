"""Run every email through the pipeline and write submission.json.

    python scripts/run_pipeline.py                      # local bundle
    python scripts/run_pipeline.py http://localhost:8080  # the server

Classification is warmed in one batched pass first, so the per-email loop
makes no API calls and is fast to re-run while tuning later stages.
"""
import pathlib
import sys
from collections import Counter

# let this script find the sdoc package when run from the repo root
sys.path.insert(0, str(pathlib.Path(__file__).resolve().parent.parent))

from sdoc import pipeline, submission
from sdoc.classify.llm import GeminiClassifier
from sdoc.config import describe, load_env
from sdoc.extract.llm import GeminiExtractor
from sdoc.loader import Inbox                    

SOURCE = sys.argv[1] if len(sys.argv) > 1 else "data/sdoc-hackathon-bundle"


def main():
    load_env()                       # picks up GEMINI_API_KEY from .env
    print(f"   {describe()}\n")

    inbox = Inbox(SOURCE)
    emails = inbox.emails()
    print(f"{len(emails)} emails from {SOURCE}\n")

    print("1. classifying")
    classifier = GeminiClassifier()
    classifier.warm(emails)

    print("\n2. reading documents and comparing")
    extractor = GeminiExtractor()
    results = pipeline.run_all(inbox, classifier=classifier,
                               extractor=extractor)

    print("\n3. writing submission")
    path = submission.write(results, "submission.json")
    print(f"   {path}  ({len(results)} entries)")

    cats = Counter(r.category.value for r in results.values())
    stats = Counter(r.status.value for r in results.values())
    reasons = Counter(r.review_reason.value for r in results.values()
                      if r.review_reason)
    decided = Counter(r.decided_by for r in results.values())

    print("\n   categories     ", dict(cats))
    print("   statuses       ", dict(stats))
    print("   review reasons ", dict(reasons))
    print("   decided by     ", dict(decided))
    print("\nNow score it:  python scripts/score.py")


if __name__ == "__main__":
    main()
