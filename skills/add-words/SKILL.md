---
name: add-words
description: Add one or more English words to the Word Memory Assistant through its authenticated REST API, with local dictionary enrichment for phonetics, Chinese meanings, and example sentences. Use when a user asks to add, import, save, or preview English words or a plain-text word list in their vocabulary system.
---

# Add Words

Use `scripts/add_words.py`; do not access SQLite or expose the bearer token.

## Workflow

1. Read `WORD_MEMORY_BASE_URL` and `WORD_MEMORY_API_TOKEN` from the environment. Never print the token.
2. Collect English words from arguments or a UTF-8 text file. Keep one word per line; blank lines and lines beginning with `#` are ignored.
3. Preview dictionary enrichment before writing:

   ```bash
   python scripts/add_words.py --dry-run abandon camera
   ```

4. If the user asked to add the words, run without `--dry-run`. Add `--tag NAME` or `--custom` only when requested:

   ```bash
   python scripts/add_words.py --file words.txt --tag CET4
   ```

5. Report created, duplicate, and failed words with each failure's `request_id`. If enrichment reports a missing Chinese meaning, ask the user for a manual meaning; do not invent one.

The API token needs `words:write`. Treat 401 as invalid/expired credentials, 403 as insufficient scope, and 409 as an existing word rather than retrying blindly.
