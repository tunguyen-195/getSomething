param(
    [string]$Output = "docs/research/reference-repo-audit/hardware-profile.json",
    [string]$ProfileId = "cand-dev-win4070s-12g-v1",
    [string]$WorkspaceDrive = "D"
)

$osInfo = Get-CimInstance Win32_OperatingSystem
$cpuInfo = Get-CimInstance Win32_Processor | Select-Object -First 1
$memoryBytes = (Get-CimInstance Win32_PhysicalMemory | Measure-Object -Property Capacity -Sum).Sum
$volumeInfo = Get-Volume -DriveLetter $WorkspaceDrive

$gpuFields = @(& nvidia-smi --query-gpu=name,memory.total,driver_version --format=csv,noheader,nounits 2>$null)
if ($LASTEXITCODE -ne 0 -or $gpuFields.Count -eq 0) {
    throw "nvidia-smi did not return a GPU profile"
}
$gpuParts = $gpuFields[0].Split(",") | ForEach-Object { $_.Trim() }
$nvidiaSummary = (& nvidia-smi 2>$null) -join "`n"
$cudaMatch = [regex]::Match($nvidiaSummary, "CUDA Version:\s*([0-9.]+)")

$profileResult = [ordered]@{
    schema_version = "offline-hardware-profile-v1"
    generated_at_utc = [DateTime]::UtcNow.ToString("o")
    profile_id = $ProfileId
    role = "development_evaluation"
    os = [ordered]@{
        caption = $osInfo.Caption
        version = $osInfo.Version
        architecture = $osInfo.OSArchitecture
    }
    cpu = [ordered]@{
        name = $cpuInfo.Name.Trim()
        physical_cores = [int]$cpuInfo.NumberOfCores
        logical_processors = [int]$cpuInfo.NumberOfLogicalProcessors
    }
    memory = [ordered]@{
        physical_bytes = [int64]$memoryBytes
        os_visible_bytes = [int64]$osInfo.TotalVisibleMemorySize * 1024
    }
    gpu = [ordered]@{
        name = $gpuParts[0]
        memory_mib = [int]$gpuParts[1]
        driver_version = $gpuParts[2]
        cuda_api_version = if ($cudaMatch.Success) { $cudaMatch.Groups[1].Value } else { $null }
    }
    workspace_volume = [ordered]@{
        drive = $WorkspaceDrive
        filesystem = $volumeInfo.FileSystem
        total_bytes = [int64]$volumeInfo.Size
        free_bytes = [int64]$volumeInfo.SizeRemaining
    }
    capture_commands = @(
        "Get-CimInstance Win32_OperatingSystem",
        "Get-CimInstance Win32_Processor",
        "Get-CimInstance Win32_PhysicalMemory",
        "Get-Volume -DriveLetter $WorkspaceDrive",
        "nvidia-smi --query-gpu=name,memory.total,driver_version --format=csv,noheader,nounits",
        "nvidia-smi"
    )
    promotion_policy = "Benchmark evidence is valid only for this exact profile; production requires a separate signed target profile."
}

$outputPath = if ([IO.Path]::IsPathRooted($Output)) {
    $Output
} else {
    Join-Path (Get-Location) $Output
}
$outputDirectory = Split-Path -Parent $outputPath
New-Item -ItemType Directory -Path $outputDirectory -Force | Out-Null
$profileResult | ConvertTo-Json -Depth 6 | Set-Content -LiteralPath $outputPath -Encoding utf8
Write-Output ([IO.Path]::GetFullPath($outputPath))
