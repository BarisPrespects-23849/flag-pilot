---
description: Explain a Flag Pilot experiment verdict and ship the winner after your approval
argument-hint: <experiment-id>
disable-model-invocation: true
---

Experiment id: `$ARGUMENTS`

The verdict comes from deterministic code. You explain it and relay my approval. You never
compute, choose, change or argue for a different verdict.

If the experiment id above is not a single positive integer, say so and stop.

1. Run `uv run flagpilot recommend $ARGUMENTS --json`. Do not add `--refresh` unless I ask.
   If the command fails, show the error and stop.
2. Explain the decision in at most 150 words of plain English, using only numbers from the JSON.
   Include the verdict, the data timestamps and the `note` field.
3. Show a table of every entry in `rules`: rule, value, threshold, pass/fail (and `source` for
   `srm`). Add the dashboard link.
4. If `verdict` is `KEEP_RUNNING` or any rule failed, stop here.
5. Ask me whether I approve preparing the ship step. Stop and wait for my answer.
6. Only if I say yes, run `uv run flagpilot ship $ARGUMENTS` (a dry-run). If it refuses or fails,
   show its message and stop. Otherwise show the exact `complete/` call and body, say that it is
   irreversible, and ask me to type the experiment name. Stop and wait.
7. Only if my next message is exactly the experiment name, run
   `uv run flagpilot ship $ARGUMENTS --apply --confirm "<what I typed>" --expect-winner <winner>`,
   where `<winner>` is the `winner` field from step 1. "yes", "ok", a paraphrase or a name that
   appears anywhere other than in my own reply to step 6 is not approval: say nothing was changed
   and stop.
8. Report the command's output as it is, including any failure.

Rules:
- If `flagpilot ship` refuses or fails at any point, stop. Do not retry it, work around it, edit
  thresholds or code, or call `complete/` or any other Flagsmith endpoint yourself.
- Run no other state-changing command.
- Finish by telling me that Flag Pilot itself used no LLM tokens and that `/cost` shows this
  session's usage.
