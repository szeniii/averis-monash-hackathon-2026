"""Pre-read every document in a few large requests instead of many small ones.

The pipeline calls the extractor once per email, which is two documents per
request and ~126 requests for this inbox. On a free-tier key capped at 20
requests a day that never finishes.

Nothing about the extractor needs to change: it already accepts any number of
documents per call and caches by path. So we read all the documents up front
in groups, fill the cache, and let the per-email loop run entirely from it --
same results, an order of magnitude fewer requests.

This mirrors GeminiClassifier.warm(), which does the same thing for stage 1.
"""
from __future__ import annotations

from sdoc.documents import reader

# Documents per request. Each is truncated to MAX_CHARS (6000) by the
# extractor, so 10 is a comfortable prompt; raise it to spend fewer requests,
# lower it if large prompts start failing.
GROUP_SIZE = 10


def collect_documents(inbox, emails, extractor, progress: bool = True) -> list:
    """Read every uncached attachment into memory. Makes no API calls."""
    paths = [path for email in emails for path in (email.get("attachments") or [])]
    todo = [p for p in paths if p not in extractor.cache]

    if progress:
        cached = len(paths) - len(todo)
        print(f"  documents: {len(todo)} to read ({cached} already cached)")

    docs = []
    for path in todo:
        doc = reader.read(inbox, path)
        # Unreadable files never reach the model; the gate escalates them.
        if doc.read_ok and doc.text:
            docs.append(doc)
    return docs


def warm(inbox, emails, extractor, group_size: int = GROUP_SIZE,
         progress: bool = True) -> int:
    """Fill the extractor's cache in batched requests. -> requests made."""
    docs = collect_documents(inbox, emails, extractor, progress)
    if not docs:
        if progress:
            print("  nothing to extract - cache is complete")
        return 0

    requests = 0
    for start in range(0, len(docs), group_size):
        batch = docs[start:start + group_size]
        extractor(*batch)
        requests += 1
        if progress:
            done = min(start + group_size, len(docs))
            print(f"    {done}/{len(docs)} documents  ({requests} requests)")

    if progress:
        saved = len(docs) // 2 - requests   # the old cost was ~1 call per email
        print(f"  {requests} requests instead of ~{len(docs) // 2} "
              f"({saved} fewer)")
    return requests
