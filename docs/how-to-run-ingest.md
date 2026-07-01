# How to Run the A2Zero Ingest Pipeline

Step-by-step runbook for ingesting a new source into the wiki. Structured around the actual command sequence and the human-in-the-loop (HITL) review gates between phases.

---

## Before You Start: Two Key Decisions

### 1. Which LLM provider?

The pipeline supports Anthropic (default) and OpenAI. You set this per-command with an environment variable prefix.

| Provider | Prefix | When to use |
|----------|--------|-------------|
| **Anthropic** (default) | `LLM_PROVIDER=anthropic` (or omit — Anthropic is the default) | Default. Requires `ANTHROPIC_API_KEY` in your env. |
| **OpenAI** | `LLM_PROVIDER=openai` | Requires `OPENAI_API_KEY` in your env. Use when your Anthropic key is unavailable or you're A/B testing. |

If you have a stale `LLM_PROVIDER` exported in your shell, **always prefix commands explicitly** to avoid silently routing to the wrong provider. Check with `echo $LLM_PROVIDER`.

### 2. Wiki, quads, or both?

| Mode | Flag | What it does | When to use |
|------|------|--------------|-------------|
| **Wiki only** (default) | *(no flag)* | Comprehend → holistic synthesis → LDP chunk extraction → wiki pages. Skips quad LLM call per chunk. | **Use this for all current ingests.** The quad pipeline (linter + review-queue) is paused pending schema redesign. |
| **Wiki + quads** | `--include-quads` | Same as wiki-only PLUS one extra quad-extraction LLM call per chunk, writing facts to `blackboard/quads.jsonl`. | Only when the quad pipeline has been re-designed and you're ready to consume the output. |
| **Quads only** | `--quads-only` | Skips Pass 1 (Comprehend + holistic) and wiki page writes. Just emits quads. | Rare — re-run quad extraction against an already-ingested source without rewriting the wiki. |

Wiki-only is now the default because quad extraction costs ~50% of per-chunk tokens for output nothing currently reads.

---

## The Steps

### Step 0: Prepare the source markdown

The pipeline reads from `prepared/<type>/<uuid>.md`, never from `raw/`. If you've cleaned a PDF or are revising a source's structure (e.g. fixing heading depths so chunking works), edit the file in `prepared/`.

```bash
# Example: cleaning a new annual report
$EDITOR prepared/annual-reports/a2zero-year3.md
```

If the file isn't yet in `prepared/`, copy it from `raw/` and clean it up:
```bash
cp raw/<source>.md prepared/<type>/<uuid>.md
$EDITOR prepared/<type>/<uuid>.md
```

---

### Step 1: Preflight — generate the proposed chunking map

This runs a mechanical regex over markdown headings to produce a section map. No LLM call. Fast.

```bash
python -m pipeline.orchestrator preflight \
  --source prepared/<type>/<uuid>.md \
  --uuid <uuid>
```

Output:
- `blackboard/section_maps/<uuid>_proposed.json` — editable JSON map
- `blackboard/section_maps/<uuid>_preview.md` — human-readable preview

If a `_proposed.json` already exists, `preflight` refuses to overwrite. Add `--force` to regenerate (useful when you've edited the source markdown and want fresh chunks).

---

### Step 2: HITL Gate — Review the chunking

Open `blackboard/section_maps/<uuid>_preview.md` and read it. You're checking:

- **Are any chunks suspiciously small?** (e.g. heading-only stubs of 4–40 tokens) → these usually mean the source has empty section headers. Either fix the markdown in `prepared/` and re-run preflight, OR disable those sections in the JSON.
- **Are any chunks suspiciously large?** (e.g. >2,000 tokens) → consider whether they should be split, or whether the whole-document depth-1 wrapper is duplicating content.
- **Does the depth-1 title chunk cover the whole document?** That's almost always wrong — set it to `is_chunk: false` so the depth-2 sections beneath it do the work.

**Editing options:**

1. **Fix the source markdown.** Often the cleanest fix — re-run `preflight --force` after editing.
2. **Edit `<uuid>_proposed.json` directly.** Per-section knobs:
   - `is_chunk: true/false` — whether this section becomes its own LDP chunk
   - `line_start` / `line_end` — adjust boundaries (e.g. merge two sections by extending one's `line_end` and disabling the next)
   - Delete sections entirely if irrelevant

The `approve` validator checks that no two `is_chunk: true` sections have overlapping line ranges, so disabling a section is the safest way to merge.

---

### Step 3: Approve the chunking map

Once the proposed map looks right:

```bash
python -m pipeline.orchestrator approve --uuid <uuid>
```

This validates the JSON (no overlapping ranges, all line numbers in-bounds, at least one `is_chunk: true`, `approved` flag currently false), flips the flag, and renames the file from `_proposed.json` → `_approved.json`. The pipeline's `source` command looks for `_approved.json` specifically.

If validation fails, fix the JSON and re-run `approve`.

---

### Step 4: Run the ingest

This is the main event. Pass 0 (copy) → Pass 1A (Comprehend) → Pass 1B (holistic synthesis) → Pass 1.5 (alias resolution) → Pass 2 (LDP chunked extraction) → Pass 3 (finalize).

**Default (wiki-only, Anthropic):**
```bash
LLM_PROVIDER=anthropic python -m pipeline.orchestrator source \
  --source prepared/<type>/<uuid>.md \
  --uuid <uuid> \
  --title "<human-readable title>" \
  --quads-path blackboard/quads.jsonl \
  --wiki-root wiki \
  --review-queue review-queue.md \
  --section-maps-dir blackboard/section_maps
```

**With quad extraction (only when the quad pipeline is ready):**
Add `--include-quads`.

**On OpenAI:**
Replace `LLM_PROVIDER=anthropic` with `LLM_PROVIDER=openai`.

Expect ~5–15 minutes total wall-clock for a typical annual report — Comprehend (~1 min) + holistic synthesis (~2–4 min) + LDP (~30–60 sec per chunk × number of chunks).

Watch the terminal output:
- `[ingest] ... comprehend took Xs (extends=N, new=M, retrieve=K)` — Pass 1A done
- `[holistic:writer]` → `[holistic:evaluator]` → `[holistic:editor]` — Pass 1B Writer/Evaluator/Editor loop
- `[holistic] Strategy body integrated: strategy-N-*.md` (×7) — strategies updated
- `[ldp] <uuid>: N sections, M chunks to extract [wiki-only|quads+wiki]` — Pass 2 begins
- `[wiki_writer:pass1.5] '<slug>' → canonical '<canonical-slug>'` — alias resolution per entity
- (each chunk repeats the pass1.5 block, then writes pages)

---

### Step 5: HITL Gate — Post-ingest lint review

After the ingest, run the lint passes to surface structural and semantic issues for human review.

```bash
# Find broken wikilinks and orphan pages
python -m pipeline.phase_b_lint --wiki-root wiki --structural

# Find near-duplicate entity pages (LLM-driven)
python -m pipeline.phase_b_lint --wiki-root wiki --semantic

# Find missed entity mentions in strategy/overview bodies
python -m pipeline.phase_b_lint --wiki-root wiki --backlink
```

Each pass writes its proposals to `review-queue.md`. Open that file and annotate each proposal with one of:

- `[x] APPROVE_MERGE <slug-a> <slug-b>` — collapse two entities into one
- `[x] APPROVE_ALIAS <alias> <canonical>` — record an alias without merging now
- `[x] KEEP_SEPARATE` — explicitly mark a proposal as a non-issue
- `[ ] DEFER` — punt to next session

Unactioned items stay in the file across runs. `DEFER`d items are preserved too.

---

### Step 6: Apply the approved lint proposals

```bash
python -m pipeline.phase_b_lint --wiki-root wiki --apply
```

This executes every `[x] APPROVE_*` proposal:
- Approved merges call the LLM merge function, write the merged page, update aliases in `registry/entity_aliases.json`, and append to `registry/merge-log.jsonl`
- The cleared proposals are removed from `review-queue.md`

If a merge goes wrong, every page is recoverable via `git show <pre-merge-hash>:wiki/<path>.md`.

---

### Step 7: Phase C — Synthesize the wiki

Rebuilds the synthesis blocks in all 7 strategy pages and the L2 digest. **Always run this after lint + apply, before your next ingest.** The digest is what the next Comprehend pass reads to inform its plan.

```bash
LLM_PROVIDER=anthropic python -m pipeline.phase_c_synthesize --wiki-root wiki
```

Variants:
- `--strategy strategies/strategy-1-renewable-grid` — rebuild just one strategy
- `--digest-only` — rebuild only the digest (skip strategy synthesis)

The synthesizer validates every entity slug it writes against the filesystem. Broken references trigger a scoped Reviser LLM call. Dropped slugs are logged to `wiki/meta/synthesis-ghosts.log` for future review.

---

### Step 8: Commit

```bash
git status
git add wiki/ registry/ blackboard/ review-queue.md
git commit -m "ingest: <uuid> — <short summary>"
git push
```

Don't `git add -A` blindly — `.DS_Store` and `__pycache__/` are gitignored but cruft can sneak in. Don't commit `wiki/.obsidian/workspace.json` (also gitignored).

---

## Summary: The Full Command Sequence

For a typical Year N annual report ingest, the complete command sequence is:

```bash
# 0. Edit prepared/annual-reports/a2zero-yearN.md if needed

# 1. Preflight
python -m pipeline.orchestrator preflight \
  --source prepared/annual-reports/a2zero-yearN.md \
  --uuid a2zero-yearN

# 2. Review blackboard/section_maps/a2zero-yearN_preview.md
#    Edit _proposed.json or fix the source markdown + re-preflight

# 3. Approve
python -m pipeline.orchestrator approve --uuid a2zero-yearN

# 4. Ingest (wiki-only, Anthropic)
LLM_PROVIDER=anthropic python -m pipeline.orchestrator source \
  --source prepared/annual-reports/a2zero-yearN.md \
  --uuid a2zero-yearN \
  --title "A2ZERO Year N Annual Report" \
  --quads-path blackboard/quads.jsonl \
  --wiki-root wiki \
  --review-queue review-queue.md \
  --section-maps-dir blackboard/section_maps

# 5. Lint (three passes)
python -m pipeline.phase_b_lint --wiki-root wiki --structural
python -m pipeline.phase_b_lint --wiki-root wiki --semantic
python -m pipeline.phase_b_lint --wiki-root wiki --backlink

# 6. Review and annotate review-queue.md, then apply
python -m pipeline.phase_b_lint --wiki-root wiki --apply

# 7. Phase C synthesis
LLM_PROVIDER=anthropic python -m pipeline.phase_c_synthesize --wiki-root wiki

# 8. Commit
git add wiki/ registry/ blackboard/ review-queue.md
git commit -m "ingest: a2zero-yearN — <summary>"
git push
```

---

## Troubleshooting

**`openai.AuthenticationError: Incorrect API key`** — You have `LLM_PROVIDER=openai` set in your environment but your OpenAI key is bad/missing. Prefix commands with `LLM_PROVIDER=anthropic` to force the working provider.

**`json.decoder.JSONDecodeError` in Comprehend** — The LLM returned malformed or truncated JSON. The pipeline writes the raw response to `blackboard/_comprehend_raw_<uuid>.txt` so you can inspect it. Most common cause is `max_tokens` truncation; if you see the file end mid-object, the prompt may need tightening or `max_tokens` raising in `pipeline/pass1a_comprehend.py`.

**`No approved section map for <uuid>`** — You skipped Steps 1–3. Run preflight + approve first. Or, for a trusted batch ingest, pass `--auto-approve` to the `source` command to bypass the gate.

**`[quads] WARNING: response was truncated`** — Only appears when `--include-quads` is set. The quad extractor recovered the complete quads but lost any partial trailing one. Not fatal but means that chunk's quad set is incomplete.

**Pipeline mid-run is unsafe to kill.** If you cancel during Pass 2 (LDP), entities mentioned in unprocessed chunks never get pages. Either let it finish or be prepared to manually clean up the partial wiki state.
