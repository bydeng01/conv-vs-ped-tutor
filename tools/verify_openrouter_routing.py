"""Captured verification of the OpenRouter routing pin frozen by
cross-judge-amendment-openrouter-2026-07-20.md §3.

WHY THIS EXISTS: the original routing probes printed to stdout and were never saved, so every
routing claim in the amendment was uncaptured prose (§6). This script is the replacement. It
WRITES ITS OWN TRANSCRIPT to results/judge_robustness/gpt-5.6-sol/preflight/ so the amendment
can cite an artifact instead of a memory. That is the whole point -- do not "just run it and
read the output".

WHAT IT PROVES, and why the obvious test is not enough:

  A weak negative control was the flaw in the earlier probe. A bogus provider tag returned 404
  -- but so did a valid-but-MISCASED tag (`order:["OpenAI"]`). So a 404 only ever demonstrated
  "tag unrecognized", NOT "provider refused". On that evidence the pin could equally have been
  accepted-and-ignored while OpenAI merely happened to be the default route.

  The discriminating test is a POSITIVE control on a DIFFERENT provider: pin `azure` and see
  who serves it. If order=["openai"] is served by OpenAI *and* order=["azure"] is served by
  Azure, then routing demonstrably FOLLOWS `order`. That is proof the pin binds; no 404 can
  establish it.

  A second positive control isolates `allow_fallbacks`: an unroutable pin must SUCCEED with
  fallbacks enabled and FAIL with them disabled. If both fail, the refusal is coming from
  something other than the fallback setting.

It also settles whether `reasoning_effort` survives the route (minimal vs high on one
reasoning-heavy prompt), which the scoring preflight cannot show because its prompts are
trivial.

SAFETY:
  * Makes ~12 TINY calls (16-256 max_completion_tokens). Cents.
  * Touches NO study artifact: no cache, no wire log, no spend ledger, no resolved_config.
  * Paces at 1.5s. An unpaced burst previously produced 401 "Missing Authentication header",
    which is an edge-side throttle and NOT an auth failure -- pacing avoids conflating them.
  * Aborts on a real auth failure rather than scoring it as a routing result.
  * Safe to run while a scoring batch is in flight, but running it AFTER a base finishes keeps
    provider-side rate contention out of the paid run.

RUN:
  OPENROUTER_API_KEY=... .venv/bin/python tools/verify_openrouter_routing.py
"""
from __future__ import annotations

import datetime as _dt
import json
import re
import os
import sys
import time
from pathlib import Path

import openai

REPO_ROOT = Path(__file__).resolve().parents[1]
OUT_DIR = REPO_ROOT / "results/judge_robustness/gpt-5.6-sol/preflight"
OUT_JSON = OUT_DIR / "routing_verification.json"
OUT_LOG = OUT_DIR / "routing_verification.log"

BASE_URL = "https://openrouter.ai/api/v1"
SLUG = "openai/gpt-5.6-sol"
PACE = 1.5

# The frozen pin, quoted from the amendment. Kept as a literal here on purpose: this script
# must verify what the amendment CLAIMS, not import whatever the runner currently does.
FROZEN_PIN = {"provider": {"order": ["openai"], "allow_fallbacks": False}}

_lines: list[str] = []
_records: list[dict] = []


def say(s: str = "") -> None:
    print(s)
    _lines.append(s)


def _now() -> str:
    return _dt.datetime.now(_dt.timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ")


key = os.getenv("OPENROUTER_API_KEY", "").strip()
if not key:
    sys.exit("OPENROUTER_API_KEY is not set")
client = openai.OpenAI(base_url=BASE_URL, api_key=key, max_retries=0)


def ask(label, extra=None, prompt="Reply with the single word: ok", max_tok=16, effort=None):
    """One probe call. Returns (served_provider, returned_model, usage, error)."""
    kw = dict(model=SLUG, messages=[{"role": "user", "content": prompt}],
              max_completion_tokens=max_tok)
    if extra:
        kw["extra_body"] = extra
    if effort:
        kw["reasoning_effort"] = effort
    rec = {"label": label, "utc": _now(), "extra_body": extra, "reasoning_effort": effort}
    try:
        r = client.chat.completions.create(**kw)
        d = r.model_dump()
        u = d.get("usage") or {}
        det = u.get("completion_tokens_details") or {}
        out = (d.get("provider"), d.get("model"),
               {"prompt": u.get("prompt_tokens"), "completion": u.get("completion_tokens"),
                "reasoning": det.get("reasoning_tokens")}, None)
        rec.update(served_provider=out[0], returned_model=out[1], usage=out[2],
                   response_id=d.get("id"), error=None)
    except openai.AuthenticationError as e:
        msg = _scrub(str(e))
        if "missing authentication header" in msg.lower():
            rec.update(error=f"TRANSIENT-AUTH: {msg[:160]}")
            _records.append(rec)
            say(f"  !! edge-side throttle during {label}; pausing 10s and retrying once")
            time.sleep(10)
            return ask(label + " (retry)", extra, prompt, max_tok, effort)
        say(f"\n  !! REAL AUTH FAILURE during {label}: {msg[:160]}")
        say("     This is NOT a routing result. Aborting so it cannot be misread as one.")
        _records.append(dict(rec, error=f"FATAL-AUTH: {msg[:200]}"))
        _flush()
        sys.exit(2)
    except Exception as e:  # noqa: BLE001
        out = (None, None, None, f"{type(e).__name__}: {_scrub(str(e))[:200]}")
        rec.update(served_provider=None, returned_model=None, usage=None, error=out[3])
    _records.append(rec)
    return out


_ACCOUNT_HANDLE = re.compile(
    r"\b(?:user|org|organization|account|proj|project|team)[-_][A-Za-z0-9]{12,}\b")


def _scrub(text: str) -> str:
    """Strip provider ACCOUNT handles out of captured error text.

    Provider errors echo back an account-scoped id (OpenRouter puts `user_...` in its 404
    body). That id is not a credential, but it is a durable handle that links this repo to
    the account that produced it -- an identity link that must stay out of published
    output. Everything this script writes is a published artifact, so redact at the
    point of capture, not afterwards.
    """
    return _ACCOUNT_HANDLE.sub("<redacted-account-handle>", text)


def _flush() -> None:
    OUT_DIR.mkdir(parents=True, exist_ok=True)
    OUT_JSON.write_text(json.dumps(
        {"purpose": "captured verification of the OpenRouter routing pin "
                    "(cross-judge-amendment-openrouter-2026-07-20.md §3, §6)",
         "utc": _now(), "base_url": BASE_URL, "model_slug": SLUG,
         "frozen_pin": FROZEN_PIN, "calls": _records, "verdicts": VERDICTS},
        indent=2) + "\n")
    OUT_LOG.write_text("\n".join(_lines) + "\n")


VERDICTS: dict[str, object] = {}


def verdict(name, ok, detail):
    VERDICTS[name] = {"pass": bool(ok), "detail": detail}
    say(f"  {'PASS' if ok else '**FAIL**'}  {name}: {detail}")


say(f"OpenRouter routing verification -- {_now()}")
say(f"  endpoint {BASE_URL}   slug {SLUG}")
say(f"  frozen pin: {json.dumps(FROZEN_PIN)}")
say()

# ---------------------------------------------------------------- [0] auth precondition
say("[0] auth precondition -- one UNPINNED call must succeed before anything is interpreted")
prov0, model0, _u, err0 = ask("precondition-unpinned")
if err0:
    verdict("auth_precondition", False, f"precondition failed: {err0}")
    _flush()
    sys.exit(f"  precondition FAILED: {err0}\n  Resolve this before reading any routing result.")
say(f"  unpinned call served by {prov0!r} (model {model0!r})")
say("  NOTE: default routing is NOT the frozen route -- recorded only as a baseline.")
verdict("auth_precondition", True, f"unpinned call succeeded, served by {prov0!r}")
time.sleep(PACE)

# ---------------------------------------------------------------- [1] the frozen pin holds
say()
say("[1] POSITIVE CONTROL -- the frozen pin, repeated, must be stable")
seen = []
for i in range(3):
    p, m, _u, e = ask(f"frozen-pin-{i+1}", FROZEN_PIN)
    seen.append(p or f"ERR:{(e or '')[:40]}")
    time.sleep(PACE)
say(f"  order=['openai'] over 3 calls -> {seen}")
verdict("frozen_pin_stable",
        len(set(seen)) == 1 and seen[0] == "OpenAI",
        f"served by {sorted(set(seen))} (expected exactly ['OpenAI'])")

# ------------------------------------------------- [2] THE DISCRIMINATING POSITIVE CONTROL
say()
say("[2] DISCRIMINATING POSITIVE CONTROL -- pin a DIFFERENT provider; routing must follow it")
say("    If order=['azure'] is served by Azure while order=['openai'] is served by OpenAI,")
say("    then `order` demonstrably SELECTS the upstream. No 404 can establish this.")
pa, ma, _u, ea = ask("positive-control-azure",
                     {"provider": {"order": ["azure"], "allow_fallbacks": False}})
if ea:
    verdict("order_selects_provider", False,
            f"order=['azure'] errored ({ea}) -- inconclusive, NOT proof the pin binds")
else:
    say(f"  order=['azure'] -> served by {pa!r} (model {ma!r})")
    verdict("order_selects_provider",
            pa is not None and pa != seen[0],
            f"order=['azure'] served by {pa!r} vs order=['openai'] served by {seen[0]!r}; "
            "routing follows `order`" if pa != seen[0] else
            f"BOTH pins served by {pa!r} -- `order` may be IGNORED; the pin is unproven")
time.sleep(PACE)

# ---------------------------------------------------------------- [3] negative control
say()
say("[3] NEGATIVE CONTROL -- a bogus tag must be refused")
pb, _m, _u, eb = ask("negative-control-bogus",
                     {"provider": {"order": ["definitely-not-a-provider"],
                                   "allow_fallbacks": False}})
verdict("bogus_tag_refused", pb is None,
        f"refused ({eb})" if pb is None else f"**SERVED by {pb!r} -- the pin is being IGNORED**")
time.sleep(PACE)

# --------------------------------------------- [4] what a 404 actually means (miscase probe)
say()
say("[4] MISCASE PROBE -- documents what a 404 proves")
say("    A valid-but-miscased tag returning the SAME error as a bogus one means 404 shows")
say("    'tag unrecognized', not 'provider refused'. This is why [2] is the real control.")
pm, _m, _u, em = ask("miscase-OpenAI",
                     {"provider": {"order": ["OpenAI"], "allow_fallbacks": False}})
same = (pm is None and eb is not None and em is not None
        and em.split(":")[0] == eb.split(":")[0])
verdict("miscase_documented", True,
        f"order=['OpenAI'] -> {'refused: ' + str(em) if pm is None else 'served by ' + repr(pm)}; "
        f"{'same error class as the bogus tag (404 == unrecognized)' if same else 'differs from the bogus tag'}")
time.sleep(PACE)

# ---------------------------------------------------- [5] allow_fallbacks is load-bearing
say()
say("[5] allow_fallbacks ISOLATION -- an unroutable pin must SUCCEED when fallbacks are on")
pf, _m, _u, ef = ask("bogus-with-fallbacks",
                     {"provider": {"order": ["definitely-not-a-provider"],
                                   "allow_fallbacks": True}})
verdict("allow_fallbacks_is_load_bearing", pf is not None,
        f"bogus tag + allow_fallbacks=True -> served by {pf!r} (so allow_fallbacks=False is "
        "what blocks the fallback)" if pf is not None else
        f"bogus tag + allow_fallbacks=True ALSO failed ({ef}); the refusal in [3] is not "
        "attributable to allow_fallbacks")
time.sleep(PACE)

# ---------------------------------------------------------------- [6] reasoning_effort
say()
say("[6] reasoning_effort through the route (the scoring preflight's prompts are too trivial)")
HARD = ("A rope burns unevenly in exactly 60 minutes. Using two such ropes and a lighter, "
        "measure exactly 45 minutes. Explain the reasoning step by step.")
eff = {}
for level in ("minimal", "high"):
    p, _m, u, e = ask(f"reasoning-{level}", FROZEN_PIN, prompt=HARD, max_tok=256, effort=level)
    eff[level] = (u or {}).get("reasoning") if not e else f"ERR:{e[:40]}"
    say(f"  reasoning_effort={level:8} -> reasoning_tokens={eff[level]}")
    time.sleep(PACE)
try:
    honored = (isinstance(eff["minimal"], int) and isinstance(eff["high"], int)
               and eff["high"] > eff["minimal"])
except Exception:  # noqa: BLE001
    honored = False
_reason_note = ("high > minimal, so the parameter survives the route" if honored else
                "NOT demonstrated -- the frozen config sets reasoning_effort=medium, so this "
                "must be resolved or disclosed")
verdict("reasoning_effort_honored", honored,
        f"minimal={eff['minimal']} high={eff['high']}; {_reason_note}")

# ---------------------------------------------------------------- summary
say()
say("=" * 74)
passed = sum(1 for v in VERDICTS.values() if v["pass"])
say(f"  {passed}/{len(VERDICTS)} verdicts passed")
say()
say("  The load-bearing one is `order_selects_provider` [2]: it is the only test that")
say("  distinguishes an ENFORCED pin from one that is accepted and ignored while OpenAI")
say("  happens to be the default. `bogus_tag_refused` [3] alone cannot.")
say("=" * 74)
_flush()
say()
say(f"transcript -> {OUT_JSON.relative_to(REPO_ROOT)}")
say(f"log        -> {OUT_LOG.relative_to(REPO_ROOT)}")
