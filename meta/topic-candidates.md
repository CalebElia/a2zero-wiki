# Topic Candidates

LLM-surfaced cross-cutting themes from Pass 1 (holistic synthesizer). The Writer
flags candidates in its `topic_candidates` output; candidates land here for human
review rather than being auto-promoted to `wiki/topics/<slug>.md`.

To promote a candidate: create `wiki/topics/<slug>.md` (manually or via a
synthesis pass) and mark the candidate `[x] Promoted`.
To dismiss: mark `[x] Dismissed` with a one-line reason.

## Format

```
## <Topic Title> | Source: <source-uuid> | <YYYY-MM-DD>
Rationale: <why the LLM thinks this is cross-cutting>
Resolution: [ ] Promote to wiki/topics/<slug>.md  [ ] Dismiss
```

---
