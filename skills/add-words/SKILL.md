---
name: add-words
description: Add one or more English words to Word Memory through its authenticated REST API, with server-side dictionary enrichment for phonetics, Chinese meanings, and examples. Use when a user asks to add, save, or preview up to 200 English words or a small plain-text word list.
---

# Add Words

Use `scripts/add_words.py`; never access SQLite or print the bearer token. Use `import-words` instead for large files or background progress.

## Configuration

Set `WORD_MEMORY_BASE_URL` to the HTTPS site root and `WORD_MEMORY_API_TOKEN` to a token with `words:write`. See the repository README for installation and token creation.

## Workflow

1. Collect words from arguments or a UTF-8 file. Files use one word per line; blank and `#` lines are ignored. The script normalizes whitespace, removes case-insensitive duplicates, and accepts at most 200 words.
2. Preview server-side dictionary enrichment before writing:

   ```bash
   python scripts/add_words.py --dry-run abandon camera
   ```

3. If any preview item lists `cn_meaning` in `missing_fields`, ask the user for a Chinese meaning. Never invent one. Supply it directly or through a UTF-8 TSV:

   ```bash
   python scripts/add_words.py obscureword --meaning "obscureword=用户提供的释义"
   python scripts/add_words.py --file words.txt --meaning-file meanings.tsv
   ```

   `meanings.tsv` uses `WORD<TAB>CHINESE_MEANING`, one mapping per line.

4. If the user confirms the write, run without `--dry-run`. Add `--tag NAME` or `--custom` only when requested:

   ```bash
   python scripts/add_words.py --file words.txt --tag CET4
   ```

5. Report the JSON `created`, `duplicates`, and `failed` arrays. Include each failure's `code` and `request_id`. `MANUAL_MEANING_REQUIRED` means the user must provide a meaning and rerun.

Treat only `DUPLICATE_WORD` as an existing word. Treat other 409 responses as failures rather than duplicates. Treat 401 as invalid/expired credentials and 403 as missing `words:write` scope.
