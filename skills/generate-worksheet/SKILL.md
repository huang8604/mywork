---
name: generate-worksheet
description: Generate a printable Word Memory practice worksheet through the authenticated REST API. Use when a user asks to create today's worksheet, choose a total word count or category weights, or generate a worksheet from explicit word IDs.
---

# Generate Worksheet

Use `scripts/generate_worksheet.py`; never access SQLite or print the bearer token.

## Configuration

Set `WORD_MEMORY_BASE_URL` to the HTTPS site root and `WORD_MEMORY_API_TOKEN` to a token with `practice:generate`. See the repository README for installation and token creation.

## Workflow

1. Confirm the requested selection mode. Do not combine `--total-words` with `--word-id`.
2. Run one of:

   ```bash
   python scripts/generate_worksheet.py
   python scripts/generate_worksheet.py --total-words 20 --new 10 --error 5 --due 5 --custom 0
   python scripts/generate_worksheet.py --word-id 12 --word-id 18
   ```

   With no category flags, the API defaults to new `0`, error `10`, due `0`, custom `0`.

3. Report `worksheet.session_id`, `web_url`, `print_url`, the actual category counts, and status `not_started` (new worksheets are not in progress until a review round starts or the user changes the status).
4. If a request times out after it may have reached the server, retry with the exact `idempotency_key` printed by the failed run:

   ```bash
   python scripts/generate_worksheet.py --idempotency-key KEY [same options]
   ```

Treat `NO_PRACTICE_CANDIDATES` as an empty eligible pool, validation errors as bad selection parameters, 401 as invalid credentials, and 403 as missing `practice:generate` scope.
