# Agent Notes

- For GitHub pushes from this Windows workspace, use Python `dulwich` when Git for Windows HTTPS credential helpers or `gh` authentication are unreliable.
- Do not print, log, commit, or store GitHub tokens, API keys, database URLs, cookies, or other secrets.
- Push the current branch only after local status, intended staged files, and verification commands have been checked.
- Do not force-push `codex/db-to-excel-extractor` unless the user explicitly asks for it.
