param(
    [ValidateSet('gpu12gb', 'cpu')]
    [string]$HardwareProfile = 'gpu12gb',
    [switch]$Force
)

$ErrorActionPreference = 'Stop'
$repoRoot = (Resolve-Path (Join-Path $PSScriptRoot '..')).Path
$python = Join-Path $repoRoot 'venv\Scripts\python.exe'
$modelManifestPath = Join-Path $repoRoot 'config\models\qwen3-8b-q4_k_m.manifest.json'
$runtimeManifestPath = Join-Path $repoRoot 'config\runtimes\llama.cpp-b10331-windows-cuda-12.4.runtime.json'

function Get-SafeChildPath {
    param(
        [Parameter(Mandatory = $true)][string]$Root,
        [Parameter(Mandatory = $true)][string]$RelativePath
    )

    if ([string]::IsNullOrWhiteSpace($RelativePath) -or
        [IO.Path]::IsPathRooted($RelativePath) -or
        $RelativePath -split '[\\/]' | Where-Object { $_ -in @('', '.', '..') }) {
        throw "Unsafe manifest-relative path: $RelativePath"
    }
    $rootFull = [IO.Path]::GetFullPath($Root).TrimEnd('\', '/')
    $candidate = [IO.Path]::GetFullPath(
        (Join-Path $rootFull ($RelativePath -replace '/', '\'))
    )
    $prefix = $rootFull + [IO.Path]::DirectorySeparatorChar
    if (-not $candidate.StartsWith($prefix, [StringComparison]::OrdinalIgnoreCase)) {
        throw "Manifest path escapes its root: $RelativePath"
    }
    return $candidate
}

function Test-FileAgainstSpec {
    param(
        [Parameter(Mandatory = $true)][string]$Path,
        [Parameter(Mandatory = $true)]$Spec
    )

    if (-not (Test-Path -LiteralPath $Path -PathType Leaf)) {
        return $false
    }
    if ((Get-Item -LiteralPath $Path).Length -ne [int64]$Spec.size_bytes) {
        return $false
    }
    $observedHash = (Get-FileHash -LiteralPath $Path -Algorithm SHA256).Hash.ToLowerInvariant()
    return $observedHash -eq ([string]$Spec.sha256).ToLowerInvariant()
}

function Get-VerifiedDownload {
    param(
        [Parameter(Mandatory = $true)][string]$Uri,
        [Parameter(Mandatory = $true)][string]$Destination,
        [Parameter(Mandatory = $true)]$Spec
    )

    if (Test-Path -LiteralPath $Destination -PathType Leaf) {
        if (Test-FileAgainstSpec -Path $Destination -Spec $Spec) {
            Write-Host "[REUSE] $Destination"
            return
        }
        if (-not $Force) {
            throw "Existing artifact does not match its manifest. Refusing overwrite without -Force: $Destination"
        }
    }

    $parent = Split-Path -Parent $Destination
    New-Item -ItemType Directory -Path $parent -Force | Out-Null
    $partial = "$Destination.partial-$([Guid]::NewGuid().ToString('N'))"
    try {
        Write-Host "[DOWNLOAD] $Uri"
        Invoke-WebRequest -UseBasicParsing -Uri $Uri -OutFile $partial
        if (-not (Test-FileAgainstSpec -Path $partial -Spec $Spec)) {
            throw "Downloaded artifact failed the manifest size/SHA-256 gate: $Uri"
        }
        if (Test-Path -LiteralPath $Destination) {
            Remove-Item -LiteralPath $Destination -Force
        }
        Move-Item -LiteralPath $partial -Destination $Destination
        Write-Host "[VERIFIED] $Destination"
    }
    finally {
        if (Test-Path -LiteralPath $partial) {
            Remove-Item -LiteralPath $partial -Force
        }
    }
}

function Install-VerifiedExtractedFile {
    param(
        [Parameter(Mandatory = $true)][string]$Source,
        [Parameter(Mandatory = $true)][string]$Destination,
        [Parameter(Mandatory = $true)]$Spec
    )

    if (-not (Test-FileAgainstSpec -Path $Source -Spec $Spec)) {
        throw "Extracted runtime file failed the manifest size/SHA-256 gate: $Source"
    }
    if (Test-Path -LiteralPath $Destination -PathType Leaf) {
        if (Test-FileAgainstSpec -Path $Destination -Spec $Spec) {
            Write-Host "[REUSE] $Destination"
            return
        }
        if (-not $Force) {
            throw "Existing runtime file does not match its manifest. Refusing overwrite without -Force: $Destination"
        }
    }

    $parent = Split-Path -Parent $Destination
    New-Item -ItemType Directory -Path $parent -Force | Out-Null
    $partial = "$Destination.partial-$([Guid]::NewGuid().ToString('N'))"
    try {
        Copy-Item -LiteralPath $Source -Destination $partial
        if (-not (Test-FileAgainstSpec -Path $partial -Spec $Spec)) {
            throw "Copied runtime file failed the manifest size/SHA-256 gate: $Destination"
        }
        if (Test-Path -LiteralPath $Destination) {
            Remove-Item -LiteralPath $Destination -Force
        }
        Move-Item -LiteralPath $partial -Destination $Destination
        Write-Host "[VERIFIED] $Destination"
    }
    finally {
        if (Test-Path -LiteralPath $partial) {
            Remove-Item -LiteralPath $partial -Force
        }
    }
}

if (-not (Test-Path -LiteralPath $python -PathType Leaf)) {
    throw "Create the pinned Python 3.11 venv before acquiring artifacts: $python"
}

$modelManifest = Get-Content -LiteralPath $modelManifestPath -Raw -Encoding UTF8 | ConvertFrom-Json
$runtimeManifest = Get-Content -LiteralPath $runtimeManifestPath -Raw -Encoding UTF8 | ConvertFrom-Json
$model = $modelManifest.model
$runtime = $runtimeManifest.runtime

if ($model.id -ne 'qwen.qwen3-8b-q4_k_m' -or
    $model.source.repository -ne 'Qwen/Qwen3-8B-GGUF' -or
    $model.source.revision -ne '7c41481f57cb95916b40956ab2f0b139b296d974') {
    throw 'The canonical Qwen3 staging manifest changed. Review and update this installer explicitly.'
}
if ($runtime.id -ne 'llama.cpp.windows-cuda-12.4-x64' -or
    $runtime.version -ne 'b10331' -or
    $runtime.source.release_url -ne 'https://github.com/ggml-org/llama.cpp/releases/tag/b10331') {
    throw 'The canonical llama.cpp staging manifest changed. Review and update this installer explicitly.'
}

$modelRoot = Get-SafeChildPath -Root (Join-Path $repoRoot 'models') -RelativePath $model.relative_path
$modelBaseUrl = 'https://huggingface.co/{0}/resolve/{1}' -f @(
    $model.source.repository,
    $model.source.revision
)
foreach ($spec in $model.files) {
    if ($spec.required -ne $true) {
        continue
    }
    $destination = Get-SafeChildPath -Root $modelRoot -RelativePath $spec.path
    $encodedName = [Uri]::EscapeDataString([string]$spec.path)
    $uri = '{0}/{1}?download=true' -f $modelBaseUrl, $encodedName
    Get-VerifiedDownload -Uri $uri -Destination $destination -Spec $spec
}

$runtimeRoot = Get-SafeChildPath -Root $repoRoot -RelativePath $runtime.relative_path
$packageSpecs = @($runtime.files | Where-Object { $_.path -like 'packages/*' })
$binarySpecs = @($runtime.files | Where-Object { $_.path -notlike 'packages/*' })
$releaseBaseUrl = ([string]$runtime.source.release_url) -replace '/tag/', '/download/'

foreach ($spec in $packageSpecs) {
    $destination = Get-SafeChildPath -Root $runtimeRoot -RelativePath $spec.path
    $assetName = [IO.Path]::GetFileName([string]$spec.path)
    $uri = '{0}/{1}' -f $releaseBaseUrl, [Uri]::EscapeDataString($assetName)
    Get-VerifiedDownload -Uri $uri -Destination $destination -Spec $spec
}

$stagingRoot = Join-Path $runtimeRoot ('.install-staging-' + [Guid]::NewGuid().ToString('N'))
New-Item -ItemType Directory -Path $stagingRoot -Force | Out-Null
try {
    foreach ($spec in $packageSpecs) {
        $archive = Get-SafeChildPath -Root $runtimeRoot -RelativePath $spec.path
        $archiveName = [IO.Path]::GetFileNameWithoutExtension($archive)
        $extractRoot = Join-Path $stagingRoot $archiveName
        Expand-Archive -LiteralPath $archive -DestinationPath $extractRoot
    }

    foreach ($spec in $binarySpecs) {
        $leafName = [IO.Path]::GetFileName([string]$spec.path)
        $candidates = @(
            Get-ChildItem -LiteralPath $stagingRoot -Recurse -File |
                Where-Object { $_.Name -eq $leafName }
        )
        $matching = @(
            $candidates | Where-Object { Test-FileAgainstSpec -Path $_.FullName -Spec $spec }
        )
        if ($matching.Count -ne 1) {
            throw "Expected exactly one verified '$leafName' in the pinned release archives; found $($matching.Count)."
        }
        $destination = Get-SafeChildPath -Root $runtimeRoot -RelativePath $spec.path
        Install-VerifiedExtractedFile -Source $matching[0].FullName -Destination $destination -Spec $spec
    }
}
finally {
    $runtimePrefix = $runtimeRoot.TrimEnd('\', '/') + [IO.Path]::DirectorySeparatorChar
    $resolvedStaging = [IO.Path]::GetFullPath($stagingRoot)
    if ($resolvedStaging.StartsWith($runtimePrefix, [StringComparison]::OrdinalIgnoreCase) -and
        (Test-Path -LiteralPath $resolvedStaging)) {
        Remove-Item -LiteralPath $resolvedStaging -Recurse -Force
    }
}

$runtimeVerifier = Join-Path $repoRoot 'scripts\verify_llama_runtime.py'
$runtimeArgs = @($runtimeVerifier, '--repo-root', $repoRoot, '--json')
if ($HardwareProfile -eq 'gpu12gb') {
    $runtimeArgs += '--probe'
}
$runtimeReport = & $python @runtimeArgs
if ($LASTEXITCODE -ne 0) {
    throw "Pinned llama.cpp verification failed:`n$($runtimeReport | Out-String)"
}

if ($HardwareProfile -eq 'cpu') {
    $server = Get-SafeChildPath -Root $runtimeRoot -RelativePath $runtime.probe.executable
    $versionOutput = (& $server --version 2>&1 | Out-String)
    if (-not $versionOutput.Contains([string]$runtime.probe.version_contains)) {
        throw 'Pinned llama.cpp CPU version probe failed.'
    }
}

$modelStore = Join-Path $repoRoot 'scripts\model_store.py'
$modelReport = & $python $modelStore --repo-root $repoRoot preflight --model $model.id --json
if ($LASTEXITCODE -ne 0) {
    throw "Pinned Qwen3 verification failed:`n$($modelReport | Out-String)"
}

Write-Host '[PASS] Pinned local LLM staging artifacts are installed and hash-verified.'
Write-Host "Next: powershell -ExecutionPolicy Bypass -File scripts\preflight_new_machine.ps1 -HardwareProfile $HardwareProfile"
