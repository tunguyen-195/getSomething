# GPU Worker Concurrency Fix Review

**Date:** 2026-08-09

## Verdict

PASS for the primary native startup path.

## Confirmed problem

`START_ALL_SERVICES.bat` overrode the Celery application's sequential setting
with `--pool=gevent --concurrency=4`. The same command installed unpinned
`gevent` from the network at every startup.

This allowed up to four ASR, diarization, Summary, or Analysis tasks to compete
for the same GPU. On the current RTX 4070 SUPER 12 GB host, the Celery process
already retains about 7.9 GB of GPU memory; loading the configured 3B LLM raised
total usage to about 10.8 GB. Larger Qwen2.5 14B inference filled nearly all VRAM
and exceeded the 904-second benchmark timeout. GPU contention is therefore a
credible cause of browser/UI stutter and duplicate heavy-task behavior.

## Fix

- The primary startup script now uses Celery `solo` with `concurrency=1`.
- Runtime `pip install gevent` was removed.
- A source-level regression test keeps the startup command aligned with
  `worker_concurrency=1` in `src/worker/worker.py`.

## Verification gate

- Startup-profile tests pass (`2 passed`).
- The staged script contains `--pool=solo --concurrency=1`.
- The staged script contains no `pip install`, `--pool=gevent`, or
  `--concurrency=4`.
- The restarted worker command line contains `--pool=solo --concurrency=1`.
- `celery inspect ping --timeout=10` reports one online node with `pong`.
- UI `http://localhost:3000` returns HTTP 200 and API
  `http://localhost:8000/api/v1/health` reports `ok` after the restart.

## Residual risks

- Other startup scripts still use divergent worker pools and ports; canonical
  bootstrap consolidation remains a separate T0 task.
- Single-task execution protects GPU ownership but reduces parallel throughput.
  Future concurrency must use explicit resource queues/leases, not a shared GPU
  process pool.
- Startup still lacks model-manifest preflight and network-denied bundle checks.
