# Demo script (about 2:30)

## Before recording

- [ ] **One take for the real ship.** Shipping `570` is irreversible. Rehearse only up to the
      dry-run, and don't type the experiment name until the final take.
- [ ] Run `uv run flagpilot recommend 570`. Expect `SHIP_VARIANT`. To refresh first, add
      `--refresh` at least 5 minutes before recording.
- [ ] Run `uv run flagpilot recommend 1194`. Expect `KEEP_RUNNING` with control 12 / 1 and
      `new` 18 / 6. Leave `1194` running, and send it no more traffic.
- [ ] Open a fresh Claude Code session in the repo. Expect permission prompts.
- [ ] The refusal's permission prompt only appears when Claude Code runs the command. Ask the
      agent to run the exact `ship 1194` line; don't use `!` or another terminal.
- [ ] `retire` asks for the flag name in a terminal. Run it in your own terminal, next to Claude
      Code.
- [ ] Keep `.env` off screen. Make the terminal wide enough for the rule table (about 130 columns).
- [ ] Open the experiment in the Flagsmith dashboard in a second tab.
- [ ] Leave room for waiting. In rehearsal the agent took about 9 s to explain and verification
      took 7 s. Opening the pull request took about 40 s,
      longer than its slot. Trim waits in the edit.

## Script

Numbers for `570` are from the card with results as of 2026-11-26 09:27 UTC. Numbers for `1194`
are as of 2026-11-27 09:05 UTC. **Read what is on screen** if they differ.

| Time | On screen | Say |
|---|---|---|
| **0:00–0:10** Problem | Dashboard, experiment `570` | "Flagsmith gives a win probability. Someone still has to trust the data, ship the winner and delete the old code." |
| **0:10–0:25** Too early | `uv run flagpilot recommend 1194` | "A second experiment, 30 simulated users. 'New' looks four times better: 33 percent against 8. But that's 12 and 18 users, so the verdict is keep running." |
| **0:25–0:45** Refusal | Agent runs `uv run flagpilot ship 1194 --apply --confirm flagpilot-refuse --expect-winner new`: the permission prompt, approve it, then the `REFUSED:` line | "I approve it in Claude Code, and even type the name. Flagsmith's own API would end this experiment; Flag Pilot refuses." |
| **0:45–1:00** Recommend card | `uv run flagpilot recommend 570` | "Now one that's ready. Simulated users again; Flagsmith computed the results. Control 6.6 percent, 'Buy now' 16, 98.9 percent chance to win." |
| **1:00–1:10** 8-rule table | Scroll to `Rules` (below) | "Eight rules in plain code, no LLM. Flag Pilot computed its own sample-ratio check. All pass." |
| **1:10–1:35** Approval | `/ship-winner 570`, read the explanation, reply `yes`, show the dry-run, type `checkout-button-buy-now` | "The agent explains but can't change the verdict. Yes only gets a dry-run. To ship, I type the name." |
| **1:35–1:47** Verify | Command output `10/10 sample identities get "buy_now"`, then the dashboard tab, reloaded: Completed | "It polls until all ten sample identities get the winner. The dashboard agrees." |
| **1:47–1:52** Audit | `tail -n 6 audit.jsonl \| jq -c '{ts,action,tier,dry_run,approved_by,status}'` | "Every dry-run, approval, refusal and call is logged." |
| **1:52–2:08** Cleanup | `/cleanup-flag 570`: call site and diff, reply `yes` | "Now the dead code. One call site, winner stays, flag read goes, purchase tracking stays." |
| **2:08–2:18** Pull request and merge | Open the PR URL: rules table, results; click **Merge** | "Tests passed first. The PR carries the evidence. I merge, never the agent." |
| **2:18–2:30** Retire | Your terminal: `uv run flagpilot retire checkout_button --apply`, type `checkout_button` | "Retire checks the PR is merged and no code reads the flag, then archives it." |

This is tight. Cut waits in the edit (the PR takes about 40 s to open), and drop the
mistyped-id story unless a judge asks.

**If the cleanup step fails**, show the dry-run diff and say the pull request didn't open. Don't
show or describe a PR that doesn't exist.

## After recording

1. If the merge or retire wasn't recorded, do it now: merge the cleanup PR, then
   `uv run flagpilot retire checkout_button --apply` and type `checkout_button`.
2. Leave `1194` running. `retire flagpilot-refuse` refuses while an experiment on the flag is
   not `completed`.

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
