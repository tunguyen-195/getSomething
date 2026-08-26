param(
    [Parameter(Mandatory = $true)]
    [string]$BundleDirectory,
    [string]$ManifestName = 'pyannote-3.1-offline-gated-20260826.manifest.json',
    [switch]$Force
)

$ErrorActionPreference = 'Stop'
$repoRoot = (Resolve-Path (Join-Path $PSScriptRoot '..')).Path
$modelsRoot = Join-Path $repoRoot 'models'
$pyannoteRoot = Join-Path $modelsRoot 'pyannote'
$resolvedBundle = (Resolve-Path -LiteralPath $BundleDirectory).Path
$manifestPath = Join-Path $resolvedBundle $ManifestName

if (-not (Test-Path -LiteralPath $manifestPath -PathType Leaf)) {
    throw "Gated bundle manifest not found: $manifestPath"
}
$bundleManifest = Get-Content -LiteralPath $manifestPath -Raw -Encoding UTF8 | ConvertFrom-Json
if ($bundleManifest.schema_version -ne 1 -or
    $bundleManifest.artifact_id -ne 'diarization.pyannote-3.1-offline') {
    throw 'Unsupported gated pyannote bundle manifest.'
}
$archivePath = Join-Path $resolvedBundle ([string]$bundleManifest.archive.name)
if (-not (Test-Path -LiteralPath $archivePath -PathType Leaf)) {
    throw "Gated bundle archive not found: $archivePath"
}
$archive = Get-Item -LiteralPath $archivePath
if ([int64]$archive.Length -ne [int64]$bundleManifest.archive.size_bytes) {
    throw 'Gated bundle archive size mismatch.'
}
$archiveHash = (Get-FileHash -LiteralPath $archivePath -Algorithm SHA256).Hash.ToLowerInvariant()
if ($archiveHash -ne ([string]$bundleManifest.archive.sha256).ToLowerInvariant()) {
    throw 'Gated bundle archive SHA-256 mismatch.'
}

$sourceManifestPath = Join-Path $repoRoot 'config\models\pyannote-3.1-offline.manifest.json'
$sourceManifestHash = (Get-FileHash -LiteralPath $sourceManifestPath -Algorithm SHA256).Hash.ToLowerInvariant()
if ($sourceManifestHash -ne ([string]$bundleManifest.source_manifest.sha256).ToLowerInvariant()) {
    throw 'Clone manifest differs from the manifest used to build the gated bundle.'
}
$existingFiles = @(Get-ChildItem -LiteralPath $pyannoteRoot -Recurse -File -Force -ErrorAction SilentlyContinue)
if ($existingFiles.Count -gt 0 -and -not $Force) {
    throw "Destination already contains pyannote files: $pyannoteRoot"
}

New-Item -ItemType Directory -Path $modelsRoot -Force | Out-Null
Expand-Archive -LiteralPath $archivePath -DestinationPath $modelsRoot -Force:$Force

$sourceManifest = Get-Content -LiteralPath $sourceManifestPath -Raw -Encoding UTF8 | ConvertFrom-Json
foreach ($spec in $sourceManifest.files) {
    $path = Join-Path $repoRoot ([string]$spec.path -replace '/', '\')
    if (-not (Test-Path -LiteralPath $path -PathType Leaf)) {
        throw "Restored gated artifact is missing: $($spec.path)"
    }
    $stream = [IO.File]::OpenRead($path)
    try {
        $fileLength = $stream.Length
    }
    finally {
        $stream.Dispose()
    }
    $hash = (Get-FileHash -LiteralPath $path -Algorithm SHA256).Hash.ToLowerInvariant()
    if ([int64]$fileLength -ne [int64]$spec.size -or
        $hash -ne ([string]$spec.sha256).ToLowerInvariant()) {
        throw "Restored gated artifact failed verification: $($spec.path)"
    }
}
foreach ($source in @($sourceManifest.pipeline) + @($sourceManifest.dependencies)) {
    $parts = ([string]$source.model_id).Split('/', 2)
    $refPath = Join-Path $pyannoteRoot "models--$($parts[0])--$($parts[1])\refs\main"
    $refValue = $(if (Test-Path -LiteralPath $refPath -PathType Leaf) {
        (Get-Content -LiteralPath $refPath -Raw -Encoding UTF8).Trim()
    } else { '' })
    if ($refValue -ne [string]$source.revision) {
        throw "Restored gated ref is invalid: $($source.model_id)"
    }
}

Write-Host "[PASS] Pinned gated pyannote artifacts restored to: $pyannoteRoot"
