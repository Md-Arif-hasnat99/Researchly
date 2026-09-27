"""Cross-encoder style reranking of retrieved candidates (FR-15).

FR-15's pipeline::

    Top 20 retrieved
         ↓
      Reranker
         ↓
    Best 5–8
         ↓
      Gemini

Retrievers rank by cheap proxies — cosine distance to an embedding, or
``ts_rank`` over a tsvector. Neither can tell whether a chunk actually
*answers* the question; they only tell whether it looks similar. A
reranker re-reads the query against each candidate's text and orders
them by whether they would actually satisfy the request, which is why
ranking the top of a 20-candidate set beats taking its first 5.

The reranker is a listwise Gemini call: the query and all candidates go
in one request and the model returns the indices in ranked order. There
is no separate cross-encoder model in the Gemini API, and a listwise
call is also cheaper than scoring candidates one at a time.

Two properties are enforced throughout, because a reranker that gets
either wrong makes retrieval strictly worse than not having one:

1. **Reranking reorders, it never filters.** Every candidate handed in
   comes back out, in some order. Silently dropping candidates would cut
   recall, and recall is the thing a reranker exists to preserve. Any
   candidate the model omits is appended in its original rank order.

2. **Failure degrades to the original order.** Reranking is an
   improvement, not a correctness requirement, so a model error, a
   missing API key, or unparseable output returns the input order
   untouched instead of failing the request.
"""

import json
import logging
from dataclasses import dataclass, field

import google.genai as genai
import google.genai.types as genai_types

from app.core.config import get_settings
from app.core.retry import with_retry
from app.schemas.search import SearchResultChunk

logger = logging.getLogger("researchly")

# Hard ceiling on how many candidates one rerank call may consider. A
# reranker is a single LLM request over the whole candidate set, so this
# bounds both latency and token cost. Above the cap the deepest
# candidates are left out rather than truncated mid-sentence.
MAX_RERANK_CANDIDATES = 20

# Per-candidate character budget sent to the reranker. Chunks are
# truncated for the ranking judgement only; the text handed to the
# generator downstream is never modified, so this cannot corrupt the
# context the answer is built from.
_CANDIDATE_CHAR_BUDGET = 1200


# ---------------------------------------------------------------------------
# System prompt
# ---------------------------------------------------------------------------

_SYSTEM_PROMPT = """\
You are a relevance reranker for a scientific paper search engine.

You are given a user query and a numbered list of candidate excerpts. \
Your only task is to decide which excerpts genuinely serve the user's \
actual information need, and return every index in order of usefulness.

Rank by how well an excerpt would answer this specific query:
- An excerpt that directly answers the query ranks highest, even if it \
reads in an unusual way.
- An excerpt that is on the same broad topic but does not address the \
actual question ranks lower. Topical overlap is not relevance.
- An excerpt that is off-topic ranks last, but you must still include it.

Rules you MUST follow:
1. Judge only from the query and the supplied excerpts. Do not use prior \
knowledge of the papers, and do not try to identify them.
2. Return EVERY index exactly once, most useful first. A partial list \
loses results the user could have needed.
3. Never invent, skip, or renumber indices. Use only the numbers given, \
in the range 1 to the number of candidates.
4. Base relevance on the excerpt's content, not on which paper it came \
from or how it is worded.

Return a single JSON object matching the provided schema. Output no prose \
outside the JSON.
"""


# ---------------------------------------------------------------------------
# Result
# ---------------------------------------------------------------------------


@dataclass
class RerankResult:
    """Outcome of one reranking pass."""

    chunks: list[SearchResultChunk] = field(default_factory=list)
    reranked: bool = False
    """True only when the model's ordering was actually applied.

    False covers every no-op and every degraded case, so a caller can
    report "not reranked" honestly instead of implying the model
    contributed to the order.
    """

    dropped_indices: list[int] = field(default_factory=list)
    """Indices the model emitted that were not valid candidates.

    Tracked for observability: a model that invents indices is worth
    knowing about even though the output is still salvaged.
    """

    reordered_count: int = 0
    """How many chunks ended up in a different position than they started."""


# ---------------------------------------------------------------------------
# Prompt construction
# ---------------------------------------------------------------------------


def _excerpt(chunk: SearchResultChunk) -> str:
    """Render one candidate for the reranker prompt."""
    content = chunk.content.strip()
    if len(content) > _CANDIDATE_CHAR_BUDGET:
        content = content[:_CANDIDATE_CHAR_BUDGET].rstrip() + "…"
    location = f"page {chunk.page_number}"
    if chunk.section:
        location += f", {chunk.section}"
    return f"[{location}] {content}"


def _build_prompt(query: str, chunks: list[SearchResultChunk]) -> str:
    """Assemble the user-turn prompt with 1-based candidate indices."""
    lines = [f"{idx} = {_excerpt(chunk)}" for idx, chunk in enumerate(chunks, start=1)]
    return (
        f"Query:\n{query}\n\n"
        f"Candidates (use these exact indices):\n" + "\n".join(lines) + "\n\n"
        f"---\n"
        f"Rank all {len(chunks)} candidates by how well each answers the query."
    )


def _response_schema() -> dict:
    """JSON schema for the reranker's reply."""
    return {
        "type": "object",
        "properties": {
            "ranking": {
                "type": "array",
                "items": {"type": "integer"},
                "description": "Candidate indices, most relevant first.",
            },
        },
        "required": ["ranking"],
        "propertyOrdering": ["ranking"],
    }


# ---------------------------------------------------------------------------
# Parsing
# ---------------------------------------------------------------------------


def _parse_ranking(
    payload_text: str,
    candidates: list[SearchResultChunk],
) -> tuple[list[int], list[int], bool]:
    """Extract a valid, complete ordering from the model's reply.

    Returns ``(ordering, dropped, applied)`` where *ordering* is a list of
    zero-based positions covering every candidate exactly once, *dropped*
    lists the one-based indices the model emitted that were not valid
    candidates, and *applied* is True only when the reply contained at
    least one usable index.

    The reply is treated as untrusted: it may be malformed JSON, a bare
    list, out-of-range indices, duplicates, or plain prose. In every
    case the function still returns a complete ordering, because losing
    candidates to a bad model reply would be worse than ignoring it.
    *applied* is what lets the caller tell "the model reordered these"
    apart from "we fell back to the retrieval order".
    """
    identity = list(range(len(candidates)))

    try:
        payload = json.loads(payload_text)
    except (TypeError, ValueError):
        logger.warning("Reranker returned unparseable JSON; keeping original order.")
        return identity, [], False

    if isinstance(payload, dict):
        raw = payload.get("ranking", [])
    elif isinstance(payload, list):
        # Tolerate a bare array in place of the schema object.
        raw = payload
    else:
        raw = []

    if not isinstance(raw, list):
        raw = []

    ordering: list[int] = []
    seen: set[int] = set()
    dropped: list[int] = []

    for item in raw:
        try:
            index = int(item)
        except (TypeError, ValueError):
            continue
        if not 1 <= index <= len(candidates):
            dropped.append(index)
            continue
        zero_based = index - 1
        if zero_based in seen:
            # A repeated index is not an error worth reporting, but it
            # must not consume the candidate a second time.
            continue
        seen.add(zero_based)
        ordering.append(zero_based)

    # Append whatever the model did not rank, in its original order. This
    # is what guarantees no candidate is ever lost to a partial reply.
    for position in range(len(candidates)):
        if position not in seen:
            ordering.append(position)

    # The model's contribution is whatever it ranked. An empty *seen* set
    # means it contributed nothing usable and the ordering below is purely
    # the retrieval order.
    return ordering, dropped, bool(seen)


# ---------------------------------------------------------------------------
# Public API
# ---------------------------------------------------------------------------


def rerank_chunks(
    query: str,
    candidates: list[SearchResultChunk],
    top_k: int | None = None,
) -> RerankResult:
    """Rerank retrieved candidates by genuine query relevance (FR-15).

    Args:
        query:       The user's query.
        candidates:  Retrieved chunks, best-first, as returned by the
                     retrievers. More than *top_k* is what lets a
                     reranker pick a different set, but a shorter list is
                     still reordered.
        top_k:       If given, the reranked list is truncated to this many
                     chunks after reordering.

    Returns:
        :class:`RerankResult` whose ``chunks`` are the input candidates
        reordered. ``reranked`` is True only when the model supplied a
        readable ranking that actually changed the order; otherwise
        ``chunks`` is the input order and ``reranked`` is False.

    Never raises for model or configuration problems: a reranker failure
    downgrades to the retrieval order rather than failing the query.
    """
    if not candidates:
        return RerankResult(chunks=[], reranked=False)

    # Only a list too short to reorder is worth skipping. A list that
    # already happens to be the requested size is still reranked: the
    # retrievers ordered by cosine similarity, and the point of a
    # reranker is that a better ordering exists even when every candidate
    # fits.
    if len(candidates) <= 1:
        logger.info("Rerank skipped: only %d candidate(s)", len(candidates))
        return RerankResult(chunks=list(candidates), reranked=False)

    settings = get_settings()
    if not settings.GEMINI_API_KEY:
        logger.warning(
            "Rerank skipped: GEMINI_API_KEY is not configured. "
            "Returning the retrieval order."
        )
        return RerankResult(chunks=list(candidates), reranked=False)

    # Cap the candidate depth. Anything past the cap was never in
    # contention for the final top_k anyway.
    considered = candidates[:MAX_RERANK_CANDIDATES]
    if len(considered) < len(candidates):
        logger.info(
            "Rerank considering %d of %d candidates (cap %d)",
            len(considered),
            len(candidates),
            MAX_RERANK_CANDIDATES,
        )

    prompt = _build_prompt(query, considered)
    client = genai.Client(api_key=settings.GEMINI_API_KEY)
    model = settings.GEMINI_GENERATION_MODEL

    try:
        response = with_retry(
            lambda: client.models.generate_content(
                model=model,
                contents=[
                    genai_types.Content(
                        role="user",
                        parts=[genai_types.Part(text=prompt)],
                    )
                ],
                config=genai_types.GenerateContentConfig(
                    system_instruction=_SYSTEM_PROMPT,
                    temperature=0.0,
                    max_output_tokens=1024,
                    response_mime_type="application/json",
                    response_schema=_response_schema(),
                ),
            ),
            label="rerank",
            # One extra attempt only: this runs inside an interactive
            # search, so the retry budget is bounded by how long a user
            # will wait, unlike the long-form generation calls.
            retries=1,
        )
    except Exception as exc:  # noqa: BLE001
        # A reranker is an optimisation; a failed one must not fail the
        # request. Retrieval already produced a usable ordering. This
        # path also covers a reranker that is still failing after the
        # transient retries in app.core.retry are exhausted.
        logger.warning("Rerank call failed, keeping retrieval order: %s", exc)
        return RerankResult(chunks=list(candidates), reranked=False)

    ordering, dropped, applied = _parse_ranking(response.text or "", considered)

    if dropped:
        logger.warning(
            "Reranker emitted %d invalid index(es): %s",
            len(dropped),
            dropped,
        )

    reordered = [considered[position] for position in ordering]
    moved = sum(
        1
        for new_position, chunk in enumerate(reordered)
        if new_position != _original_position(considered, chunk)
    )

    if top_k is not None:
        reordered = reordered[:top_k]

    # Candidates past the rerank cap were never sent to the model. If the
    # caller wants more than the reranked head holds, extend with them in
    # their original order so the response is never shorter than it should
    # be. Current callers cap top_k at the rerank cap, so this only
    # matters if a caller asks for a wider list later.
    if top_k is not None and len(reordered) < top_k and len(considered) < len(candidates):
        tail = candidates[len(considered) :]
        already = {chunk.chunk_id for chunk in reordered}
        reordered.extend(c for c in tail if c.chunk_id not in already)
        reordered = reordered[:top_k]

    # A reply we could not read, or one that only restated the retrieval
    # order, did not rerank anything. Reporting either as a rerank would
    # claim a result the user did not get.
    reranked = applied and moved > 0

    logger.info(
        "Rerank complete | considered=%d reordered=%d invalid=%d returned=%d applied=%s",
        len(considered),
        moved,
        len(dropped),
        len(reordered),
        reranked,
    )

    return RerankResult(
        chunks=reordered,
        reranked=reranked,
        dropped_indices=dropped,
        reordered_count=moved,
    )


def _original_position(candidates: list[SearchResultChunk], chunk: SearchResultChunk) -> int:
    """Position of *chunk* in the original candidate list."""
    for position, candidate in enumerate(candidates):
        if candidate.chunk_id == chunk.chunk_id:
            return position
    return -1
