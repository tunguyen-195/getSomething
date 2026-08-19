param(
    [int]$Port = 8088,
    [int]$ContextSize = 0,
    [int]$GpuLayers = 99,
    [int]$MinimumFreeVramMiB = 0,
    [int]$SleepIdleSeconds = 2,
    [string]$ModelAlias = 'speechintel-qwen3-8b-q4_k_m',
    [string]$ApiKey = $env:LLAMA_SERVER_API_KEY,
    [switch]$SkipResourceCheck
)

$ErrorActionPreference = 'Stop'
$repoRoot = (Resolve-Path (Join-Path $PSScriptRoot '..')).Path
$python = Join-Path $repoRoot 'venv\Scripts\python.exe'
$runtimeRoot = Join-Path $repoRoot 'models\runtimes\llama.cpp\b10331\windows-cuda-12.4-x64'
$server = Join-Path $runtimeRoot 'bin\llama-server.exe'
$model = Join-Path $repoRoot 'models\qwen3\Qwen3-8B-Q4_K_M.gguf'
$envFile = Join-Path $repoRoot '.env'

function Get-CanonicalPositiveIntSetting {
    param(
        [Parameter(Mandatory = $true)][string]$Name,
        [Parameter(Mandatory = $true)][int]$DefaultValue
    )

    $rawValue = [Environment]::GetEnvironmentVariable($Name)
    if ([string]::IsNullOrWhiteSpace($rawValue) -and (Test-Path -LiteralPath $envFile -PathType Leaf)) {
        $pattern = '^\s*' + [regex]::Escape($Name) + '\s*='
        $line = Get-Content -LiteralPath $envFile -Encoding UTF8 |
            Where-Object { $_ -match $pattern } |
            Select-Object -Last 1
        if ($line) {
            $rawValue = ($line -split '=', 2)[1].Trim()
        }
    }
    if ([string]::IsNullOrWhiteSpace($rawValue)) {
        return $DefaultValue
    }

    $parsedValue = 0
    if (-not [int]::TryParse($rawValue.Trim(), [ref]$parsedValue) -or $parsedValue -lt 1) {
        throw "$Name must be a positive integer."
    }
    return $parsedValue
}

$canonicalContextSize = Get-CanonicalPositiveIntSetting `
    -Name 'LLAMA_SERVER_CONTEXT_SIZE' `
    -DefaultValue 12288
if ($ContextSize -le 0) {
    $ContextSize = $canonicalContextSize
}
elseif ($ContextSize -ne $canonicalContextSize) {
    throw "ContextSize must match canonical LLAMA_SERVER_CONTEXT_SIZE=$canonicalContextSize."
}
$canonicalMinimumFreeVramMiB = Get-CanonicalPositiveIntSetting `
    -Name 'LLAMA_SERVER_MINIMUM_FREE_VRAM_MIB' `
    -DefaultValue 7000
if ($MinimumFreeVramMiB -le 0) {
    $MinimumFreeVramMiB = $canonicalMinimumFreeVramMiB
}
elseif ($MinimumFreeVramMiB -ne $canonicalMinimumFreeVramMiB) {
    throw "MinimumFreeVramMiB must match canonical LLAMA_SERVER_MINIMUM_FREE_VRAM_MIB=$canonicalMinimumFreeVramMiB."
}

if (-not (Test-Path -LiteralPath $python -PathType Leaf)) {
    throw "Python environment not found: $python"
}

if (Get-NetTCPConnection -LocalPort $Port -State Listen -ErrorAction SilentlyContinue) {
    throw "Port $Port is already in use. Refusing to start a second llama-server."
}
if ($SleepIdleSeconds -lt 1) {
    throw 'SleepIdleSeconds must be at least 1 so the single GPU can return to audio stages.'
}

& $python (Join-Path $repoRoot 'scripts\verify_llama_runtime.py') --probe
if ($LASTEXITCODE -ne 0) {
    throw 'Pinned llama.cpp runtime verification failed.'
}

& $python (Join-Path $repoRoot 'scripts\model_store.py') preflight --model qwen.qwen3-8b-q4_k_m
if ($LASTEXITCODE -ne 0) {
    throw 'Pinned Qwen3 model verification failed.'
}

if (-not $SkipResourceCheck) {
    $freeVram = [int](& nvidia-smi --query-gpu=memory.free --format=csv,noheader,nounits | Select-Object -First 1)
    if ($freeVram -lt $MinimumFreeVramMiB) {
        throw "Insufficient free VRAM: ${freeVram} MiB available, ${MinimumFreeVramMiB} MiB required."
    }
}

$env:HF_HUB_OFFLINE = '1'
$env:TRANSFORMERS_OFFLINE = '1'

$serverArgs = @(
    '--model', $model,
    '--alias', $ModelAlias,
    '--host', '127.0.0.1',
    '--port', $Port,
    '--ctx-size', $ContextSize,
    '--n-gpu-layers', $GpuLayers,
    '--parallel', '1',
    '--flash-attn', 'on',
    '--cache-type-k', 'q8_0',
    '--cache-type-v', 'q8_0',
    '--reasoning', 'off',
    '--jinja',
    '--cache-reuse', '256',
    '--offline',
    '--no-webui',
    '--metrics',
    '--slots',
    '--sleep-idle-seconds', $SleepIdleSeconds
)

Write-Host "Starting pinned llama-server on http://127.0.0.1:$Port"
Write-Host "Model alias: $ModelAlias"
Write-Host "Context size: $ContextSize tokens"
$previousLlamaApiKey = $env:LLAMA_API_KEY
try {
    if ($ApiKey) {
        # Keep the secret out of the process command line.
        $env:LLAMA_API_KEY = $ApiKey
    }
    & $server @serverArgs
    $serverExitCode = $LASTEXITCODE
}
finally {
    $env:LLAMA_API_KEY = $previousLlamaApiKey
}
exit $serverExitCode
