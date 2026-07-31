"""List available model ids from a provider (the slugs change over time). Two uses:

  - the free-tier student/calibration providers, so configs/models.free.yaml uses valid slugs;
  - the CROSS-MODEL tutor bases: confirm + pin the exact flagship chat id (and capture the
    evidence) for the per-base pin addendum (decisions-log.md 2026-06-27, point 1).

OpenAI and Gemini both expose an OpenAI-compatible models.list(), so one client lists them all.
Run with whichever keys you have set:

    export OPENAI_API_KEY=...; export GEMINI_API_KEY=...        # cross-model tutor bases
    export GROQ_API_KEY=...; export CEREBRAS_API_KEY=...; export OPENROUTER_API_KEY=...   # free tier
    python experiments/list_models.py
"""
import os
import re
from openai import OpenAI

PROVIDERS = [
    # cross-model tutor bases (Phase 1) -- confirm the flagship chat id at pin time
    ("openai",     "https://api.openai.com/v1",                          "OPENAI_API_KEY"),
    ("gemini",     "https://generativelanguage.googleapis.com/v1beta/openai/", "GEMINI_API_KEY"),
    # free-tier student / calibration providers
    ("groq",       "https://api.groq.com/openai/v1", "GROQ_API_KEY"),
    ("cerebras",   "https://api.cerebras.ai/v1",     "CEREBRAS_API_KEY"),
    ("openrouter", "https://openrouter.ai/api/v1",   "OPENROUTER_API_KEY"),
]

# Utility / non-chat / variant families to drop when surfacing flagship CHAT candidates, so the
# tutor-base shortlist excludes mini/nano/embeddings/audio/image/realtime/etc. Matched as whole
# id TOKENS (split on non-alphanumerics), so "mini" drops gpt-4o-mini but NOT ge-MINI. The lead
# still applies the deterministic rule (current flagship general-purpose chat; NOT a reasoning
# variant) against the full list below -- this is a hint, not the decision.
_NON_CHAT = {"mini", "nano", "lite", "embed", "embedding", "embeddings", "tts", "whisper",
             "audio", "speech", "transcribe", "image", "vision", "dall", "sora", "realtime",
             "search", "moderation", "guard", "rerank", "tuning", "instruct", "codex"}


def _chat_candidates(ids):
    return [i for i in ids if not (_NON_CHAT & set(re.split(r"[^a-z0-9]+", i.lower())))]


def main():
    for name, url, env in PROVIDERS:
        key = os.environ.get(env)
        if not key:
            print(f"\n[{name}] {env} not set — skipping")
            continue
        try:
            ids = sorted(m.id for m in OpenAI(base_url=url, api_key=key).models.list().data)
        except Exception as e:  # noqa: BLE001
            print(f"\n[{name}] ERROR: {str(e)[:200]}")
            continue
        print(f"\n[{name}] {len(ids)} models")
        if name in ("openai", "gemini"):
            # flagship-chat shortlist for the cross-model tutor base
            cand = _chat_candidates(ids)
            print("  chat candidates (mini/nano/embed/audio/image/realtime dropped):",
                  ", ".join(cand) or "(none after filtering)")
        else:
            # 70B-class tutor + small student candidates for the free-tier pilot config
            big = [i for i in ids if "70b" in i.lower() or "72b" in i.lower()]
            small = [i for i in ids if any(s in i.lower() for s in ("8b", "7b", "3b", "1b", "mini", "small"))]
            if big:
                print("  ~70B (tutor candidates):", ", ".join(big))
            if small:
                print("  small (student candidates):", ", ".join(small))
        print("  all:", ", ".join(ids))


if __name__ == "__main__":
    main()
