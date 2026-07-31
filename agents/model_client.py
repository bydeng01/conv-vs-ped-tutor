"""Unified model client.

Backends:
  - "live": a real API. The provider is chosen per role (or globally) in the
    models config: "anthropic" (Anthropic SDK) or any OpenAI-compatible endpoint
    ("openai_compat" — Groq, Cerebras, OpenRouter, OpenAI, ...). Anthropic is the
    final-stage provider (build brief); the OpenAI-compatible path is for free-
    tier pilot/calibration (logged as a deviation in decisions-log.md).
  - "mock": deterministic, offline, seeded. A DEVELOPMENT STAND-IN that lets the
    full harness, logging, and metrics run with no API access and no cost. The
    mock is explicitly *parameterized by the harness* (via `mock_meta`) rather
    than peeking at hidden state, so its behavior is auditable. Behavior priors
    in the mock are placeholders; the real student priors are calibrated against
    a live model in Step 2 (see paper-plan.md §6).

Every call is routed through `complete()`, which logs the full request and
response and returns a `Completion`. Agents never call a backend directly.
"""
from __future__ import annotations

import hashlib
import os
import time
from dataclasses import dataclass, field
from typing import Any, Optional

from .extraction import extract_final_answer  # re-exported; frozen (paper-plan §9)
from .logging_utils import RunLogger


@dataclass
class Completion:
    text: str
    input_tokens: int
    output_tokens: int
    model: str
    backend: str
    role: str
    raw_response: Any = None
    provider: Optional[str] = None   # the serving provider (OpenRouter reports this)


@dataclass
class ModelClient:
    models_cfg: dict
    backend: str
    logger: Optional[RunLogger] = None
    _clients: dict = field(default_factory=dict, repr=False)
    _seed_ok: dict = field(default_factory=dict, repr=False)
    _temp_ok: dict = field(default_factory=dict, repr=False)
    _token_param: dict = field(default_factory=dict, repr=False)

    # ------------------------------------------------------------------ public
    def complete(
        self,
        role: str,
        system: str,
        messages: list[dict[str, str]],
        seed: int,
        tags: Optional[dict[str, Any]] = None,
        mock_meta: Optional[dict[str, Any]] = None,
    ) -> Completion:
        spec = self.models_cfg["roles"][role]
        tags = tags or {}
        if self.backend == "live":
            comp = self._complete_live(role, spec, system, messages, seed)
        elif self.backend == "mock":
            comp = self._complete_mock(role, spec, system, messages, seed, mock_meta or {})
        else:
            raise ValueError(f"unknown backend: {self.backend}")

        if self.logger is not None:
            self.logger.log_call({
                "role": role,
                "backend": self.backend,
                "provider": (self._provider_for(spec) if self.backend == "live" else None),
                "served_provider": comp.provider,   # downstream serving (e.g. OpenRouter -> DeepInfra)
                "model": spec["model"],
                "seed": seed,
                "tags": tags,
                "request": {
                    "system": system,
                    "messages": messages,
                    "temperature": spec.get("temperature"),
                    "max_tokens": spec.get("max_tokens"),
                    "reasoning_effort": spec.get("reasoning_effort"),
                    "extra_body": spec.get("extra_body"),   # records the provider pin
                },
                "response": {"text": comp.text},
                "usage": {
                    "input_tokens": comp.input_tokens,
                    "output_tokens": comp.output_tokens,
                },
            })
        return comp

    # -------------------------------------------------------------------- live
    def _provider_for(self, spec: dict) -> str:
        """Provider precedence: role spec > global config > 'anthropic'."""
        return spec.get("provider") or self.models_cfg.get("provider") or "anthropic"

    def _provider_cfg(self, name: str) -> dict:
        return (self.models_cfg.get("providers") or {}).get(name, {})

    def _complete_live(self, role, spec, system, messages, seed) -> Completion:
        provider = self._provider_for(spec)
        if provider == "anthropic":
            return self._complete_anthropic(role, spec, system, messages)
        return self._complete_openai(role, spec, system, messages, seed, provider)

    def _complete_anthropic(self, role, spec, system, messages) -> Completion:
        if "anthropic" not in self._clients:
            import anthropic
            pc = self._provider_cfg("anthropic")
            key = os.environ.get(pc.get("api_key_env", "ANTHROPIC_API_KEY"))
            if not key:
                raise RuntimeError("Anthropic provider requires its API key in the environment.")
            self._clients["anthropic"] = anthropic.Anthropic(api_key=key)
        client = self._clients["anthropic"]
        model = spec["model"]

        def _call(with_temp: bool):
            kw = dict(model=model, system=system, messages=messages,
                      max_tokens=spec.get("max_tokens", 1024))
            temp = spec.get("temperature")
            if with_temp and temp is not None:
                kw["temperature"] = temp
            return client.messages.create(**kw)

        def _attempt():
            # Some models (e.g. claude-opus-4-8) reject `temperature` outright
            # ("temperature is deprecated for this model"). Drop it and remember per
            # model, mirroring the OpenAI seed fallback. This is NOT a rate limit, so
            # _with_backoff would otherwise just raise it.
            use_temp = self._temp_ok.get(model, True)
            try:
                return _call(use_temp)
            except Exception as e:  # noqa: BLE001
                msg = str(e).lower()
                if (use_temp and "temperature" in msg
                        and any(s in msg for s in ("deprecat", "not supported",
                                                   "unsupported", "not allowed"))):
                    self._temp_ok[model] = False
                    return _call(False)
                raise

        resp = _with_backoff(_attempt)
        text = "".join(b.text for b in resp.content if getattr(b, "type", None) == "text")
        return Completion(text, resp.usage.input_tokens, resp.usage.output_tokens,
                          model, "live", role,
                          resp.model_dump() if hasattr(resp, "model_dump") else None)

    def _complete_openai(self, role, spec, system, messages, seed, provider) -> Completion:
        if provider not in self._clients:
            from openai import OpenAI
            pc = self._provider_cfg(provider)
            base_url = pc.get("base_url")
            key = os.environ.get(pc.get("api_key_env", ""))
            if not base_url or not key:
                raise RuntimeError(
                    f"Provider '{provider}' needs providers.{provider}.base_url and "
                    f"its api_key_env ({pc.get('api_key_env')!r}) set in the environment."
                )
            self._clients[provider] = OpenAI(base_url=base_url, api_key=key)
        client = self._clients[provider]
        oai_messages = [{"role": "system", "content": system}] + messages

        token_key = (provider, spec["model"])

        def _call(with_seed: bool):
            token_param = self._token_param.get(token_key, "max_tokens")
            kw = dict(model=spec["model"], messages=oai_messages,
                      **{token_param: spec.get("max_tokens", 1024)})
            # temperature: an EXPLICIT null in the role spec means OMIT the parameter
            # entirely (send no `temperature` field), NOT send JSON null. A missing key
            # keeps the historical 0.4 default; a numeric value is sent unchanged. This
            # mirrors the Anthropic path, which also drops a null temperature, and lets a
            # judge config request the model's own default sampling (e.g. GPT-5.6 Sol,
            # cross-judge-amendment-2026-07-19.md).
            temp = spec.get("temperature", 0.4)
            if temp is not None:
                kw["temperature"] = temp
            if with_seed:
                kw["seed"] = seed
            if spec.get("reasoning_effort") is not None:
                kw["reasoning_effort"] = spec["reasoning_effort"]
            # Provider-routing / any OpenAI-compatible extras (e.g. OpenRouter's
            # {"provider": {"order": [...], "allow_fallbacks": false, "quantizations": [...]}}
            # to PIN one serving so it can't silently drift -- decisions-log 2026-06-18).
            extra = spec.get("extra_body")
            if extra:
                kw["extra_body"] = extra
            return client.chat.completions.create(**kw)

        def _attempt():
            use_seed = self._seed_ok.get(provider, True)
            while True:
                try:
                    return _call(use_seed)
                except Exception as e:  # noqa: BLE001
                    # Only fall back to compatible request fields when the field
                    # itself is rejected (a 400/unsupported-parameter), NOT on
                    # rate limits or quota failures.
                    msg = str(e).lower()
                    if (_uses_max_completion_tokens(msg)
                            and self._token_param.get(token_key) != "max_completion_tokens"):
                        self._token_param[token_key] = "max_completion_tokens"
                        continue
                    if use_seed and "seed" in msg and "rate" not in msg:
                        self._seed_ok[provider] = False
                        use_seed = False
                        continue
                    raise

        resp = _with_backoff(_attempt)
        text = resp.choices[0].message.content or ""
        usage = getattr(resp, "usage", None)
        in_tok = getattr(usage, "prompt_tokens", 0) if usage else 0
        out_tok = getattr(usage, "completion_tokens", 0) if usage else 0
        # OpenRouter reports the provider that actually served the request; capture it so
        # silent routing drift (the cold-100% failure) is visible in the logs.
        served = getattr(resp, "provider", None)
        if served is None and hasattr(resp, "model_dump"):
            try:
                served = (resp.model_dump() or {}).get("provider")
            except Exception:  # noqa: BLE001
                served = None
        return Completion(text, in_tok, out_tok, spec["model"], "live", role,
                          resp.model_dump() if hasattr(resp, "model_dump") else None,
                          provider=served)

    # -------------------------------------------------------------------- mock
    def _complete_mock(self, role, spec, system, messages, seed, mock_meta) -> Completion:
        rng = _seeded_rng(seed, role, messages, mock_meta)
        if role == "tutor":
            text = _mock_tutor(rng, messages, mock_meta)
        elif role == "student":
            text = _mock_student(rng, messages, mock_meta)
        elif role == "judge":
            text = _mock_judge(rng, mock_meta)
        else:
            text = "(mock) no behavior for role"
        return Completion(
            text=text,
            input_tokens=_approx_tokens(system) + sum(_approx_tokens(m["content"]) for m in messages),
            output_tokens=_approx_tokens(text),
            model=spec["model"],
            backend="mock",
            role=role,
        )


# ---------------------------------------------------------------- mock helpers
def _seeded_rng(seed: int, role: str, messages, mock_meta) -> "random.Random":
    import random
    key = f"{seed}|{role}|{mock_meta.get('turn_index', 0)}|{mock_meta.get('problem_id','')}"
    key += "|" + "".join(m["content"] for m in messages[-1:])
    digest = hashlib.sha256(key.encode()).hexdigest()
    return random.Random(int(digest[:16], 16))


def _approx_tokens(s: str) -> int:
    # Rough stand-in for tokenizer; ~0.75 words/token -> ~1.3 tokens/word.
    return max(1, int(len(s.split()) * 1.3))


def _last_tutor_text(messages) -> str:
    # In the student's view, tutor turns arrive as 'user' messages.
    for m in reversed(messages):
        if m["role"] == "user":
            return m["content"]
    return ""


def _mock_tutor(rng, messages, mock_meta) -> str:
    """ConvTutor stand-in: helpful and answer-eager. PedTutor nodes (Step 4)
    will use their own scoped prompts; this generic mock is for ConvTutor and
    harness smoke-testing."""
    ans = mock_meta.get("canonical_answer")
    turn = mock_meta.get("turn_index", 0)
    student_last = ""
    for m in reversed(messages):
        if m["role"] == "user":
            student_last = m["content"].lower()
            break
    asked_for_answer = any(p in student_last for p in ("what's the answer", "what is the answer",
                                                        "just tell me", "give me the answer", "the answer"))
    # Answer-eager behavior: reveal quickly if asked, or by turn 2 regardless.
    reveal = asked_for_answer or turn >= 1
    if reveal and ans is not None:
        a = _fmt_num(ans)
        return (f"Sure — set it up as x + 7 = 19, then subtract 7 from both sides, "
                f"so x = {a}. The number is {a}.")
    return ("Good start. Try writing an equation: let x be the unknown number. "
            "What equation matches 'a number increased by 7 equals 19'?")


def _mock_student(rng, messages, mock_meta) -> str:
    """Student stand-in. Behavior priors are PLACEHOLDERS (calibrated in Step 2):
       ~0.5 ask for answer when stuck, ~0.2 restate, ~0.3 attempt reasoning.
    Emits 'FINAL ANSWER: <n>' when it commits to an answer."""
    ans = mock_meta.get("canonical_answer")
    turn = mock_meta.get("turn_index", 0)
    tutored = mock_meta.get("tutored", True)
    tutor_text = _last_tutor_text(messages).lower()

    # Forced elicitation: state the answer in parseable form.
    if mock_meta.get("committing"):
        if not tutored and rng.random() >= mock_meta.get("cold_success_prob", 0.5):
            return f"FINAL ANSWER: {_fmt_num((ans or 0) + rng.choice([-3, -2, 2, 3]))}"
        return f"FINAL ANSWER: {_fmt_num(ans)}"

    # Did the tutor reveal a usable answer? (mock detects to drive realism)
    revealed = ans is not None and _fmt_num(ans) in tutor_text

    if not tutored:
        # Cold baseline: lone attempt. Translation is the hard part; the student
        # often mis-sets-up. Placeholder correctness prob; real value comes from
        # calibration. The trivial seed problem is gettable.
        if rng.random() < mock_meta.get("cold_success_prob", 0.5):
            return f"I think the number is {_fmt_num(ans)}. FINAL ANSWER: {_fmt_num(ans)}"
        wrong = _fmt_num((ans or 0) + rng.choice([-3, -2, 2, 3, 5]))
        return f"Maybe I add 7? So {wrong}. FINAL ANSWER: {wrong}"

    if revealed:
        return f"Oh I see, so x = {_fmt_num(ans)}. FINAL ANSWER: {_fmt_num(ans)}"

    r = rng.random()
    if r < 0.5:
        return "I'm stuck. What's the answer?"
    elif r < 0.7:
        return "So the problem says a number increased by 7 equals 19."
    else:
        guess = _fmt_num((ans or 0) + rng.choice([-2, -1, 1]))
        return f"Let me try... is it x = {guess}?"


def _mock_judge(rng, mock_meta) -> str:
    score = rng.choice([3, 4, 4, 5])
    return f'{{"clarity": {score}, "responsiveness": {score}, "helpfulness": {score}, "overall": {score}}}'


def _fmt_num(x) -> str:
    if x is None:
        return "?"
    f = float(x)
    return str(int(f)) if f.is_integer() else f"{f:g}"


# ----------------------------------------------------------------- live helpers
def _uses_max_completion_tokens(msg: str) -> bool:
    return ("max_tokens" in msg and "max_completion_tokens" in msg
            and any(s in msg for s in ("unsupported", "not supported", "invalid")))


class QuotaExhausted(RuntimeError):
    """A non-recoverable provider quota (e.g. per-day token cap) was hit."""


def _with_backoff(fn, attempts: int = 5, base: float = 2.0):
    """Retry transient rate limits with exponential backoff. Fail FAST on
    non-recoverable daily/quota caps (retrying a per-day limit just wastes calls).

    A per-MINUTE limit (TPM/RPM) is transient and is retried even when the provider
    appends an upsell mentioning billing/credits/upgrade — those words must not be read
    as a permanent quota stop. Groq's free-tier 429 does exactly this: it is a
    tokens-per-minute limit whose message links to .../settings/billing, which the
    earlier substring net mistook for a daily cap."""
    last = None
    for i in range(attempts):
        try:
            return fn()
        except Exception as e:  # noqa: BLE001 - provider-agnostic
            last = e
            msg = str(e).lower()
            # Per-minute limits are transient; detect them first so an upsell URL
            # ("billing"/"upgrade"/"credits") on a per-minute 429 isn't read as daily.
            per_minute = any(s in msg for s in ("per minute", "tpm", "rpm"))
            # Non-recoverable daily/quota cap — only when it is NOT a per-minute limit.
            daily = (not per_minute) and any(
                s in msg for s in ("per day", "tpd", "rpd", "tokens per day",
                                   "daily", "quota", "insufficient"))
            if daily:
                raise QuotaExhausted(
                    "Provider daily/quota cap hit — won't reset within a backoff. "
                    "Switch that role to another provider (Cerebras/OpenRouter) in "
                    "configs/models.free.yaml, or wait for the daily reset.\n"
                    f"Original error: {e}"
                ) from e
            transient = per_minute or any(s in msg for s in ("rate", "429", "timeout",
                                                             "overloaded", "503", "502",
                                                             "temporarily"))
            if not transient or i == attempts - 1:
                raise
            time.sleep(base ** i)
    raise last  # pragma: no cover


# `extract_final_answer` is imported from .extraction (frozen, paper-plan §9) and
# re-exported here for backward compatibility with existing imports.
