# Cross-model base — per-vendor PIN RECORD template

A pin record is the **immutable, audit-grade evidence** that one cross-model tutor base's exact
model id was chosen **by the frozen deterministic rule, before that base's leakage gate, and never
reselected after any outcome** (paper-plan.md §12; `decisions-log.md` 2026-06-27 "Cross-model base
SELECTION RULES"). Produce **one per vendor** (OpenAI, Gemini).

**How to use it**
1. Run the [pin-acceptance checklist in `RUN.md`](RUN.md) (§A) — list-evidence, right-class,
   reproducible-id-form, non-study smoke, held config, guards, etc.
2. Only when **every box passes**, copy the skeleton below into `decisions-log.md` as a **new dated
   entry**, fill every `<…>` / `[ ]`, and commit it as part of (or just before) that base's
   collection commit.
3. After it is recorded it is **immutable**: do not edit it, and **never reselect the model after
   any leakage or outcome information is observed**. A genuine vendor-side forced change (e.g. the
   pinned id is retired) requires a *new* dated entry that states the integrity rationale and flags
   that the base must be recollected — it does not silently overwrite this record.

This file is a template only — it pins nothing. The base configs stay `REPLACE-WITH-PINNED-…` until
the filled record exists.

---

## Skeleton (copy into `decisions-log.md`, one per vendor)

```
### <YYYY-MM-DD> — Cross-model base PIN RECORD: <vendor> base (<slug>) — IMMUTABLE
**Status:** IMMUTABLE. Pinned by the frozen §12 rule BEFORE this base's leakage gate and before any
live session. No reselection after any leakage/outcome (decisions-log 2026-06-27 selection rules).
**Pinned by:** <operator>   **Pinned at:** <YYYY-MM-DD HH:MM UTC>

**1. Identity**
- Vendor / base slug: <openai | gemini> / <slug>            (run id namespace: conf-<slug>-s0-…)
- Provider / endpoint: <provider> / <base_url>
- Tutor key env: <OPENAI_API_KEY | GEMINI_API_KEY>          (judge ANTHROPIC_API_KEY, student OPENROUTER_API_KEY — unchanged)
- **Pinned model id (exact): `<exact-id>`**
- Id form: <GA | dated-snapshot | preview>   Reproducibility caveat (if preview/alias): <none | "preview, may drift; …">

**2. Rule application (deterministic; not a preference)**
- Rule: the vendor's CURRENT FLAGSHIP GENERAL-PURPOSE CHAT model — not a reasoning/o-series/mini/nano variant.
- Why this id satisfies it: <1–2 lines: it is the current flagship general chat; the excluded
  variants present in the list and why they were excluded (reasoning / mini / nano / preview-only)>.
- LearnLM note (Gemini only): integrated into the flagship; NO separate LearnLM variant selected.

**3. Held config (capability/config control — guard-enforced)**
- temperature 0.4, max_tokens 1024 (identical to primary; tutor_only_drift enforces).
- Reasoning: `reasoning_effort=<none | low>`  (<disabled | vendor minimum — model cannot disable thinking>).
- Tools / search grounding / code execution: DISABLED by omission (not sent). Documented off-fields used: <none | list>.
- Request shape: reasoning via the documented `reasoning_effort` field <yes | via extra_body because: …>.

**4. Evidence — live model list (the rule's required record)**
- `list_models.py` run at: <YYYY-MM-DD HH:MM TZ>; provider [<provider>] returned <N> models.
- Pinned id present in the account-visible list: YES.
- Flagship-chat shortlist (paste the relevant lines, or path to the captured output):
  <paste / path>

**5. Evidence — non-study preflight smoke (throwaway, NOT a study run)**
- Serialized request payload: model=`<exact-id>`, reasoning_effort=`<…>`, max_tokens=1024, temperature=0.4; no tools/grounding/code-exec keys present.
- API acceptance: HTTP 200; response id <…>.
- Returned model identifier: `<returned-id>`  (matches the pin: YES).
- Output respected max_tokens: YES (<finish_reason / token count>).
- No tools / grounding / code execution in request OR response: YES.
- model_client path: `reasoning_effort` sent as <documented field | extra_body>; one-line forwarding addition needed: <no | yes → commit <hash>>.
- Request/response snippet or path: <paste / path>

**6. Guards (mock dry run before live)**
- `run_confirmatory --base <slug> --models configs/models.<base>.yaml --backend mock` started clean:
  tutor_only_drift PASS (only the tutor model differs), protocol_knob_drift PASS
  (domain/conditions/replicates/base-seed/turns match the registered protocol).

**7. Freeze**
- Cross-model extension freeze commit/tag this base is collected at: `<crossmodel-freeze-hash | crossmodel-freeze>` (NOT the primary 1a12b56).
- `configs/models.<base>.yaml` updated: REPLACE-stub → `<exact-id>` in commit <hash>.

**Immutability:** recorded above. The id is frozen for this base; never reselected after any leakage
or outcome. A vendor-forced change requires a NEW dated entry (with rationale) and base recollection.
```

---

## Provisional starting values (NOT pins — fill via the checklist)

From the 2026-06-27 selection-rule entry. These are *candidates*; they become pins only after the
checklist passes and the record above is filled and dated.

| field | OpenAI base | Gemini base |
|---|---|---|
| slug (suggested) | `gpt` | `gemini` |
| provider / endpoint | `openai` / `https://api.openai.com/v1` | `gemini` / `https://generativelanguage.googleapis.com/v1beta/openai/` |
| tutor key env | `OPENAI_API_KEY` | `GEMINI_API_KEY` |
| provisional id | `gpt-5.5-2026-04-23` | `gemini-3.1-pro-preview` |
| `reasoning_effort` | `none` (disabled) | `low` (vendor minimum — can't disable) |
| id-form preference | dated snapshot ✓ | prefer GA/dated snapshot over `-preview` if exposed |
| temperature / max_tokens | 0.4 / 1024 | 0.4 / 1024 (Google's higher default noted, not adopted) |
| tools / grounding / code-exec | off (omit) | off (omit) |
