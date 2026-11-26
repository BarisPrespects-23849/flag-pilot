# Flag Pilot: NOTES.md

> An agent that takes a Flagsmith experiment from **results to recommendation to human approval to rollout to cleanup PR**.
> Track 02: *AI Agents and Feature Flags* ($1,000).

Each fact is tagged with how it was checked:
- **[doc]**: docs.flagsmith.com (read 2026-11-26).
- **[schema]**: the live OpenAPI spec at `https://api.flagsmith.com/api/v1/swagger.json`.
- **[probe]**: an unauthenticated request to Flagsmith Cloud returned 401, so the route exists (404 would mean it doesn't).
- **[ran]**: the command was executed.

---

## 1. What the track asks for

**Brief:** "Build an agent or a tool that works with Flagsmith for you, like setting up experiments from a prompt."

**Suggested ideas, and how Flag Pilot covers them:**

| Track idea | Flag Pilot |
|---|---|
| Turn a feature request into a flagged rollout | ➖ Already covered by Flagsmith's own setup prompt; we reuse its steps |
| PR reviewer that wraps risky code in flags | ❌ Out of scope |
| **Agent that opens PRs to remove stale flags** | ✅ `flagpilot cleanup` |
| **Roll out the winning version after human approval** | ✅ `flagpilot ship` |
| **Bot that explains which flags a user sees** | ✅ `flagpilot explain` (plain-English results; per-identity is a stretch goal) |

**Track tip:** *"The MCP server, API and CLI give your agent access to Flagsmith. The interesting part is deciding what the agent does on its own and where it stops to ask a person."* The autonomy matrix in §4 is our answer, and it is the centrepiece of the demo.

**How a round is played (challenge page):**
1. Create a flag.
2. Pick a metric.
3. Split the traffic.
4. Ship the winner ("Flagsmith shows the win probability for each version. Roll the winner out with the same flag.").

Flagsmith's setup prompt covers 1–3. **Flag Pilot owns step 4 and what comes after it.**

**Track 2 judging criteria (from the challenge page). Build these first:**

| Criterion | How Flag Pilot earns it |
|---|---|
| CLI / API / MCP use | CLI v2 plus the Experiments, Metrics, Results and Exposures APIs, and the Python SDK with events |
| Saves time | Reading results, deciding and rolling out takes one command and one approval, instead of dashboard clicks |
| Human approves changes | Tiered gates (§4). Ending and shipping requires typing the experiment name. |
| Clear output | One decision card: verdict, why, the checks that passed or failed, and the exact call that will run |

**Our own additions, after the four above** (token efficiency and production safety are Track 4 criteria; the rest are our own rules):
- **Token efficiency:** Flagsmith already computes the probabilities. Our code reads them and applies the rules; the LLM only writes the explanation from a compact JSON summary. Tokens are printed on every run.
- **Safety:** dry-run by default, `audit.jsonl`, no secrets in the repo.
- **Real data only:** we never demo against fabricated results.

---

## 2. Current status (2026-11-26)

| Item | State |
|---|---|
| Flagsmith Cloud org | **CapRock** ✅ |
| Project | **flag-pilot** ✅ |
| Environment | **Development** (Production also exists) ✅ |
| Experimentation enabled | ✅ The Experiments and Metrics menus are visible |
| Warehouse | **Flagsmith (managed)**, id `12751`: still shows `pending_connection`, but has 670 events and results for experiment `570` are computed (2026-11-26) [ran]. **Local fallback not needed.** |
| CLI | `flagsmith v2.0.0` on macOS arm64 via `get.flagsmith.com` ✅ [ran] |
| CLI auth | `flagsmith login` (OAuth, macOS keychain). `auth status` and `project list` both work ✅ [ran] |
| Claude Code | v2.1.326 on the Mac ✅ [ran] |
| `flagsmith init` | ✅ Done: `flagsmith.json` written for project id `56454`, Development environment [ran] |
| Docker (local fallback, §6.8) | Docker.app and Compose v5.3.0 installed; daemon not running; no listener seen on 8000/8001 [ran] |
| Server-side env key | ⏳ Create in **SDK Keys**. Store only in `.env`. |

---

## 3. Verified commands and endpoints

`E` = `api/v1/environments/<env_key>`. Use `--json` / `--jq` on every call.

### CLI facts [ran]
- Global flags: `--json`, `--jq <expr>`, `--no-input`, `--yes`, `-p/--project`, `-e/--environment` (client-side key), `--api-url`.
- `flagsmith api <path>`:
  - GET by default; `-X METHOD` sets the method.
  - `--input -` reads a JSON body from stdin.
  - `-F k=v` sends a typed field (implies POST); `-i` includes the status line and headers.
- **The CLI has no `--dry-run`**, so Flag Pilot implements it (§5).
- Auth:
  - Use OAuth via `flagsmith login`, or `FLAGSMITH_API_KEY`, a Master API key in `{prefix}.{secret}` format.
  - Either way the CLI sends `Authorization: Api-Key <key>`.
  - `flagsmith auth token` prints the credential. **Never run it.**
- A new flag can take a moment to reach the SDK API: `evaluate checkout_button` right after `feature create` found nothing, and a retry shortly after returned it [ran].
- `flagsmith feature get <flag> --json` returns `{id, name, type, enabled, default_value, description}`; `type` is `standard` before any variant exists [ran].
- After `variant add`, `feature get` reports `type: multivariate` and `variants: [{id, key, value, weight}]`; `id` is the multivariate option id the experiment body needs. The Admin API (`api/v1/projects/<id>/features/<flag id>/`) lists the same ids under `multivariate_options` [ran].
- `POST E/experiment-metrics/` with the body in the Lifecycle table works and returns `id`; `GET` returns a paginated `results` list [ran].
- `flagsmith init --project <p> --environment <env key>` writes `flagsmith.json`. It contains no secrets and is safe to commit [doc].
- `flagsmith feature update <flag> --archive` / `--unarchive` archive and restore a flag (help output) [ran].
- Archived `flagpilot-smoke` (`305152`) and `flagpilot-rehearsal` (`305225`) on 2026-11-26. Both read back `is_archived: true` from `api/v1/projects/56454/features/`; `feature list` hides them unless `--include-archived`. Right after, and about a minute later (10:50:46 UTC), `evaluate` still returned `winner` / `buy_now` for an identity and `control` without one: archiving did not stop evaluation [ran].
- A completed experiment (`576`, `592`) keeps `rollout_decision`, `rollout_variant` and `feature.multivariate_options` (id → key, `string_value`). `GET …/experiments/592/results/` still returned the pre-completion results, `is_final: false` [ran].

### Flag Pilot commands
- `uv run flagpilot recommend <id> [--json] [--refresh]`: verdict from the real payload; thresholds in `flagpilot.toml`. Run on `570`: `SHIP_VARIANT` (`buy_now`), SRM p=0.288 computed by Flag Pilot [ran].
- `uv run flagpilot ship <id>` is a dry-run (run on `570`) [ran]. `--apply` asks for the experiment name, or takes `--confirm "<name>" --expect-winner <key>`. `ship --apply` is verified end to end on `592` (§6.3) [ran]. Keep `570` for the demo.
- Agent layer: `/ship-winner <id>` (`.claude/commands/ship-winner.md`). No paid LLM API; the `anthropic` dependency was removed.
- The `control` rollout decision of `complete/` is untested; only `variant` was smoke-tested.
- `uv run flagpilot cleanup <id> [--assume-winner <key>] [--apply] [--patch <file>]`: removes the flag from `app_paths` (`demo/`) and deletes test files marked `pytest.mark.flag("<flag>")`; tooling, docs and fixtures are listed and left alone. `cleanup 570 --assume-winner buy_now` (dry-run) found one read, `demo/app.py:39`; its edit passed the tests on a scratch copy for both winners [ran]. `--apply` is tested only on a throwaway local repo with `gh` faked: no real PR yet. It refuses while `app_paths` or `test_paths` differ from `origin/main`.
- `uv run flagpilot retire <flag> [--no-code] [--apply --confirm <flag>]`: `--apply --no-code` ran on `flagpilot-smoke` and `flagpilot-rehearsal` after typed names; a second run is refused as already archived [ran]. The PR check (`gh pr view <branch> --json state,baseRefName,url`) is tested with `gh` faked only. `--target rehearsal` tooling still names the archived flag.
- `ship --apply` now stores its decision in `.flagpilot_state.json` as evidence for the cleanup PR (tests only).
- `uv run python -m flagpilot.{provision,lifecycle,simulate} … --target {checkout,rehearsal}`: `--target` is required. Each target has its own user prefix (`sim-user`, `rehearsal-user`) because metric `565` counts every `purchase` event [ran: `rehearsal`; `checkout` tests only].

### Lifecycle

| Step | Command / endpoint | Source |
|---|---|---|
| List projects | `flagsmith project list --json` | ran |
| List environments | `flagsmith environment list --project flag-pilot --json` | doc |
| Check warehouse | `flagsmith api E/warehouse-connections/` (empty list means stop) | doc, probe |
| Create flag | `flagsmith feature create <flag> --value control --enabled` | doc |
| Add variant | `flagsmith feature variant add <flag> --value <v> --key <key> --weight 0` | doc |
| Get flag + variant ids | `flagsmith feature get <flag> --json` | doc |
| Create metric | `POST E/experiment-metrics/` with `{"name","aggregation":"occurrence","direction":"up","definition":{"version":1,"event":"<event>"}}` | doc, schema |
| Create experiment | `POST E/experiments/` (body below) | doc, schema |
| Start | `POST E/experiments/<id>/start/`, then check `status == "running"` | doc, schema |
| Pause | `POST E/experiments/<id>/pause/` | schema |
| Edit rollout | `PATCH E/experiments/<id>/rollout/` (audience can change only before start) | schema |
| Exposures | `POST E/experiments/<id>/exposures/refresh/`, then `GET …/exposures/` | schema |
| Refresh results | `POST E/experiments/<id>/results/refresh/`, **at most once every 5 minutes** | doc |
| Read results | `GET E/experiments/<id>/results/` (null until computed) | doc, schema |
| **End + ship winner** | `POST E/experiments/<id>/complete/` with `{"rollout_decision":"variant","rollout_variant":<mv option id>}` (or `"control"` / `"disable"`) | schema |
| Delete flag | `flagsmith feature delete <flag>` | ran help |
| Dashboard link | `https://app.flagsmith.com/project/<project id>/environment/<env key>/experiments/<id>` | doc |

`stop/`, `end/` and `conclude/` return **404** [probe]. `complete/` is the API behind the dashboard's **End Experiment** button.

Experiment create body [doc]:
```json
{"feature": <flag id>, "name": "<name>", "hypothesis": "<hypothesis>",
 "metrics": [{"metric": <metric id>, "expected_direction": "increase"}],
 "experiment_rollout": {"enabled": true, "rollout_percentage": 100,
   "feature_state_value": {"type": "string", "value": "control"},
   "multivariate_feature_state_values": [{"multivariate_feature_option": <variant id>, "percentage_allocation": 50}]}}
```

Verified on experiment `570` (`checkout-button-buy-now`, flag `305133`, variant `37071`, metric `565`) [ran]:
- **Creating an experiment with `experiment_rollout` changes what is served immediately**, while `status` is still `created`: Development identities split between `control` and `buy_now` (SDK and `evaluate`). Treat it as Tier 2.
- Before start the SDK returns no experiment metadata (`flag.experiment` is `None`), so `get_experiment_flag` records no exposure.
- Production kept serving `control` (`STATIC`) to 10 test identities.
- The inline metric id is accepted as an integer.

Enums [schema]:
- `status`: created, running, paused, completed.
- `rollout_decision`: control, variant, disable.
- `expected_direction`: increase, decrease, not_increase, not_decrease.
- `aggregation`: occurrence, count, sum, mean.
- `direction`: up, down, informational.

Results payload, real, from `GET E/experiments/570/results/` at 2026-11-26T09:10:21Z, trimmed to one example per field [ran]:
```json
{"results": {
  "as_of": "2026-11-26T09:10:21.835497Z",
  "is_final": false,
  "last_error_at": null,
  "refresh_requested_at": "2026-11-26T09:10:21.726318Z",
  "payload": {
    "srm_p_value": null,
    "exposures_timeseries": {"granularity": "hour",
      "points": [{"bucket": "2026-11-26T08:00:00+00:00", "new_identities": {"buy_now": 313}}]},
    "metrics": [{
      "metric_id": 565,
      "variants": {"buy_now": {"n": 313, "sum": 50, "sum_squares": 50}},
      "inference": {"buy_now": {"chance_to_win": 0.9885853264341431, "lift": 1.4129813351269547,
                                "ci_low": 0.19634964935773724, "ci_high": 2.629613020896172}},
      "conversions_timeseries": {"granularity": "hour",
        "points": [{"bucket": "2026-11-26T08:00:00+00:00", "converted_identities": {"buy_now": 50}}]}
    }]
  }
}}
```
- **This does not match the spec's `ExperimentResults` schema**: there is no `statistics`, `winner`, `significant`, `p_value`, `recommendation`, `sample_size_warning`, `evaluations`, `conversions` or `conversion_rate`.
- `variants` has `control` and `buy_now`; `inference` has only `buy_now` (compared against control).
- Conversion rate is `sum / n` (control 19/287, `buy_now` 50/313). `lift` is relative, as a fraction: it equals rate ratio minus 1 (1.41 = +141%).
- `srm_p_value` was `null` with 600 identities. What `null` means is unconfirmed.
- Before the first refresh the response is `{"results": null}`.

Exposures, from `GET E/experiments/570/exposures/` after a refresh [ran]: `{"exposures": {as_of, is_final, last_error_at, refresh_requested_at, payload: {excluded_identities: 0, timeseries: {granularity, points: [{bucket, new_identities: {buy_now: 313, control: 287}}]}}}}`.

- `results/refresh/` answered HTTP 202 with no JSON body; `exposures/refresh/` also returned an empty body. `flagsmith api … --jq` exits 1 on an empty body, so check the status line with `-i` [ran].
- Both were computed while the warehouse still showed `pending_connection` (670 events) [ran].

### Python SDK [doc]

Verified against the 6.7.0 source [ran]:
- `flush_events()` sends buffered events and waits; `close()` sends them and stops. Nothing flushes at exit, so call `close()`. (The docs don't show either.)
- `max_buffer_items` is also the buffer's capacity. With `1`, call `flush_events()` after every event: 200 events tracked back to back delivered only 1 (local stub) [ran].
- Delivery failures are only logged (logger `flagsmith`), never raised.
- `get_experiment_flag` records an exposure only if the flag is enabled, has a variant key and `flag.experiment.in_experiment` is true.
- The server-side key from `.env` is accepted by the SDK API [ran].
- Real events API: one `flagpilot_smoke` event (identity `flagpilot-smoke-1`) got HTTP 202 on the first attempt at 08:21 UTC on 2026-11-26; the warehouse still showed `pending_connection`, 0 events, seconds later [ran]. At 08:38 UTC it showed 1 event received, still `pending_connection` [ran].

```python
# pip install "flagsmith>=6.3.0"   (6.7.0 is the latest on PyPI)
from flagsmith import EventProcessorConfig, Flagsmith
fs = Flagsmith(environment_key=SERVER_KEY, enable_events=True,
               event_processor_config=EventProcessorConfig(max_buffer_items=1))  # short-lived scripts
flag = fs.get_experiment_flag("<flag>", identifier=user_id)    # evaluate + record exposure
fs.track_event("<event>", identifier=user_id)                  # conversion (same identifier!)
```

---

## 4. Autonomy matrix: what the agent does alone and where it stops

| Tier | Actions | Behaviour |
|---|---|---|
| **0 Read** | list, get, `results/`, `exposures/`, warehouse status, refresh (rate-limited) | Runs on its own; results are cached |
| **1 Reversible, nothing served** | create flag, add variant, create metric | Dry-run shown first, then a single `y/N` |
| **2 Changes what users see** | create experiment (its rollout is served immediately, §6.11), `start/`, `pause/`, `PATCH rollout/` | Decision card plus `y/N`. Start gate: warehouse connection exists (pending or connected); refuse if none |
| **3 Irreversible** | `complete/` (ship the winner), `feature delete` | Decision card plus **typing the experiment name**. Refused if any gate fails |
| **Never** | `auth token`, editing the flag while running, auto-merging a PR, deleting a metric on an active experiment | Not implemented |

**Ship gates.** All must pass before Tier 3; the agent explains each one that fails:
1. Status is `running` or `paused`.
2. Every arm has ≥ 50 identities, and ≥ 5 conversions for occurrence metrics [doc].
3. No SRM warning (only checked once there are ≥ 100 identities) [doc].
4. Best chance to win ≥ 95%. If it is ≤ 5%, recommend `control` [doc].
5. Quarantined identities make up less than a set threshold of all exposures (we choose the number).

An inconclusive result means the agent recommends **keep running** and does nothing.

---

## 5. Safety and engineering rules
- **Dry-run is the default** for every Tier ≥ 1 action. `--apply` executes. Every plan and result is appended to `audit.jsonl` with these fields:
  - `ts`, `actor`, `action`, `tier`, `method`, `path`, `body_hash`, `dry_run`, `approved_by`, `status`, `response_id`.
- **Secrets:**
  - Only in `.env`, which is git-ignored; `.env.example` holds placeholders.
  - Never print keys, and never copy `flagsmith.env`.
  - Audit bodies are hashed and keys redacted.
- **Rate limit:** store the last `results/refresh/` time and refuse a refresh within 5 minutes.
- **Token efficiency:**
  - All CLI calls use `--jq`, so only the fields we need reach the LLM.
  - Gates and the verdict are deterministic Python. The LLM writes only the explanation and the code-removal diff.
  - Use a prompt-cached system prompt.
  - Print `input_tokens` / `output_tokens` per run and the session total.
- **Cleanup PR:**
  - Find the `get_experiment_flag("<flag>"…)` call sites, keep the winning branch and delete the losing one.
  - Run the tests, open the PR with `gh`, and link the experiment in the PR body.
  - **A human merges.** Deleting the flag is a separate Tier 3 step after the merge.

---

## 6. Constraints that shape the plan
1. **The flag is locked while running.** Only the rollout % can change [doc].
2. **Ending is final.** Results freeze, the flag unlocks, and the experiment can't be restarted [doc].
3. **`complete/` is in the API spec only, not in the docs** [schema]. **Smoke test passed on 2026-11-26** (results below) [ran]. The spec says it "completes an experiment and decides what its feature serves afterwards: control, one variant, or the flag disabled. The rollout override is removed."
   **Gate before building `ship`:** run it once on a throwaway flag and experiment, `flagpilot-smoke`. Confirm the request is accepted, `status` becomes `completed`, and `flagsmith evaluate --identity <id>` returns the winning value for every identity. If that fails, the fallback is to end the experiment in the dashboard and roll out with a documented flag update.

   Smoke test: Development, flag `flagpilot-smoke` (`305152`), variant `winner` (`37078`), experiment `576`, metric `565` [ran]:
   - Request: `POST E/experiments/576/complete/` with `{"rollout_decision":"variant","rollout_variant":37078}`, from status `running`.
   - Response: accepted, body includes `id: 576`. The full body and HTTP code weren't captured; the spec says 200 with the experiment object [schema].
   - `GET E/experiments/576/` afterwards: `status: completed`, `ended_at` set, `rollout_decision: variant`, `rollout_variant: 37078`, `experiment_rollout: null`.
   - Before: 5 of `smoke-1..10` got `winner`, 5 `control`. About 1 s after, 1 still got `control`; at about 14 s and 17 s all 10 got `winner` (`SPLIT; weight=100.0`). **The rollout reaches all identities in about 15 s, so `ship` must poll `flagsmith evaluate` until all sampled identities return the winner.** 20 other identities also got `winner`.
   - **The rollout is a 100% variant weight; the flag's default value stays `control` for unidentified requests** (`evaluate` without an identity).
   - After completion the SDK returns no experiment metadata, so no further exposures are recorded. Production still served `control` (5 identities).
   - **Accepted with the warehouse `pending_connection`, no simulated traffic and no results refresh**, so `complete/` does not check results: Flag Pilot's ship gates are the only safety net.

   **`ship --apply` verified end to end on `592` [ran]** (2026-11-26, through `/ship-winner`):
   - Rehearsal: flag `flagpilot-rehearsal` (`305225`), variant `buy_now` (`37123`), experiment `592`, metric `565`, 600 SIMULATED users (rates 0.10 / 0.16, seed 1).
   - Flagsmith's results matched the delivered counts: control 27/300, `buy_now` 53/300; `SHIP_VARIANT`, chance to win 98.6%.
   - `complete/` accepted; `status: completed`, `ended_at` set, `rollout_decision: variant`, `rollout_variant: 37123`, `experiment_rollout: null`.
   - 10/10 verify identities got `buy_now` 7 s after the call (before the simulator run: 6 `buy_now`, 4 `control`). `evaluate` without an identity still returned `control`.
   - `audit.jsonl` has the dry-run and apply of each provisioning, start, simulator and ship step.
   - `/ship-winner` stopped, changing nothing, on an empty id, on "no", and on the experiment name sent before the dry-run.
   - Mistyped id (09:42 UTC): `/ship-winner 570` was sent when the rehearsal `592` was meant. The agent warned that `570` is the demo experiment and recommended "no"; the answer was no and `ship` was not run for it [ran]. The catch came from the agent layer using that session's instructions, not from a gate (`570` passed all 8 rules). The code's backstop is the typed experiment name.
4. **Refresh at most once every 5 minutes** [doc].
   `exposures/refresh/` is limited too: 12 s after a refresh it answered 429, `A refresh was requested recently… Expected available in 288 seconds.` `recommend --refresh` now skips a rate-limited step and carries on [ran].
   On `592`, a refresh seconds after the simulator finished already counted all 600 users, and results about 1 minute later included every conversion [ran].
5. **Every variant needs `--key`**, or no exposures are recorded. `control` is reserved. `--variants` on `feature create` can't set keys [doc].
6. **Identify before getting the flag.** Use the same identifier for exposure and conversion. Event names are case-sensitive [doc].
7. **Events** older than 10 days or more than 24 hours in the future are rejected. A batch over 2 MiB is rejected whole [doc].
8. **Warehouse is the critical-path risk.** Results can't show until it is Connected, the first event can take hours, and the official prompt says to stop if there's no warehouse [doc].
   **Deadline: end of day 1.** If Cloud is still "Pending Connection", take one of these:
   - Switch to a local instance using Flagsmith's local setup prompt. It needs Docker and ports 8000/8001 on the Mac, and its Flagsmith-database warehouse connects immediately.
   - Ask the organizers for help.
   We never demo with fabricated results.
   **Resolved 2026-11-26:** the warehouse still says `pending_connection`, but it has 670 events and results are computed, so the local fallback is not needed [ran].
9. **MCP server:** not used for experiments (it can't start them) [doc].
10. **One active experiment per flag** [doc, schema].
11. Creating an experiment with experiment_rollout.enabled=true applies the split immediately, before start; exposures are only recorded after start [ran].

---

## 7. Phase plan

| Phase | Deliverable | Done when |
|---|---|---|
| **0 Verify** | This file, CLI auth, `flagsmith init`, warehouse status | ⏳ Only `init` and recording the warehouse status are left |
| **1 Foundation** | Python 3.12 project; `flagsmith>=6.3.0`, `anthropic`; `.env.example`; FastAPI demo (one flag, control + one variant, identify, conversion, flush); flag + metric + experiment created via CLI/API (**not started**, dry-run first); simulator (a few hundred users) | `feature get` shows the keyed variant, and the experiment `status == created` |
| **2 Recommend + ship (core)** | Start the experiment (Tier 2) and run simulator traffic. `complete/` smoke test on `flagpilot-smoke`. `flagpilot recommend` (rules plus plain-English card). `flagpilot ship` (Tier 3 approval, then `complete/`). | Real results read; experiment `completed`; flag serves the winner; actions in the audit log |
| **3 Polish core** | README, demo script, 2-minute video, token report | Submittable without the stretch goal |
| **4 Cleanup PR (stretch)** | `flagpilot cleanup`: removes the losing branch and the flag reads, runs tests, opens the PR; a human merges; flag deletion after merge | PR open with a passing diff |

**Day-1 checkpoint:** warehouse Connected? If not, use the fallback in §6.8.

**Demo story (about 2 min):**
1. Results arrive.
2. `flagpilot recommend` shows "Variant `buy_now` has a 97% chance to win, +12% lift; all gates pass."
3. `flagpilot ship` stops and asks for approval; type the name; the flag ships.
4. `flagpilot cleanup` opens a PR deleting the dead code.
5. `audit.jsonl` and the token report are shown.

---

## 8. Open items
- [x] Run `flagsmith init` with the Development client-side key [ran].
- [x] Record the warehouse status from `GET E/warehouse-connections/`: `pending_connection` (§2) [ran].
- [ ] Create a server-side key and put it in `.env` only.
- [x] Confirm the real `results/` payload shape once there's data: differs from the spec, see §3 [ran].
- [x] Smoke-test `complete/` on `flagpilot-smoke` before building `ship` (§6.3): passed [ran]. The flag can be archived later.
- [x] Run `docker info` on the Mac: the daemon is not running, so start Docker Desktop and rerun before relying on the fallback [ran].
- [x] End of day 1: stay on Cloud. The warehouse says `pending_connection` but results are computed (§6.8) [ran].
- [ ] Pick the quarantine threshold for gate 5.
- [x] GitHub repo for the cleanup PR: private `BarisPrespects-23849/flag-pilot` created and `main` pushed (2026-11-26) [ran].
