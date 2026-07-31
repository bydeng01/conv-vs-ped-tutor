# Cross-model base run — per-base operating notes

Run the **GPT** base and the **Gemini** base separately, one base at a time. Each
run re-executes the **identical frozen protocol with only the tutor model swapped**
(`paper-plan.md` §12), pins the vendor's model by rule, and reports the base
regardless of outcome. This document and `RUN.md` are the operating instructions.

**Prerequisite (do once, before any base run):** the cross-model docset and the
pedagogy-judge code must be **committed and tagged** as the cross-model freeze (for
example `crossmodel-freeze`, **not** the primary `1a12b56`). `run_confirmatory`
refuses to run unless the tree is clean and HEAD is a freeze commit, so each base
branches from that tag. Until the tag exists, base runs are blocked.

## Read first
1. **`experiments/RUN.md` → "Rigor reminders (non-negotiable)"** and **`paper-plan.md`
   §11** — the integrity discipline: freeze before data, **no result-chasing**, no
   answer leakage, **report every outcome**. These are the binding rules; read them
   before touching anything.
2. **`paper-plan.md` §12** (cross-model extension) and **§13** (pedagogy judge) — the
   additive extensions. §4/§9/§10 are frozen; do not touch them.
3. **`decisions-log.md`** 2026-06-27 entries: cross-model Phase-0 (base tagging and
   guards), the **base selection rules**, and the **leakage-advisory** entry.
4. **`experiments/RUN.md` → "Cross-model base runs (Phase 1)"** — the §A–F runbook and
   the **pin-acceptance checklist**, the main operating doc.
5. **`experiments/PIN-RECORD-TEMPLATE.md`** — the immutable pin record filled at pin
   time.

## Per-base parameters
| | **GPT base** | **Gemini base** |
|---|---|---|
| slug | `gpt` | `gemini` |
| config | `configs/models.gpt.yaml` | `configs/models.gemini.yaml` |
| vendor key | `OPENAI_API_KEY` | `GEMINI_API_KEY` |
| provisional id (confirm via the live list) | `gpt-5.5-2026-04-23` | `gemini-3.1-pro-preview` |
| `reasoning_effort` | `none` | `low` (vendor minimum; declared §12 heterogeneity exception) |
| branch | `crossmodel-gpt` | `crossmodel-gemini` |

Both bases also need `ANTHROPIC_API_KEY` (judge) and `OPENROUTER_API_KEY` (student).
**The judge never changes**: leave the analysis `--models` at its default
`configs/models.yaml`.

## Commands (substitute the row above for `<slug>`, `<config>`, `<key>`, `<pin-title>`)
```bash
# 0. Branch from the frozen cross-model commit
git checkout -b crossmodel-<slug> crossmodel-freeze

# A. PIN — run the live list, apply RUN.md §A pin-acceptance checklist, fill the pin record
OPENAI_API_KEY=... GEMINI_API_KEY=... python experiments/list_models.py
#   -> edit <config>: REPLACE-stub -> exact id + reasoning_effort
#   -> copy PIN-RECORD-TEMPLATE.md into decisions-log.md, fill every field
#   -> guards must pass on a mock dry-run:
python experiments/run_confirmatory.py --base <slug> --models <config> --backend mock
git add <config> decisions-log.md && git commit -m "Pin <slug> base + pin record"
git tag crossmodel-<slug>-freeze            # this commit IS the base freeze

# B. ConvTutor leakage DIAGNOSTIC (advisory for a base: recorded, NON-blocking)
ANTHROPIC_API_KEY=... OPENROUTER_API_KEY=... <key>=... \
  python experiments/preflight.py --backend live --models <config> \
    --leakage-advisory --pin-record-ref "<pin-title>" \
    --diagnostic-out results/leakage_diag_<slug>

# C. Collect the frozen 10x3
ANTHROPIC_API_KEY=... OPENROUTER_API_KEY=... <key>=... \
  python experiments/run_confirmatory.py --base <slug> --models <config> \
    --replicates 10 --freeze-commit "$(git rev-parse crossmodel-<slug>-freeze)"

# D. Metrics + both judges + divergence (per-base out dir; judge stays default Opus)
ANTHROPIC_API_KEY=... python analysis/compute_metrics.py \
  logs/conf-<slug>-s0-cold-r* logs/conf-<slug>-s0-conv-r* logs/conf-<slug>-s0-ped-r* \
  --out results/confirmatory_<slug> --judge-helpfulness --judge-pedagogy

# E. Per-base inference (the base freeze tag, NOT the primary's)
python analysis/run_inference.py results/confirmatory_<slug> --freeze-tag crossmodel-<slug>-freeze
```

**Cost safety:** before C, run a one-pair smoke (C with `--replicates 1`, and D over
only `...conv-r0 ...ped-r0 --out /tmp/smoke`) to confirm the key and guards before
spending the full 10x3 plus two Opus judge passes per base. The runner resumes on
re-run; `--status` shows progress.

## What each base run records
- The **immutable pin record** (step A), from the template, into `decisions-log.md`.
- A **leakage-diagnostic note** referencing
  `results/leakage_diag_<slug>/leakage_diagnostic.json` (numerator, denominator,
  rate).
- A **per-base findings entry** after E, using the fixed template below so both bases
  report identically, **reported regardless of outcome** (§11). Then push the branch
  and open a pull request for review.

### Per-base findings entry — fill in (identical format for both bases)

Transcribe the numbers from `results/confirmatory_<slug>/inference.json`,
`metrics_summary.json`, and `divergence_detail.json` into `decisions-log.md`. Do
**not** reshape or omit fields; report every outcome.

```
### <YYYY-MM-DD> — Cross-model base FINDINGS: <vendor> base (<slug>)
**Base:** <slug> · tutor `<pinned-id>` (reasoning_effort=<none|low>) · pin record: <pin-title>
**Provenance:** freeze <crossmodel-<slug>-freeze hash> · runs logs/conf-<slug>-s0-* · results
results/confirmatory_<slug>/ · judge <model/backend/reps=3> · n = 10 replicates × 3 conditions.

**ConvTutor leakage diagnostic (advisory, §12):** <leak_turns>/<tutor_turns> = <rate>
(<present | ABSENT — reported finding, NOT tuned>). Ref: results/leakage_diag_<slug>/leakage_diagnostic.json

**Marginals — PedTutor vs ConvTutor, paired by replicate (Wilcoxon two-sided, Cliff's δ, 95% CI):**
- P1 leakage:       conv <c> vs ped <p> | diff(conv−ped) <d> CI [<lo>,<hi>] | p=<p> | δ=<δ> | <SIG|n.s.>
- P2 helpfulness:   conv <c> vs ped <p> | diff <d> CI [<lo>,<hi>] | p=<p> | δ=<δ> | <SIG|n.s.>   (the live test)
- P3 independence:  conv <c> vs ped <p> | diff <d> CI [<lo>,<hi>] | p=<p> | δ=<δ> | <SIG|n.s.>
- Accuracy (secondary, descriptive): immediate <c/p> · delayed <c/p> · transfer <c/p>

**J1 (joint):** <supported | NOT supported> — <which directions held; was P2 significant?>
**J2 (per-turn coupling, crossed replicate+problem mixed model):**
  leak→helpfulness coef <b> CI [<lo>,<hi>] (p=<p>); leak→next-turn-independence coef <b> CI [<lo>,<hi>] (p=<p>).
  <holds | does not hold>.

**Extension — pedagogy & divergence (descriptive):** pedagogy_mean conv <c> vs ped <p>;
  per-turn agreement help~ped <r> · help~indep <r> · ped~indep <r>.
  (Read with the §12/§13 construct-overlap caveat: a pedagogy gap is partly by-construction.)

**Interpretation (§11 — report regardless):** matches outcome-table row "<…>". <1–2 lines; do NOT
call a non-supported J1 "supported".>
```

**Artifacts (gitignored is not disposable).** Raw logs under `logs/` are gitignored and
pinned by a SHA-256 manifest, not committed as files. The per-base
`results/confirmatory_<slug>` analysis outputs, however, **are now tracked** (committed
since `19d0c37`), alongside the dated decisions-log findings entry. Retain the raw run
logs in the designated run-artifact location and keep them manifest-pinned.

## Hard don'ts (integrity)
- **No reselection** of the model after seeing any leakage or outcome; **no prompt
  tuning, no config change** to chase a result. A non-leaking base is a *finding*,
  not a failure (report, don't tune).
- **Only change** the tutor model id (plus Gemini's `reasoning_effort`) in the base
  config. Do not edit any frozen artifact (`analysis/judge.py`, the rubrics, the
  problem set, the answer-phase window, either tutor prompt, `configs/models.yaml`).
- **Never pool bases.** Use a per-base `results/confirmatory_<slug>` directory; the
  analysis guard refuses mixed-base globs anyway.

Coding hygiene: keep changes surgical and additive, favor simplicity, and keep the
offline tests green. Scope every change to the base being run.
