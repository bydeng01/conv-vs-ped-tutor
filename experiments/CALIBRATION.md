# Running the live calibration locally

The calibration diagnostic checks two design requirements on a live model
**before** the frozen problem set is authored:

- **Failure mode #1** — cold-baseline accuracy LOW (target **20–40%**).
- **Failure mode #3** — ConvTutor actually leaks answers (leakage rate **≥ ~20%**).

It also reports the §6 student acceptance bands (behavior frequencies, FINAL
ANSWER marker rate). It is **non-inferential** — purely a go/no-go for the design.

Run it on a machine with outbound access to the free providers. It is a single
command.

## 1. Setup (once)

```bash
cd conv-vs-ped-tutor
python -m venv .venv && source .venv/bin/activate      # Windows: .venv\Scripts\activate
pip install -r requirements.txt
```

## 2. (Optional) connectivity + model-name check

Free-tier model names change. Verify before the full run:

```bash
export GROQ_API_KEY=gsk_...                            # Windows PowerShell: $env:GROQ_API_KEY="gsk_..."
python - <<'PY'
import os
from openai import OpenAI
c = OpenAI(base_url="https://api.groq.com/openai/v1", api_key=os.environ["GROQ_API_KEY"])
for m in ["llama-3.3-70b-versatile", "llama-3.1-8b-instant"]:
    try:
        r = c.chat.completions.create(model=m, messages=[{"role":"user","content":"say ok"}], max_tokens=5)
        print("OK ", m, "->", r.choices[0].message.content.strip())
    except Exception as e:
        print("ERR", m, str(e)[:160])
PY
```

If a model name errors (deprecated), edit `configs/models.free.yaml` →
`roles.<role>.model` to a current Groq model and re-run.

## 3. Run the calibration

The default config splits providers to dodge free-tier **daily** token caps
(Groq's 70B is only ~100k tokens/day): the 70B **tutor runs on Cerebras**, the 8B
**student on Groq**. So export BOTH keys:

```bash
export GROQ_API_KEY=gsk_...
export CEREBRAS_API_KEY=csk_...
python experiments/calibrate.py --models configs/models.free.yaml
# dialogues are capped at 4 rounds/problem by default; override with --max-turns N
```

It prints a CALIBRATION REPORT table and a `run_id`. The full report and all
transcripts are written under `logs/<run_id>/`.

If you hit a **daily cap** anyway, the run now fails fast with guidance instead
of hanging: switch that role's `provider:` in `configs/models.free.yaml` (e.g.
tutor → `openrouter`, set `OPENROUTER_API_KEY`) and re-run, or wait for the reset.
Confirm valid slugs with `python experiments/list_models.py` (it prints each
provider's model ids). As of 2026-06-15 Cerebras offered only `gpt-oss-120b` and
`zai-glm-4.7`; OpenRouter uses `vendor/model[:free]` slugs.

## 4. Interpreting the output

The artifacts to review are:

- the printed **CALIBRATION REPORT** table, and
- the file `logs/<run_id>/calibration_report.json`,

plus one or two transcripts from `logs/<run_id>/` (ideally one `cold_*.txt` and one
`conv_*.txt`) to confirm by eye that the student genuinely struggles cold and that
ConvTutor visibly hands over answers.

Read the two gates from the report. If the cold-baseline accuracy or the ConvTutor
leakage rate is out of band, adjust the student strength or the problem difficulty
and re-run. If both gates pass, proceed to author the frozen problem set.

## Final-student difficulty check (cold-only)

> Note: this check originally targeted a Haiku-tier Claude student. Calibration
> found Haiku too capable to struggle, so the final student was changed to the weak
> open Llama-3.1-8B model (`decisions-log.md` 2026-06-15). The `--cold-only` check
> still applies to whichever student `configs/models.yaml` pins.

The free-tier calibration validates the design, but difficulty must be set against
the student used in the confirmatory run. Use `--cold-only` for a cheap check (no
tutor calls, only the student runs):

```bash
export OPENROUTER_API_KEY=...
python experiments/calibrate.py --models configs/models.yaml --cold-only
```

This reports the student's unaided accuracy on the current problem batch, which
should land in the calibration band. If it is higher, the problems need to be
authored harder; if it is already in band, author at this level. Cost is small
(about 10 problems and a few short student calls).

## Switching provider (optional)

Default is Groq. To use Cerebras or OpenRouter instead, edit
`configs/models.free.yaml`: set each role's `provider:` to `cerebras` or
`openrouter`, pick that provider's model strings, and export the matching key
(`CEREBRAS_API_KEY` or `OPENROUTER_API_KEY`). Cerebras model names look like
`llama-3.3-70b` / `llama3.1-8b`; OpenRouter uses `vendor/model[:free]` slugs.

## Notes

- Backend, providers, and per-role models are all read from
  `configs/models.free.yaml` — no code edits needed to retarget.
- The proxy calibration uses `configs/models.free.yaml`. The primary confirmatory
  configuration uses an Anthropic tutor and an OpenRouter student pinned to Groq.
  Re-check calibration gates on that serving configuration before collection.
- Rate limits: the runner retries with exponential backoff on 429s. If a free
  tier is very limited, re-run — logging is per-run and append-only.
