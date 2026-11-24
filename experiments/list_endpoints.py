"""List the OpenRouter serving providers, precision, context limits and prices for a model.

With OPENROUTER_API_KEY set, inspect the endpoint used by the study student:

    python experiments/list_endpoints.py meta-llama/llama-3.1-8b-instruct

The study configuration routes student requests to Groq with fallbacks disabled.
"""
from __future__ import annotations

import json
import os
import sys
import urllib.request


def main():
    if len(sys.argv) < 2:
        raise SystemExit("usage: python experiments/list_endpoints.py <author/slug>\n"
                         "  e.g. python experiments/list_endpoints.py meta-llama/llama-3.1-8b-instruct")
    model = sys.argv[1]
    key = os.environ.get("OPENROUTER_API_KEY")
    if not key:
        raise SystemExit("OPENROUTER_API_KEY not set")

    url = f"https://openrouter.ai/api/v1/models/{model}/endpoints"
    req = urllib.request.Request(url, headers={"Authorization": f"Bearer {key}"})
    try:
        with urllib.request.urlopen(req, timeout=30) as r:
            data = json.load(r)
    except Exception as e:  # noqa: BLE001
        raise SystemExit(f"failed to fetch endpoints for {model}: {str(e)[:300]}")

    # Expected shape: {"data": {"endpoints": [{provider_name, quantization,
    # context_length, pricing:{prompt,completion}, ...}]}}. Be defensive about it.
    endpoints = (data.get("data") or {}).get("endpoints")
    if not isinstance(endpoints, list) or not endpoints:
        print(f"{model}: could not parse an endpoints list — raw response below "
              f"(adapt the field names if OpenRouter changed them):\n")
        print(json.dumps(data, indent=2)[:3000])
        return

    print(f"{model}: {len(endpoints)} endpoint(s)")
    print(f"{'provider':24s}{'quantization':14s}{'context':>9s}  {'$in/M':>8s}{'$out/M':>8s}")
    for e in endpoints:
        name = e.get("provider_name") or e.get("name") or "?"
        quant = e.get("quantization") or "unknown"
        ctx = e.get("context_length") or e.get("context") or 0
        pr = e.get("pricing") or {}
        try:
            pin = float(pr.get("prompt", 0) or 0) * 1e6
            pout = float(pr.get("completion", 0) or 0) * 1e6
        except (TypeError, ValueError):
            pin = pout = 0.0
        print(f"{str(name):24s}{str(quant):14s}{str(ctx):>9}  {pin:>8.3f}{pout:>8.3f}")

    print("\nPick a low-precision (weaker) serving, pin it in configs/models.yaml "
          "(student.extra_body.provider), then re-gate cold.")


if __name__ == "__main__":
    main()
