param(
    [string]$ContainerLlamaServerBaseUrl = $env:CONTAINER_LLAMA_SERVER_BASE_URL,
    [string]$ContainerLlamaServerModelPath = $env:CONTAINER_LLAMA_SERVER_MODEL_PATH,
    [string]$LlamaServerApiKey = $env:LLAMA_SERVER_API_KEY,
    [switch]$ConfigOnly,
    [string]$OutputPath
)

$ErrorActionPreference = 'Stop'
$repoRoot = (Resolve-Path (Join-Path $PSScriptRoot '..')).Path
$checks = New-Object 'System.Collections.Generic.List[object]'

function Add-Check {
    param(
        [string]$Name,
        [bool]$Passed,
        [string]$Expected,
        [string]$Observed,
        [string]$Remediation
    )
    $checks.Add([pscustomobject]@{
        name = $Name
        status = $(if ($Passed) { 'PASS' } else { 'FAIL' })
        expected = $Expected
        observed = $Observed
        remediation = $(if ($Passed) { '' } else { $Remediation })
    }) | Out-Null
}

$uri = $null
try {
    if ($ContainerLlamaServerBaseUrl) {
        $uri = [Uri]$ContainerLlamaServerBaseUrl
    }
}
catch {
    $uri = $null
}
$urlValid = $null -ne $uri -and $uri.Scheme -in @('http', 'https') -and $uri.Host
Add-Check -Name 'compose.llama-url' -Passed $urlValid `
    -Expected 'absolute http(s) URL reachable from containers' `
    -Observed $ContainerLlamaServerBaseUrl `
    -Remediation 'Set CONTAINER_LLAMA_SERVER_BASE_URL to a secured sidecar or external llama-server.'

$normalizedHost = $(if ($urlValid) { $uri.Host.Trim('[', ']').ToLowerInvariant() } else { '' })
$notLoopback = $urlValid -and -not $uri.IsLoopback -and $normalizedHost -ne '0.0.0.0'
Add-Check -Name 'compose.llama-url-not-loopback' -Passed $notLoopback `
    -Expected 'non-loopback container endpoint' `
    -Observed $(if ($urlValid) { $normalizedHost } else { 'invalid' }) `
    -Remediation 'Container loopback cannot reach the native host-only launcher; use a secured external endpoint.'

$apiKeyConfigured = -not [string]::IsNullOrWhiteSpace($LlamaServerApiKey)
Add-Check -Name 'compose.llama-api-key' -Passed $apiKeyConfigured `
    -Expected 'non-empty LLAMA_SERVER_API_KEY' `
    -Observed $(if ($apiKeyConfigured) { 'configured' } else { 'missing' }) `
    -Remediation 'Protect the container-reachable llama-server with an API key and firewall rules.'

$modelPathValid = $ContainerLlamaServerModelPath -match '^/[A-Za-z0-9._/-]+\.gguf$' -and
    $ContainerLlamaServerModelPath -notmatch '(^|/)\.\.(/|$)'
Add-Check -Name 'compose.llama-model-path' -Passed $modelPathValid `
    -Expected 'absolute normalized Linux GGUF path shared by backend, Celery, and sidecar' `
    -Observed $ContainerLlamaServerModelPath `
    -Remediation 'Set CONTAINER_LLAMA_SERVER_MODEL_PATH to the identical read-only model path exposed by the sidecar /props endpoint.'

if ($urlValid -and $notLoopback -and $apiKeyConfigured -and $modelPathValid) {
    $oldUrl = $env:CONTAINER_LLAMA_SERVER_BASE_URL
    $oldModelPath = $env:CONTAINER_LLAMA_SERVER_MODEL_PATH
    $oldKey = $env:LLAMA_SERVER_API_KEY
    try {
        $env:CONTAINER_LLAMA_SERVER_BASE_URL = $ContainerLlamaServerBaseUrl
        $env:CONTAINER_LLAMA_SERVER_MODEL_PATH = $ContainerLlamaServerModelPath
        $env:LLAMA_SERVER_API_KEY = $LlamaServerApiKey
        $rendered = & docker compose config --format json 2>&1 | Out-String
        $composeExit = $LASTEXITCODE
        $payload = $null
        if ($composeExit -eq 0) {
            try { $payload = $rendered | ConvertFrom-Json } catch { $payload = $null }
        }
        $projectionPassed = $null -ne $payload
        foreach ($serviceName in @('backend', 'celery_worker')) {
            if ($null -eq $payload.services.$serviceName) {
                $projectionPassed = $false
                continue
            }
            $serviceEnv = $payload.services.$serviceName.environment
            $projectionPassed = $projectionPassed -and
                $serviceEnv.LOCAL_LLM_PROVIDER -eq 'llama_cpp_server' -and
                $serviceEnv.LLAMA_SERVER_BASE_URL -eq $ContainerLlamaServerBaseUrl -and
                $serviceEnv.LLAMA_SERVER_MODEL_PATH -eq $ContainerLlamaServerModelPath -and
                $serviceEnv.LLAMA_SERVER_API_KEY -eq $LlamaServerApiKey -and
                $serviceEnv.TRANSCRIPTION_ENGINE -ne 'auto'
            foreach ($modelTarget in @('/models', '/app/models')) {
                $modelMount = @($payload.services.$serviceName.volumes | Where-Object {
                    $_.target -eq $modelTarget -and $_.read_only -eq $true
                })
                $projectionPassed = $projectionPassed -and $modelMount.Count -eq 1
            }
        }
        Add-Check -Name 'compose.runtime-projection' -Passed $projectionPassed `
            -Expected 'backend and Celery share canonical llama-server configuration' `
            -Observed $(if ($composeExit -eq 0) { 'compose config rendered' } else { "compose config exit $composeExit" }) `
            -Remediation 'Fix docker-compose.yml runtime projection before starting containers.'
    }
    finally {
        $env:CONTAINER_LLAMA_SERVER_BASE_URL = $oldUrl
        $env:CONTAINER_LLAMA_SERVER_MODEL_PATH = $oldModelPath
        $env:LLAMA_SERVER_API_KEY = $oldKey
    }
}

if (-not $ConfigOnly -and -not ($checks | Where-Object { $_.status -eq 'FAIL' })) {
    $probe = @'
from src.services.summarization.models.llm_manager import get_llm_manager
manager = get_llm_manager()
if not manager.check_availability(force_refresh=True):
    raise SystemExit("application llama-server attestation failed")
print(manager.select_best_model())
'@
    $probeOutput = $probe | docker compose run --rm --no-deps -T backend python - 2>&1 | Out-String
    $probePassed = $LASTEXITCODE -eq 0
    Add-Check -Name 'compose.llama-connectivity' -Passed $probePassed `
        -Expected 'application attests local SHA, remote /props path, context, slots, and model alias' `
        -Observed $probeOutput.Trim() `
        -Remediation 'Start/build the backend image and fix sidecar DNS, firewall, API key, or model alias.'
}

$checkRows = $checks.ToArray()
$failed = @($checkRows | Where-Object { $_.status -eq 'FAIL' })
$report = [ordered]@{
    schema_version = 'stt-compose-runtime-preflight-v1'
    generated_at = [DateTime]::UtcNow.ToString('o')
    mode = $(if ($ConfigOnly) { 'config_only' } else { 'config_and_connectivity' })
    status = $(if ($failed.Count -eq 0) { 'PASS' } else { 'FAIL' })
    checks = $checkRows
}
$json = $report | ConvertTo-Json -Depth 8
if ($OutputPath) {
    $target = $OutputPath
    if (-not [IO.Path]::IsPathRooted($target)) { $target = Join-Path $repoRoot $target }
    $parent = Split-Path -Parent $target
    if ($parent) { New-Item -ItemType Directory -Force -Path $parent | Out-Null }
    [IO.File]::WriteAllText($target, $json + [Environment]::NewLine, [Text.UTF8Encoding]::new($false))
}
Write-Output $json
if ($failed.Count -gt 0) { exit 1 }
exit 0
