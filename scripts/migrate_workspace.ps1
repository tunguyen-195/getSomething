param(
    [Parameter(Mandatory = $true)]
    [string]$Source,

    [Parameter(Mandatory = $true)]
    [string]$Destination,

    [Parameter(Mandatory = $true)]
    [string]$EvidenceDirectory,

    [switch]$Resume
)

$ErrorActionPreference = 'Stop'
Set-StrictMode -Version Latest

function Get-TreeInventory {
    param([string]$Root)

    $rootPath = [System.IO.Path]::GetFullPath($Root).TrimEnd('\')
    $rootPrefix = "$rootPath\"
    foreach ($filePath in [System.IO.Directory]::EnumerateFiles(
        $rootPath,
        '*',
        [System.IO.SearchOption]::AllDirectories
    )) {
        $item = [System.IO.FileInfo]::new($filePath)
        [pscustomobject]@{
            RelativePath = $filePath.Substring($rootPrefix.Length)
            Length = $item.Length
        }
    }
}

function Get-StreamingSha256 {
    param([string]$Path)

    $ioPath = if ($Path.StartsWith('\\?\')) {
        $Path
    }
    elseif ($Path -match '^[A-Za-z]:\\') {
        "\\?\$Path"
    }
    else {
        "\\?\$([System.IO.Path]::GetFullPath($Path))"
    }
    try {
        $stream = [System.IO.File]::Open(
            $ioPath,
            [System.IO.FileMode]::Open,
            [System.IO.FileAccess]::Read,
            [System.IO.FileShare]::Read
        )
    }
    catch {
        throw "Cannot open file for SHA-256: $Path. $($_.Exception.Message)"
    }
    try {
        $sha = [System.Security.Cryptography.SHA256]::Create()
        try {
            $hex = [System.BitConverter]::ToString($sha.ComputeHash($stream))
            return $hex.Replace('-', '').ToLowerInvariant()
        }
        finally {
            $sha.Dispose()
        }
    }
    finally {
        $stream.Dispose()
    }
}

function Invoke-GitCheck {
    param(
        [string]$Root,
        [string[]]$Arguments
    )

    $output = & git -C $Root @Arguments 2>&1
    if ($LASTEXITCODE -ne 0) {
        throw "git $($Arguments -join ' ') failed in $Root`: $output"
    }
    return @($output)
}

$sourcePath = [System.IO.Path]::GetFullPath((Resolve-Path -LiteralPath $Source).Path).TrimEnd('\')
$destinationPath = [System.IO.Path]::GetFullPath($Destination).TrimEnd('\')
$evidencePath = [System.IO.Path]::GetFullPath($EvidenceDirectory).TrimEnd('\')

if ($destinationPath.StartsWith("$sourcePath\", [System.StringComparison]::OrdinalIgnoreCase)) {
    throw 'Destination cannot be inside the source tree.'
}

if (Test-Path -LiteralPath $destinationPath) {
    $existingItems = @(Get-ChildItem -LiteralPath $destinationPath -Force)
    if ($existingItems.Count -ne 0 -and -not $Resume) {
        throw "Destination must be empty before migration: $destinationPath"
    }
}
else {
    New-Item -ItemType Directory -Path $destinationPath | Out-Null
}

New-Item -ItemType Directory -Path $evidencePath -Force | Out-Null

$reparsePoints = @(
    Get-ChildItem -LiteralPath $sourcePath -Force -Recurse -Attributes ReparsePoint `
        -ErrorAction SilentlyContinue
)
if ($reparsePoints.Count -ne 0) {
    $reparsePoints.FullName | Set-Content -LiteralPath "$evidencePath\reparse-points.txt"
    throw 'Source contains reparse points. Review them before copying.'
}

Write-Host '[MIGRATION] Building source inventory...'
$sourceInventory = @(Get-TreeInventory -Root $sourcePath)
$sourceInventory | Export-Csv -LiteralPath "$evidencePath\source-inventory.csv" `
    -NoTypeInformation -Encoding utf8
$sourceBytes = [long](($sourceInventory | Measure-Object -Property Length -Sum).Sum)

$destinationDrive = Get-PSDrive -Name ([System.IO.Path]::GetPathRoot($destinationPath).Substring(0, 1))
$requiredBytes = $sourceBytes + 10GB
if ($destinationDrive.Free -lt $requiredBytes) {
    throw "Insufficient destination space. Required=$requiredBytes Free=$($destinationDrive.Free)"
}

$preflight = [ordered]@{
    generated_at = [DateTimeOffset]::UtcNow.ToString('o')
    source = $sourcePath
    destination = $destinationPath
    source_file_count = $sourceInventory.Count
    source_bytes = $sourceBytes
    destination_free_bytes_before = [long]$destinationDrive.Free
    required_bytes_with_headroom = [long]$requiredBytes
    source_git_head = [string](
        Invoke-GitCheck -Root $sourcePath -Arguments @('rev-parse', 'HEAD') |
            Select-Object -First 1
    )
    source_git_branch = [string](
        Invoke-GitCheck -Root $sourcePath -Arguments @('branch', '--show-current') |
            Select-Object -First 1
    )
}
$preflight | ConvertTo-Json -Depth 4 | Set-Content `
    -LiteralPath "$evidencePath\preflight.json" -Encoding utf8

Write-Host '[MIGRATION] Copying complete workspace with robocopy...'
$copyLog = "$evidencePath\robocopy-copy.log"
$robocopyArgs = @(
    $sourcePath,
    $destinationPath,
    '/E',
    '/COPY:DAT',
    '/DCOPY:DAT',
    '/R:2',
    '/W:2',
    '/XJ',
    '/SL',
    '/MT:16',
    '/BYTES',
    '/NP',
    "/LOG:$copyLog"
)
& robocopy @robocopyArgs | Out-Null
$copyExitCode = $LASTEXITCODE
if ($copyExitCode -ge 8) {
    throw "Robocopy failed with exit code $copyExitCode. See $copyLog"
}

Write-Host '[MIGRATION] Building destination inventory...'
$destinationInventory = @(Get-TreeInventory -Root $destinationPath)
$destinationInventory | Export-Csv `
    -LiteralPath "$evidencePath\destination-inventory.csv" `
    -NoTypeInformation -Encoding utf8
$destinationBytes = [long](
    ($destinationInventory | Measure-Object -Property Length -Sum).Sum
)

$sourceIndex = @{}
foreach ($row in $sourceInventory) {
    $sourceIndex[$row.RelativePath] = [long]$row.Length
}
$destinationIndex = @{}
foreach ($row in $destinationInventory) {
    $destinationIndex[$row.RelativePath] = [long]$row.Length
}

$inventoryMismatches = New-Object System.Collections.Generic.List[object]
foreach ($relativePath in $sourceIndex.Keys) {
    if (-not $destinationIndex.ContainsKey($relativePath)) {
        $inventoryMismatches.Add([pscustomobject]@{
            RelativePath = $relativePath
            Reason = 'missing_at_destination'
        })
    }
    elseif ($destinationIndex[$relativePath] -ne $sourceIndex[$relativePath]) {
        $inventoryMismatches.Add([pscustomobject]@{
            RelativePath = $relativePath
            Reason = 'size_mismatch'
        })
    }
}
foreach ($relativePath in $destinationIndex.Keys) {
    if (-not $sourceIndex.ContainsKey($relativePath)) {
        $inventoryMismatches.Add([pscustomobject]@{
            RelativePath = $relativePath
            Reason = 'unexpected_at_destination'
        })
    }
}
$inventoryMismatches | Export-Csv `
    -LiteralPath "$evidencePath\inventory-mismatches.csv" `
    -NoTypeInformation -Encoding utf8
if ($inventoryMismatches.Count -ne 0) {
    throw "Inventory verification failed with $($inventoryMismatches.Count) mismatch(es)."
}

# Dependencies and Git objects are verified by their own runtime/fsck gates. Hash every
# non-regenerable project, model, storage, configuration, and evidence file byte-for-byte.
$regenerablePrefixes = @(
    'venv\',
    'frontend\node_modules\',
    '.git\objects\'
)
$materialFiles = @(
    $sourceInventory | Where-Object {
        $relative = $_.RelativePath
        -not ($regenerablePrefixes | Where-Object {
            $relative.StartsWith($_, [System.StringComparison]::OrdinalIgnoreCase)
        })
    }
)

Write-Host "[MIGRATION] Hashing $($materialFiles.Count) non-regenerable files..."
$hashRows = New-Object System.Collections.Generic.List[object]
$hashMismatches = 0
$index = 0
foreach ($row in $materialFiles) {
    $index += 1
    $sourceFile = Join-Path $sourcePath $row.RelativePath
    $destinationFile = Join-Path $destinationPath $row.RelativePath
    $sourceHash = Get-StreamingSha256 -Path $sourceFile
    $destinationHash = Get-StreamingSha256 -Path $destinationFile
    $matches = $sourceHash -eq $destinationHash
    if (-not $matches) {
        $hashMismatches += 1
    }
    $hashRows.Add([pscustomobject]@{
        RelativePath = $row.RelativePath
        Length = $row.Length
        SourceSha256 = $sourceHash
        DestinationSha256 = $destinationHash
        Match = $matches
    })
    if (($index % 1000) -eq 0) {
        Write-Host "[MIGRATION] Hashed $index/$($materialFiles.Count) files"
    }
}
$hashRows | Export-Csv -LiteralPath "$evidencePath\material-hashes.csv" `
    -NoTypeInformation -Encoding utf8
if ($hashMismatches -ne 0) {
    throw "Content verification failed with $hashMismatches hash mismatch(es)."
}

Write-Host '[MIGRATION] Verifying Git object database and worktree state...'
$sourceStatus = Invoke-GitCheck -Root $sourcePath -Arguments @(
    'status', '--porcelain=v1', '--untracked-files=all'
)
$destinationStatus = Invoke-GitCheck -Root $destinationPath -Arguments @(
    'status', '--porcelain=v1', '--untracked-files=all'
)
if (($sourceStatus -join "`n") -ne ($destinationStatus -join "`n")) {
    $sourceStatus | Set-Content -LiteralPath "$evidencePath\source-git-status.txt"
    $destinationStatus | Set-Content -LiteralPath "$evidencePath\destination-git-status.txt"
    throw 'Source and destination Git worktree states differ.'
}
Invoke-GitCheck -Root $destinationPath -Arguments @('fsck', '--full') | `
    Set-Content -LiteralPath "$evidencePath\git-fsck.txt"
Invoke-GitCheck -Root $destinationPath -Arguments @('lfs', 'fsck') | `
    Set-Content -LiteralPath "$evidencePath\git-lfs-fsck.txt"

$result = [ordered]@{
    completed_at = [DateTimeOffset]::UtcNow.ToString('o')
    status = 'PASS'
    source = $sourcePath
    destination = $destinationPath
    file_count = $sourceInventory.Count
    bytes = $sourceBytes
    destination_file_count = $destinationInventory.Count
    destination_bytes = $destinationBytes
    material_file_hashes_verified = $materialFiles.Count
    inventory_mismatches = $inventoryMismatches.Count
    hash_mismatches = $hashMismatches
    robocopy_exit_code = $copyExitCode
    git_head = $preflight.source_git_head
    source_preserved = $true
}
$result | ConvertTo-Json -Depth 4 | Set-Content `
    -LiteralPath "$evidencePath\result.json" -Encoding utf8
$result | ConvertTo-Json -Depth 4
