# 07 — Small-batch run: 10 patients, brief conversations, configurable max_tokens

**Status:** awaiting approval
**Author:** Claude (Data Engineer role), for Gabriel Cepeda
**Date:** 2026-07-15
**Based on:** Plans 01–06 (scaffold, Free Edition fixes, deploy/run tests, real pipeline
logic, OpenRouter provisioning + 1-patient pilot). Current baseline per Plan 06: pilot ran
successfully end-to-end except `publish_gold`'s §12 quality gate, which correctly refused
to publish a 1-patient (4-caso) run for label imbalance. Nothing currently deployed.

## Why this plan exists (recap of this session's conversation)

The original ask was to scale to the full 300-patient population (§14, `population.
n_pacientes_representativos` = 300 in `conf/project.yml`), widen the §12 quality gate by
5 points, and schedule the job to run unattended. Working through the numbers made that
infeasible as stated:

- 300 patients × 4 `call_days` × 6 `FOLLOWUP_AREAS` × 2 speakers = **14,400 LLM calls**.
- On OpenRouter's free tier that's ~24 days at the no-credit 50/day cap, or ~15 days even
  with the $10 credit's 1,000/day cap.
- Claude API (Sonnet 5) was evaluated as an alternative: roughly **$650–970** for the full
  run (linear extrapolation from the pilot's 316,734 tokens/patient — a rough floor, not a
  real estimate), paid once instead of throttled over weeks. Set aside for this run.
- Self-hosted Ollama was evaluated too: architecturally clean (mirrors the existing
  `_openrouter_client` shape), likely cheaper/faster than both of the above if real GPU
  infra is available — but needs a GPU host reachable from Databricks Free Edition
  serverless (a public, authenticated endpoint — Free Edition can't reach a private LAN).
  Not set up yet; revisit as a future option, not blocking this plan.

Given that, the scope for **this** plan is deliberately smaller:

1. **10 patients**, not 300 → 10 × 4 × 6 × 2 = **480 LLM calls** (40 conversations, 12
   turns each) — fits inside OpenRouter's quota in a single day with the $10 credit, or
   ~10 days spread over the no-credit 50/day cap.
2. **Brief conversations** — same 12 turns per conversation (unchanged structure: 6
   `FOLLOWUP_AREAS` × agent+patient), but each turn's *visible* text capped short via a
   new **configurable `max_tokens`** parameter (this session's concrete ask) plus a
   brevity instruction added to both prompt templates.
3. **§12 quality gate widened** from `[10%, 70%]` to `[5%, 75%]` per label
   (verde/amarillo/rojo) — confirmed interpretation: ±5 percentage points on both bounds.
4. **Schedule/deploy the job** to actually run this to completion.

Provider stays **OpenRouter**, same pinned model as the pilot
(`nvidia/nemotron-3-nano-omni-30b-a3b-reasoning:free`, falling back to `openrouter/free`)
— no change to `llm_provider` or the model choice in this plan.

## A real gotcha with the `max_tokens` cap, worth stating up front

The pinned model is a **reasoning** model. In the pilot, hidden chain-of-thought tokens
were the large majority of `completion_tokens` on both sampled turns (303/314 and
216/245). `max_tokens` caps *total* output — reasoning + visible text combined. Set it too
low and the model can burn its whole budget "thinking" and return truncated or empty
visible dialogue. This plan validates a real default empirically (Phase 0) instead of
guessing a number and hoping.

## Plan

### Phase 0 — Spike: validate before writing code

- **Schedule support on Free Edition, unconfirmed.** Databricks Asset Bundles support a
  `schedule:` block (cron trigger) on a job resource, but nothing so far in this project
  has exercised it against this specific Free Edition workspace — Plan 02 only confirmed
  serverless-only *compute*, not job-trigger behavior. Confirm via `databricks jobs
  update`/bundle validate against a trivial test, or check the workspace's Jobs UI for
  trigger support, before committing Phase 1's job.yml change to a `schedule:` block. If
  unsupported, fall back to manual daily `databricks bundle run` invocations — no code
  blocker either way, since the resume/skip logic (`_casos_pendientes`) already handles
  picking up where a prior day's run left off.
- **`max_tokens` value, tested against the real model.** Send 1–2 real test calls to
  `nvidia/nemotron-3-nano-omni-30b-a3b-reasoning:free` with a candidate `max_tokens` (start
  around 500) and the new brevity instruction (see Phase 1). Confirm: the visible dialogue
  text is actually short (~1–2 sentences) and not truncated mid-reasoning. Adjust the
  default up/down based on what's actually observed, not the guess above.

### Phase 1 — Code changes

- **`src/postop/simulate_dual_llm.py`:**
  - New `--openrouter-max-tokens` CLI arg (default = whatever Phase 0 validates), threaded
    through `_build_default_client` → `_openrouter_client(..., max_tokens=...)` →
    `_openrouter_request(...)` → included in the OpenRouter JSON payload as
    `"max_tokens": max_tokens`. (`_default_client`/Databricks Model Serving path left
    unchanged — unused provider, out of scope.)
  - New/updated tests in `tests/test_simulate_dual_llm.py`: payload includes `max_tokens`;
    the value is threaded correctly from the CLI arg through to the request.
- **`prompts/agent_system.md` / `prompts/patient_system.md`:** add one line to each
  template's instructions — brevity, phone-call register (e.g. "Responde de forma breve,
  1–2 frases, como en una llamada telefónica real — no des discursos largos.").
- **`databricks.yml`:** new `openrouter_max_tokens` bundle variable (default from Phase 0).
  Update `pilot_n_pacientes`'s default from `"25"` to `"10"` — this run's intended size,
  not a smaller pilot-of-a-pilot (the wiring from Plan 06 Phase 1 already threads this
  variable into `generate_synthea_profiles`, so no job.yml change needed for patient
  count).
- **`resources/postop_pipeline.job.yml`:**
  - `simulate_dual_llm` task: add `"--openrouter-max-tokens",
    "${var.openrouter_max_tokens}"` to its parameters.
  - If Phase 0 confirms schedule support: add a `schedule:` block (daily cron, e.g.
    `"0 6 * * *"`, `timezone_id: "America/Bogota"`). `max_concurrent_runs: 1` (already set)
    prevents an overlapping run if one day's run is still going when the next fires.
- **`src/postop/publish_gold.py`:** widen `check_casos_clinicos_etiquetados`'s per-label
  band from `0.10`/`0.70` to `0.05`/`0.75` (both the comparison and the message string).
- **`tests/test_publish_gold_expectations.py`:** update/add cases for the new band — a
  label at 6% now passes (previously failed), a label at 3% still fails; a label at 74%
  now passes, 76% still fails.

### Phase 2 — Deploy

- `databricks bundle validate -t dev --profile default`
- `databricks bundle deploy -t dev --profile default`
- Confirm deployed task parameters reflect Phase 1 wiring (`pilot_n_pacientes=10`,
  `openrouter_max_tokens` present, and the schedule if Phase 0 confirmed it) via
  `databricks jobs get`.

### Phase 3 — Run (confirm before triggering — this is the step that spends quota/time)

480 calls, two ways to run them:

1. **No new spend (default for this plan unless you say otherwise):** stay on the
   no-credit 50/day cap. Trigger `databricks bundle run postop_pipeline -t dev --profile
   default` once/day (or let the cron fire, if Phase 0 confirmed it) — resume/skip logic
   picks up where the previous day's cap-out left off. **~10 days to finish all 480
   calls.**
2. **$10 one-time OpenRouter credit:** raises the cap to 1,000/day → all 480 calls in a
   **single day**, no schedule needed.

Either way: `publish_gold`'s §12 gate evaluates against 40 casos under the widened
`[5%, 75%]` band — more signal than the pilot's n=4, but still small. This is **not
guaranteed to pass** — real label distribution at n=40 could still land outside the band,
same as the pilot did at n=4. That's a real possible outcome of this run, not something
this plan engineers around.

### Phase 4 — Validate and report

- Confirm all 480 calls completed (or, on the free-tier path, the daily progress toward
  480).
- Task-by-task results, §12 outcomes (pass/fail + real label distribution, not assumed),
  real token totals, whether the brevity cap kept visible dialogue actually short, and
  whether `gold_participantes`/`gold_comite` published.

## Explicitly out of scope

- **Claude API (Sonnet 5) or self-hosted Ollama** — both evaluated this session and set
  aside; OpenRouter stays the provider for this run.
- **Scaling to the full 300-patient population** — separate future plan, once this
  small-batch run's numbers (cost, timing, §12 pass/fail at real scale) are in.
- **Reducing `call_days` or `FOLLOWUP_AREAS`** (i.e., fewer turns per conversation) — only
  turn *length* is being reduced here; the 12-turns/conversation structure is unchanged.
- **`prod` target** — `dev` only.

## Risks / confirm before I run this

- **Phase 0's schedule-support finding is unconfirmed going in** — if Free Edition doesn't
  support job triggers, Phase 1's job.yml change drops the `schedule:` block and Phase 3
  becomes manual daily runs instead of a true "leave it running" — same eventual outcome,
  more manual effort.
- **Phase 3's free-vs-$10-credit choice is yours** — defaulting to no-spend/~10-days unless
  you say otherwise, per this session's cost-conscious direction (the Ollama detour).
- **`max_tokens` risk is validated empirically in Phase 0, not guessed** — if the reasoning
  model still truncates badly at the tested value, this plan's brevity approach may need a
  different model or a much larger cap (defeating some of the token-cost benefit).
- **§12 gate may still fail at n=40** even with the widened band — a real, not
  hypothetical, possible outcome; this plan does not assume success.

## Verification

- `pytest -q` green after Phase 1 (existing suite + new `max_tokens` and §12-band tests).
- Phase 0's spike results (schedule support, real `max_tokens` behavior) captured verbatim
  in the report, not summarized away or assumed.
- Phase 4's numbers are pulled from the real deployed tables/run logs, not estimated.
