# Nemotron model and runtime configuration

Snapshot: 2026-07-17.

## Active contract

| Item | Active value |
|---|---|
| Model | `nvidia/nemotron-nano-9b-v2` (instruct/chat, not Base) |
| Serving layer | NVIDIA NIM `1.0.0` |
| Engine/profile | NVIDIA vLLM `0.10.2`, NVFP4, TP1/PP1 |
| Runtime maximum context | `131072` tokens, verified by `/v1/models` and Phase 3 artifacts |
| Application context | `32768` tokens with dynamic evidence budgets |
| Embedding | `nvidia/llama-nemotron-embed-300m-v2` `1.13.0`, 2048 dimensions |
| Exact tokenizer | Local Nemotron tokenizer, SHA-256 `32bd2509c1acc93dc18bdd0f9a2d9a15e72fd3110f24cfc9ff3fb820f4e20b6b` |
| Prompt | `nemotron-grounded-v8`, SHA-256 `de7e06df0c49e06170b9a39be06c7a3eb95c4cb04b5c331a6726bbeb2713ec84` |

The API rejects an enabled non-selected model/version unless deliberate development mode
is used. It also fails closed when the exact tokenizer is unavailable.

## Generation profiles

| Mode | Reasoning signal | Temperature/top-p | Default output cap | Use |
|---|---|---:|---:|---|
| Fast | `/no_think` | `0.0 / 1.0` | 1024 | greeting, direct lookup, simple prompt |
| Reasoning | `/think` | `0.6 / 0.95` | 4096 | follow-up, technical analysis, multi-step RAG |
| Adaptive multi-document | `/think` | `0.6 / 0.95` | up to 8192 | complex multi-file synthesis |

`response_depth` supports `concise`, `normal` and `detailed`; `detailed` is the project
default. The prompt budget reserves output and safety tokens before admitting memory or
evidence, and counts the final rendered chat messages exactly.

## Runtime optimizations and limits

- Chunked prefill is supported by the selected NIM profile.
- Prefix caching is automatically disabled by this hybrid Mamba runtime; it must not be
  reported as an active optimization.
- The active NVIDIA profile does not expose a supported control or proof for
  `mamba_ssm_cache_dtype=float32`; that `plan.md` DoD is therefore not verified.
- A like-for-like BF16 versus NVFP4 run on the new fixed chatbot eval set was not produced.
  Historical profile inventory is not a substitute for this A/B gate.
- NIM timeout is 120 seconds and the API caps in-flight RAG requests with a semaphore.

## Rollback switches

`ENABLE_ADAPTIVE_REASONING=false` returns to static mode policy. Memory and hybrid
retrieval have independent flags documented in their design files. The final-answer cache
must remain off until its identity binds all memory, evidence, prompt and policy inputs.
