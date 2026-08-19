# Vietnamese ASR Product Review

**Date:** 2026-08-11  
**Workspace:** `E:\research\STT`  
**Scope:** Product transcription quality for Vietnamese investigative audio; no model promotion from model-card claims alone.

## Falsifiable Requirements

1. The active runtime and exact model revision must be observable in every task result.
2. The default product path must prioritize content retention and entity accuracy; a speed profile must be explicit.
3. A model can be promoted only after a frozen Vietnamese product corpus measures CER/WER, critical-entity recall, omitted voiced speech, hallucinated speech, timestamp error, latency and VRAM.
4. A coverage rescue pass must never publish a low-confidence or hallucinated segment merely because it increases transcript length.

## Current Runtime Evidence

- Effective engine: `legacy` -> `faster-whisper 1.2.1` / `CTranslate2 4.6.0`.
- Effective model after the product decision: `Systran/faster-whisper-large-v2`.
- Pinned local revision: `f0fe81560cb8b68660e564f55dd99207059c092e`.
- Device: CUDA FP16 on NVIDIA GeForce RTX 4070 SUPER.
- Before this review, `transcribe_service_v2.py` forced `beam_size=1`, `temperature=0.0`, `no_speech_threshold=0.5`, a generic initial prompt and one fixed VAD profile. This bypassed the configured beam setting and omitted model/decode provenance.
- The clean-install configuration also defaulted to `large-v3-turbo`, while API, Celery and legacy-service entrypoints defaulted to `fast_mode=true`. These defaults contradicted the investigation UI and are now aligned on user-selected `large-v2` plus `fast_mode=false`.

## Migration Artifact Finding

- The active `large-v3` snapshot was complete and loadable.
- The local `large-v2` and `large-v3-turbo` snapshot files were zero bytes after migration even though their Hugging Face `blobs` directories contained the complete artifacts. A directory-exists check therefore overstated availability.
- The candidate snapshots were materialized from their exact local blobs inside `E:\research\STT`; no file was read from or written to the D repository.
- The loader and benchmark preflight now require non-empty `config.json`, `model.bin` and `tokenizer.json`. An incomplete migrated snapshot is unavailable instead of failing late in CTranslate2.

## Live Decode Review

Audio: task `d59205bd-7955-4143-a721-3cb40ca4ba7c`, duration 304.321 seconds.

| Run | Decode | Time | Words | Timeline coverage | Observation |
|---|---|---:|---:|---:|---|
| Previous product path | beam 1, temperature 0, current VAD | 14.831 s | 835 | 250.660 s | Fast, but sentence boundaries and short continuations were weaker. |
| Accuracy candidate | beam 5, temperature fallback, current VAD | 17.947 s | 834 | comparable | About 3.1 s slower and joined several continuations more coherently. |
| Coverage diagnostic | beam 5, no VAD | 18.176 s | 858 | 258.620 s | Recovered a short filler but also generated a false closing sentence. Full no-VAD output is unsafe for release. |

A second 322.847-second task produced no materially new low-overlap segment in the no-VAD pass. The omission complaint is therefore not solved by unconditional full-audio decoding; it needs confidence-aware gap rescue and human references.

The repeatable local harness then ran all three materialized offline models on the same audio with `investigation-accuracy-v1`:

| Model | Warm decode | Words | Timeline coverage | Mean log probability | Pairwise disagreement vs large-v3 |
|---|---:|---:|---:|---:|---:|
| large-v3 | 18.202 s | 838 | 249.720 s | -0.136927 | baseline |
| large-v2 | 19.132 s | 844 | 253.780 s | -0.270214 | 11.0% |
| large-v3-turbo | 6.195 s | 848 | 261.270 s | -0.156593 | 5.9% |

These are diagnostics, not WER results. More words or wider segment coverage can mean recovered speech or hallucination. The first model in a fresh process also paid one-time CUDA/VAD initialization, so a reverse-order run was recorded before comparing warm latency.

## GPU Hallucination Reproduction

The reported GPU-only failure was reproduced and then falsified as a CUDA root cause on the same audio and exact `large-v2` snapshot:

| Path | Transcript result | Observation |
|---|---|---|
| CTranslate2 CPU FP32, primary VAD | hash `bff195...4236` | Exactly equal to GPU FP32. |
| CTranslate2 GPU FP32, primary VAD | hash `bff195...4236` | Exact CPU/GPU parity. |
| CTranslate2 GPU FP16, primary VAD | 0.237% word disagreement | Two-word numerical difference, not a catastrophic hallucination. |
| CPU FP32, GPU FP32 and GPU FP16, forced `0-20.14 s` no-VAD clip | identical 15-word output | The same unsupported span appears on every device and precision. |

The apparent device split came from a threshold edge in `leading-gap-rescue-v1`: GPU FP16 produced `no_speech=0.474609` and passed the old `0.5` gate, while CPU INT8 produced `0.505575` and failed it. Silero VAD found speech only from about `19.744 s`; roughly 95.8% of the candidate span lay outside voiced audio. The root cause was forced no-VAD decoding of the inferred leading gap, not GPU execution.

## Model Decision

| Candidate | Product decision | Reason |
|---|---|---|
| Whisper large-v3 via faster-whisper | Pinned challenger | Complete and locally available. Official multilingual evidence is stronger than large-v2, but the user selected large-v2 as the product primary. |
| Whisper large-v3-turbo | Speed profile only | Roughly 3x faster in the local warm run and close to large-v3 text, but extra coverage is not proof of correctness. Do not use as the high-stakes default without references. |
| Whisper large-v2 | **Primary now** | Explicit product decision. The snapshot is complete, pinned and loaded by exact path. This is not a claim that it has lower WER than large-v3; the frozen Vietnamese corpus gate remains mandatory. |
| PhoWhisper-large | **Pinned challenger, not active** | VinAI fine-tuned Whisper on 844 hours of diverse Vietnamese accents and reports its strongest PhoWhisper WER. The current adapter is not production-ready: the model is absent, chunk overlap is not deterministically deduplicated, and word timestamps are estimated. |
| PhoWhisper-medium/small | Resource fallback challengers | Lower resource cost, but official PhoWhisper benchmark rows are weaker than PhoWhisper-large. |

The official PhoWhisper repository reports PhoWhisper-large WER of 8.14 on Common Voice Vietnamese, 4.67 on VIVOS, 13.75 on VLSP 2020 Task 1 and 26.68 on VLSP 2020 Task 2. This makes it the strongest official Vietnamese-specific challenger in this review, not a product winner: those datasets and decoding conditions differ from covert, noisy and overlapping investigation audio.

Low-download community Vietnamese Whisper fine-tunes were not promoted. Their cards do not provide enough reproducible, product-matched evidence to replace the official large-v3 or PhoWhisper baselines.

## Implemented Product Changes

- Added explicit `fast-v1` and `investigation-accuracy-v1` decoding profiles.
- Made the UI, API, Celery, schema, legacy services and clean-install configuration default to accuracy mode.
- Accuracy mode uses deterministic beam 5, `temperature=0.0`, `no_speech_threshold=0.6`, word timestamps and hallucination-silence control. Temperature sampling is excluded from the investigation release path.
- Removed the generic initial prompt; language is already pinned to Vietnamese.
- Added task provenance for provider, model ID, revision, artifact status, device, compute type and effective decode parameters.
- Added non-empty local snapshot validation so migrated placeholders fail closed.
- The manager now loads the exact verified snapshot path instead of resolving the model alias a second time.
- Leading-gap candidates must overlap detected speech for at least 50% of their duration. VAD validation failure withholds the rescue instead of publishing it.
- Added `scripts/benchmark_vietnamese_asr.py`, which records audio/model hashes, runtime/config, latency, coverage, confidence, repetition and optional reference/entity metrics without transcript text by default.

## Promotion Gate

A new default must pass all conditions on a frozen, human-verified Vietnamese investigation corpus:

1. Critical-entity recall improves without material regression for names, amounts, accounts, dates, phone numbers and vehicle plates.
2. Omitted voiced-speech seconds decrease and hallucinated speech in verified silence does not increase.
3. WER/CER improve or remain within the agreed non-inferiority margin across telephone, noise, regional accent and overlap slices.
4. Word timestamp MAE and speaker-attributed WER do not regress beyond the release threshold.
5. RTF and peak VRAM remain inside the RTX 4070 SUPER product budget.
6. Model ID, revision, conversion command, artifact hashes, runtime versions and decode parameters reproduce offline.

## Next Product Slice

1. Freeze representative Vietnamese audio with human references: telephone, noise, regional accents, overlap, names, numbers, amounts, accounts, plates and technical identifiers.
2. Add a conservative voiced-gap detector. Re-decode only uncovered voiced windows without VAD; accept a segment only when confidence, non-hallucination and timeline merge gates pass.
3. Add case-scoped hotwords for investigator-provided names and identifiers. Hints are not facts.
4. Download and pin official `vinai/PhoWhisper-large`, convert it locally to CTranslate2 with a reproducible manifest, and A/B it against the large-v2 primary and large-v3 challenger.
5. Promote only if critical-entity recall and omitted-speech rate improve without increasing unsupported or hallucinated spans.

## Required Metrics

- CER and WER.
- Recall/F1 for people, organizations, locations, dates, times, amounts, accounts, phone numbers and other investigation-critical identifiers.
- Omitted voiced-speech seconds and false speech inserted into silence.
- Hallucinated/repeated span rate.
- Segment and word timestamp MAE.
- RTF, wall time, peak RAM and peak VRAM.
- Speaker-attributed WER after diarization merge.

## Primary Sources

Source check date: 2026-08-11.

- OpenAI Whisper large-v3 model card: https://huggingface.co/openai/whisper-large-v3
- OpenAI Whisper large-v3-turbo model card: https://huggingface.co/openai/whisper-large-v3-turbo
- SYSTRAN faster-whisper runtime and VAD documentation: https://github.com/SYSTRAN/faster-whisper
- VinAI PhoWhisper repository and reported Vietnamese WER table: https://github.com/VinAIResearch/PhoWhisper
- VinAI PhoWhisper-large artifact: https://huggingface.co/vinai/PhoWhisper-large

Retrieved source hashes:

- PhoWhisper README SHA-256: `b0009e276f267bb10dc62f402d92f2f30cb55e45f7ac7106a894696c5ec64b90`.
- faster-whisper README SHA-256: `5ae59e0781834e6887bbd51bda2d8bd5dfe08cd345e0c6f7f3aca455d129cc69`.

## Reproducible Evidence

```powershell
.\venv\Scripts\python.exe scripts\benchmark_vietnamese_asr.py `
  --audio storage\audio\cases\3020\947d315589294014aef808c23942029e.mp3 `
  --models large-v3 large-v2 large-v3-turbo `
  --profile investigation-accuracy-v1 `
  --output docs\reviews\artifacts\2026-08-11-vietnamese-asr-local-ab.json
```

- Primary artifact: `docs/reviews/artifacts/2026-08-11-vietnamese-asr-local-ab.json`, SHA-256 `93ff7ebb318f377ca59773e0e975ce2a67aa8093d0fa2d2dd3bd7a898c337d62`.
- Reverse-order latency check: `docs/reviews/artifacts/2026-08-11-vietnamese-asr-local-ab-reverse.json`, SHA-256 `854dfd9523ac99b2c254206deec7731a54c4bd225f330ddbabde6539f0a1d088`.
- Both artifacts set `transcript_included=false` and `audio_path_included=false`.
- Device-parity artifacts containing raw transcript stay under `output/transcribe/2026-08-11-large-v2-device-parity/` and `output/transcribe/2026-08-11-large-v2-leading-gap-parity/`; they are not copied into review documents.

## Residual Uncertainty

- The live A/B audio has no human reference transcript, so word count, confidence and coverage are diagnostics rather than accuracy metrics.
- PhoWhisper benchmark results do not prove superiority on covert, noisy or investigative recordings.
- The voiced-overlap rescue gate is implemented and live-verified, but a frozen human-reference product corpus and PhoWhisper/Qwen3-ASR challengers are still missing.
