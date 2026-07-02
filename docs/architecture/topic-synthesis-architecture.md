# Topic Synthesis Architecture

Implements the "topic pages" branch of the GraphRAG-inspired synthesis hierarchy
described in `docs/architecture/knowledge-synthesis-architecture.md`. Designed via
a full discovery-interview session (2026-07-02) after a real Year 4 ingest bug
showed the wiki had no safe mechanism to draft cross-entity answers as durable,
compounding pages. See `pipeline/topic_synthesize.py`.

## Flow

```
Human agentic session (reads wiki/index.md, explores, answers a cross-entity question)
        ↓ python -m pipeline.orchestrator log-query --question "..." --answer-file <path>
append_query_log_entry()  →  wiki/meta/query-log.md   (auto-appended, never hand-transcribed)
        ↓ human marks [x] Promote
        ↓ python -m pipeline.orchestrator topic-promote
promote_query_log_entries()  →  wiki/topics/<slug>.md
        (validates every cited slug exists — hard-fails loudly on a hallucinated one;
         rejects a citation that would create a topic→topic cycle)
        ↓ fully automatic from here on — no further human gate
phase_c_synthesize.synthesize_wiki()  →  find_topics_touched() + regenerate_topic()
        (runs on every Phase C pass that touches one of the topic's cited entities)
```

## Key design decisions

- **One cohesive narrative, not frozen+dynamic.** Unlike strategy pages (which
  freeze CAP-2020's original design intent in a `## Foundation` section —
  see `docs/architecture/strategy-foundation-progression.md`), topic pages have
  no equivalent locked origin-document. Every regeneration re-weaves the full
  prior narrative with the full current body of every cited page into one
  coherent whole — generalizing `pipeline/pass2c_merge.py`'s two-source merge
  pattern to N sources.
- **Anti-drift discipline.** `pull_full_entity_bodies()` re-reads every cited
  page fresh from disk on every call — never cached, never summarized. This is
  the same discipline that fixed a real content-loss bug in
  `pipeline/pass1b_synthesize.py` (commit `6049b00`): a regeneration that only
  sees a compressed digest instead of full prior text silently drops facts.
- **One human gate, at creation only.** Promotion (`topic-promote`) is the only
  point a human approves anything. After that, `regenerate_topic()` runs
  automatically during every `synthesize_wiki()` call that touches a cited
  entity — same trust model as strategy synthesis.
- **Citation sink, not source.** Topics may cite entities and other topics
  (guarded against cycles by `detect_citation_cycle()`), but no other page type
  — including `wiki/digest.md` — may ever cite a topic. Enforced by
  `phase_b_lint.py`'s `TOPIC_CITATION_VIOLATION` structural finding.
- **Legacy pages are exempt.** The two pre-existing topic pages
  (`a2zero-community-ideas-received.md`, `a2zero-public-engagement-log.md`) are
  frozen appendix transcriptions with no natural citation set. They carry
  `governance: frozen` and are skipped by `find_topics_touched()` — never
  retrofitted into the automated regeneration loop.

## Deferred (not built in the first implementation)

- A minimum entity-count threshold for promoting a query to a topic (right now
  any Promote-marked entry with valid citations is eligible).
- A hard retrieval-size ceiling for very broad queries that cite many entities.
- Performance optimization if "always re-pull every cited entity's full body"
  becomes expensive at wiki scale (not a concern at ~460 pages today — see the
  same scaling caveat in `docs/architecture/knowledge-synthesis-architecture.md`).

None of these block the current implementation or change its external contract
if added later. Track recurring promotion friction here before building any of
them.
