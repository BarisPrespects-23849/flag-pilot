# Flag Pilot

Hackathon project for Flagsmith Track 2 ("AI Agents and Feature Flags").
NOTES.md is the source of truth: commands, endpoints, constraints, autonomy matrix (§4),
phase plan (§7). Read it before doing anything.

@NOTES.md

## Rules
- Work in phases. Finish one, summarize in 5 lines, STOP and wait for my approval.
- Never guess commands or endpoints. Use what NOTES.md marks as verified, or verify by running
  (help output, GET calls) and add it to NOTES.md with its source tag.
- Use the Flagsmith CLI v2 and `flagsmith api <path>` (JSON via --input -).
  Don't use the Flagsmith MCP server for experiments.
- Keep output small: --json and --jq on every call.
- Any state-changing action: dry-run first, and log it to audit.jsonl.
- Never call `experiments/<id>/complete/` on the real experiment until the smoke test in
  NOTES.md §6.3 has passed.
- Never demo or test with fabricated results.
- Secrets only in .env (git-ignored). Never print, log or commit keys.
  Never run `flagsmith auth token`.
- Track input/output tokens per agent run and print them at the end.
- When something new is verified, update NOTES.md. Don't change its other sections.
