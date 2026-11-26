---
description: Preview the cleanup pull request for a completed experiment and open it after your approval
argument-hint: <experiment-id>
disable-model-invocation: true
---

Experiment id: `$ARGUMENTS`

`flagpilot cleanup` decides the winner (from the API) and verifies every edit. You explain and
relay my approval.

If the experiment id above is not a single positive integer, say so and stop.

1. Run `uv run flagpilot cleanup $ARGUMENTS` (a dry-run). If it refuses or fails, show its message
   and stop.
2. Show the call sites (file:line), the files to delete, the other mentions it leaves alone, and the
   planned diff exactly as printed.
3. Explain the plan in at most 100 words: what stays, what goes, and the note about other
   environments.
4. Ask whether I want the pull request opened. Stop and wait for my answer.
5. Only if my reply is yes:
   - If the dry-run has no `NEEDS A MANUAL EDIT` section, run
     `uv run flagpilot cleanup $ARGUMENTS --apply`.
   - If it has one, write the edit yourself as a unified diff in a temporary file outside the repo,
     touching only the files listed under `Files a cleanup may change`. Keep the winning behaviour
     and all `track_event` calls. Show me the whole patch, ask again, and only after a second yes
     run `uv run flagpilot cleanup $ARGUMENTS --apply --patch <file>`.
6. Report the command's output as it is, including the pull request URL or the failure.

Rules:
- If `flagpilot cleanup` refuses or fails, stop. Do not retry, weaken or delete tests to get a
  pass, edit Flag Pilot or `flagpilot.toml`, or push or open the pull request yourself.
- Never use `--assume-winner` unless I ask for a preview, and never with `--apply`.
- Never merge the pull request, and never run `flagpilot retire` from this command.
- Run no other state-changing command.
- Finish by telling me that Flag Pilot itself used no LLM tokens and that `/cost` shows this
  session's usage.
