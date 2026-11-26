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
| Warehouse | **Flagsmith (managed)**, id `12751`: `pending_connection`, created 07:24 UTC; 0 events at 07:42 UTC [ran]. Test event sent. Up to a few hours for the first event [doc] |
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
- `flagsmith init --project <p> --environment <env key>` writes `flagsmith.json`. It contains no secrets and is safe to commit [doc].

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

Enums [schema]:
- `status`: created, running, paused, completed.
- `rollout_decision`: control, variant, disable.
- `expected_direction`: increase, decrease, not_increase, not_decrease.
- `aggregation`: occurrence, count, sum, mean.
- `direction`: up, down, informational.

Results fields [schema, **confirm with real data**]:
- `statistics`: `chance_to_win{variant: p}`, `lift`, `winner`, `significant`, `p_value`, `recommendation`, `sample_size_warning`.
- Per variant: `variant`, `evaluations`, `conversions`, `conversion_rate`.

### Python SDK [doc]

The docs don't show a flush or close call for Python. Buffered events are dropped when the interpreter exits, so short scripts must use `max_buffer_items=1`.

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
| **1 Reversible, nothing served** | create flag, add variant, create metric, create experiment (status `created`) | Dry-run shown first, then a single `y/N` |
| **2 Changes what users see** | `start/`, `pause/`, `PATCH rollout/` | Decision card plus `y/N`. Refused if the warehouse isn't connected |
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
3. **`complete/` is in the API spec only, not in the docs, and has never been run** [schema]. The spec says it "completes an experiment and decides what its feature serves afterwards: control, one variant, or the flag disabled. The rollout override is removed."
   **Gate before building `ship`:** run it once on a throwaway flag and experiment, `flagpilot-smoke`. Confirm the request is accepted, `status` becomes `completed`, and `flagsmith evaluate --identity <id>` returns the winning value for every identity. If that fails, the fallback is to end the experiment in the dashboard and roll out with a documented flag update.
4. **Refresh at most once every 5 minutes** [doc].
5. **Every variant needs `--key`**, or no exposures are recorded. `control` is reserved. `--variants` on `feature create` can't set keys [doc].
6. **Identify before getting the flag.** Use the same identifier for exposure and conversion. Event names are case-sensitive [doc].
7. **Events** older than 10 days or more than 24 hours in the future are rejected. A batch over 2 MiB is rejected whole [doc].
8. **Warehouse is the critical-path risk.** Results can't show until it is Connected, the first event can take hours, and the official prompt says to stop if there's no warehouse [doc].
   **Deadline: end of day 1.** If Cloud is still "Pending Connection", take one of these:
   - Switch to a local instance using Flagsmith's local setup prompt. It needs Docker and ports 8000/8001 on the Mac, and its Flagsmith-database warehouse connects immediately.
   - Ask the organizers for help.
   We never demo with fabricated results.
9. **MCP server:** not used for experiments (it can't start them) [doc].
10. **One active experiment per flag** [doc, schema].

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
- [ ] Confirm the real `results/` payload shape once there's data.
- [ ] Smoke-test `complete/` on `flagpilot-smoke` before building `ship` (§6.3).
- [x] Run `docker info` on the Mac: the daemon is not running, so start Docker Desktop and rerun before relying on the fallback [ran].
- [ ] End of day 1: decide whether the warehouse is Connected or we switch to the fallback.
- [ ] Pick the quarantine threshold for gate 5.
- [ ] GitHub repo for the cleanup PR (`gh auth status` on the Mac).
