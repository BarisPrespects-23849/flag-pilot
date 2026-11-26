# Demo script (2 minutes)

## Before recording

- [ ] **One take for the real ship.** Shipping `570` is irreversible. Rehearse only up to the
      dry-run, and don't type the experiment name until the final take.
- [ ] Run `uv run flagpilot recommend 570`. Expect `SHIP_VARIANT`. To refresh first, add
      `--refresh` at least 5 minutes before recording.
- [ ] Open a fresh Claude Code session in the repo. Expect permission prompts.
- [ ] Keep `.env` off screen. Make the terminal wide enough for the rule table (about 130 columns).
- [ ] Open the experiment in the Flagsmith dashboard in a second tab.
- [ ] Leave room for waiting. In rehearsal the agent took about 9 s to explain and verification
      took 7 s. Trim waits in the edit if you run long.

## Script

Numbers below are from the card with results as of 2026-11-26 09:27 UTC. **Read what is on
screen** if they differ.

| Time | On screen | Say |
|---|---|---|
| **0:00–0:15** Problem | Dashboard, experiment `570` | "Flagsmith sets experiments up and gives a win probability. Someone still has to trust the data, ship the winner and confirm users get it. Flag Pilot does that, and asks before anything irreversible." |
| **0:15–0:35** Recommend card | `uv run flagpilot recommend 570` | "The users here are simulated; Flagsmith assigned the arms and computed the results. Control converted 19 of 287, 6.6 percent. 'Buy now' converted 50 of 313, 16 percent. 98.9 percent chance to win. The lift interval is wide, plus 20 to plus 263 percent, and the card shows it." |
| **0:35–0:55** 8-rule table | Scroll to `Rules` (below) | "Eight rules, plain code, no LLM. Status, data, metric type, sample size, conversions, traffic split, excluded users, chance to win. Flagsmith returned no sample-ratio p-value, so Flag Pilot computed its own: 0.288. One failure and it won't ship." |
| **0:55–1:25** Approval | `/ship-winner 570`, read the explanation, reply `yes`, show the dry-run, type `checkout-button-buy-now` | "The agent explains the verdict but can't change it. Yes only gets me a dry-run: the exact call and body. To ship, I type the experiment's name." Tell the mistyped-id story while the dry-run runs. |
| **1:25–1:40** Verify | Command output: status and `10/10 sample identities get "buy_now"` | "It ends the experiment, then polls until all ten sample identities get the winner. A successful API call alone isn't proof." |
| **1:40–1:50** Audit | `tail -n 6 audit.jsonl \| jq -c '{ts,action,tier,dry_run,approved_by,status}'` | "Every step is logged: dry-run, approval, call and verification." |
| **1:50–2:00** Cleanup PR *(Phase 4, if ready)* | The open PR and its diff | "Then a pull request removes the losing branch. A human merges it." |

**If Phase 4 isn't ready**, replace the last row with: "Next is a cleanup pull request. Until then,
unidentified users still get the default, control." Don't show or describe a PR that doesn't exist.

## The 8-rule table

```text
  #  Rule                 Value                   Needs                                          Result  Detail
  1  status               running                 running or paused                              PASS
  2  data_available       ok                      results and exposures computed without errors  PASS
  3  metric_supported     occurrence/up/increase  one metric: occurrence/up/increase             PASS
  4  sample_size          287                     >= 50 in every arm                             PASS    control 287, buy_now 313
  5  conversions          19                      >= 5 in every arm                              PASS    control 19, buy_now 50
  6  srm                  p=0.288 (flagpilot)     p >= 0.001                                     PASS    exposures buy_now 313, control 287
  7  excluded_identities  0.0%                    <= 1.0% of exposures                           PASS    0 of 600
  8  chance_to_win        98.9%                   >= 0.95 or <= 0.05                             PASS    buy_now 0.9886
```

## The mistyped-id story (about 10 seconds)

> "In rehearsal I meant to ship the throwaway experiment, 592, and typed 570, my demo experiment.
> The agent flagged it before asking me anything: 'This is 570, your demo experiment, not the
> rehearsal (592).' I said no, and nothing shipped."

What happened, if a judge asks (2026-11-26, 09:42 UTC):

- The agent warned and recommended answering **no**, because that session's instructions limited
  `570` to read-only checks.
- **It was the agent's catch, not a code rule.** `570` passed all 8 rules, and a fresh session may
  not give the same warning.
- The code's backstop is the typed name: `checkout-button-buy-now` is not `flagpilot-rehearsal`.
