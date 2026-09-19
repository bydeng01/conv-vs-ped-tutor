# Confirmatory 10×3 run

The inferential run: **10 replicates × {cold, conv, ped}** through the frozen
continuous protocol, paired by replicate id (paper-plan.md §10). Runs only **after
the pre-registration is frozen**. Every step here runs live;
`experiments/run_confirmatory.py` and `experiments/preflight.py` are built and
mock-validated offline first.

Models (`configs/models.yaml`): tutor = Anthropic Sonnet, student = OpenRouter→Groq
`llama-3.1-8b-instruct` (the calibration-validated weak serving), judge = Opus.
Keys: `ANTHROPIC_API_KEY` (tutor + judge), `OPENROUTER_API_KEY` (student).

## Before collection

Freeze the prompts, problems, rubrics, metrics, configuration, and predictions before
collection. The runner requires a clean tree at the freeze commit. Preflight failures
require diagnosis before collection; results are reported under `paper-plan.md` §11.
The prompt builders exclude `canonical_answer` from tutor, student, and judge inputs.

## Gate order

### 1. Preflight (live, on the pinned student serving)

```
ANTHROPIC_API_KEY=... OPENROUTER_API_KEY=... \
    python experiments/preflight.py --pilot-results results/pilot_groq
```

All gates must read right before spending budget:
- **ISOLATED cold LOW** on the frozen 19 (each probe from a fresh context; ≈11% at
  calibration). High *continuous*-protocol cold is expected and is NOT this gate (§3).
- **FINAL-marker rate ≥ 95%.**
- **ConvTutor leakage PRESENT** (> 0; ≈52% at calibration) — failure-mode #3.
- **Student served by Groq** (`served_provider == "Groq"`) — guards the routing-drift
  that produced cold-100% before (decisions-log 2026-06-18).
- **Cost estimate** for 10×3, from the stored pilot's tokens.

If any gate is CHECK, resolve it before proceeding (do not tune toward a result). On
`--backend live` preflight **exits non-zero** when any gate fails, so a wrapper script
stops here rather than spending budget on the confirmatory run.

### 2. Confirm the freeze commit

After the independent adversarial review and any must-fixes, create the **single freeze commit**
(reframe + Step-5/6 code + metric amendment + planning docs), then record its hash:

```
git rev-parse HEAD            # this is <freeze-hash>
git status --porcelain        # MUST be empty (commit/gitignore everything, incl. tmp/)
git tag confirmatory-freeze   # optional: lets the runner resolve the hash automatically
```

### 3. Run the confirmatory 10×3

```
ANTHROPIC_API_KEY=... OPENROUTER_API_KEY=... \
    python experiments/run_confirmatory.py --replicates 10 --freeze-commit <freeze-hash>
```

- Refuses unless the tree is clean and HEAD == `<freeze-hash>` (or the
  `confirmatory-freeze` tag). Each cell → its own `logs/conf-s0-<cond>-r<r>/`, with
  `confirmatory_meta.json` recording the freeze hash.
- **Resume after a rate-limit abort:** re-run the identical command. Completed cells
  are skipped; only missing cells run (a partial cell's dir is cleared first, so logs
  never mix). Check progress without running: add `--status`.
- A daily-quota abort (`QuotaExhausted`) is raised loudly, not masked — fix the quota
  and resume.
- **`--force` is refused on a live run** (it would overwrite already-collected cells). To
  redo cells, manually quarantine the old `logs/conf-*` dirs (or use a fresh
  `--base-seed`) and re-run without `--force`.

### 4. Judge + metrics (post-hoc, paired by replicate id)

```
ANTHROPIC_API_KEY=... python analysis/compute_metrics.py \
    logs/conf-s0-cold-r* logs/conf-s0-conv-r* logs/conf-s0-ped-r* \
    --out results/confirmatory --judge-helpfulness --judge-pedagogy
```

Writes `per_turn.csv`, `per_session.csv`, `per_replicate.csv` (one row per
`(condition, replicate_id)` — the §10 unit), `metrics_summary.json` (with the
descriptive J1 paired preview), and `helpfulness_detail.json`. `--judge-pedagogy` (the
§13 extension judge) additionally fills the `pedagogy`/`pedagogy_mean` columns and
writes `pedagogy_detail.json` + `divergence_detail.json`; the shipped
`results/confirmatory` carries these, so both judges are needed to reproduce it
byte-for-byte. Judge calls are cached and kept out of the experiment's `calls.jsonl` /
cost accounting.

### 5. Inferential analysis (paper-plan.md §10)

J1 (paired Wilcoxon + Cliff's delta on leakage / helpfulness / independence), J2
(mixed-effects coupling), accuracy descriptive + CIs, cost-normalized sensitivity.
Not part of this runner.

---

## Cross-model base runs

The cross-model extension (paper-plan.md §12) re-runs this **identical frozen protocol with
only the tutor model swapped**, on additional bases (a current flagship OpenAI chat model; a
current flagship Gemini Pro). The Sonnet primary is **not re-run**. Selection is rule-governed
(`decisions-log.md` 2026-06-27 "Cross-model base SELECTION RULES"): the vendor's **current
flagship general-purpose chat model** (not reasoning/o-series/`mini`/`nano`), LearnLM treated as
integrated in Gemini (no separate variant). Run the steps below **once per base**, separately;
**bases are never pooled** (`compute_metrics` refuses a multi-base glob).

Keys: the primary's `ANTHROPIC_API_KEY` (judge — unchanged) + `OPENROUTER_API_KEY` (student —
unchanged) + the base tutor's key (`OPENAI_API_KEY` or `GEMINI_API_KEY`). **The judge never
changes — it stays the primary Opus** (default `configs/models.yaml`); only the tutor model
changes.

### A. Pin the base model — apply the rule, then the pin-acceptance checklist

Provisional candidates (from the selection-rule entry; **not pins until the checklist passes**):
OpenAI `gpt-5.5-2026-04-23` (`reasoning_effort=none`); Gemini `gemini-3.1-pro-preview`
(`reasoning_effort=low`, vendor minimum — Gemini 3.x can't disable thinking).

```
OPENAI_API_KEY=... GEMINI_API_KEY=... python experiments/list_models.py   # the EVIDENCE
```

**Pin-acceptance checklist** — every box must be checked, in order, **before** the leakage gate
and **before** recording the pin. Do not proceed on a CHECK.
- [ ] **In the live list.** The candidate id appears in this account's `list_models.py` output;
      capture that output as the pin evidence.
- [ ] **Right class.** It is the vendor's current flagship **general-purpose chat** model — not a
      reasoning/o-series model, not `mini`/`nano`/`lite`. Apply the deterministic rule to the full
      list, not to the shortlist hint.
- [ ] **Reproducible id form.** Prefer a **GA / dated-snapshot** id over a rolling alias or a
      `-preview` slug. If only a preview is exposed, pin it but record the "preview may drift"
      caveat in the pin record.
- [ ] **Non-study smoke passes** (a single throwaway request through the base tutor config — NOT a
      study run). It confirms: the **serialized request payload** (model id, `reasoning_effort`,
      `max_tokens`), **API acceptance** (200), the **output respects `max_tokens`**, the **returned
      model identifier** matches the pin, and **no tools / search grounding / code execution** in
      the request or the response. (This is what makes "no code change" real — if `model_client`
      must forward `reasoning_effort` as a documented field rather than via `extra_body`, the smoke
      catches it; make that one-line addition and re-smoke.)
- [ ] **Held config.** `configs/models.<base>.yaml` sets `roles.tutor.temperature: 0.4`,
      `max_tokens: 1024` (identical to primary), reasoning at the vendor minimum, and prefers the
      **documented `reasoning_effort` field**; `extra_body` only for what the standard interface
      can't express; tools/grounding/code-exec **omitted**. Replace the `REPLACE-WITH-PINNED-…`
      stub with the exact id.
- [ ] **Guards pass.** A `--backend mock` dry `run_confirmatory --base <slug>
      --models configs/models.<base>.yaml` starts clean: `tutor_only_drift` (only the tutor model
      differs) and `protocol_knob_drift` (domain / conditions / replicates / base-seed / turns)
      both pass.
- [ ] **Record the pin** in a **separate, immutable per-vendor pin record** — a dated
      `decisions-log.md` addendum with the `list_models.py` evidence and the smoke result. Follow
      the two filled records already in `decisions-log.md` — "2026-06-28 — Cross-model base PIN
      RECORD: OpenAI base (gpt) — IMMUTABLE" and its Gemini counterpart — field for field.
- [ ] **No reselection.** Once recorded, the id is frozen for that base: **never re-selected after
      any leakage or outcome information is observed.**

### B. ConvTutor leakage diagnostic — advisory for cross-model bases (failure mode #3, §12)

After the pin (A), measure this base's minimal-prompt ConvTutor leakage on the frozen training
problems. (`protocol/leakage.py` is only the matcher; `experiments/preflight.py` runs ConvTutor over
the frozen problems and applies it.) For a base, run it in **advisory** mode: ConvTutor leakage is
**recorded but non-blocking**, because a base whose ConvTutor does not leak is a **reported finding
about the base, not a stop** (§12). **Every other gate stays blocking.**

```
ANTHROPIC_API_KEY=... OPENROUTER_API_KEY=... <BASE_TUTOR_KEY>=... \
    python experiments/preflight.py --backend live \
        --models configs/models.<base>.yaml \
        --leakage-advisory \
        --pin-record-ref "<this base's dated pin-record title>" \
        --diagnostic-out results/leakage_diag_<slug>
```

- **Advisory is surgical, not a blanket pass.** `--leakage-advisory` downgrades **only** the
  ConvTutor-leakage gate. The **cold**, **FINAL-marker**, and **served-by-Groq** gates — and all
  **key / config / API errors** — **still block** (preflight exits non-zero). It does **not** use
  `|| true`: a real failure still stops you before you spend the 10×3 budget.
- **Full read + provenance, in a separate artifact.** It writes
  `results/leakage_diag_<slug>/leakage_diagnostic.json` with the **numerator** (`leak_turns`),
  **denominator** (`tutor_turns`), and `leak_rate` — not merely present/absent — plus provenance
  (tutor model, models config, problem-set sha256, repo commit, timestamp, raw log dir) and a
  **reference to the immutable pin record**. The pin record itself is **not edited** by this read —
  the model was pinned by rule in step A, before this gate, and is never reselected after it.
- **Report, don't tune.** **No leakage result may trigger prompt tuning, model reselection, or
  configuration changes.** Record the rate as a finding about the base and proceed; a base that does
  not leak is reported as such (§11/§12, no file-drawer).
- **Primary unchanged.** Without `--leakage-advisory`, preflight keeps the preregistered **hard-gate**
  semantics (ConvTutor leakage absent = a blocking CHECK), exactly as for the Sonnet run in §1 above.
  *(Fallback only if a code path is ever unavailable: never `|| true`; instead inspect the per-gate
  lines and continue only if ConvTutor leakage is the **sole** failed condition.)*
- **Note on the printed cost line.** Preflight's "4. Cost estimate" extrapolates from `--pilot-results`
  (default the Sonnet pilot `results/pilot_groq`), so for a base it is a rough Sonnet-based budget, not
  the base's own token profile; point `--pilot-results` at a base pilot if you have one. Cost is not a
  gate.

### C. Collect the frozen 10×3 for the base

```
ANTHROPIC_API_KEY=... OPENROUTER_API_KEY=... <BASE_TUTOR_KEY>=... \
    python experiments/run_confirmatory.py --base <slug> \
        --models configs/models.<base>.yaml \
        --replicates 10 --freeze-commit <crossmodel-freeze-hash>
```

- Uses the **cross-model extension's own freeze commit/tag** (e.g. `crossmodel-freeze`), **not**
  the primary `1a12b56`. Each cell → `logs/conf-<slug>-s0-<cond>-r<r>/`, stamping `base` +
  `tutor_model` in `confirmatory_meta.json` and on every call. Cold is re-run per base for an exact
  protocol match. Resume / `--status` / quota behavior is identical to the primary run above.

### D. Metrics + judges + divergence (per base, separate out dir)

```
ANTHROPIC_API_KEY=... python analysis/compute_metrics.py \
    logs/conf-<slug>-s0-cold-r* logs/conf-<slug>-s0-conv-r* logs/conf-<slug>-s0-ped-r* \
    --out results/confirmatory_<slug> --judge-helpfulness --judge-pedagogy
```

- **Per-base `--out results/confirmatory_<slug>`**; the base guard refuses a glob spanning more than
  one base. The judge stays the primary Opus (default `configs/models.yaml`); the live judge-identity
  guard enforces judge == primary, reps == 3. Unlike the Sonnet primary, a fresh base has **no cached
  helpfulness**, so `--judge-helpfulness` pays the helpfulness judge **and** `--judge-pedagogy` pays
  the pedagogy judge (cold cells cost nothing). Writes the `pedagogy`/`pedagogy_mean` columns,
  `pedagogy_detail.json`, and (both judges present) `divergence_detail.json`.

### E. Per-base inferential analysis (§10, grouped by base)

```
python analysis/run_inference.py results/confirmatory_<slug> --freeze-tag <crossmodel-freeze-tag>
```

- `run_inference` refuses the default primary freeze tag when `base != primary`, and verifies the
  resolved freeze commit matches the recorded run head(s). Same verdict table as the primary
  (P1/P2/P3 with Cliff's delta + conversation-level CIs, J1, J2) — **no new covariates or specs**.

### F. Report every base

Every base that is run is reported, whatever it shows (§11, §12 — no file-drawer, no
cherry-picking). Effects are **expected to differ** across bases; that heterogeneity is the
cross-model finding. Read cross-base differences under the §12 **declared provider-specific
implementation heterogeneity** caveat (model family and mandatory reasoning configuration vary
together, so cross-base differences are not attributable to model identity alone); within-base
ConvTutor-vs-PedTutor contrasts are unaffected.
