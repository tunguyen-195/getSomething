# Runbook: pinned local LLM tren Windows

## Muc dich

Run `Qwen3-8B Q4_K_M` bang runtime `llama.cpp` CUDA da duoc pin trong repo,
khong download ngam va khong nap model truc tiep vao Celery worker.

Day la production candidate cho may hien tai: RTX 4070 SUPER 12 GB, mot GPU,
summary/analysis xu ly tuan tu. Ollama van la development fallback cho den khi
benchmark corpus tieng Viet dat promotion gate.

## Artifact da pin

- Runtime: `models/runtimes/llama.cpp/b10331/windows-cuda-12.4-x64`
- Runtime manifest: `config/runtimes/llama.cpp-b10331-windows-cuda-12.4.runtime.json`
- Model: `models/qwen3/Qwen3-8B-Q4_K_M.gguf`
- Model manifest: `config/models/qwen3-8b-q4_k_m.manifest.json`
- API alias: `speechintel-qwen3-8b-q4_k_m`

## 1. Preflight offline

Chay tu repo root:

```powershell
python scripts/verify_llama_runtime.py --probe --json
python scripts/model_store.py preflight --model qwen.qwen3-8b-q4_k_m --json
nvidia-smi --query-gpu=memory.total,memory.used,memory.free --format=csv,noheader,nounits
```

Khong start neu VRAM trong nho hon 6500 MiB. Tren mot GPU, khong chay dong thoi
Whisper/Pyannote va llama-server.

## 2. Start server

```powershell
powershell -ExecutionPolicy Bypass -File scripts/start_llama_server.ps1
```

Script tu dong:

- verify SHA-256 runtime/model;
- bat `HF_HUB_OFFLINE=1` va `TRANSFORMERS_OFFLINE=1`;
- bind duy nhat `127.0.0.1:8088`;
- tat reasoning, gioi han context 8192 va parallel 1;
- bat Flash Attention, KV cache Q8, prefix reuse va metrics;
- cho model sleep sau 2 giay idle de tra VRAM cho audio stage;
- tu choi start khi port dang bi chiem hoac VRAM khong du.

Neu can API key noi bo:

```powershell
$env:LLAMA_SERVER_API_KEY='<local-secret>'
powershell -ExecutionPolicy Bypass -File scripts/start_llama_server.ps1
```

Khong commit key vao `.env` hoac runbook.

## 3. Probe API

```powershell
Invoke-RestMethod http://127.0.0.1:8088/health
Invoke-RestMethod http://127.0.0.1:8088/v1/models
```

Smoke structured output:

```powershell
$body = @{
  model = 'speechintel-qwen3-8b-q4_k_m'
  messages = @(@{ role = 'user'; content = 'Tra ve JSON co truong status bang OK.' })
  temperature = 0
  max_tokens = 32
  reasoning_effort = 'none'
  response_format = @{
    type = 'json_object'
    schema = @{
      type = 'object'
      properties = @{ status = @{ type = 'string' } }
      required = @('status')
    }
  }
} | ConvertTo-Json -Depth 8

Invoke-RestMethod `
  -Uri http://127.0.0.1:8088/v1/chat/completions `
  -Method Post `
  -ContentType application/json `
  -Body $body
```

## 4. Cau hinh ung dung

Backend va Celery doc settings luc khoi dong, vi vay phai restart hai process sau
khi doi provider:

```dotenv
LOCAL_LLM_PROVIDER=llama_cpp_server
LLAMA_SERVER_BASE_URL=http://127.0.0.1:8088
LLAMA_SERVER_MODEL=speechintel-qwen3-8b-q4_k_m
LLAMA_SERVER_MODEL_PATH=models/qwen3/Qwen3-8B-Q4_K_M.gguf
LLAMA_SERVER_API_KEY=
LLAMA_SERVER_SLEEP_IDLE_SECONDS=2
LLAMA_SERVER_SLEEP_WAIT_SECONDS=15
LLM_SEED=42
SUMMARY_SINGLE_PASS_INVESTIGATION=true
```

`SUMMARY_SINGLE_PASS_INVESTIGATION` hien la compatibility setting; production
khong duoc suy ra so lan goi model tu bien nay. Benchmark phai ghi
`llm_call_count` thuc te va xac nhan tokenizer cua writer trung voi GGUF dang
phuc vu.

Voi `include_context=true` va summary type `investigation`, context extraction
tra luon narrative summary; backend tai su dung ket qua nay thay vi gui full
transcript lan thu hai. Neu context schema/grounding fail, task fail closed; backend
khong chuyen sang free-text summary khong co evidence.

Khi `OFFLINE_STRICT=true`, adapter chi chap nhan HTTP loopback, tat environment
proxy, tu choi redirect, bat buoc alias da cau hinh va bind `/props.model_path`
voi file GGUF da verify. Bat ky sai lech nao deu lam provider unavailable.

De quay lai development fallback:

```dotenv
LOCAL_LLM_PROVIDER=ollama
```

## 5. Benchmark promotion gate

Khong promote model chi vi smoke pass. Chay cung corpus, prompt, schema va seed
cho baseline/challenger; ghi TTFT, p50/p95, token/s, peak VRAM/RAM, schema valid,
critical-fact recall, evidence precision va unsupported release.

```powershell
python scripts/benchmark_summary_runtime.py `
  --provider llama_cpp_server `
  --base-url http://127.0.0.1:8088 `
  --models speechintel-qwen3-8b-q4_k_m `
  --warmup 1 `
  --repetitions 3 `
  --load-states warm `
  --output docs/evals/runs/summary-runtime-llama-server.json
```

Cold-load benchmark can lifecycle harness start/stop process cho moi repetition;
khong gan nhan cold cho server resident. Khong dien giai smoke synthetic la chat
luong dieu tra.

## 6. Single-GPU lifecycle

`llama-server` so huu lifecycle cua model. Script bat idle sleep va application
giu GPU lease den khi `/props.is_sleeping=true`. Vi vay:

1. Hoan tat ASR/diarization va unload audio models.
2. Chi start llama-server khi preflight bao du VRAM va khong co audio job.
3. Chay extraction/summary/analysis tuan tu, parallel 1.
4. Sau task, doi server sleep truoc khi giao GPU lai cho audio stage.

Startup process van nam ngoai Python GPU lease, nen live gate phai chung minh
startup, sleep, wake va VRAM release tren may dich. Truoc khi gate nay pass, chi
start server trong cua so LLM co kiem soat; dung bang `Ctrl+C` neu `/props` khong
chuyen sang sleeping dung han.

## 7. Failure handling

- `Insufficient free VRAM`: cho audio job ket thuc; khong bo qua resource check.
- `Port 8088 is already in use`: probe `/health`; khong start process thu hai.
- `MODEL_NOT_INSTALLED` hoac checksum mismatch: dung ngay, khoi phuc artifact tu
  release bundle da ky/hash; khong download tu runtime production.
- JSON invalid: khong fallback sang text tu do; giu task failed va luu metadata.
- Unsupported claim: khong phat hanh nhu fact; chi giu `unverified` kem evidence.
