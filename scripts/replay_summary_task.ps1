[CmdletBinding()]
param(
    [string]$TaskId = 'd59205bd-7955-4143-a721-3cb40ca4ba7c',
    [string]$BaseUrl = 'http://127.0.0.1:8000',
    [string]$WorkerHost = 'celery@iamasweater',
    [string]$Username = $env:STT_API_USERNAME,
    [string]$Password = $env:STT_API_PASSWORD,
    [int]$PollIntervalSeconds = 5,
    [int]$TimeoutSeconds = 1800,
    [string]$ArtifactDir,
    [string]$VerificationResultPath,
    [switch]$Execute
)

Set-StrictMode -Version Latest
$ErrorActionPreference = 'Stop'

$RepoRoot = [IO.Path]::GetFullPath((Join-Path $PSScriptRoot '..'))
$Python = Join-Path $RepoRoot 'venv\Scripts\python.exe'
$WorkerPattern = '(?i)-m\s+celery\s+-A\s+src\.worker\.worker\s+worker'
$RequiredWorkerArgs = @(
    '--pool=solo',
    '--concurrency=1',
    '--without-heartbeat',
    '--without-gossip',
    '--without-mingle'
)
$CriticalSources = @(
    'src\core\config.py',
    'src\services\summarization\bulletin_writer.py',
    'src\services\summarization\deterministic_analysis.py',
    'src\services\summarization\summary_service_v2.py',
    'src\services\summarization\models\llm_manager.py',
    'src\services\summarization\models\openai_compatible_client.py',
    'src\worker\tasks\summarize_task.py',
    'src\worker\runtime_contract.py'
)

function Get-JsonLine {
    param([object[]]$Lines)

    $jsonLines = @(
        $Lines |
            ForEach-Object { [string]$_ } |
            Where-Object { $_.TrimStart().StartsWith('{') }
    )
    if ($jsonLines.Count -eq 0) {
        throw 'Command did not emit a JSON object.'
    }
    return ($jsonLines[-1] | ConvertFrom-Json)
}

function Invoke-CeleryInspect {
    param([string]$Command)

    $output = @(
        & $Python -m celery -A src.worker.worker inspect $Command `
            --timeout 10 --destination $WorkerHost --json 2>&1
    )
    if ($LASTEXITCODE -ne 0) {
        throw "Celery inspect $Command failed: $($output -join [Environment]::NewLine)"
    }
    $report = Get-JsonLine -Lines $output
    $workerProperty = @(
        $report.PSObject.Properties | Where-Object { $_.Name -eq $WorkerHost }
    )
    if ($workerProperty.Count -ne 1) {
        throw "Expected exactly one response from $WorkerHost."
    }
    return $workerProperty[0].Value
}

function Assert-SingleFreshWorkerTree {
    $workers = @(
        Get-CimInstance Win32_Process |
            Where-Object { $_.CommandLine -match $WorkerPattern }
    )
    if ($workers.Count -eq 0) {
        throw 'No matching Celery worker process exists.'
    }

    $workerIds = @($workers | ForEach-Object { [int]$_.ProcessId })
    $roots = @(
        $workers | Where-Object { $workerIds -notcontains [int]$_.ParentProcessId }
    )
    if ($roots.Count -ne 1) {
        throw "Expected one Celery worker tree; found $($roots.Count) roots."
    }

    foreach ($worker in $workers) {
        foreach ($requiredArg in $RequiredWorkerArgs) {
            if ([string]$worker.CommandLine -notmatch [regex]::Escape($requiredArg)) {
                throw "Worker PID $($worker.ProcessId) is missing $requiredArg."
            }
        }
    }

    $latestSource = @(
        $CriticalSources |
            ForEach-Object { Get-Item (Join-Path $RepoRoot $_) } |
            Sort-Object LastWriteTime -Descending
    )[0]
    if ($roots[0].CreationDate -le $latestSource.LastWriteTime) {
        throw (
            "Worker root PID $($roots[0].ProcessId) predates $($latestSource.FullName) " +
            "($($latestSource.LastWriteTime.ToString('o'))). Restart it first."
        )
    }
}

function Assert-WorkerIdle {
    $ping = Invoke-CeleryInspect -Command 'ping'
    if ($ping.ok -ne 'pong') {
        throw "Unexpected Celery ping response: $($ping | ConvertTo-Json -Compress)"
    }
    foreach ($queueName in @('active', 'reserved', 'scheduled')) {
        $items = @(Invoke-CeleryInspect -Command $queueName)
        if ($items.Count -ne 0) {
            throw "Celery $queueName is not empty."
        }
    }
}

function Assert-WorkerContract {
    $output = @(
        & $Python scripts\probe_celery_worker_contract.py --timeout 30 --json 2>&1
    )
    $report = Get-JsonLine -Lines $output
    if ($LASTEXITCODE -ne 0 -or $report.status -ne 'PASS') {
        throw "Worker runtime contract failed: $($report.errors -join '; ')"
    }
}

function Get-ReplayTerminalDisposition {
    param([object]$Verification)

    if ([string]$Verification.status -ne 'PASS') {
        return [pscustomobject]@{
            exit_code = 2
            stream = 'error'
            message = 'Replay invariants failed.'
        }
    }

    if ([string]$Verification.outcome -eq 'typed_writer_rejection') {
        $generationPath = [string]$Verification.recovery.generation_path
        $message = switch ($generationPath) {
            'all_attempts_rejected' {
                'Worker contract passed, but the writer rejected all three attempts.'
            }
            'bounded_non_delta_rejection' {
                'Worker contract passed, but the investigation report was rejected after the bounded initial and repair attempts.'
            }
            default {
                throw "Verifier returned an unexpected typed rejection path: $generationPath"
            }
        }
        return [pscustomobject]@{
            exit_code = 3
            stream = 'warning'
            message = $message
        }
    }

    if (
        [string]$Verification.outcome -eq 'summarized' -and
        [string]$Verification.report_availability.status -eq 'AVAILABLE'
    ) {
        return [pscustomobject]@{
            exit_code = 0
            stream = 'host'
            message = 'Summary replay verified.'
        }
    }

    return [pscustomobject]@{
        exit_code = 2
        stream = 'error'
        message = 'Verifier returned an unsupported terminal outcome.'
    }
}

function Write-ReplayTerminalDisposition {
    param(
        [object]$Disposition,
        [string]$VerificationPath
    )

    $message = "$($Disposition.message) See $VerificationPath"
    switch ([string]$Disposition.stream) {
        'warning' { Write-Warning $message }
        'error' { [Console]::Error.WriteLine($message) }
        default { Write-Host $message }
    }
}

if (-not (Test-Path -LiteralPath $Python)) {
    throw "Repository Python was not found at $Python"
}
if ($PollIntervalSeconds -le 0 -or $TimeoutSeconds -le 0) {
    throw 'PollIntervalSeconds and TimeoutSeconds must be positive.'
}

if (-not [string]::IsNullOrWhiteSpace($VerificationResultPath)) {
    $VerificationResultPath = [IO.Path]::GetFullPath($VerificationResultPath)
    if (-not (Test-Path -LiteralPath $VerificationResultPath)) {
        throw "Verification result was not found: $VerificationResultPath"
    }
    $offlineVerification = Get-Content -Raw -LiteralPath $VerificationResultPath |
        ConvertFrom-Json
    $offlineDisposition = Get-ReplayTerminalDisposition `
        -Verification $offlineVerification
    Write-ReplayTerminalDisposition `
        -Disposition $offlineDisposition `
        -VerificationPath $VerificationResultPath
    exit [int]$offlineDisposition.exit_code
}

if (-not $Execute) {
    [pscustomobject]@{
        mode = 'DRY_RUN'
        task_id = $TaskId
        base_url = $BaseUrl
        worker = $WorkerHost
        next_command = (
            "powershell -ExecutionPolicy Bypass -File scripts/replay_summary_task.ps1 " +
            "-TaskId $TaskId -Execute"
        )
    } | ConvertTo-Json
    exit 0
}

if ([string]::IsNullOrWhiteSpace($Username) -or [string]::IsNullOrWhiteSpace($Password)) {
    throw 'Set STT_API_USERNAME and STT_API_PASSWORD without placing secrets in command arguments.'
}

$stamp = Get-Date -Format 'yyyyMMdd-HHmmss'
if ([string]::IsNullOrWhiteSpace($ArtifactDir)) {
    $ArtifactDir = Join-Path $RepoRoot "output\summary-replay\$TaskId-$stamp"
}
$ArtifactDir = [IO.Path]::GetFullPath($ArtifactDir)
$BaselinePath = Join-Path $ArtifactDir 'baseline.json'
$VerificationPath = Join-Path $ArtifactDir 'verification.json'
$EnqueuePath = Join-Path $ArtifactDir 'enqueue.json'

Push-Location $RepoRoot
try {
    New-Item -ItemType Directory -Path $ArtifactDir -Force | Out-Null
    $health = Invoke-RestMethod -Method Get -Uri "$BaseUrl/api/v1/health" -TimeoutSec 10
    if ($health.status -ne 'ok') {
        throw 'Backend health gate failed.'
    }

    Assert-SingleFreshWorkerTree
    Assert-WorkerIdle
    Assert-WorkerContract
    Assert-WorkerIdle

    & $Python scripts\assert_summary_replay.py capture `
        --task-id $TaskId --output $BaselinePath | Out-Null
    if ($LASTEXITCODE -ne 0) {
        throw 'Failed to capture the database baseline.'
    }

    $webSession = New-Object Microsoft.PowerShell.Commands.WebRequestSession
    $csrf = Invoke-RestMethod -Method Get `
        -Uri "$BaseUrl/api/v1/auth/csrf" `
        -WebSession $webSession `
        -TimeoutSec 10
    $csrfToken = [string]$csrf.csrf_token
    if ([string]::IsNullOrWhiteSpace($csrfToken)) {
        throw 'CSRF endpoint did not return a token.'
    }
    $csrfHeaders = @{ 'x-csrf-token' = $csrfToken }
    $loginBody = @{
        username = $Username
        password = $Password
    } | ConvertTo-Json -Compress
    $null = Invoke-RestMethod -Method Post `
        -Uri "$BaseUrl/api/v1/auth/login" `
        -WebSession $webSession `
        -Headers $csrfHeaders `
        -ContentType 'application/json' `
        -Body $loginBody `
        -TimeoutSec 15
    $null = Invoke-RestMethod -Method Get `
        -Uri "$BaseUrl/api/v1/auth/me" `
        -WebSession $webSession `
        -TimeoutSec 10

    $payload = @{
        model_name = $null
        summary_type = 'investigation'
        include_context = $true
        async_mode = $true
        min_length = 120
        max_length = 400
        investigation_scenario = 'auto'
    } | ConvertTo-Json -Compress

    $enqueue = Invoke-RestMethod -Method Post `
        -Uri "$BaseUrl/api/v1/audio/v2/summarize/$TaskId" `
        -WebSession $webSession `
        -Headers $csrfHeaders `
        -ContentType 'application/json' `
        -Body $payload `
        -TimeoutSec 30
    $enqueue | ConvertTo-Json -Depth 10 | Set-Content -LiteralPath $EnqueuePath -Encoding utf8

    $deadline = (Get-Date).AddSeconds($TimeoutSeconds)
    $terminalStatus = $null
    while ((Get-Date) -lt $deadline) {
        $status = Invoke-RestMethod -Method Get `
            -Uri "$BaseUrl/api/v1/audio/v2/tasks/$TaskId/status?include_result=true" `
            -WebSession $webSession `
            -TimeoutSec 30
        Write-Host "[$(Get-Date -Format o)] task=$TaskId status=$($status.status)"
        if ($status.status -in @('summarized', 'failed')) {
            $terminalStatus = [string]$status.status
            break
        }
        Start-Sleep -Seconds $PollIntervalSeconds
    }
    if ($null -eq $terminalStatus) {
        throw "Summary replay did not reach a terminal state within $TimeoutSeconds seconds."
    }

    & $Python scripts\assert_summary_replay.py verify `
        --task-id $TaskId --baseline $BaselinePath --output $VerificationPath | Out-Null
    $verificationExit = $LASTEXITCODE
    if ($verificationExit -notin @(0, 2)) {
        throw "Replay verifier failed to execute. Inspect $VerificationPath"
    }
    $verification = Get-Content -Raw -LiteralPath $VerificationPath | ConvertFrom-Json
    $disposition = Get-ReplayTerminalDisposition -Verification $verification
    if ($verificationExit -eq 2 -and [int]$disposition.exit_code -ne 2) {
        throw 'Replay verifier exit code disagrees with its verification artifact.'
    }
    Write-ReplayTerminalDisposition `
        -Disposition $disposition `
        -VerificationPath $VerificationPath
    exit [int]$disposition.exit_code
}
finally {
    Pop-Location
}
