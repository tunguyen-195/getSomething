# Safe Celery Summary Restart And Replay

This runbook restarts only the solo summary worker and replays one stored task.
It does not reset the task row, transcript, segments, context, or visualization.

## Safety gates

- Run from `E:\research\STT`.
- Require exactly one Celery worker tree using `--pool=solo --concurrency=1`.
- Require `active`, `reserved`, and `scheduled` to be empty before shutdown.
- Require the runtime-contract probe to return `PASS` after restart.
- Replay through the authenticated API with cookie-bound double-submit CSRF.
- Compare canonical transcript and segment hashes before and after replay.

## 1. Capture and drain the exact worker

```powershell
cd E:\research\STT

$WorkerPattern = '(?i)-m\s+celery\s+-A\s+src\.worker\.worker\s+worker'
$WorkerTree = @(
  Get-CimInstance Win32_Process |
    Where-Object { $_.CommandLine -match $WorkerPattern }
)
$WorkerTree | Select-Object ProcessId, ParentProcessId, CreationDate, ExecutablePath, CommandLine

.\venv\Scripts\python.exe -m celery -A src.worker.worker inspect ping --timeout 10 --destination celery@iamasweater --json
.\venv\Scripts\python.exe -m celery -A src.worker.worker inspect active --timeout 10 --destination celery@iamasweater --json
.\venv\Scripts\python.exe -m celery -A src.worker.worker inspect reserved --timeout 10 --destination celery@iamasweater --json
.\venv\Scripts\python.exe -m celery -A src.worker.worker inspect scheduled --timeout 10 --destination celery@iamasweater --json
```

Do not continue unless ping is `pong` and all three queue responses are `[]`.

## 2. Graceful targeted shutdown

```powershell
.\venv\Scripts\python.exe -m celery -A src.worker.worker control shutdown --timeout 10 --destination celery@iamasweater --json

$WorkerTree | ForEach-Object {
  Get-Process -Id $_.ProcessId -ErrorAction SilentlyContinue
}
```

If the two captured processes do not exit, recapture their command lines and
parent relationship. Only after they still match the exact worker command may
the child be stopped before the wrapper. Never match and stop all Python
processes.

## 3. Start the required solo worker

```powershell
$Repo = 'E:\research\STT'
$Stamp = Get-Date -Format 'yyyyMMdd-HHmmss'
$WorkerArgs = @(
  '-m', 'celery',
  '-A', 'src.worker.worker',
  'worker',
  '--pool=solo',
  '--concurrency=1',
  '--loglevel=info',
  '--logfile=logs/celery-s2.log',
  '--without-heartbeat',
  '--without-gossip',
  '--without-mingle'
)

$Worker = Start-Process `
  -FilePath "$Repo\venv\Scripts\python.exe" `
  -ArgumentList $WorkerArgs `
  -WorkingDirectory $Repo `
  -WindowStyle Hidden `
  -RedirectStandardOutput "$Repo\logs\celery-s2-$Stamp.stdout.log" `
  -RedirectStandardError "$Repo\logs\celery-s2-$Stamp.stderr.log" `
  -PassThru

$Worker | Select-Object Id, StartTime
```

## 4. Post-start contract gates

```powershell
.\venv\Scripts\python.exe -m celery -A src.worker.worker inspect ping --timeout 10 --destination celery@iamasweater --json
.\venv\Scripts\python.exe scripts\probe_celery_worker_contract.py --timeout 30 --json
```

The probe must exit `0` and report `"status":"PASS"`. The replay harness also
checks that the single worker tree is newer than the critical summary sources.

## 5. Authenticated replay

Enter credentials without placing the password in shell history:

```powershell
$env:STT_API_USERNAME = Read-Host 'STT username'
$SecurePassword = Read-Host 'STT password' -AsSecureString
$Credential = [pscredential]::new($env:STT_API_USERNAME, $SecurePassword)
$env:STT_API_PASSWORD = $Credential.GetNetworkCredential().Password

powershell -ExecutionPolicy Bypass -File scripts\replay_summary_task.ps1 `
  -TaskId d59205bd-7955-4143-a721-3cb40ca4ba7c `
  -Execute

Remove-Item Env:STT_API_PASSWORD -ErrorAction SilentlyContinue
```

Without `-Execute`, the script is a no-contact dry run. With `-Execute`, it
checks health, worker topology, empty queues, runtime fingerprint, database
baseline, login/CSRF, enqueue, polling, and terminal database invariants.

## Raw API sequence

Use this only when inspecting the HTTP flow directly. The same
`WebRequestSession` and CSRF header are required for login and summarize.

```powershell
$BaseUrl = 'http://127.0.0.1:8000'
$TaskId = 'd59205bd-7955-4143-a721-3cb40ca4ba7c'
$Session = New-Object Microsoft.PowerShell.Commands.WebRequestSession
$Csrf = Invoke-RestMethod -Method Get -Uri "$BaseUrl/api/v1/auth/csrf" -WebSession $Session
$Headers = @{ 'x-csrf-token' = [string]$Csrf.csrf_token }
$Login = @{
  username = $env:STT_API_USERNAME
  password = $env:STT_API_PASSWORD
} | ConvertTo-Json -Compress
Invoke-RestMethod -Method Post -Uri "$BaseUrl/api/v1/auth/login" -WebSession $Session -Headers $Headers -ContentType 'application/json' -Body $Login

$Payload = @{
  model_name = $null
  summary_type = 'investigation'
  include_context = $true
  async_mode = $true
  min_length = 120
  max_length = 400
  length_mode = 'auto'
  investigation_scenario = 'auto'
} | ConvertTo-Json -Compress
Invoke-RestMethod -Method Post -Uri "$BaseUrl/api/v1/audio/v2/summarize/$TaskId" -WebSession $Session -Headers $Headers -ContentType 'application/json' -Body $Payload
Invoke-RestMethod -Method Get -Uri "$BaseUrl/api/v1/audio/v2/tasks/$TaskId/status?include_result=true" -WebSession $Session
```

## Read-only database assertions

```powershell
$ArtifactDir = 'output\summary-replay\manual-check'
New-Item -ItemType Directory -Path $ArtifactDir -Force | Out-Null
.\venv\Scripts\python.exe scripts\assert_summary_replay.py capture --task-id d59205bd-7955-4143-a721-3cb40ca4ba7c --output "$ArtifactDir\baseline.json"

# Run only after the replay reaches summarized or failed.
.\venv\Scripts\python.exe scripts\assert_summary_replay.py verify --task-id d59205bd-7955-4143-a721-3cb40ca4ba7c --baseline "$ArtifactDir\baseline.json" --output "$ArtifactDir\verification.json"
```

The verifier accepts only the current product contract: a non-empty
`summary_state=generated` result from `single_prompt_llm`, exactly one LLM call,
the prompt version exported by the Summary service, and an adaptive
`length_mode=auto` contract whose source word count, proportional ratio,
preferred length, and actual length match the persisted result. The adaptive
maximum must not be enforced. Transcript, segment, and persisted Analysis hashes
must remain unchanged across Summary generation. The context budget must prove
that the full transcript appears in exactly one framed source block and that
prompt, completion, and safety reserve fit the attested model context window.

Writer repair, semantic-gate rejection, multi-call recovery, a hard word cap,
or any source/Analysis mutation fails verification. `replay_summary_task.ps1`
exits `0` only for the available one-call result, `2` for verifier invariant
failures, and `1` for harness/tool errors.

If the complete transcript cannot fit, Summary returns
`SUMMARY_CONTEXT_WINDOW_EXCEEDED` before any LLM call. The product does not
truncate the source or silently switch to a multi-call writer path.

Exit `0` proves one-call availability and persistence only. Until the shared
report-quality validator runs, `report_quality=NOT_EVALUATED` and
`product_status=BLOCKED`; the replay harness does not claim product quality.

## Residual risks

- A task can be enqueued by another client between the last idle check and replay.
- Duplicate workers sharing one hostname can confuse Celery inspect; process-tree validation is an independent gate.
- Login or process rate limits can return `429`; do not loop login attempts.
- The worker contract can pass while GPU quarantine or llama-server sleep verification fails later.
- A provider failure remains possible; it is a product failure and is never
  counted as a successful replay.
- If graceful shutdown times out, force-stop only the revalidated captured worker PIDs.
