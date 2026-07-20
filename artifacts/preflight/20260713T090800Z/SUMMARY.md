# Phase 0 preflight summary — 20260713T090800Z

## Host

- Linux `aarch64`, NVIDIA GB10.
- NVIDIA driver 580.142; `nvidia-smi` reports CUDA 13.0.
- Docker Engine 29.1.3 (`linux/arm64`), Compose 2.40.3.
- All nine master-plan preflight commands exited 0.

See `preflight.txt`, `command-status.tsv`, and the structured image JSON files
in this directory.

## NVIDIA NIM

- One local NIM image:
  `nvcr.io/nim/meta/llama-3.1-8b-instruct:2.0.6` at immutable index digest
  `sha256:31e360dbb15f825d69e5d68c2032e334301523b4957091270385ed7ef3db5e81`.
- Local image: Linux ARM64. Registry index: Linux ARM64 child manifest
  `sha256:249dcac461f20bc29ddb0924bf0c30e0e3f646c26bd849d978996cbe30b4d06e`.
- `list-model-profiles` passed on GB10 and reported BF16, FP8, and NVFP4 vLLM
  profiles (plus LoRA variants).
- No live NIM API smoke: no service is running, no standard host cache was
  identified, and no NGC/HF token was present in the capture shell.
- Required Nemotron 9B, embedding, and reranking NIM images are absent. They
  were not pulled. Registry inspection confirms Linux ARM64 manifests for the
  exact catalog tags, but Retriever documentation still states an x86 CPU
  requirement, so platform support remains an explicit contradiction.

## Python DG-01

- CPython 3.14.5 / ARM64 dependency lock: pass (183 packages).
- Normal locked install: pass (180 distributions).
- Top-level imports and Torch CUDA/GB10 matrix multiply: pass.
- Wheel-only install: fail because two pure-Python transitive packages require
  source builds; the normal install built both successfully.
- `uv pip check`: one known `manylinux2014_sbsa` tag warning for the ARM
  `nvidia-cusparselt-cu13` wheel. The ELF is aarch64, loads, and the CUDA smoke
  passes. This exception is documented in ADR 0002.
- Python 3.13 was not tested because the required 3.14 lock/install/import gate
  passed.

## Security and reproducibility

- Credential values and container environments were not captured; `docker info`
  was reduced to an explicit non-secret field allowlist.
- `secret-scan.txt` records that the high-confidence local artifact scan found no
  credential value, and `command-status.tsv` records the scan exit status.
- The dependency input and lock checksums are in `python314-environment.txt`.
