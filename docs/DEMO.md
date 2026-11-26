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
      took 7 s. Opening the pull request hasn't been timed. Trim waits in the edit.

## Script

Numbers below are from the card with results as of 2026-11-26 09:27 UTC. **Read what is on
screen** if they differ.

| Time | On screen | Say |
|---|---|---|
| **0:00–0:12** Problem | Dashboard, experiment `570` | "Flagsmith gives a win probability. Someone still has to trust the data, ship the winner and delete the old code." |
| **0:12–0:30** Recommend card | `uv run flagpilot recommend 570` | "These users are simulated; Flagsmith computed the results. Control: 6.6 percent. 'Buy now': 16 percent. 98.9 percent chance to win, with a wide lift interval, shown honestly." |
| **0:30–0:45** 8-rule table | Scroll to `Rules` (below) | "Eight rules in plain code, no LLM. Flagsmith sent no sample-ratio value, so Flag Pilot computed its own. One failure and it won't ship." |
| **0:45–1:12** Approval | `/ship-winner 570`, read the explanation, reply `yes`, show the dry-run, type `checkout-button-buy-now` | "The agent explains but can't change the verdict. Yes only gets a dry-run. To ship, I type the name." Tell the mistyped-id story while the dry-run runs. |
| **1:12–1:22** Verify | Command output: status and `10/10 sample identities get "buy_now"` | "It polls until all ten sample identities get the winner." |
| **1:22–1:30** Audit | `tail -n 6 audit.jsonl \| jq -c '{ts,action,tier,dry_run,approved_by,status}'` | "Every dry-run, approval and call is logged." |
| **1:30–1:48** Cleanup | `/cleanup-flag 570`: call site and diff, reply `yes` | "Now the dead code. One call site, winner stays, flag read goes, purchase tracking stays. I approve." |
| **1:48–2:00** Pull request | Open the PR URL: rules table, results, checklist | "Tests passed first. The PR carries the evidence. I merge, never the agent. Then retire archives the flag." |

**If the cleanup step fails**, show the dry-run diff and say the pull request didn't open. Don't
show or describe a PR that doesn't exist.

## After recording

1. Review and merge the cleanup PR.
2. `uv run flagpilot retire checkout_button`, then `--apply` and type `checkout_button`.

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
