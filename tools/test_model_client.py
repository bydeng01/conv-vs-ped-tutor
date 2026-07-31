"""Offline tests for provider compatibility fallbacks in agents/model_client.py.

Run: python tools/test_model_client.py
"""
from __future__ import annotations

import sys
from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(REPO_ROOT))

from agents.model_client import ModelClient  # noqa: E402

_passed = _failed = 0


def check(name, cond):
    global _passed, _failed
    if cond:
        _passed += 1
        print(f"  PASS  {name}")
    else:
        _failed += 1
        print(f"  FAIL  {name}")


class _Usage:
    prompt_tokens = 7
    completion_tokens = 3


class _Choice:
    class message:
        content = "ok"


class _Response:
    choices = [_Choice()]
    usage = _Usage()

    def model_dump(self):
        return {"id": "resp_fake", "model": "gpt-5.5-2026-04-23"}


class _Completions:
    def __init__(self, reject_max_tokens=True):
        self.calls = []
        self.reject_max_tokens = reject_max_tokens

    def create(self, **kw):
        self.calls.append(dict(kw))
        if self.reject_max_tokens and "max_tokens" in kw:
            raise RuntimeError(
                "Unsupported parameter: 'max_tokens' is not supported with this model. "
                "Use 'max_completion_tokens' instead."
            )
        return _Response()


class _FakeClient:
    def __init__(self, reject_max_tokens=True):
        self.chat = type("Chat", (), {"completions": _Completions(reject_max_tokens)})()


def test_openai_max_completion_tokens_fallback():
    cfg = {
        "providers": {"openai": {"base_url": "unused", "api_key_env": "UNUSED"}},
        "roles": {
            "tutor": {
                "provider": "openai",
                "model": "gpt-5.5-2026-04-23",
                "temperature": 0.4,
                "max_tokens": 1024,
            },
            "student": {"model": "unused"},
            "judge": {"model": "unused"},
        },
    }
    fake = _FakeClient()
    client = ModelClient(models_cfg=cfg, backend="live")
    client._clients["openai"] = fake

    comp = client._complete_openai(
        role="tutor",
        spec=cfg["roles"]["tutor"],
        system="sys",
        messages=[{"role": "user", "content": "hi"}],
        seed=0,
        provider="openai",
    )

    calls = fake.chat.completions.calls
    check("fallback first tries max_tokens", "max_tokens" in calls[0])
    check("fallback retries with max_completion_tokens",
          "max_completion_tokens" in calls[1] and "max_tokens" not in calls[1])
    check("completion succeeds after fallback", comp.text == "ok")

    client._complete_openai(
        role="tutor",
        spec=cfg["roles"]["tutor"],
        system="sys",
        messages=[{"role": "user", "content": "again"}],
        seed=1,
        provider="openai",
    )
    check("remembered fallback for later calls",
          "max_completion_tokens" in calls[2] and "max_tokens" not in calls[2])


def test_openai_forwards_reasoning_effort_as_top_level_field():
    cfg = {
        "providers": {"gemini": {"base_url": "unused", "api_key_env": "UNUSED"}},
        "roles": {
            "tutor": {
                "provider": "gemini",
                "model": "gemini-3.1-pro-preview",
                "temperature": 0.4,
                "max_tokens": 1024,
                "reasoning_effort": "low",
            },
            "student": {"model": "unused"},
            "judge": {"model": "unused"},
        },
    }
    fake = _FakeClient(reject_max_tokens=False)
    client = ModelClient(models_cfg=cfg, backend="live")
    client._clients["gemini"] = fake

    comp = client._complete_openai(
        role="tutor",
        spec=cfg["roles"]["tutor"],
        system="sys",
        messages=[{"role": "user", "content": "hi"}],
        seed=0,
        provider="gemini",
    )

    call = fake.chat.completions.calls[0]
    check("reasoning_effort forwarded", call.get("reasoning_effort") == "low")
    check("reasoning_effort is top-level, not extra_body", call.get("extra_body") is None)
    check("normal completion still succeeds", comp.text == "ok")


def test_openai_null_temperature_is_omitted_not_sent_as_null():
    """An explicit `temperature: null` in the spec must OMIT the parameter, not send
    JSON null; a numeric value is still sent; a missing key keeps the 0.4 default."""
    def _client_and_call(temp_value, has_key):
        role_spec = {"provider": "openai", "model": "gpt-5.6-sol", "max_tokens": 2048,
                     "reasoning_effort": "medium"}
        if has_key:
            role_spec["temperature"] = temp_value
        cfg = {"providers": {"openai": {"base_url": "u", "api_key_env": "U"}},
               "roles": {"tutor": role_spec, "student": {"model": "u"}, "judge": {"model": "u"}}}
        fake = _FakeClient(reject_max_tokens=False)
        client = ModelClient(models_cfg=cfg, backend="live")
        client._clients["openai"] = fake
        client._complete_openai(role="tutor", spec=role_spec, system="s",
                                messages=[{"role": "user", "content": "hi"}],
                                seed=0, provider="openai")
        return fake.chat.completions.calls[0]

    call_null = _client_and_call(None, has_key=True)
    check("null temperature omits the parameter entirely", "temperature" not in call_null)

    call_num = _client_and_call(0.4, has_key=True)
    check("numeric temperature is still sent", call_num.get("temperature") == 0.4)

    call_absent = _client_and_call(None, has_key=False)
    check("absent temperature keeps the 0.4 default", call_absent.get("temperature") == 0.4)

    check("null-temp path still forwards reasoning_effort",
          call_null.get("reasoning_effort") == "medium")
    check("null-temp path still uses max_completion_tokens field is not forced",
          "max_tokens" in call_null and call_null["max_tokens"] == 2048)


def main():
    test_openai_max_completion_tokens_fallback()
    test_openai_forwards_reasoning_effort_as_top_level_field()
    test_openai_null_temperature_is_omitted_not_sent_as_null()
    print(f"\n{_passed} passed, {_failed} failed")
    sys.exit(1 if _failed else 0)


if __name__ == "__main__":
    main()
