param(
    [Parameter(Mandatory = $true)]
    [string]$OutputDirectory,
    [string]$BundleName = 'pyannote-3.1-offline-gated-20260826'
)

$ErrorActionPreference = 'Stop'
$repoRoot = (Resolve-Path (Join-Path $PSScriptRoot '..')).Path
$modelsRoot = Join-Path $repoRoot 'models'
$pyannoteRoot = Join-Path $modelsRoot 'pyannote'
$sourceManifestPath = Join-Path $repoRoot 'config\models\pyannote-3.1-offline.manifest.json'

if (-not (Test-Path -LiteralPath $pyannoteRoot -PathType Container)) {
    throw "Pinned pyannote cache not found: $pyannoteRoot"
}
$sourceManifest = Get-Content -LiteralPath $sourceManifestPath -Raw -Encoding UTF8 | ConvertFrom-Json
if ($sourceManifest.artifact_id -ne 'diarization.pyannote-3.1-offline') {
    throw 'Unexpected pyannote manifest identity.'
}
foreach ($spec in $sourceManifest.files) {
    $path = Join-Path $repoRoot ([string]$spec.path -replace '/', '\')
    if (-not (Test-Path -LiteralPath $path -PathType Leaf)) {
        throw "Missing gated artifact: $($spec.path)"
    }
    $stream = [IO.File]::OpenRead($path)
    try {
        $fileLength = $stream.Length
    }
    finally {
        $stream.Dispose()
    }
    if ([int64]$fileLength -ne [int64]$spec.size) {
        throw "Gated artifact size mismatch: $($spec.path)"
    }
    $hash = (Get-FileHash -LiteralPath $path -Algorithm SHA256).Hash.ToLowerInvariant()
    if ($hash -ne ([string]$spec.sha256).ToLowerInvariant()) {
        throw "Gated artifact SHA-256 mismatch: $($spec.path)"
    }
}

$resolvedOutput = [IO.Path]::GetFullPath($OutputDirectory)
New-Item -ItemType Directory -Path $resolvedOutput -Force | Out-Null
$archivePath = Join-Path $resolvedOutput "$BundleName.zip"
$bundleManifestPath = Join-Path $resolvedOutput "$BundleName.manifest.json"
if ((Test-Path -LiteralPath $archivePath) -or
    (Test-Path -LiteralPath $bundleManifestPath)) {
    throw "Bundle output already exists in $resolvedOutput. Remove or rename it explicitly."
}

$stagingParent = Join-Path ([IO.Path]::GetTempPath()) ('stt-pyannote-' + [Guid]::NewGuid().ToString('N'))
$stagingModels = Join-Path $stagingParent 'models'
$stagingPyannote = Join-Path $stagingModels 'pyannote'
New-Item -ItemType Directory -Path $stagingPyannote -Force | Out-Null
try {
    # Dereference Hugging Face snapshot symlinks into regular files. This keeps
    # the private transfer portable to Windows hosts without Developer Mode.
    foreach ($spec in $sourceManifest.files) {
        $source = Join-Path $repoRoot ([string]$spec.path -replace '/', '\')
        $relative = ([string]$spec.path).Substring('models/'.Length) -replace '/', '\'
        $destination = Join-Path $stagingModels $relative
        New-Item -ItemType Directory -Path (Split-Path -Parent $destination) -Force | Out-Null
        [IO.File]::Copy($source, $destination, $false)
    }
    foreach ($source in @($sourceManifest.pipeline) + @($sourceManifest.dependencies)) {
        $parts = ([string]$source.model_id).Split('/', 2)
        $relative = "pyannote\models--$($parts[0])--$($parts[1])\refs\main"
        $sourceRef = Join-Path $modelsRoot $relative
        $destinationRef = Join-Path $stagingModels $relative
        New-Item -ItemType Directory -Path (Split-Path -Parent $destinationRef) -Force | Out-Null
        [IO.File]::Copy($sourceRef, $destinationRef, $false)
    }

    Push-Location $stagingModels
    try {
        Compress-Archive -LiteralPath 'pyannote' -DestinationPath $archivePath -CompressionLevel Optimal
    }
    finally {
        Pop-Location
    }
}
finally {
    if (Test-Path -LiteralPath $stagingParent) {
        Remove-Item -LiteralPath $stagingParent -Recurse -Force
    }
}

Add-Type -AssemblyName System.IO.Compression.FileSystem
$zip = [IO.Compression.ZipFile]::OpenRead($archivePath)
try {
    $entryCount = $zip.Entries.Count
    $hasExpectedRoot = @($zip.Entries | Where-Object {
        ($_.FullName -replace '\\', '/') -like 'pyannote/*'
    }).Count -gt 0
}
finally {
    $zip.Dispose()
}
if (-not $hasExpectedRoot) {
    throw 'Gated bundle does not contain the expected pyannote/ root.'
}

$archive = Get-Item -LiteralPath $archivePath
$bundleManifest = [ordered]@{
    schema_version = 1
    artifact_id = 'diarization.pyannote-3.1-offline'
    generated_at_utc = [DateTime]::UtcNow.ToString('o')
    archive = [ordered]@{
        name = $archive.Name
        size_bytes = [int64]$archive.Length
        sha256 = (Get-FileHash -LiteralPath $archivePath -Algorithm SHA256).Hash.ToLowerInvariant()
        entry_count = $entryCount
    }
    extraction = [ordered]@{
        destination = '<repo-root>/models'
        expected_root = 'models/pyannote'
    }
    source_manifest = [ordered]@{
        path = 'config/models/pyannote-3.1-offline.manifest.json'
        sha256 = (Get-FileHash -LiteralPath $sourceManifestPath -Algorithm SHA256).Hash.ToLowerInvariant()
    }
}
$bundleManifest | ConvertTo-Json -Depth 6 | Set-Content -LiteralPath $bundleManifestPath -Encoding UTF8

Write-Host "[PASS] Gated pyannote bundle: $archivePath"
Write-Host "[PASS] Bundle manifest: $bundleManifestPath"
