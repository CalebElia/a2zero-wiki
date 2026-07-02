# Query Log

Cross-entity questions answered via an agentic session against the wiki, captured
here for human review before promotion to a durable `wiki/topics/<slug>.md` page.

**Entries in this file are written automatically by the `log-query` CLI command —
never hand-transcribed.** Run this at the end of an agentic session that answered
a cross-entity question (see `docs/how-to-run-ingest.md` once documented there):

```
python -m pipeline.orchestrator log-query --question "..." --answer-file <path>
```

The question text and full answer are populated programmatically by
`pipeline.topic_synthesize.append_query_log_entry`. Do not hand-edit an entry's
question or answer text — that would drift from what the agentic session actually
produced. The only manual action here is ticking the `Resolution:` checkbox below
each entry during review.

To promote an entry: mark `[x] Promote` and run:
```
python -m pipeline.orchestrator topic-promote
```
This validates every cited entity actually exists (hard-fails loudly on a
hallucinated slug), writes `wiki/topics/<slug>.md`, and clears the entry from
this file. Once promoted, the topic page is `governance: synthesized` and
regenerates automatically on every future Phase C run that touches one of its
cited entities — no further human gate.

To dismiss: mark `[x] Dismiss` with a one-line reason.

## Format

```
## <Question> | <YYYY-MM-DD>
<full answer text, with [ [slug] ] citations to entities/topics>
Resolution: [ ] Promote to wiki/topics/<slug>.md  [ ] Dismiss
```

---
