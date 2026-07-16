# 08 — Add Anthropic API as a provider option for simulate_dual_llm

**Status:** awaiting approval
**Author:** Claude (Data Engineer role), for Gabriel Cepeda
**Date:** 2026-07-15
**Based on:** Plan 07 (small-batch run, in progress — Phase 0 partially done, see below).

## Why now

Plan 07's Phase 0 spike hit a real blocker: OpenRouter's free-tier daily quota (50
calls/day, no credit) is already at 0 remaining for today (confirmed via a live 429 with
`X-RateLimit-Remaining: 0`, resetting `2026-07-16T00:00:00 UTC`) — almost certainly used up
by today's earlier 1-patient pilot run. That left Phase 3's "wait ~1.5h, then still only
get 50 calls/day toward 480" vs. "$10 credit for 1,000/day" fork unresolved.

Rather than settle that fork, you asked for something more general: add the Anthropic API
as a provider option, integrated to work the same way OpenRouter does — a `--llm-provider`
switch, not a rewrite. This sidesteps the OpenRouter daily-cap question entirely if you
choose it (pay-per-token, no daily call quota), without forcing that choice — Phase 3 can
still pick either provider.

## What already works in this codebase that makes this easy

`simulate_dual_llm.py`'s orchestration (`simulate_conversation`, `run_dual_llm_batch`,
per-caso resume/skip, `MERGE` checkpointing, schemas) is already provider-agnostic — it
depends only on the `LLMClientFn` signature (`(system_prompt, history) -> LLMTurnResult`).
`_openrouter_client`/`_default_client` are the two concrete implementations behind that
seam. This plan adds a third, `_anthropic_client`, with no changes to anything above that
seam — provider choice stays a `--llm-provider` flag.

One more thing that lines up cleanly: `agent_history`/`patient_history` inside
`simulate_conversation` are already built as `[{"role": "user"/"assistant", "content":
"..."}]` — the exact shape the Anthropic Messages API's `messages` parameter expects, with
`system` passed as a separate parameter. OpenRouter's OpenAI-shaped payload has to inline
the system prompt into the messages list (`_openrouter_request` does this); Anthropic's
client won't need that step at all.

## Design

- **New `_anthropic_client(model, secret_scope, secret_key="anthropic-api-key",
  max_tokens=...)`** in `src/postop/simulate_dual_llm.py`, parallel to
  `_openrouter_client`:
  - `WorkspaceClient().secrets.get_secret(scope, key)` → base64-decode (identical pattern
    to the OpenRouter key).
  - `anthropic.Anthropic(api_key=...)` (official SDK, per this project's `anthropic`
    dependency — see below), then `client.messages.create(model=model,
    max_tokens=max_tokens, system=system_prompt, messages=history, thinking={"type":
    "adaptive"}, output_config={"effort": "low"})`. `effort: "low"` + adaptive thinking is
    chosen for the same reason as the `max_tokens` cap — these are short, single-topic
    conversational turns, not tasks needing deep reasoning; low effort keeps responses
    terse and cheap.
  - Parse: first `text`-type block in `response.content` → `texto`;
    `response.usage.input_tokens`/`output_tokens` → `LLMTurnResult.prompt_tokens`/
    `completion_tokens` (Anthropic's field names, not OpenAI's `prompt_tokens`/
    `completion_tokens` — mapped at this boundary so the rest of the pipeline, which
    already expects `LLMTurnResult`, doesn't know the difference).
  - No custom pacer/backoff like OpenRouter's — the Anthropic SDK's built-in retry
    (`max_retries` default 2, covers 429/408/409/5xx and connection errors) is adequate
    for a paid-tier account; OpenRouter's free-tier congestion problem doesn't apply here.
- **`--llm-provider` choices become `["openrouter", "databricks", "anthropic"]`** (CLI
  `argparse`, `_build_default_client` dispatch).
- **New `--anthropic-model` CLI arg**, default `claude-sonnet-5` — the model this session
  actually priced out and discussed, not a silent default to Opus.
- **Generalizing the brevity cap (amends Plan 07's not-yet-written Phase 1 design):** Plan
  07 planned a `--openrouter-max-tokens` flag; since no code has been written yet, this
  plan folds that into a single provider-agnostic **`--max-tokens`** CLI arg / bundle
  variable, applied to both the OpenRouter and Anthropic paths. One flag controls turn
  brevity no matter which provider is active — this is the concrete meaning of "integrate
  seamlessly" here. (Databricks Model Serving path stays unchanged — still unvalidated,
  still unused.)
- **`databricks.yml`:** new `anthropic_model` variable (default `claude-sonnet-5`); rename
  the not-yet-deployed `openrouter_max_tokens` → `max_tokens`.
- **`resources/postop_pipeline.job.yml`:** `simulate_dual_llm` task parameters gain
  `"--anthropic-model", "${var.anthropic_model}"` and `"--max-tokens", "${var.max_tokens}"`;
  the `postop_env` environment's `dependencies` gains `anthropic>=0.68` (Plan 06 dropped
  this package when OpenRouter's plain-`urllib` path made it dead weight — it's genuinely
  used again now).
- **`requirements.txt`:** add `anthropic>=0.68` back, with a comment explaining why
  (mirrors the job.yml change, keeps local `pytest` environment consistent).
- **`run_dual_llm_batch`'s `modelo_configurado` provenance column:** extend to cover the
  anthropic case, so `dialogos_capa1_limpia.modelo_paciente`/`modelo_agente` correctly
  records which model actually generated each row regardless of provider.

## Prerequisite — your action, not mine

I cannot create the secret myself; it needs a real Anthropic API key, a credential only
you have. Once you have one:

```
databricks secrets put-secret postop-llm-secrets anthropic-api-key
```

(prompts interactively, keeps the value out of shell history). This assumes reusing the
existing `postop-llm-secrets` scope with a new key — "a different secret," not necessarily
a different scope. Say so if you'd rather it live in its own scope.

## Testing approach

- `_anthropic_client` itself stays untested directly — same as `_openrouter_client`/
  `_default_client`, since it calls `WorkspaceClient().secrets.get_secret(...)`, which only
  works with real cluster/secret-scope auth.
- The response-shape mapping gets pulled into a small pure function,
  `_parse_anthropic_response(response) -> LLMTurnResult`, so `content` → `texto` and
  `usage.input_tokens`/`output_tokens` → `prompt_tokens`/`completion_tokens` are
  unit-testable against a constructed fake response object, no real API call needed.
- New tests in `tests/test_simulate_dual_llm.py`: `_parse_anthropic_response` against a
  few shapes (single text block, multiple content blocks); `--llm-provider anthropic`
  dispatch reaches `_anthropic_client`; `--anthropic-model`/`--max-tokens` thread through
  correctly.

## Cost, recomputed for the actual scope in play (10 patients, not 300)

Scaling the pilot's real per-patient token counts (126,936 prompt + 189,798 completion,
1 patient) to 10 patients: **~1.27M prompt + ~1.9M completion tokens** for all 480 calls.
At Sonnet 5 intro pricing ($2/$10 per 1M through 2026-08-31): **≈$21 upper bound** — likely
lower in practice, since the pilot's completion-token count was inflated by the OpenRouter
reasoning model's hidden chain-of-thought, which this plan's `effort: "low"` + `max_tokens`
cap is specifically meant to avoid. Much cheaper than the earlier 300-patient estimate
(~$650–970) — worth knowing regardless of which provider Phase 3 ends up using.

## Explicitly out of scope

- **Deciding which provider Phase 3 actually runs with** — this plan only adds the
  *capability*. The choice between OpenRouter (currently quota-blocked until reset, or
  unblocked with the $10 credit) and Anthropic (pay-per-token, ~$21 upper bound at this
  scope) is still yours, made when Phase 3 actually triggers.
- Databricks Model Serving path — unchanged, still unvalidated, still unused.
- Any change to conversation structure — still 12 turns/conversation, 480 calls total for
  10 patients (this plan only changes *which provider* generates each turn and how short
  it is).

## Risks

- **Real spend if Anthropic is chosen** — no free tier, billed from the first call.
- **Rate limits on a new/low-usage-tier Anthropic key are unproven for 480 calls in one job
  run.** The SDK's built-in retry covers transient 429s; a persistently-too-low tier limit
  is a different problem retries don't fix. Worth a 1–2 call spike (same spirit as Plan
  06's Phase 0 and Plan 07's Phase 0) once the secret exists, before trusting a full run.
- **`effort: "low"` is a judgment call**, same as Plan 07's `max_tokens` guess for
  OpenRouter — needs the same kind of real-call validation (does it still sound natural
  and in-character at low effort?) before being trusted for a full run.

## Verification

- `pytest -q` green after implementation.
- One real spike call against the Anthropic path (once the secret exists) confirming:
  correct Spanish, in-character, no label leakage, and response length actually short
  under the brevity instruction + `max_tokens`/`effort` settings — captured verbatim in the
  report, not assumed.
