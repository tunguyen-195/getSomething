param(
    [ValidateSet('gpu12gb', 'cpu')]
    [string]$HardwareProfile = 'gpu12gb',
    [string]$EnvFile = '.env',
    [string]$OutputPath
)

$ErrorActionPreference = 'Stop'
$repoRoot = (Resolve-Path (Join-Path $PSScriptRoot '..')).Path
$checks = New-Object 'System.Collections.Generic.List[object]'

function Add-Check {
    param(
        [Parameter(Mandatory = $true)][string]$Name,
        [Parameter(Mandatory = $true)][bool]$Passed,
        [Parameter(Mandatory = $true)][string]$Expected,
        [string]$Observed = '',
        [bool]$Required = $true,
        [string]$Remediation = ''
    )

    $checks.Add([pscustomobject]@{
        name = $Name
        status = $(if ($Passed) { 'PASS' } else { 'FAIL' })
        required = $Required
        expected = $Expected
        observed = $Observed
        remediation = $(if ($Passed) { '' } else { $Remediation })
    }) | Out-Null
}

function Test-TcpPort {
    param([string]$HostName, [int]$Port, [int]$TimeoutMilliseconds = 1200)

    $client = New-Object System.Net.Sockets.TcpClient
    try {
        $pending = $client.BeginConnect($HostName, $Port, $null, $null)
        if (-not $pending.AsyncWaitHandle.WaitOne($TimeoutMilliseconds, $false)) {
            return $false
        }
        $client.EndConnect($pending)
        return $client.Connected
    }
    catch {
        return $false
    }
    finally {
        $client.Dispose()
    }
}

function Read-DotEnv {
    param([string]$Path)

    $values = @{}
    foreach ($line in Get-Content -LiteralPath $Path -Encoding UTF8) {
        $trimmed = $line.Trim()
        if (-not $trimmed -or $trimmed.StartsWith('#') -or -not $trimmed.Contains('=')) {
            continue
        }
        $parts = $trimmed.Split('=', 2)
        $key = $parts[0].Trim()
        $value = $parts[1].Trim()
        if (($value.StartsWith('"') -and $value.EndsWith('"')) -or
            ($value.StartsWith("'") -and $value.EndsWith("'"))) {
            $value = $value.Substring(1, $value.Length - 2)
        }
        $values[$key] = $value
    }
    return $values
}

function Get-NormalizedPackageName {
    param([string]$Name)

    return ($Name.ToLowerInvariant() -replace '[_.]+', '-')
}

function Read-ExactDependencyManifest {
    param(
        [string]$Path,
        [string]$ExpectedConstraint = ''
    )

    $pins = @{}
    $issues = New-Object 'System.Collections.Generic.List[string]'
    $activeLines = New-Object 'System.Collections.Generic.List[string]'
    if (-not (Test-Path -LiteralPath $Path -PathType Leaf)) {
        $issues.Add("missing-manifest:$Path") | Out-Null
        return [pscustomobject]@{
            active_lines = $activeLines.ToArray()
            pins = $pins
            issues = $issues.ToArray()
        }
    }
    foreach ($rawLine in Get-Content -LiteralPath $Path -Encoding UTF8) {
        $line = $rawLine.Trim()
        if (-not $line -or $line.StartsWith('#')) {
            continue
        }
        $activeLines.Add($line) | Out-Null
        if ($line.StartsWith('-c ')) {
            if (-not $ExpectedConstraint -or $line -ne "-c $ExpectedConstraint") {
                $issues.Add("unexpected-directive:$line") | Out-Null
            }
            continue
        }
        if ($line -notmatch '^(?<name>[A-Za-z0-9_.-]+)(?:\[[^\]]+\])?==(?<version>[^;\s]+)$') {
            $issues.Add("not-exact:$line") | Out-Null
            continue
        }
        $name = Get-NormalizedPackageName -Name $Matches.name
        if ($pins.ContainsKey($name)) {
            $issues.Add("duplicate:$name") | Out-Null
            continue
        }
        $pins[$name] = [string]$Matches.version
    }

    return [pscustomobject]@{
        active_lines = $activeLines.ToArray()
        pins = $pins
        issues = $issues.ToArray()
    }
}

function Invoke-JsonVerifier {
    param([string[]]$Arguments)

    $raw = (& $Arguments[0] $Arguments[1..($Arguments.Count - 1)] 2>&1 | Out-String).Trim()
    $exitCode = $LASTEXITCODE
    try {
        $payload = $raw | ConvertFrom-Json
    }
    catch {
        $payload = $null
    }
    return [pscustomobject]@{
        exit_code = $exitCode
        raw = $raw
        payload = $payload
    }
}

function Invoke-SecurityConfigValidation {
    param(
        [string]$PythonPath,
        [hashtable]$EnvironmentValues
    )

    $previousValues = @{}
    try {
        foreach ($entry in $EnvironmentValues.GetEnumerator()) {
            $key = [string]$entry.Key
            if ($key -notmatch '^[A-Za-z_][A-Za-z0-9_]*$') {
                continue
            }
            $previousValues[$key] = [Environment]::GetEnvironmentVariable(
                $key,
                [EnvironmentVariableTarget]::Process
            )
            [Environment]::SetEnvironmentVariable(
                $key,
                [string]$entry.Value,
                [EnvironmentVariableTarget]::Process
            )
        }

        Push-Location $repoRoot
        try {
            $validationCode = @'
from src.core.config import validate_security_settings

validate_security_settings()
print("security_config_valid")
'@
            $raw = (& $PythonPath -c $validationCode 2>&1 | Out-String).Trim()
            $exitCode = $LASTEXITCODE
        }
        finally {
            Pop-Location
        }
    }
    finally {
        foreach ($entry in $previousValues.GetEnumerator()) {
            [Environment]::SetEnvironmentVariable(
                [string]$entry.Key,
                $entry.Value,
                [EnvironmentVariableTarget]::Process
            )
        }
    }

    return [pscustomobject]@{
        exit_code = $exitCode
        output = $raw
    }
}

$requirementsPath = Join-Path $repoRoot 'requirements.txt'
$constraintsName = 'requirements-constraints-py311.txt'
$constraintsPath = Join-Path $repoRoot $constraintsName
$requirementsManifest = Read-ExactDependencyManifest `
    -Path $requirementsPath `
    -ExpectedConstraint $constraintsName
$constraintsManifest = Read-ExactDependencyManifest -Path $constraintsPath

$requiredRuntimePins = [ordered]@{
    'llama-cpp-python' = '0.3.16'
    'huggingface-hub' = '0.36.0'
    'pyannote-audio' = '3.1.1'
    'faster-whisper' = '1.2.1'
    'ctranslate2' = '4.6.0'
    'celery' = '5.3.4'
    'redis' = '5.0.1'
}
$requirementsIssues = New-Object 'System.Collections.Generic.List[string]'
foreach ($issue in $requirementsManifest.issues) {
    $requirementsIssues.Add([string]$issue) | Out-Null
}
if ($requirementsManifest.active_lines.Count -eq 0 -or
    $requirementsManifest.active_lines[0] -ne "-c $constraintsName") {
    $requirementsIssues.Add('constraints-directive-not-first') | Out-Null
}
foreach ($entry in $requiredRuntimePins.GetEnumerator()) {
    if (-not $requirementsManifest.pins.ContainsKey($entry.Key) -or
        [string]$requirementsManifest.pins[$entry.Key] -ne $entry.Value) {
        $requirementsIssues.Add("pin:$($entry.Key)==$($entry.Value)") | Out-Null
    }
}
if ($requirementsManifest.pins.ContainsKey('diart')) {
    $requirementsIssues.Add('noncanonical-runtime:diart') | Out-Null
}
Add-Check -Name 'dependency.requirements-manifest' `
    -Passed ($requirementsIssues.Count -eq 0) `
    -Expected 'requirements.txt uses the Python 3.11 constraints file and exact canonical runtime pins without diart' `
    -Observed $(if ($requirementsIssues.Count -eq 0) {
        "$($requirementsManifest.pins.Count) exact direct pins"
    } else { $requirementsIssues -join ';' }) `
    -Remediation 'Restore the canonical requirements.txt dependency lock.'

$requiredConstraintPins = [ordered]@{
    'av' = '14.2.0'
    'pyannote-core' = '5.0.0'
    'pyannote-database' = '5.1.3'
    'pyannote-metrics' = '3.2.1'
    'pyannote-pipeline' = '3.0.1'
}
$constraintIssues = New-Object 'System.Collections.Generic.List[string]'
foreach ($issue in $constraintsManifest.issues) {
    $constraintIssues.Add([string]$issue) | Out-Null
}
foreach ($entry in $requiredConstraintPins.GetEnumerator()) {
    if (-not $constraintsManifest.pins.ContainsKey($entry.Key) -or
        [string]$constraintsManifest.pins[$entry.Key] -ne $entry.Value) {
        $constraintIssues.Add("pin:$($entry.Key)==$($entry.Value)") | Out-Null
    }
}
foreach ($torchPackage in @('torch', 'torchvision', 'torchaudio')) {
    if ($constraintsManifest.pins.ContainsKey($torchPackage)) {
        $constraintIssues.Add("torch-profile-leak:$torchPackage") | Out-Null
    }
}
Add-Check -Name 'dependency.constraints-manifest' `
    -Passed ($constraintIssues.Count -eq 0) `
    -Expected 'all Python 3.11 constraints are exact and preserve the tested pyannote 3.1 closure without torch profile pins' `
    -Observed $(if ($constraintIssues.Count -eq 0) {
        "$($constraintsManifest.pins.Count) exact transitive pins"
    } else { $constraintIssues -join ';' }) `
    -Remediation 'Restore requirements-constraints-py311.txt from the resolver-tested lock.'

$python = Join-Path $repoRoot 'venv\Scripts\python.exe'
$pythonExists = Test-Path -LiteralPath $python -PathType Leaf
Add-Check -Name 'python.venv' -Passed $pythonExists `
    -Expected 'venv\Scripts\python.exe exists' -Observed $python `
    -Remediation 'Create the venv with Python 3.11 and install the pinned dependencies.'

if ($pythonExists) {
    $pythonVersion = (& $python -c 'import platform; print(platform.python_version())').Trim()
    Add-Check -Name 'python.version' -Passed ($pythonVersion -match '^3\.11\.') `
        -Expected 'Python 3.11.x' -Observed $pythonVersion `
        -Remediation 'Recreate venv with a 64-bit Python 3.11 interpreter.'

    $packageRaw = (& $python -m pip --disable-pip-version-check list --format json 2>&1 | Out-String).Trim()
    try {
        $packageRows = ConvertFrom-Json -InputObject $packageRaw
        $packageVersions = @{}
        foreach ($row in $packageRows) {
            $packageKey = Get-NormalizedPackageName -Name ([string]$row.name)
            $packageVersions[$packageKey] = [string]$row.version
        }
    }
    catch {
        $packageVersions = $null
    }

    $torchSuffix = $(if ($HardwareProfile -eq 'gpu12gb') { '+cu121' } else { '+cpu' })
    $expectedPackages = [ordered]@{
        'torch' = "2.1.1$torchSuffix"
        'torchvision' = "0.16.1$torchSuffix"
        'torchaudio' = "2.1.1$torchSuffix"
        'llama-cpp-python' = '0.3.16'
        'huggingface-hub' = '0.36.0'
        'pyannote-audio' = '3.1.1'
        'faster-whisper' = '1.2.1'
        'ctranslate2' = '4.6.0'
        'celery' = '5.3.4'
        'redis' = '5.0.1'
    }
    foreach ($entry in $expectedPackages.GetEnumerator()) {
        $actual = $null
        if ($null -ne $packageVersions) {
            if ($packageVersions.ContainsKey($entry.Key)) {
                $actual = [string]$packageVersions[$entry.Key]
            }
        }
        Add-Check -Name "python.package.$($entry.Key)" -Passed ($actual -eq $entry.Value) `
            -Expected $entry.Value -Observed $actual `
            -Remediation 'Re-run the exact package installation commands in docs/NEW_MACHINE_SETUP.md.'
    }

    $pipCheckRaw = (& $python -m pip --disable-pip-version-check check 2>&1 | Out-String).Trim()
    $pipCheckExitCode = $LASTEXITCODE
    Add-Check -Name 'dependency.pip-check' -Passed ($pipCheckExitCode -eq 0) `
        -Expected 'pip check reports no broken or conflicting dependencies' `
        -Observed $(if ($pipCheckExitCode -eq 0) { 'No broken requirements found.' } else { $pipCheckRaw }) `
        -Remediation 'Recreate the venv and install the selected torch profile before requirements.txt.'

    $torchProbeCode = 'import json,torch; a=bool(torch.cuda.is_available()); print(json.dumps(dict(cuda_build=torch.version.cuda,cuda_available=a,device=torch.cuda.get_device_name(0) if a else None),sort_keys=True))'
    $torchProbeRaw = (& $python -c $torchProbeCode 2>&1 | Out-String).Trim()
    try {
        $torchProbe = $torchProbeRaw | ConvertFrom-Json
    }
    catch {
        $torchProbe = $null
    }
    if ($HardwareProfile -eq 'gpu12gb') {
        $torchPassed = $null -ne $torchProbe -and
            $torchProbe.cuda_build -eq '12.1' -and
            $torchProbe.cuda_available -eq $true
        Add-Check -Name 'python.torch-runtime' -Passed $torchPassed `
            -Expected 'CUDA 12.1 build with torch.cuda.is_available()=true' `
            -Observed $torchProbeRaw `
            -Remediation 'Install the cu121 torch wheels and verify the NVIDIA driver.'
    }
    else {
        $torchPassed = $null -ne $torchProbe -and $null -eq $torchProbe.cuda_build
        Add-Check -Name 'python.torch-runtime' -Passed $torchPassed `
            -Expected 'CPU-only torch 2.1.1 build' -Observed $torchProbeRaw `
            -Remediation 'Install the pinned torch wheels from the PyTorch CPU index.'
    }
}

$nodeCommand = Get-Command node -ErrorAction SilentlyContinue
$npmCommand = Get-Command npm -ErrorAction SilentlyContinue
$nodeVersion = $(if ($nodeCommand) { (& node --version).Trim() } else { '' })
$npmVersion = $(if ($npmCommand) { (& npm --version).Trim() } else { '' })
Add-Check -Name 'frontend.node' -Passed ($nodeVersion -match '^v22\.') `
    -Expected 'Node.js 22.x (validated: 22.22.2)' -Observed $nodeVersion `
    -Remediation 'Install a 64-bit Node.js 22 LTS runtime.'
Add-Check -Name 'frontend.npm' -Passed ($npmVersion -match '^(1[0-9]|[2-9][0-9])\.') `
    -Expected 'npm 10+ (validated: 11.17.0)' -Observed $npmVersion `
    -Remediation 'Use the npm bundled with Node.js 22, then run npm ci.'
$frontendModules = Join-Path $repoRoot 'frontend\node_modules'
Add-Check -Name 'frontend.node_modules' `
    -Passed (Test-Path -LiteralPath $frontendModules -PathType Container) `
    -Expected 'frontend\node_modules created by npm ci' -Observed $frontendModules `
    -Remediation 'Run: Set-Location frontend; npm ci'

foreach ($tool in @('ffmpeg', 'ffprobe')) {
    $command = Get-Command $tool -ErrorAction SilentlyContinue
    $observed = $(if ($command) { $command.Source } else { '' })
    Add-Check -Name "media.$tool" -Passed ($null -ne $command) `
        -Expected "$tool is available in PATH" -Observed $observed `
        -Remediation 'Install a pinned FFmpeg build and add its bin directory to PATH.'
}

$repoDrive = Get-PSDrive -Name ([IO.Path]::GetPathRoot($repoRoot).TrimEnd(':', '\')) -ErrorAction SilentlyContinue
$freeDiskBytes = $(if ($repoDrive) { [int64]$repoDrive.Free } else { 0 })
Add-Check -Name 'storage.free-space' -Passed ($freeDiskBytes -ge 4GB) `
    -Expected 'at least 4 GiB operational headroom after artifact installation' `
    -Observed ("{0:N2} GiB" -f ($freeDiskBytes / 1GB)) `
    -Remediation 'Free disk space before downloading the pinned model/runtime artifacts.'

$envPath = $EnvFile
if (-not [IO.Path]::IsPathRooted($envPath)) {
    $envPath = Join-Path $repoRoot $envPath
}
$envExists = Test-Path -LiteralPath $envPath -PathType Leaf
$envValues = @{}
Add-Check -Name 'config.env-file' -Passed $envExists -Expected '.env exists' `
    -Observed $envPath -Remediation 'Copy .env.example to .env and set local secrets/endpoints.'
if ($envExists) {
    $envValues = Read-DotEnv -Path $envPath
    $expectedEnv = [ordered]@{
        'ENVIRONMENT' = 'development'
        'DEBUG' = 'true'
        'AUTH_ENABLED' = 'true'
        'DEV_AUTH_BYPASS' = 'false'
        'DEV_USER_ID' = '0'
        'BACKEND_HOST' = '127.0.0.1'
        'LOCAL_LLM_PROVIDER' = 'llama_cpp_server'
        'LLAMA_SERVER_BASE_URL' = 'http://127.0.0.1:8088'
        'LLAMA_SERVER_MODEL' = 'speechintel-qwen3-8b-q4_k_m'
        'LLAMA_SERVER_MODEL_PATH' = 'models/qwen3/Qwen3-8B-Q4_K_M.gguf'
        'LLAMA_SERVER_CONTEXT_SIZE' = '12288'
        'LLAMA_SERVER_MINIMUM_FREE_VRAM_MIB' = '7000'
        'OFFLINE_STRICT' = 'true'
        'HF_HUB_OFFLINE' = '1'
        'TRANSFORMERS_OFFLINE' = '1'
        'LLM_SEED' = '42'
    }
    foreach ($entry in $expectedEnv.GetEnumerator()) {
        $actual = [string]$envValues[$entry.Key]
        if ($entry.Key -eq 'LLAMA_SERVER_MODEL_PATH') {
            $actual = $actual -replace '\\', '/'
        }
        Add-Check -Name "config.$($entry.Key)" -Passed ($actual -eq $entry.Value) `
            -Expected $entry.Value -Observed $actual `
            -Remediation 'Use the pinned local-LLM block from .env.example.'
    }

    $secret = [string]$envValues['SECRET_KEY']
    $secretLooksConfigured = $secret.Length -ge 32 -and
        $secret -notmatch '(?i)change-me|changeme|your-super-secret|password|template'
    Add-Check -Name 'config.SECRET_KEY' -Passed $secretLooksConfigured `
        -Expected 'generated secret with at least 32 characters' `
        -Observed $(if ($secretLooksConfigured) { 'configured' } else { 'missing or placeholder' }) `
        -Remediation 'Generate SECRET_KEY with secrets.token_urlsafe(48); never commit it.'

    $adminPassword = [string]$envValues['INITIAL_ADMIN_PASSWORD']
    $adminPasswordConfigured = $adminPassword.Length -ge 12 -and
        $adminPassword -notmatch '(?i)local-admin-password|password|changeme'
    Add-Check -Name 'config.INITIAL_ADMIN_PASSWORD' -Passed $adminPasswordConfigured `
        -Expected 'non-placeholder local admin password with at least 12 characters' `
        -Observed $(if ($adminPasswordConfigured) { 'configured' } else { 'missing or placeholder' }) `
        -Remediation 'Set a unique INITIAL_ADMIN_PASSWORD before the first database seed.'

    if ($pythonExists) {
        $securityValidation = Invoke-SecurityConfigValidation `
            -PythonPath $python `
            -EnvironmentValues $envValues
        Add-Check -Name 'config.security-contract' `
            -Passed ($securityValidation.exit_code -eq 0) `
            -Expected 'src.core.config.validate_security_settings accepts the exact .env' `
            -Observed $(if ($securityValidation.exit_code -eq 0) {
                'validated by application security contract'
            } else {
                $securityValidation.output
            }) `
            -Remediation 'Use AUTH_ENABLED=true for canonical clone/run, or satisfy every explicit loopback-only dev bypass requirement.'
    }
}

$postgresReady = Test-TcpPort -HostName '127.0.0.1' -Port 5432
Add-Check -Name 'service.postgresql' -Passed $postgresReady `
    -Expected 'PostgreSQL listens on 127.0.0.1:5432' `
    -Observed $(if ($postgresReady) { 'listening' } else { 'closed' }) `
    -Remediation 'Start PostgreSQL and create the configured development database.'
$redisReady = Test-TcpPort -HostName '127.0.0.1' -Port 6379
Add-Check -Name 'service.redis' -Passed $redisReady `
    -Expected 'Redis/Memurai listens on 127.0.0.1:6379' `
    -Observed $(if ($redisReady) { 'listening' } else { 'closed' }) `
    -Remediation 'Start Redis or Memurai before backend/Celery.'

if ($pythonExists) {
    $runtimeVerifier = Join-Path $repoRoot 'scripts\verify_llama_runtime.py'
    $runtimeArgs = @($python, $runtimeVerifier, '--repo-root', $repoRoot, '--json')
    if ($HardwareProfile -eq 'gpu12gb') {
        $runtimeArgs += '--probe'
    }
    $runtimeResult = Invoke-JsonVerifier -Arguments $runtimeArgs
    $runtimePassed = $runtimeResult.exit_code -eq 0 -and
        $null -ne $runtimeResult.payload -and
        $runtimeResult.payload.valid -eq $true
    $runtimeObserved = $(if ($null -ne $runtimeResult.payload) {
        "version=$($runtimeResult.payload.version); commit=$($runtimeResult.payload.commit); issues=$(@($runtimeResult.payload.issues).Count)"
    } else { $runtimeResult.raw })
    Add-Check -Name 'artifact.llama-runtime' -Passed $runtimePassed `
        -Expected 'b10331 manifest hashes valid; GPU profile also reports CUDA0' `
        -Observed $runtimeObserved `
        -Remediation 'Run scripts/install_local_llm_staging.ps1 explicitly and resolve all hash/probe issues.'

    if ($HardwareProfile -eq 'cpu') {
        $server = Join-Path $repoRoot 'models\runtimes\llama.cpp\b10331\windows-cuda-12.4-x64\bin\llama-server.exe'
        $versionOutput = ''
        if (Test-Path -LiteralPath $server -PathType Leaf) {
            $versionOutput = (& $server --version 2>&1 | Out-String).Trim()
        }
        Add-Check -Name 'artifact.llama-runtime-cpu-probe' `
            -Passed ($versionOutput -like '*version: 10331 (7ba604f1c)*') `
            -Expected 'llama-server --version contains version: 10331 (7ba604f1c)' `
            -Observed $versionOutput `
            -Remediation 'Reinstall the pinned b10331 runtime; CPU fallback does not require a CUDA device.'
    }

    $modelStore = Join-Path $repoRoot 'scripts\model_store.py'
    $modelResult = Invoke-JsonVerifier -Arguments @(
        $python, $modelStore, '--repo-root', $repoRoot,
        'preflight', '--model', 'qwen.qwen3-8b-q4_k_m', '--json'
    )
    $modelPassed = $modelResult.exit_code -eq 0 -and
        $null -ne $modelResult.payload -and
        $modelResult.payload.valid -eq $true
    $modelObserved = $(if ($null -ne $modelResult.payload) {
        "manifests=$($modelResult.payload.manifests_found); valid=$($modelResult.payload.valid)"
    } else { $modelResult.raw })
    Add-Check -Name 'artifact.qwen3-model' -Passed $modelPassed `
        -Expected 'qwen.qwen3-8b-q4_k_m manifest size/SHA-256 valid' `
        -Observed $modelObserved `
        -Remediation 'Run scripts/install_local_llm_staging.ps1 explicitly and resolve all model issues.'

    $asrResult = Invoke-JsonVerifier -Arguments @(
        $python, $modelStore, '--repo-root', $repoRoot,
        'preflight', '--model', 'systran.faster-whisper-large-v2', '--json'
    )
    $asrPassed = $asrResult.exit_code -eq 0 -and
        $null -ne $asrResult.payload -and
        $asrResult.payload.valid -eq $true
    $asrObserved = $(if ($null -ne $asrResult.payload) {
        "manifests=$($asrResult.payload.manifests_found); valid=$($asrResult.payload.valid)"
    } else { $asrResult.raw })
    Add-Check -Name 'artifact.faster-whisper-large-v2' -Passed $asrPassed `
        -Expected 'Systran large-v2 pinned snapshot size/SHA-256 valid' `
        -Observed $asrObserved `
        -Remediation 'Run scripts/install_audio_models_staging.py for large-v2 and resolve all hash issues.'

    $asrManifest = Get-Content -LiteralPath (Join-Path $repoRoot 'config\models\faster-whisper-large-v2.manifest.json') -Raw -Encoding UTF8 | ConvertFrom-Json
    $asrSnapshot = Join-Path (Join-Path $repoRoot 'models') ($asrManifest.model.relative_path -replace '/', '\')
    $asrModelRoot = Split-Path -Parent (Split-Path -Parent $asrSnapshot)
    $asrRef = Join-Path $asrModelRoot 'refs\main'
    $asrRefValue = $(if (Test-Path -LiteralPath $asrRef -PathType Leaf) {
        (Get-Content -LiteralPath $asrRef -Raw -Encoding UTF8).Trim()
    } else { '' })
    Add-Check -Name 'artifact.faster-whisper-large-v2-ref' `
        -Passed ($asrRefValue -eq [string]$asrManifest.model.source.revision) `
        -Expected ([string]$asrManifest.model.source.revision) -Observed $asrRefValue `
        -Remediation 'Re-run the audio-model installer so refs/main selects the immutable large-v2 revision.'

    $pyannoteManifestPath = Join-Path $repoRoot 'config\models\pyannote-3.1-offline.manifest.json'
    $pyannoteManifest = Get-Content -LiteralPath $pyannoteManifestPath -Raw -Encoding UTF8 | ConvertFrom-Json
    $pyannoteIssues = New-Object 'System.Collections.Generic.List[string]'
    foreach ($spec in $pyannoteManifest.files) {
        $artifactPath = Join-Path $repoRoot ([string]$spec.path -replace '/', '\')
        if (-not (Test-Path -LiteralPath $artifactPath -PathType Leaf)) {
            $pyannoteIssues.Add("missing:$($spec.path)") | Out-Null
            continue
        }
        $artifactStream = [IO.File]::OpenRead($artifactPath)
        try {
            $artifactSize = $artifactStream.Length
        }
        finally {
            $artifactStream.Dispose()
        }
        if ($artifactSize -ne [int64]$spec.size) {
            $pyannoteIssues.Add("size:$($spec.path)") | Out-Null
            continue
        }
        $hash = (Get-FileHash -LiteralPath $artifactPath -Algorithm SHA256).Hash.ToLowerInvariant()
        if ($hash -ne ([string]$spec.sha256).ToLowerInvariant()) {
            $pyannoteIssues.Add("sha256:$($spec.path)") | Out-Null
        }
    }
    $pyannoteSources = @($pyannoteManifest.pipeline) + @($pyannoteManifest.dependencies)
    foreach ($source in $pyannoteSources) {
        $parts = ([string]$source.model_id).Split('/', 2)
        $cacheName = "models--$($parts[0])--$($parts[1])"
        $refPath = Join-Path $repoRoot "models\pyannote\$cacheName\refs\main"
        $refValue = $(if (Test-Path -LiteralPath $refPath -PathType Leaf) {
            (Get-Content -LiteralPath $refPath -Raw -Encoding UTF8).Trim()
        } else { '' })
        if ($refValue -ne [string]$source.revision) {
            $pyannoteIssues.Add("ref:$($source.model_id)") | Out-Null
        }
    }
    Add-Check -Name 'artifact.pyannote-3.1-offline' `
        -Passed ($pyannoteIssues.Count -eq 0) `
        -Expected 'pipeline/dependency sizes, SHA-256 values and refs/main all match the pinned revisions' `
        -Observed $(if ($pyannoteIssues.Count -eq 0) { '5 files and 3 refs verified' } else { $pyannoteIssues -join ';' }) `
        -Remediation 'Accept the gated terms, set HF_TOKEN, and re-run scripts/install_audio_models_staging.py.'
}

$llmPortOpen = Test-TcpPort -HostName '127.0.0.1' -Port 8088
$minimumFreeVramMiB = 7000
if ($envValues.ContainsKey('LLAMA_SERVER_MINIMUM_FREE_VRAM_MIB')) {
    [int]::TryParse(
        [string]$envValues['LLAMA_SERVER_MINIMUM_FREE_VRAM_MIB'],
        [ref]$minimumFreeVramMiB
    ) | Out-Null
}
$expectedContextSize = 12288
if ($envValues.ContainsKey('LLAMA_SERVER_CONTEXT_SIZE')) {
    [int]::TryParse(
        [string]$envValues['LLAMA_SERVER_CONTEXT_SIZE'],
        [ref]$expectedContextSize
    ) | Out-Null
}

if ($HardwareProfile -eq 'gpu12gb') {
    $nvidiaSmi = Get-Command nvidia-smi -ErrorAction SilentlyContinue
    $gpuName = ''
    $totalVram = 0
    $freeVram = 0
    if ($nvidiaSmi) {
        $gpuRow = (& nvidia-smi --query-gpu=name,memory.total,memory.free --format=csv,noheader,nounits 2>&1 | Select-Object -First 1)
        $gpuFields = @([string]$gpuRow -split ',' | ForEach-Object { $_.Trim() })
        if ($gpuFields.Count -ge 3) {
            $gpuName = $gpuFields[0]
            [int]::TryParse($gpuFields[1], [ref]$totalVram) | Out-Null
            [int]::TryParse($gpuFields[2], [ref]$freeVram) | Out-Null
        }
    }
    $gpuCapacityPassed = $totalVram -ge 12000 -and
        ($freeVram -ge $minimumFreeVramMiB -or $llmPortOpen)
    $gpuExpected = $(if ($llmPortOpen) {
        'NVIDIA GPU with >=12000 MiB total; pinned server health is checked separately'
    } else {
        "NVIDIA GPU with >=12000 MiB total and >=$minimumFreeVramMiB MiB free VRAM before server start"
    })
    Add-Check -Name 'hardware.gpu-capacity' `
        -Passed $gpuCapacityPassed `
        -Expected $gpuExpected `
        -Observed "$gpuName; total=$totalVram MiB; free=$freeVram MiB" `
        -Remediation 'Free GPU memory or use -HardwareProfile cpu for functional fallback.'
    Add-Check -Name 'hardware.reference-gpu' `
        -Passed ($gpuName -like '*RTX 4070 SUPER*') -Required $false `
        -Expected 'Validated reference: RTX 4070 SUPER 12GB' -Observed $gpuName `
        -Remediation 'Record and benchmark this alternate >=12GB NVIDIA GPU before accepting an SLO.'
}

if ($llmPortOpen) {
    try {
        $null = Invoke-RestMethod -UseBasicParsing -Uri 'http://127.0.0.1:8088/health' -TimeoutSec 5
        $models = Invoke-RestMethod -UseBasicParsing -Uri 'http://127.0.0.1:8088/v1/models' -TimeoutSec 5
        $props = Invoke-RestMethod -UseBasicParsing -Uri 'http://127.0.0.1:8088/props' -TimeoutSec 5
        $slots = @(Invoke-RestMethod -UseBasicParsing -Uri 'http://127.0.0.1:8088/slots' -TimeoutSec 5)
        $modelIds = @($models.data | ForEach-Object { $_.id })
        $modelRow = @($models.data | Where-Object { $_.id -eq 'speechintel-qwen3-8b-q4_k_m' }) | Select-Object -First 1
        $expectedModelPath = [IO.Path]::GetFullPath(
            (Join-Path $repoRoot 'models\qwen3\Qwen3-8B-Q4_K_M.gguf')
        )
        $observedModelPath = $(if ($props.model_path) {
            [IO.Path]::GetFullPath([string]$props.model_path)
        } else { '' })
        $observedPropsContext = [int]$props.default_generation_settings.n_ctx
        $observedModelContext = [int]$modelRow.meta.n_ctx
        $observedTrainContext = [int]$modelRow.meta.n_ctx_train
        $slotContexts = @($slots | ForEach-Object { [int]$_.n_ctx })
        $contextBound = $observedPropsContext -eq $expectedContextSize -and
            $observedModelContext -eq $expectedContextSize -and
            $observedTrainContext -ge $expectedContextSize -and
            $slotContexts.Count -eq 1 -and
            $slotContexts[0] -eq $expectedContextSize
        $llmHealthy = ($modelIds -contains 'speechintel-qwen3-8b-q4_k_m') -and
            $observedModelPath -eq $expectedModelPath -and
            $contextBound
        Add-Check -Name 'port.8088' -Passed $llmHealthy `
            -Expected 'pinned alias, model path and context binding pass' `
            -Observed "models=$($modelIds -join ','); props_ctx=$observedPropsContext; model_ctx=$observedModelContext; train_ctx=$observedTrainContext; slots=$($slotContexts -join ',')" `
            -Remediation 'Restart the pinned llama-server through scripts/start_llama_server.ps1 so alias, path and context match .env.'
    }
    catch {
        Add-Check -Name 'port.8088' -Passed $false `
            -Expected 'port free, or pinned llama-server health/models pass' `
            -Observed $_.Exception.Message `
            -Remediation 'Stop the unexpected process using port 8088.'
    }
}
else {
    Add-Check -Name 'port.8088' -Passed $true `
        -Expected 'port free before llama-server start' -Observed 'available'
}

$backendPortOpen = Test-TcpPort -HostName '127.0.0.1' -Port 8000
if ($backendPortOpen) {
    try {
        $health = Invoke-RestMethod -UseBasicParsing -Uri 'http://127.0.0.1:8000/api/v1/health' -TimeoutSec 5
        Add-Check -Name 'port.8000' -Passed ($null -ne $health) `
            -Expected 'port free, or backend /api/v1/health responds' -Observed 'backend health responded' `
            -Remediation 'Stop the unexpected process using port 8000.'
    }
    catch {
        Add-Check -Name 'port.8000' -Passed $false `
            -Expected 'port free, or backend /api/v1/health responds' -Observed $_.Exception.Message `
            -Remediation 'Stop the unexpected process using port 8000.'
    }
}
else {
    Add-Check -Name 'port.8000' -Passed $true `
        -Expected 'port free before backend start' -Observed 'available'
}

$frontendPortOpen = Test-TcpPort -HostName '127.0.0.1' -Port 3000
if ($frontendPortOpen) {
    try {
        $frontend = Invoke-WebRequest -UseBasicParsing -Uri 'http://127.0.0.1:3000/' -TimeoutSec 5
        Add-Check -Name 'port.3000' -Passed ($frontend.StatusCode -eq 200) `
            -Expected 'port free, or frontend returns HTTP 200' -Observed "HTTP $($frontend.StatusCode)" `
            -Remediation 'Stop the unexpected process using port 3000.'
    }
    catch {
        Add-Check -Name 'port.3000' -Passed $false `
            -Expected 'port free, or frontend returns HTTP 200' -Observed $_.Exception.Message `
            -Remediation 'Stop the unexpected process using port 3000.'
    }
}
else {
    Add-Check -Name 'port.3000' -Passed $true `
        -Expected 'port free before frontend start' -Observed 'available'
}

$failedRequired = @($checks | Where-Object { $_.required -and $_.status -ne 'PASS' })
$reportStatus = $(if ($failedRequired.Count -eq 0) { 'PASS' } else { 'FAIL' })
$checkArray = $checks.ToArray()
$report = [ordered]@{
    schema_version = 1
    gate = 'new-machine-development-staging-preflight'
    generated_at_utc = [DateTime]::UtcNow.ToString('o')
    repo_root = $repoRoot
    hardware_profile = $HardwareProfile
    production_offline_bundle_status = 'BLOCKED'
    status = $reportStatus
    required_failures = $failedRequired.Count
    checks = $checkArray
}
$json = $report | ConvertTo-Json -Depth 8

if ($OutputPath) {
    $resolvedOutput = $OutputPath
    if (-not [IO.Path]::IsPathRooted($resolvedOutput)) {
        $resolvedOutput = Join-Path $repoRoot $resolvedOutput
    }
    $outputParent = Split-Path -Parent $resolvedOutput
    if ($outputParent) {
        New-Item -ItemType Directory -Path $outputParent -Force | Out-Null
    }
    Set-Content -LiteralPath $resolvedOutput -Value $json -Encoding UTF8
    Write-Host "Preflight report: $resolvedOutput"
}

Write-Output $json
if ($failedRequired.Count -gt 0) {
    exit 1
}
exit 0
