# 06 — Provision the dual-LLM execution path (OpenRouter free tier) and run the pilot

**Status:** awaiting approval
**Author:** Claude (Data Engineer role), for Gabriel Cepeda
**Date:** 2026-07-15 (revised same day: switch LLM provider to OpenRouter free models per
explicit request)
**Based on:** `Plans/01`–`05` (scaffold, Free Edition fixes, a deploy test, a run+destroy
test, and the real pipeline implementation — all already applied). Current baseline:
`pytest -q` passes 54/54, no `NotImplementedError` remains anywhere in `src/postop/*.py`
or `notebooks/curate_edge_cases.py`. Per Plan 04, the bundle deployed for that earlier
test (against stub code, expected to fail) was torn down afterward
(`databricks bundle destroy -t dev`) — **nothing is currently deployed to the workspace**,
and `sql/ddl/*.sql` has never been run against it.

## Goal

Get from "code is real and unit-tested locally" to "the §14 pilot (20-30 patients) has
actually run end-to-end on the real Free Edition workspace, and we know its real cost and
data-quality numbers" — the last unresolved item in the Technical Design's own §17
"Próximos pasos", short of the two items that aren't engineering work (clinical-committee
sign-off, human-curated edge cases).

## Revision note (why this plan changed from the first draft)

The first draft of this plan treated Databricks Model Serving as the primary LLM path and
left "external API" as an unvalidated fallback (risk R5). Explicit instruction now is to
use a **free external API — OpenRouter — for the implementation**, so this revision
promotes that path from fallback to primary and designs around OpenRouter's real
constraint: **its free (`:free`) models are rate-limited per-account, and this pilot's call
volume does not fit inside a single day's free quota.** That changes Phase 0 (what to
spike), Phase 1 (what code needs to exist), and Phase 4 (how the pilot actually gets run)
compared to the first draft. Databricks Model Serving isn't removed from the code — it
stays as a second, still-untested provider option — but it's no longer what this plan
pursues.

## What's still missing, concretely (found while drafting this)

1. **Job wiring gap:** `databricks.yml` declares a `pilot_n_pacientes` bundle variable
   (default `"25"`), but `resources/postop_pipeline.job.yml`'s `generate_synthea_profiles`
   task never references it — its `parameters` list is just `["--catalog",
   "${var.catalog_name}"]`. Run the job today and it silently falls through to
   `generate_synthea_profiles.py`'s own default, `population.n_pacientes_representativos`
   = **300**, not the pilot's 25. That defeats the entire point of piloting before scaling
   (§14) and would 12x the LLM spend of a "pilot" run without anyone asking for that.
2. **No OpenRouter client exists yet.** `simulate_dual_llm._default_client` only
   implements the Databricks Model Serving path (`WorkspaceClient().serving_endpoints
   .query()`). There is no HTTP client for OpenRouter's chat-completions endpoint, no
   throttling/backoff logic, and no code path selecting between providers. This needs
   real code, not just a wired-up variable — see Phase 1.
3. **Free-tier call budget doesn't cover the pilot in one day.** OpenRouter's `:free`
   model variants are capped per-account at **20 requests/minute**, and **50
   requests/day** with no credit purchased, or **1,000 requests/day** once at least
   $10 in credits has been purchased (all-time, not a subscription) — per OpenRouter's
   rate-limit docs, confirmed via their FAQ and API-reference pages during this planning
   pass. This pilot's call volume is deterministic, not "up to": `simulate_postop_
   trajectories` fires exactly `len(trajectories.call_days)` = 4 calls per patient (no
   probabilistic skipping — confirmed by reading the code), × 6 `FOLLOWUP_AREAS` × 2
   LLM calls per turn (agent + patient) = **48 LLM calls/patient**. A 25-patient pilot is
   therefore exactly **1,200 calls** — over 24x the no-credit daily cap and still over the
   1,000/day cap with credit purchased. See Phase 4 for how this gets resolved.
4. **No resume/skip logic for a multi-day run.** `run_dual_llm_batch` re-simulates (i.e.,
   re-calls the LLM for) every row in `casos_table` on every invocation. The `MERGE INTO
   ... WHEN MATCHED THEN UPDATE` makes re-running non-duplicating in the *output table*,
   but it does **not** skip LLM calls for casos already written — rerunning today burns
   the same call budget a second time instead of resuming where a throttled run left off.
   If the pilot has to span more than one day (likely, per #3), this has to be fixed:
   filter `casos_rows` against `caso_id`s already present in `output_table` before calling
   `simulate_conversation` at all.
5. **DDL never applied, and it targets the wrong catalog name for `dev`:**
   `sql/ddl/00_catalog_schemas.sql` (and the table DDLs under it) hardcode
   `postop_dataset`, but the bundle's `dev` target overrides `catalog_name` to
   `postop_dataset_dev` (`databricks.yml`). Applying the DDL as-is would create
   `postop_dataset`, not the catalog the `dev` job actually writes to. Needs a
   catalog-name substitution when applying, not a DDL file rewrite (prod still wants the
   literal `postop_dataset` name).
6. **`governance.committee_emails` is `[]`:** not a blocker — for a participant-only pilot
   this just means `sql/ddl/30_publish_gold_grants.sql`'s comité-specific grants are a
   no-op, which is correct until real committee emails exist.

## OpenRouter model choice — Phase 0 spike run, real results (2026-07-15)

Ran three one-off `databricks jobs submit` notebook tasks against the real Free Edition
workspace (no bundle deploy needed, nothing left deployed afterward — spike notebooks were
deleted from the workspace after gathering results). Full evidence below is the actual
output, not a plan-time guess.

**1. Egress confirmed working.** `GET https://openrouter.ai/api/v1/models` from Free
Edition serverless compute returned `200`, 342 models, 23 with zero/`:free` pricing. The
docstring's assumption that Free Edition blocks external egress by default does **not**
hold for openrouter.ai — no workaround needed.

**2. Upstream-provider throttling is real and immediate, not a rare edge case.** Sent one
real agent-turn Spanish request (using the actual `prompts/agent_system.md` template) to
each of 6 candidates, with one respected retry honoring the provider's
`retry_after_seconds` on a 429:

| Model | Result |
|---|---|
| `meta-llama/llama-3.3-70b-instruct:free` | 429 both attempts — "temporarily rate-limited upstream" (provider: Venice) |
| `qwen/qwen3-next-80b-a3b-instruct:free` | 429 both attempts |
| `nvidia/nemotron-3-super-120b-a12b:free` | 429 |
| `google/gemma-4-31b-it:free` | 429 |
| `nvidia/nemotron-3-nano-omni-30b-a3b-reasoning:free` | **200 OK** — coherent, on-character Spanish: *"¿Cómo ha estado el dolor desde la última vez que le llamé?"* |
| `openrouter/free` (auto-router) | **200 OK** — coherent, on-character Spanish: *"¿Cómo está el dolor hoy? ¿En qué escala lo calificaría del 1 al 10?"* |

The two most name-recognizable models (Llama 3.3 70B, Qwen3-Next-80B) are the ones
everyone else on OpenRouter's free tier hits first, so they're the most congested — this
matches the user's warning going in. The 429 error is a **provider-level** rejection
("temporarily rate-limited upstream"), separate from OpenRouter's own account-wide
20/min-50-or-1000/day cap (see below) — a real pilot run has to survive both failure
modes, not just one.

**3. Retry hint location, confirmed empirically:** on a provider 429, `Retry-After` is
**not** a top-level HTTP response header (came back empty in every case checked) — it's
nested in the JSON error body at `error.metadata.retry_after_seconds` (seen values: 12,
24, 25, 29 — i.e. roughly "try again in ~15-30s", not immediately). `_openrouter_client`'s
retry logic (Phase 1) must parse the JSON body for this, not just check response headers.

**4. Token usage confirmed OpenAI-shaped**, as assumed: `usage.prompt_tokens` /
`usage.completion_tokens` present on success. One wrinkle found: both successful
responses came from **reasoning-capable models** — `nemotron-3-nano-omni-...-reasoning`
by name, and `openrouter/free` also landed on a reasoning model this time — and
`completion_tokens_details.reasoning_tokens` accounted for the large majority of
`completion_tokens` (303/314 and 216/245 respectively). Phase 5's token-total reporting
should note this: the `completion_tokens` sum will include hidden chain-of-thought tokens,
not just the visible dialogue text, so it overstates "cost of the visible transcript" if
read naively.

- **Decision: pin `nvidia/nemotron-3-nano-omni-30b-a3b-reasoning:free` as the primary
  model** — it was reachable when two more "obvious" choices weren't, and produced a
  good-quality, on-character Colombian-Spanish response on the first try. **Fall back to
  `openrouter/free` (the auto-router) as the retry escape hatch** if the pinned model's
  retries are exhausted mid-run — this is no longer theoretical, it's based on the router
  succeeding in this exact spike when several pinned alternatives didn't. This keeps
  quality mostly consistent (one deliberately-chosen model) while giving real resilience
  against the congestion pattern just observed, instead of pinning a popular model likely
  to be congested again during the actual pilot run.
- Rate limits: confirmed via docs (not directly re-verified via response headers this
  pass, since every attempted burst 429'd at the provider level before reaching any
  account-level cap) to be account-wide across `:free` traffic, per OpenRouter's FAQ
  wording — Phase 1's throttle logic still self-paces under 20/min as cheap insurance,
  independent of which failure mode actually bites first.
- This is a live-system snapshot from 2026-07-15 — which specific model is congested
  changes over time. Phase 1's fallback-to-router design is what actually matters here,
  more than which exact model is "primary" today.

## Plan

### Phase 0 — Spike: OpenRouter reachability, model pick, and quota reality-check — ✅ DONE (2026-07-15)

Results captured in the "OpenRouter model choice" section above. Egress confirmed working,
model picked (`nvidia/nemotron-3-nano-omni-30b-a3b-reasoning:free` primary,
`openrouter/free` fallback), throttling behavior characterized against the real API. Steps
below are the record of what was done, kept for reference.

- **Prerequisite (user action, not mine):** an OpenRouter account + API key
  (openrouter.ai — free to create). I cannot create this for you; once you have a key,
  store it as a Databricks secret (not pasted into chat or committed anywhere):
  `databricks secrets create-scope postop-llm-secrets` (if it doesn't already exist),
  then `databricks secrets put-secret postop-llm-secrets openrouter-api-key` (prompts for
  the value interactively, keeps it out of shell history).
- From a scratch notebook cell or a one-off serverless task (no bundle deploy needed for
  this spike): confirm serverless compute can actually reach `openrouter.ai` at all — the
  codebase's existing docstring assumes Free Edition restricts egress to "a limited set of
  trusted domains," but that's an assumption, not something confirmed for this workspace.
  (Side note found while researching: Databricks' *network policy* egress-restriction
  feature is documented as Enterprise-tier only, which suggests Free Edition may not
  actually have an enforced allowlist at all — but that's inference from docs, not proof
  for this workspace. Confirm empirically.)
- Re-query `GET https://openrouter.ai/api/v1/models` live (don't trust this plan's
  snapshot) and send one real chat-completion request in Spanish, in-character as the
  patient/agent prompts would (`prompts/patient_system.md`, `prompts/agent_system.md`),
  to the leading candidate model. Confirm: response is coherent Spanish, `usage.
  prompt_tokens`/`usage.completion_tokens` are present (OpenRouter mirrors the OpenAI
  response shape, so `_openrouter_client`, built in Phase 1, can parse it the same way
  as `_default_client` parses Model Serving's response).
- Send a couple more requests back-to-back and inspect `X-RateLimit-Limit` /
  `X-RateLimit-Remaining` / `X-RateLimit-Reset` response headers to confirm the
  account-wide-not-per-model reading above.
- **Fork:**
  - Reachable + one model behaves well → record its exact ID, carry into Phase 1.
  - Blocked (egress denied) → stop and report, same posture as Plan 05's `pysynthea`
    dead end: this is a bigger finding than something to route around silently (would mean
    falling back to Databricks Model Serving, whose own availability on Free Edition is
    *also* unconfirmed — see original Plan 06 draft's Phase 0 — a genuinely blocked-both-ways
    finding worth surfacing, not guessing past).

### Phase 1 — Fix the job/bundle wiring gap and build the OpenRouter client — ✅ DONE (2026-07-15)

Implemented as designed below. `pytest -q`: 66/66 (54 original + 12 new in
`tests/test_simulate_dual_llm.py`, covering `_casos_pendientes`, `_extract_retry_after_
seconds`, `_RequestPacer`, and `_openrouter_request`'s retry/backoff/fail-fast branches
against a mocked HTTP layer — `_openrouter_client`/`_default_client` themselves stay
untested, same as before, since both defer-import `databricks.sdk`, unavailable outside
the cluster). `databricks bundle validate -t dev --profile default` → `Validation OK!`.
Steps below are the original design, now implemented as written.

- `resources/postop_pipeline.job.yml`: add `"--n-pacientes", "${var.pilot_n_pacientes}"`
  to the `generate_synthea_profiles` task's `parameters`, so a `dev`-target run actually
  generates the pilot's patient count, not 300.
- `databricks.yml`: add an `openrouter_model` variable defaulting to whatever Phase 0
  resolved; keep `model_serving_endpoint` defaulting to `""` (Databricks path stays in the
  code, unused for now).
- `src/postop/simulate_dual_llm.py` changes:
  - New `_openrouter_client(model, secret_scope, secret_key="openrouter-api-key")`
    factory, parallel to `_default_client`: reads the API key via
    `WorkspaceClient().secrets.get_secret(scope, key)` (base64-decode the value — the SDK
    returns it encoded), `POST`s to `https://openrouter.ai/api/v1/chat/completions` using
    stdlib `urllib.request` (no new dependency needed — OpenRouter's API is a plain
    OpenAI-compatible REST endpoint, so `anthropic>=0.34` in `requirements.txt`/job
    `environments` is dead weight for this path and should come out), parses the
    OpenAI-shaped response the same way `_default_client` parses Model Serving's.
  - **Throttling, built in, not bolted on — design confirmed against real 429s in Phase
    0:** self-pace requests to stay under 20/min with margin (e.g. a simple token-bucket
    or fixed ~4s minimum gap between calls — cheap insurance against tripping the
    per-minute cap even before the daily cap is the binding constraint). On HTTP 429:
    **parse `error.metadata.retry_after_seconds` from the JSON response body** (confirmed
    empirically — the `Retry-After` HTTP header came back empty on every provider 429 seen
    in Phase 0; the hint only exists in the body), sleep accordingly, retry with
    exponential backoff + jitter if the field is missing, capped attempts. **After the
    pinned model (`nvidia/nemotron-3-nano-omni-30b-a3b-reasoning:free`) exhausts its
    retries, fall back to `openrouter/free` (the auto-router) for that call** before
    giving up entirely — Phase 0 showed the router succeeding at the exact moment three
    other pinned models were 429ing, so this is a real resilience layer, not a
    theoretical one. Only after *both* the pinned model and the router fail does the call
    raise (fail loud) so real exhaustion surfaces as a task failure, not a silent partial
    run. Free-tier models are also known to be flaky under load (shared capacity) — apply
    the same retry treatment to 5xx/timeout, not just 429.
  - `--llm-provider {openrouter,databricks}` CLI arg (default `openrouter`), dispatched in
    `main`/`simulate_conversation` to pick `_openrouter_client` vs the existing
    `_default_client`.
  - **Resume/skip fix (addresses gap #4 above):** before building `casos_rows`, query
    `output_table` for `caso_id`s already present and exclude them from the batch. Without
    this, a second `bundle run` (needed because of the daily quota — see Phase 4) redoes
    already-paid-for LLM calls instead of picking up where the first run's quota ran out.
  - New unit tests: mock the `urllib`/HTTP layer to test the throttle/backoff/retry logic
    and the resume/skip filter without any real network calls — keeps `pytest -q` fully
    offline like the rest of the suite.
- No other `src/postop/*.py` changes — Plan 05 already made the rest of the pipeline logic
  real; this phase is the LLM client + bundle/job plumbing only.

### Phase 2 — Apply DDL to the real workspace, targeting `postop_dataset_dev` — ✅ DONE (2026-07-15)

**Bug found and fixed along the way:** `publish_gold.py`'s `_load_sql_statements` helper
(which parses `sql/ddl/*.sql` into individual statements and substitutes the catalog name)
split on every literal `;` *before* filtering out comment lines — several comments in
`sql/ddl/00_catalog_schemas.sql`, `22_noise_mapping_log.sql`, `23_dialogos_capa3_limite.sql`,
and `30_publish_gold_grants.sql` contain a `;` inside the sentence (prose, or a documented
GRANT example), which corrupted the statement immediately after. Two concrete failure
modes confirmed: (1) `00_catalog_schemas.sql`'s first real statement came out as
`"...documentan el contrato\nCREATE CATALOG IF NOT EXISTS postop_dataset"` — invalid SQL,
would have failed this phase's bootstrap outright; (2) in `30_publish_gold_grants.sql` —
**auto-executed by `publish_gold.py` at job runtime, not manually** — the corruption made
`GRANT USE CATALOG ON CATALOG ... TO account users` no longer start with `GRANT`, so
`apply_grants`'s `stmt.upper().startswith(("GRANT", "REVOKE"))` filter silently dropped it.
That grant is a prerequisite for participants to access the catalog at all — this was a
silent, pre-existing correctness bug unrelated to OpenRouter, found only because Phase 2
needed to actually run this function against the real workspace. Fixed by filtering
comment lines before splitting on `;`, not after; added 3 regression tests in
`tests/test_publish_gold_expectations.py`. `pytest -q`: 69/69.

**Scope correction from the original design:** only applied `sql/ddl/00` through `23`
manually (9 files, 23 statements) — **not** `30_publish_gold_grants.sql`. Found while
reading `publish_gold.py` that it already calls this same (now-fixed) `_load_sql_statements`
helper on `30_publish_gold_grants.sql` itself at job runtime, with the same
`postop_dataset` → real catalog substitution the original Phase 2 design called for doing
manually. Running it by hand now would have been redundant (premature grants/views against
empty tables) and duplicated what Phase 4/5's `publish_gold` task already does correctly.

**Execution:** SQL Statement Execution API via `databricks api post/get` (CLI, existing
`default` profile auth) against warehouse `ec42721d582d8855` ("Serverless Starter
Warehouse", auto-started from `STOPPED` on first query). All 23 statements → `SUCCEEDED`.

**Confirmed:** `SHOW SCHEMAS IN postop_dataset_dev` → `bronze, default, gold_comite,
gold_participantes, information_schema, silver`. `SHOW TABLES IN postop_dataset_dev.silver`
→ all 7 expected tables (`casos_clinicos_etiquetados`, `dialogos_capa1_limpia`,
`dialogos_capa2_ruidosa`, `dialogos_capa3_limite`, `noise_mapping_log`,
`perfiles_pacientes`, `perfiles_pacientes_co`).

Steps below are the original design; the deviations above are what actually happened.

- Execute `sql/ddl/00_catalog_schemas.sql` through `sql/ddl/30_publish_gold_grants.sql`,
  in numeric order, against the workspace's SQL warehouse via the SQL Statement
  Execution API (`WorkspaceClient().statement_execution.execute_statement(...)`, run
  locally with the existing `default` CLI profile's auth — no manual notebook, no bundle
  task needed for a one-time bootstrap), with `postop_dataset` substituted to
  `postop_dataset_dev` for this run only (matching the `dev` target's `catalog_name`).
- Confirm afterward: `SHOW SCHEMAS IN postop_dataset_dev`, `SHOW TABLES IN
  postop_dataset_dev.silver`.

### Phase 3 — Redeploy the bundle — ✅ DONE (2026-07-15)

`validate` → `Validation OK!`. `deploy` → `Deployment complete!`. New job: `postop_pipeline`,
job ID `639001107661110`
(https://dbc-5dde2f73-7c6f.cloud.databricks.com/jobs/639001107661110?w=3987877160225648) —
the Plan 03 job (`784301521213099`) stays gone, this is a fresh one from this deploy.

Confirmed via `databricks jobs get` that the deployed task parameters actually reflect
Phase 1's wiring, not just the YAML source: `generate_synthea_profiles` →
`--n-pacientes 25`; `simulate_dual_llm` → `--llm-provider openrouter --openrouter-model
nvidia/nemotron-3-nano-omni-30b-a3b-reasoning:free --secret-scope postop-llm-secrets`; all
7 tasks target `postop_dataset_dev`. Nothing run yet — Phase 4 is the next step, and it's
the money-spending one that needs an explicit go-ahead per the options laid out below.

- `databricks bundle validate -t dev --profile default`
- `databricks bundle deploy -t dev --profile default`
- `databricks bundle summary -t dev --profile default` — new job ID/URL (the Plan 03 job,
  `784301521213099`, no longer exists — it was destroyed in Plan 04).

### Phase 4 — Run the pilot (the money-spending step, and the throttled one)

**Pilot sizing decision (2026-07-15):** given the free-tier quota math above, chose the
fully-free, one-time-run option rather than buying $10 credit: `pilot_n_pacientes=1`
(48 LLM calls, comfortably under the 50/day no-credit cap), run once, not repeated daily
toward the full 25. This trades pilot size for zero spend — a real 1-patient pilot has
limited statistical signal for §12's label-balance checks, noted explicitly as a
limitation of this run, not hidden.

**Second bug found — unrelated to OpenRouter, blocked the very first task:** the first
real `bundle run` attempt failed at cluster launch, before `generate_synthea_profiles.py`
executed at all (zero LLM calls made, zero cost, zero OpenRouter quota spent):
`Cannot launch the cluster. Cause: Invalid platform channel Client-1. Workspace doesn't
support Client-1 channel for REPL.` Root cause: `resources/postop_pipeline.job.yml`'s
`environments.spec` used `client: "1"` — a **deprecated** field (bundle schema:
`"description": "Use environment_version instead", "deprecated": true`) — and this
workspace no longer supports environment version 1 for serverless job REPLs at all.
Probed empirically via one-off `jobs submit` calls (trivial notebook, no bundle deploy):
`environment_version` 2/3/4 all launch successfully, 1 does not; confirmed 3 also
installs the real dependencies (Faker, databricks-sdk) cleanly. Fixed by switching
`resources/postop_pipeline.job.yml` to `environment_version: "3"`, redeployed the bundle,
re-triggered the run.

- **Quota math, restated:** 25 patients × 48 calls/patient = 1,200 calls. No-credit free
  tier (50/day) would take **24 days** run serially at max daily throughput. Buying $10 of
  OpenRouter credit (one-time, not a subscription) raises the cap to 1,000/day, fitting the
  pilot into **2 days** of `bundle run` invocations instead of 24 — this is a real, if
  small, spend decision and needs your explicit go-ahead, same as the Model Serving
  spend in the original draft.
- **Options, in order of recommendation:**
  1. **Buy $10 OpenRouter credit, run over 2 days.** Day 1: `databricks bundle run
     postop_pipeline -t dev --profile default` with `--var openrouter_model=<picked>`
     (exact flag confirmed against the installed CLI version at run time). It processes
     up to ~1,000 calls (~20 patients) before hitting the daily cap and failing loud on
     the 21st-ish patient's calls (per Phase 1's fail-loud retry ceiling). Day 2: rerun the
     same command — the Phase 1 resume/skip fix means it only processes the remaining
     ~5 patients, not all 25 again.
  2. **Shrink the pilot to fit one free day.** `pilot_n_pacientes` ≈ 1 (48 calls, under the
     50/day cap) gives almost no statistical signal for §12's quality checks (label
     balance needs more than one patient) — not a real option for a meaningful pilot, but
     worth naming since it's the only zero-cost path.
  3. **Multi-day free run, no purchase.** ~1 patient of signal/day, 25 days to finish.
     Technically free, practically a very slow pilot for what buying $10 of credit turns
     into a 2-day pilot.
  - I'd default to (1) but this is your call given it's real (if small) spend — confirming
    before triggering Phase 4, not assuming.
- If `_openrouter_client` fails (auth, wrong response shape, quota exhausted before
  expected, egress blocked mid-run) report the exact task-level error rather than
  iterating blindly mid-run — a real failure here is a new finding, not something to
  silently patch and re-run.

### Phase 4 — actual execution record (2026-07-15): 6 real bugs found and fixed

Getting from "bundle deployed" to "one real dialogue generated" took far more than the
throttling design this plan anticipated — every layer between "code passes `pytest`" and
"code runs on real Databricks serverless" had never been exercised before, and each one
had a real, previously-invisible bug. Found and fixed, in the order hit (all except the
last one caught with **zero** LLM cost, since the DAG only spends money at
`simulate_dual_llm`, task 5 of 7):

1. **`environment_version` (job.yml):** the original `client: "1"` field is deprecated
   (bundle schema: `"Use environment_version instead"`) and this workspace outright
   rejects it (`Invalid platform channel Client-1`). Probed 2/3/4 empirically via one-off
   `jobs submit` calls; fixed to `environment_version: "3"`.
2. **`__file__` undefined in every entrypoint:** Databricks runs `spark_python_task`
   scripts via `exec(compile(source, filename, 'exec'))`, which never injects `__file__`
   into the globals — so every `sys.path.insert(0, str(Path(__file__)...))` bootstrap
   (itself needed because `src/` isn't on `sys.path` for a bare, non-wheel-packaged
   script) raised `NameError`. Fixed by resolving the real path via
   `sys._getframe().f_code.co_filename` instead, in all 7 entrypoints (`publish_gold.py`
   had a second `__file__` reference for `_SQL_DDL_ROOT`, fixed too).
3. **`--catalog` silently ignored for all table reads/writes:** `config.catalog_name()`
   always read `conf/project.yml`'s static `postop_dataset`, with no way to override it —
   despite every script accepting `--catalog` and the module's own docstring claiming an
   override existed. `publish_gold.py` was the one file that never had this bug (it builds
   table names from `catalog` via plain f-strings, not `config.table_fqn`). Fixed by
   adding a `catalog_override` parameter threaded through `catalog_name`/`schema_fqn`/
   `table_fqn`, and updating all 6 affected entrypoints' `main()` (plus
   `run_dual_llm_batch`, which re-resolved `perfiles_table`/`perfiles_co_table`
   internally, independent of what its caller already resolved) to pass `args.catalog`.
4. **Bronze volume never cleared between runs:** `write_bundles_to_volume` wrote new
   bundle JSON files but never removed old ones, and `parse_bundles_to_perfiles_pacientes`
   globs *everything* present — so a small pilot run after an earlier larger test run
   re-ingested the old run's leftover files (`silver.perfiles_pacientes` kept coming back
   with 25 rows instead of the pilot's 1). Fixing this exposed **a second, subtler bug**:
   deleting a stale file and immediately rewriting the *same filename* (patient index 0
   under the same seed collides across runs of different sizes) raced against the Unity
   Catalog Volume's storage backend — the freshly-written file was gone by the time the
   very next `glob()` ran, moments later, confirmed via a diagnostic print showing 0 files
   immediately after a successful 1-file write. Fixed by reordering: write all target
   files first (an overwrite-in-place for colliding names, no delete-then-recreate), only
   delete genuine orphans (present before, absent from this run's target set) afterward.
5. **`prompts_dir` default was a bare relative string (`"prompts"`):** worked under
   `pytest` (which runs from the repo root) but not under a real `spark_python_task`,
   whose working directory isn't the repo root — `FileNotFoundError:
   'prompts/patient_system.md'`. Fixed with a `_DEFAULT_PROMPTS_DIR` computed once from
   the script's real path (via the same `sys._getframe()` trick).
6. **(Phase 2, found earlier) `_load_sql_statements`'s comment-vs-`;` parsing bug** —
   already fixed and reported in Phase 2 above; listed here only for the full count.

None of these were catchable by `pytest -q` alone — every one required actually executing
on Databricks serverless against the real workspace, which is exactly why this phase
existed. Regression tests added for all 6 (`tests/test_config.py`,
`tests/test_generate_synthea_profiles.py`, `tests/test_simulate_dual_llm.py`,
`tests/test_publish_gold_expectations.py`) — 79/79 passing at the end of this phase (up
from 54 at Plan 06's start).

**Debugging method:** rather than repeatedly re-running the full 7-task `bundle run`
(expensive in wall-clock time, and risky — a bug in task 2 discovered only after task 5
had already spent LLM calls would be wasteful), used the Jobs API's `run-now` with `only:
[task_keys]` to isolate and cheaply re-test individual tasks or small chains against the
already-deployed job, only assembling the full chain once each piece was confirmed working
in isolation. `simulate_dual_llm` — the one task that actually spends OpenRouter quota —
was deliberately the last thing tested, once tasks 1-4 were confirmed correct against
exactly the pilot's 1-patient dataset (not leftover data from earlier infra testing).

**The actual pilot run:** `simulate_dual_llm` → **SUCCESS**. 4 casos (1 patient × 4
`call_days`) × 6 `FOLLOWUP_AREAS` × 2 speakers = 48 real turns, all against
`nvidia/nemotron-3-nano-omni-30b-a3b-reasoning:free` (no fallback-to-router needed — the
primary model held up for the whole run). Real token totals: **126,936 prompt_tokens,
189,798 completion_tokens** across 48 turns. Sample dialogue (paciente, estilo
`minimizador_sintomas`, label `verde`) read as coherent, in-character, natural Colombian
Spanish, covering all 6 areas, no diagnostic language, no label leakage — qualitatively a
real success for the dual-LLM design.

`inject_noise` → SUCCESS, 49 rows in `dialogos_capa2_ruidosa` (48 + 1 extra row from a
`cambio_interlocutor` structural noise event splitting a turn — expected, not a bug), 21
rows in `noise_mapping_log` covering 21 distinct affected `dialogo_id`s.

`publish_gold` → **FAILED, correctly.** Not an infra bug — the §12 quality gate did
exactly what it's designed to do: refuse to publish. With only 1 patient (4 casos), label
distribution came out `verde=3 (75%), amarillo=1 (25%), rojo=0 (0%)` — verde and rojo both
fall outside the required `[10%, 70%]` band, an unavoidable consequence of a
statistically-tiny one-time pilot (the tradeoff explicitly chosen going into Phase 4, in
exchange for zero OpenRouter spend). No `gold_participantes`/`gold_comite` views or grants
were created — nothing broken publishes past this gate, which is itself a positive
confirmation that `publish_gold.py`'s safety behavior works correctly against real data,
also never exercised before this phase.

### Phase 5 — Validate and report — ✅ DONE (2026-07-15)

**Task-by-task result (single `--var="pilot_n_pacientes=1"` pilot, run in isolated/chained
pieces per the debugging method above, not one unbroken `bundle run`):**

| Task | Result |
|---|---|
| `generate_synthea_profiles` | SUCCESS (1 patient, after fixing bugs #2/#3/#4 above) |
| `simulate_postop_trajectories` | SUCCESS (4 trayectorias) |
| `adapt_colombia` | SUCCESS (1 perfil_co) |
| `classify_ground_truth` | SUCCESS (4 casos) |
| `simulate_dual_llm` | **SUCCESS** — 48 real turns, real OpenRouter cost incurred |
| `inject_noise` | SUCCESS (49 rows capa2, 21 mapping-log rows) |
| `publish_gold` | **FAILED — correctly**, §12 gate blocked publication |

****§12 quality-expectation results, in full** (`run_quality_expectations`, real tables):
- `perfiles_pacientes_co`: pass (no null demographic fields, `adapted_country == 'CO'`).
- `casos_clinicos_etiquetados`: **fail** — `label 'verde' fuera de rango [10%,70%]
  (75.0%)`, `label 'rojo' fuera de rango [10%,70%] (0.0%)`. Raw distribution: verde=3,
  amarillo=1, rojo=0 (of 4 casos) — mechanically unavoidable with n=1; not a code defect.
- `dialogos_capa1_limpia`: pass (every caso has both `paciente` and `agente` turns, no
  empty `texto`).
- `noise_mapping_log`: pass (every capa2 row with `intensidad_ruido IS NOT NULL` has ≥1
  mapping row — "no silent transformation" holds).
- `dialogos_capa3_limite`: pass vacuously (table empty — Capa 3 is out of scope for this
  plan, human-curated separately per §10).

**Token totals (real, from `dialogos_capa1_limpia`):** 126,936 `prompt_tokens` + 189,798
`completion_tokens` = **316,734 total tokens for 1 patient** (48 turns). Scaled linearly,
25 patients ≈ 7.9M tokens, 300 patients ≈ 95M tokens — but linear scaling is a rough floor,
not a real estimate, since per-turn token counts vary with conversation length and (per
Phase 0's finding) a chosen model's hidden reasoning-token overhead. Real dollar cost is
$0 on `:free` — this total exists to size what a paid-tier run would cost, per §14's ask
for real numbers before committing to scale.

**Throttling observed:** zero 429s, zero retries, zero fallback-to-`openrouter/free`
across all 48 calls — the primary model (`nvidia/nemotron-3-nano-omni-30b-a3b-reasoning
:free`) held up for the entire run without contention this time. This is a **single data
point, not a guarantee** — Phase 0 showed the same account hitting persistent 429s on
*other* models (Llama 3.3 70B, Qwen3-Next-80B) minutes earlier the same day; congestion on
free-tier models is real and model-specific, and a 25- or 300-patient run (many more calls,
over a longer wall-clock window) has more exposure to it than this 48-call pilot did.

**Recommendation on scaling:** the dual-LLM mechanism itself is validated — real,
in-character, policy-compliant Spanish dialogue, generated end-to-end on the real
workspace, at zero dollar cost. What's *not* validated by a 1-patient run: label balance
(mechanically impossible to check meaningfully at this size) and sustained throttling
behavior over many more calls. Before scaling to 25 or 300 patients: (1) revisit the Phase
4 pilot-sizing choice — a real 20-25 patient run (fitting inside 1,000 calls/day with the
$10 OpenRouter credit purchase declined this time) would give a statistically meaningful
§12 read, which this run structurally cannot; (2) budget for the fallback-to-router path
actually triggering at that volume, unlike this run.

## Explicitly out of scope for this plan

- **Scaling to the full 300-patient population run** — a follow-up plan once the pilot's
  numbers are in (§14, §17.4). Given the quota math above, that run almost certainly needs
  a paid (non-`:free`) OpenRouter model or Databricks Model Serving, not the free tier —
  a decision for that follow-up plan, not this one.
- **Validating the Databricks Model Serving path** — still unconfirmed whether Free
  Edition exposes a queryable pay-per-token foundation-model endpoint at all (original
  draft's Phase 0 concern). The code path (`_default_client`) stays in place but isn't
  exercised by this plan.
- **Clinical-committee sign-off** on `classify_ground_truth`'s thresholds — not
  satisfiable by code changes (§17.3).
- **Curating Capa 3 edge cases** — human-in-the-loop by design (§10), zero fabricated
  cases, unchanged from Plan 05's stance.
- **Tearing the bundle down afterward.** Unlike Plan 04, this run's output tables are the
  actual deliverable we want to keep and evaluate — no destroy as part of this plan
  unless asked for separately.
- **`prod` target** — `dev` only.

## Risks / confirm before I run this

- **Phase 4 spends real (small) money** — $10 one-time OpenRouter credit purchase, under
  option (1) above — plus real Free Edition serverless compute across 2 days of job runs.
  I'll pause at the Phase 3→4 boundary and confirm the credit purchase, the picked model,
  and which of the three options above before triggering anything, specifically because
  it's the one step with a real cost and a multi-day time commitment in an otherwise
  cheap/reversible sequence.
- **Phase 2 mutates real shared workspace state** (creates `postop_dataset_dev` catalog,
  schemas, tables). Reversible (`DROP CATALOG postop_dataset_dev CASCADE`), but real —
  flagging per the "actions visible to others / affecting shared state" guidance.
- **If Phase 0 finds openrouter.ai egress blocked**, I stop and report instead of guessing
  at a workaround (proxy, different domain, etc.) — that's a bigger, costlier decision I
  want your input on, same as how Plan 05 escalated the `pysynthea` dead end instead of
  silently picking a fallback.
- **This plan's OpenRouter model list and rate-limit figures are a 2026-07-15 snapshot**
  from live docs/API queries, not a guarantee — Phase 0 explicitly re-verifies before
  Phase 1 commits to a model ID, since free-tier lineups change without notice.

## Verification

- `pytest -q` still green (currently 54/54, plus Phase 1's new throttle/backoff/resume
  tests) after Phase 1 — only `simulate_dual_llm.py`, `resources/postop_pipeline.job.yml`,
  `databricks.yml`, and `requirements.txt` (dropping `anthropic`) touched, no other
  `src/postop/*.py` files change.
- Phase 0's spike output (egress result, live model list, quality-check response, rate
  -limit headers observed) captured verbatim in the final report, not summarized away.
- Phase 4's run reaches a terminal state each day it's invoked; Phase 5's §12 checks and
  token totals are real numbers pulled from the deployed tables, not estimates — and the
  resume/skip behavior across the day boundary is confirmed by row counts, not assumed.
