# Second-judge transport amendment · July 20, 2026

The July 19 plan specified direct OpenAI access for GPT-5.6 Sol. The authors switched to OpenRouter after six direct attempts yielded three ratings. The operator also reported a token limit below the planned batch size. The direct-run record contains neither the failure status codes nor the exact limit. Those three ratings were excluded. OpenRouter supplied all 7,074 ratings in the analysis. [July 19 analysis plan](cross-judge-amendment-2026-07-19.md) · [Original transport amendment](https://github.com/bydeng01/conv-vs-ped-tutor/blob/5d946321ad03e62d0f0f5b0f9040b91e73bc799d/cross-judge-amendment-openrouter-2026-07-20.md)

## Request settings

The judge requested the model `openai/gpt-5.6-sol` through OpenRouter's Chat Completions endpoint. Each request specified the `openai` upstream, disabled provider fallback, requested medium reasoning effort, omitted temperature, and allowed 2,048 completion tokens. The runner recorded the provider returned for each rating and compared it with the provider recorded at preflight. [Judge configuration](configs/models.judge-gpt56.yaml) · [Resolved settings](results/judge_robustness/gpt-5.6-sol/preflight/resolved_config.json) · [Routing tests](results/judge_robustness/gpt-5.6-sol/preflight/routing_verification.json)

## What the provider records establish

OpenRouter identified OpenAI as the upstream for every rating and returned the router model identifier. The returned metadata did not identify a dated deployment, and neither route supplied a system fingerprint. Upstream enforcement of the requested reasoning level remains unknown. Identical request settings across policies do not resolve that uncertainty. [Scoring and provenance](supplement/second-judge-transport-disclosure.md)
