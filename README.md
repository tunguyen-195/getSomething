# Speech To Information

Ung dung FastAPI + React de upload audio, chuyen giong noi thanh van ban, tom tat
va phan tich du lieu dieu tra bang local AI.

## Clean-clone development/staging

Runbook canonical tren Windows:

- [docs/NEW_MACHINE_SETUP.md](docs/NEW_MACHINE_SETUP.md)

Duong chay da duoc pin gom Python 3.11, `npm ci`, PostgreSQL, Redis/Memurai,
FFmpeg, Qwen3-8B Q4_K_M va llama.cpp `b10331`. Model/runtime khong nam trong Git;
operator phai chay installer ro rang:

```powershell
powershell -ExecutionPolicy Bypass -File scripts\install_local_llm_staging.ps1 `
  -HardwareProfile gpu12gb

powershell -ExecutionPolicy Bypass -File scripts\preflight_new_machine.ps1 `
  -HardwareProfile gpu12gb
```

ASR large-v2 tai cong khai bang installer. Pyannote la artifact gated, nen may
moi uu tien restore private bundle nho theo runbook; chi tai pyannote bang
`HF_TOKEN` neu khong co bundle:

```powershell
venv\Scripts\python.exe scripts\install_audio_models_staging.py `
  --include large-v2

powershell -ExecutionPolicy Bypass -File scripts\restore_gated_pyannote.ps1 `
  -BundleDirectory D:\STT-gated-models
```

CPU functional fallback dung `-HardwareProfile cpu`. Thu tu start bat buoc la:
PostgreSQL + Redis, llama-server, backend, Celery solo worker, frontend.

May dich i9-12900K / 32 GB / RTX 3060 12 GB / Windows 11 Pro 25H2 dung profile
`gpu12gb`. Truoc khi cai, cap nhat NVIDIA driver va de it nhat 7000 MiB VRAM
trong; runbook co lenh `nvidia-smi` va probe CUDA bat buoc de phat hien driver
khong tuong thich.

`START_ALL_SERVICES.bat` khong phai pinned-LLM staging launcher vi hien khong
start llama-server. Docker Compose cung khong thay the artifact acquisition va
LLM preflight trong runbook tren.

## Production status

Production offline/clone-only bundle van **BLOCKED**. `models/` va `venv/` bi
ignore, bundle con thieu cac runtime/cache/artifact bat buoc, va verifier hien
phai tra `release_ready=false`. Khong dung staging installer nhu production
startup hook va khong cho app runtime tu download model.

Chi tiet release boundary:

- [docs/runbooks/portable-local-llm-deployment.md](docs/runbooks/portable-local-llm-deployment.md)
- [docs/runbooks/offline-release-bundle.md](docs/runbooks/offline-release-bundle.md)
