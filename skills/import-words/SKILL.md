---
name: import-words
description: Import a UTF-8 TXT, CSV, or JSON word list through the Word Memory background import API and monitor partial-write progress. Use when a user asks to import a large vocabulary file, apply default tags, preview an import, or choose conflict and unresolved-word policies.
---

# Import Words

Use `scripts/import_words.py`; never access SQLite or print the bearer token.

## Configuration

Set `WORD_MEMORY_BASE_URL` to the HTTPS site root. Use a token with both `words:write` and `words:read`; progress polling needs the read scope. See the repository README for installation and token creation.

## Workflow

1. Accept UTF-8 `.txt`, `.csv`, or `.json`. TXT uses one English word per line and ignores blank or `#` lines.
2. Preview uncertain data before writing:

   ```bash
   python scripts/import_words.py words.txt --dry-run --tag CET4
   ```

3. Confirm the policies, then start the real import:

   ```bash
   python scripts/import_words.py words.txt --conflict-policy update --unresolved-policy ai --tag CET4
   ```

   Conflict policies are `skip`, `update`, and `reject`. Unresolved policies are `skip`, `reject`, and `ai`; unresolved rows are never written without a Chinese meaning.

4. Report created, updated, skipped, failed, unresolved words, dictionary matches, and queued audio count from the final `progress` object.

The server exposes only one global import-progress snapshot. Never start concurrent imports. The script refuses to start while another job reports `running` and stops if another request replaces the observed total. For an uncertain POST retry, reuse the emitted `idempotency_key` with identical arguments. Treat 401 as invalid credentials, 403 as missing scope, 409 as a conflict/running import, 413 as the server size limit, and 415 as an unsupported file type.
