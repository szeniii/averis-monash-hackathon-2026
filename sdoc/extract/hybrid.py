"""Field extraction: deterministic parse first, Gemini for what it cannot read.

The seven fields have to come out of four file formats with no shared layout.
Two very different problems hide behind that:

  A "Label: value" document.  Mapping "Port of Loading" to port_of_loading is
    a lookup. A model adds latency and cost and cannot be more correct than a
    table, so the table does it.

  A PDF bill of lading.  Labels have no delimiter ("Shipper APRIL FINE PAPER
    TRADING"), values run across several lines, and gross weight lives in a
    table keyed by container number. There is no rule that reads this; the
    meaning has to be understood. Gemini does it.

So the model is not a fallback in the apologetic sense -- it is the only thing
that can read roughly a tenth of this corpus, and those documents fail
entirely without it. Routing by difficulty is also what makes it affordable:
a few requests per run instead of one per email, which is the difference
between a pipeline that runs on a free key and one that does not.

A document that neither path can read (a scan with no text layer) is reported
as unreadable and escalated, never guessed at.
"""
from __future__ import annotations

from collections import Counter

from sdoc.extract import labels

# Below this many of the seven fields, a local parse is not trustworthy and
# the document goes to the model.
MIN_LOCAL_FIELDS = 5

# Documents per model request. Only the documents the parser could not read
# ever get here, so this is a handful of requests for the whole inbox.
LLM_GROUP_SIZE = 10


class HybridExtractor:
    """Same interface as GeminiExtractor: call it with documents, get fields.

        extractor = HybridExtractor(GeminiExtractor())
        fields = extractor(si_doc, bl_doc)[si_doc.path]
    """

    def __init__(self, llm=None, min_local_fields: int = MIN_LOCAL_FIELDS,
                 llm_group_size: int = LLM_GROUP_SIZE):
        self.llm = llm
        self.min_local_fields = min_local_fields
        self.llm_group_size = llm_group_size
        self.stats = Counter()
        self.llm_requests = 0
        self._results = {}          # path -> {field: ExtractedField}

    @property
    def cache(self) -> dict:
        """Everything already resolved, by either route.

        warm.py reads this to skip documents that are done, so local parses
        count as cached too -- they cost nothing but they are still answers.
        """
        return self._results

    def __call__(self, *docs) -> dict:
        docs = [d for d in docs if d is not None and d.read_ok and d.text]
        if not docs:
            return {}

        pending, resolved = [], {}

        for doc in docs:
            if doc.path in self._results:
                resolved[doc.path] = self._results[doc.path]
                continue

            found = labels.extract(doc)
            if len(found) >= self.min_local_fields:
                resolved[doc.path] = found
                self._results[doc.path] = found
                self.stats["parsed"] += 1
            else:
                # Keep what the parse did find: if the model cannot answer
                # for this document, a partial result still beats nothing.
                pending.append((doc, found))

        if pending and self.llm is not None:
            answered = {}
            # Chunk here rather than at the caller: only hard documents reach
            # the model, so batching them together is what keeps the request
            # count to a handful.
            for start in range(0, len(pending), self.llm_group_size):
                chunk = pending[start:start + self.llm_group_size]
                answered.update(self.llm(*[doc for doc, _ in chunk]))
                self.llm_requests += 1

            for doc, partial in pending:
                from_model = answered.get(doc.path) or {}
                merged = dict(partial)
                merged.update(from_model)       # the model wins where it spoke
                resolved[doc.path] = merged
                self._results[doc.path] = merged
                self.stats["gemini" if from_model else "partial"] += 1
        else:
            for doc, partial in pending:
                resolved[doc.path] = partial
                self._results[doc.path] = partial
                self.stats["partial"] += 1

        return resolved

    def summary(self) -> str:
        total = sum(self.stats.values())
        if not total:
            return "no documents extracted"
        return (f"{self.stats['parsed']} parsed locally, "
                f"{self.stats['gemini']} read by Gemini "
                f"({self.llm_requests} API requests), "
                f"{self.stats['partial']} incomplete "
                f"(of {total} documents)")
