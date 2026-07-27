---
name: record-review-results
description: Read a Word Memory practice session, create an offline or online review round, and atomically record known, unknown, or skipped results. Use when a user asks to enter answers from a printed worksheet, record review outcomes, or batch-submit results for session item IDs.
---

# Record Review Results

Use `scripts/record_review_results.py`; never access SQLite or print the bearer token.

## Configuration

Set `WORD_MEMORY_BASE_URL` to the HTTPS site root. Use a token with both `practice:read` and `reviews:write`. See the repository README for installation and token creation.

## Workflow

1. Read the session and map each printed position/word to its stable `item_id`:

   ```bash
   python scripts/record_review_results.py --session-id 42 --show-items
   ```

2. Confirm every status with the user. Use only `known`, `unknown`, or `skipped`; never infer uncertain answers.
3. Record a new offline round atomically:

   ```bash
   python scripts/record_review_results.py --session-id 42 \
     --result 501=known --result 502=unknown --result 503=skipped
   ```

   For larger batches, use a UTF-8 TSV containing `ITEM_ID<TAB>STATUS<TAB>DURATION_MS(optional)`:

   ```bash
   python scripts/record_review_results.py --session-id 42 --results-file results.tsv
   ```

4. Report the round ID, answered count, completion state, and any failed request ID.

The output includes an `operation_id`. If round creation or submission has an uncertain network result, retry with the same arguments and `--operation-id VALUE`. If the error output includes a `round_id`, also pass `--round-id ID` so the retry does not create a new round. Use `--mode online` only when the user explicitly says this was an online review. This Skill records new results; use the dedicated review-correction API for later corrections.
