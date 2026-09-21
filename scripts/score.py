"""Send submission.json to the local scoring server and print the scoreboard.

    docker compose up --build        # in the sdoc-hackathon-docker folder
    python scripts/score.py

The server holds the answers privately and returns only your score.
"""
import json
import pathlib
import sys

sys.path.insert(0, str(pathlib.Path(__file__).resolve().parent.parent))

from sdoc.loader import Inbox        # noqa: E402

SERVER = "http://localhost:8080"
SUBMISSION = sys.argv[1] if len(sys.argv) > 1 else "submission.json"


def main():
    path = pathlib.Path(SUBMISSION)
    if not path.exists():
        print(f"{SUBMISSION} not found - run scripts/run_pipeline.py first")
        return

    sub = json.loads(path.read_text())
    print(f"submitting {len(sub)} entries to {SERVER}\n")

    try:
        r = Inbox(SERVER).submit(sub)
    except Exception as exc:
        print(f"could not reach the scoring server: {exc}")
        print("Is docker running?  curl http://localhost:8080/health")
        return

    print(f"  FINAL SCORE          {r['final_score']:.4f}")
    print()
    print(f"  end-to-end (50%)     {r['end_to_end']['rate']:.4f}"
          f"   ({r['end_to_end']['success']}/{r['end_to_end']['total']}"
          f" defects caught exactly)")
    print(f"  classify   (30%)     {r['stage1']['macro_f1']:.4f}"
          f"   macro-F1   (accuracy {r['stage1']['accuracy']:.4f})")
    print(f"  defects    (20%)     {r['stage3']['defect_f1']:.4f}"
          f"   F1   (precision {r['stage3']['defect_precision']:.3f},"
          f" recall {r['stage3']['defect_recall']:.3f})")
    print()
    rel = r["reliability"]
    print(f"  escalation           recall {rel['escalation_recall']:.3f}"
          f"  precision {rel['escalation_precision']:.3f}"
          f"   (flagged {rel['pred_review']}, actually {rel['gold_review']})")
    print(f"    by reason          {rel['per_reason']}")
    print()
    print("  per-category F1")
    for cat, v in r["stage1"]["per"].items():
        tp, fp, fn = v["tp"], v["fp"], v["fn"]
        prec = tp / (tp + fp) if (tp + fp) else 0.0
        rec = tp / (tp + fn) if (tp + fn) else 0.0
        f1 = 2 * prec * rec / (prec + rec) if (prec + rec) else 0.0
        print(f"    {cat:<16} F1 {f1:.3f}   tp={tp:<4} fp={fp:<4} fn={fn}")


if __name__ == "__main__":
    main()
