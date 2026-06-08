# Model Matrix

## Mandatory Smoke Models

| Gate | backend_id | model_id | Artifact | Reproducibility | Runtime Config | Success Criteria |
| --- | --- | --- | --- | --- | --- | --- |
| mandatory real smoke | `mlc` | `Qwen3-1.7B-q4f16_1-MLC` | `mlc-ai/Qwen3-1.7B-q4f16_1-MLC`, about 984 MB | revision `80b3abcec6c3b3f5355dc0cc99cc4fb578f192bc`, `model_lib=qwen3_q4f16_1_1431bce2f7643ad37bb21ddc71153223` | `q4f16_1`, context 2048, prefill chunk 128, max_new_tokens 32, temperature 0, top_p 1 | non-empty decoded token, prompt tokens > 0, generated tokens > 0, diagnostics and hashes present |
| debug fallback only | `mlc` | `Qwen3-0.6B-q0f16-MLC` | `mlc-ai/Qwen3-0.6B-q0f16-MLC`, about 1.2 GB | `model_lib=qwen3_q0f16_e709b04052d95e24b38d40e4259e1f14` | same smoke params | may isolate package/runtime/tokenizer issues; cannot replace mandatory acceptance |
| mandatory real smoke | `llama_cpp` | `minicpm4-0.5b-q4_k_m` | `Mungert/MiniCPM4-0.5B-GGUF`, `MiniCPM4-0.5B-q4_k_m.gguf`, 276,028,992 bytes | revision `72bc14b5c718727f48743ddae278aaa555604bd9`, sha256 `66ef85bb806c973c3f24bb014b8bd2be4e41b5c51e2f64782f470589add87e74` | `Q4_K_M`, context 2048, threads 2-4, prompt template `minicpm`, max_new_tokens 32 | same real-token criteria plus GGUF size/sha preflight |

## Real Inference Gate

A backend is accepted only when it:

- Loads a real model artifact whose manifest and sha256 match.
- Emits at least one decoded token from native/runtime inference.
- Reports prompt token count and generated token count greater than zero.
- Records runtime diagnostics, model artifact identity, and native library hash.
- Completes three consecutive runs without process crash.

## Table Reproduction Models

The table reproduction suite uses `llama_cpp` GGUF Q4 artifacts only. MLC smoke
models above remain regression gates and are not part of V1 formal table
reproduction.

| model_id | HF repo/revision | artifact | sha256 | size bytes | template | context |
| --- | --- | --- | --- | ---: | --- | ---: |
| `minicpm5-1b-thinking-q4` | `openbmb/MiniCPM5-1B-GGUF` / `87007042419d30c1d8f38ef065424ee33870831e` | `MiniCPM5-1B-Q4_K_M.gguf` | `81b64d05a23b17b34c475f42b3e72fbde62d4b92cc34541f7a8031d0752deafa` | 688065920 | `minicpm` | 81920 |
| `qwen3-0.6b-thinking-q4` | `unsloth/Qwen3-0.6B-GGUF` / `50968a4468ef4233ed78cd7c3de230dd1d61a56b` | `Qwen3-0.6B-Q4_K_M.gguf` | `ac2d97712095a558e31573f62f466a3f9d93990898b0ec79d7c974c1780d524a` | 396705472 | `qwen3` | 81920 |
| `qwen3.5-0.8b-thinking-q4` | `unsloth/Qwen3.5-0.8B-GGUF` / `6ab461498e2023f6e3c1baea90a8f0fe38ab64d0` | `Qwen3.5-0.8B-Q4_K_M.gguf` | `bd258782e35f7f458f8aced1adc053e6e92e89bc735ba3be89d38a06121dc517` | 532517120 | `qwen3.5` | 81920 |
| `lfm2.5-1.2b-thinking-q4` | `LiquidAI/LFM2.5-1.2B-Thinking-GGUF` / `7cb86bcf8ccd6ef5eae50a9ccbdf690ee2646ee5` | `LFM2.5-1.2B-Thinking-Q4_K_M.gguf` | `7223a2202405b02e8e1e6c5baa543c43dc98c1d9741a5c2a0ee1583212e1231b` | 730895360 | `lfm2.5` | 81920 |

Formal reproduction params are fixed at `temperature=0.9`, `top_p=0.95`, and
`thinking_enabled=true`. Dataset-specific `max_tokens` and profile IDs are
defined in `configs/table_reproduction_v1.json`.
