#!/usr/bin/env python3
"""Start the human review interface.

    python scripts/serve_review.py              # http://localhost:8000
    python scripts/serve_review.py --port 8001

Needs results.json, which holds the full pipeline output (evidence included).
If it is missing, build it with:

    python scripts/export_results.py
"""
import argparse
import pathlib
import sys

sys.path.insert(0, str(pathlib.Path(__file__).resolve().parent.parent))

from sdoc import results_io     # noqa: E402


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument("--host", default="127.0.0.1")
    parser.add_argument("--port", type=int, default=8000)
    args = parser.parse_args()

    if not results_io.exists():
        print("! results.json not found - the queue will be empty.")
        print("  Build it first:  python scripts/export_results.py\n")

    import uvicorn
    print(f"Review interface: http://{args.host}:{args.port}\n")
    uvicorn.run("api.main:app", host=args.host, port=args.port, reload=False)


if __name__ == "__main__":
    main()
