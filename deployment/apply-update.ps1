param(
    [Parameter(Mandatory = $true)][string]$PackagePath,
    [string]$ProjectRoot = (Join-Path $PSScriptRoot ".."),
    [int]$WaitForProcessId = 0,
    [switch]$Relaunch
)

$ErrorActionPreference = "Stop"
$productId = "cinema-tms-admin"
$resolvedProject = [IO.Path]::GetFullPath((Resolve-Path -LiteralPath $ProjectRoot).Path).TrimEnd("\")
$dataRoot = Join-Path $resolvedProject "data"
$resultPath = Join-Path $dataRoot "last-update-result.json"
$historyPath = Join-Path $dataRoot "update-history.jsonl"
$temporaryRoot = Join-Path ([IO.Path]::GetTempPath()) ("CinemaTMSAdminUpdate-" + [guid]::NewGuid().ToString("N"))
$backupRoot = $null
$newFiles = [Collections.Generic.List[string]]::new()
$updatedFiles = [Collections.Generic.List[string]]::new()
$removedFiles = [Collections.Generic.List[string]]::new()

function Write-UpdateResult([bool]$Success, [string]$Version, [string]$Message) {
    New-Item -ItemType Directory -Path $dataRoot -Force | Out-Null
    $record = [ordered]@{
        success = $Success
        product = $productId
        version = $Version
        message = $Message
        applied_at = [DateTime]::Now.ToString("o")
    }
    $json = $record | ConvertTo-Json -Compress
    $json | Set-Content -LiteralPath $resultPath -Encoding utf8
    $json | Add-Content -LiteralPath $historyPath -Encoding utf8
}

function Resolve-SafeTarget([string]$RelativePath) {
    $normalized = $RelativePath.Replace("/", "\")
    if ([IO.Path]::IsPathRooted($normalized) -or $normalized -match '(^|\\)\.\.(\\|$)') {
        throw "Unsafe update path: $RelativePath"
    }
    $top = ($normalized -split '\\')[0].ToLowerInvariant()
    $allowedRoots = @("license_admin", "deployment", "docs")
    $allowedFiles = @("pyproject.toml", "readme.md", "requirements.txt", "tms_admin_handoff.md")
    if ($top -notin $allowedRoots -and $normalized.ToLowerInvariant() -notin $allowedFiles) {
        throw "Protected or unsupported update path: $RelativePath"
    }
    $target = [IO.Path]::GetFullPath((Join-Path $resolvedProject $normalized))
    if (-not $target.StartsWith($resolvedProject + "\", [StringComparison]::OrdinalIgnoreCase)) {
        throw "Update path escapes the program directory: $RelativePath"
    }
    return $target
}

try {
    if ($WaitForProcessId -gt 0) {
        $deadline = [DateTime]::UtcNow.AddSeconds(60)
        while (Get-Process -Id $WaitForProcessId -ErrorAction SilentlyContinue) {
            if ([DateTime]::UtcNow -ge $deadline) { throw "The running program did not exit within 60 seconds." }
            Start-Sleep -Milliseconds 250
        }
    }

    $resolvedPackage = (Resolve-Path -LiteralPath $PackagePath).Path
    Add-Type -AssemblyName System.IO.Compression.FileSystem
    $archive = [IO.Compression.ZipFile]::OpenRead($resolvedPackage)
    try {
        foreach ($entry in $archive.Entries) {
            $entryPath = $entry.FullName.Replace("/", "\")
            if ([IO.Path]::IsPathRooted($entryPath) -or $entryPath -match '(^|\\)\.\.(\\|$)') {
                throw "Unsafe archive entry: $($entry.FullName)"
            }
        }
    } finally { $archive.Dispose() }

    New-Item -ItemType Directory -Path $temporaryRoot -Force | Out-Null
    Expand-Archive -LiteralPath $resolvedPackage -DestinationPath $temporaryRoot -Force
    $packageRoot = Get-ChildItem -LiteralPath $temporaryRoot -Directory | Select-Object -First 1
    if (-not $packageRoot) { throw "Update package root was not found." }
    $manifestPath = Join-Path $packageRoot.FullName "update-manifest.json"
    $payloadRoot = Join-Path $packageRoot.FullName "payload"
    if (-not (Test-Path -LiteralPath $manifestPath) -or -not (Test-Path -LiteralPath $payloadRoot)) {
        throw "Update manifest or payload is missing."
    }
    $manifest = Get-Content -LiteralPath $manifestPath -Raw -Encoding utf8 | ConvertFrom-Json
    if ($manifest.schema -ne 1 -or $manifest.product -ne $productId -or -not $manifest.version) {
        throw "This is not a supported Cinema TMS Admin update package."
    }

    foreach ($entry in $manifest.files) {
        $target = Resolve-SafeTarget $entry.path
        $source = [IO.Path]::GetFullPath((Join-Path $payloadRoot $entry.path.Replace("/", "\")))
        if (-not $source.StartsWith([IO.Path]::GetFullPath($payloadRoot).TrimEnd("\") + "\", [StringComparison]::OrdinalIgnoreCase)) {
            throw "Payload path escapes the package: $($entry.path)"
        }
        if (-not (Test-Path -LiteralPath $source -PathType Leaf)) { throw "Update file is missing: $($entry.path)" }
        if ((Get-Item -LiteralPath $source).Length -ne [long]$entry.size) { throw "Update file size mismatch: $($entry.path)" }
        if ((Get-FileHash -LiteralPath $source -Algorithm SHA256).Hash.ToLowerInvariant() -ne $entry.sha256) {
            throw "Update file hash mismatch: $($entry.path)"
        }
        $null = $target
    }
    foreach ($entry in $manifest.remove) { $null = Resolve-SafeTarget ([string]$entry) }

    $backupRoot = Join-Path $dataRoot ("update-backups\" + [DateTime]::Now.ToString("yyyyMMdd-HHmmss") + "-" + $manifest.version)
    New-Item -ItemType Directory -Path $backupRoot -Force | Out-Null
    foreach ($entry in $manifest.files) {
        $target = Resolve-SafeTarget $entry.path
        $source = Join-Path $payloadRoot $entry.path.Replace("/", "\")
        if (Test-Path -LiteralPath $target -PathType Leaf) {
            if ((Get-FileHash -LiteralPath $target -Algorithm SHA256).Hash.ToLowerInvariant() -eq $entry.sha256) { continue }
            $backup = Join-Path $backupRoot $entry.path.Replace("/", "\")
            New-Item -ItemType Directory -Path (Split-Path -Parent $backup) -Force | Out-Null
            Copy-Item -LiteralPath $target -Destination $backup -Force
            $updatedFiles.Add($entry.path)
        } else {
            $newFiles.Add($entry.path)
        }
        New-Item -ItemType Directory -Path (Split-Path -Parent $target) -Force | Out-Null
        $staged = $target + ".update-new"
        Copy-Item -LiteralPath $source -Destination $staged -Force
        Move-Item -LiteralPath $staged -Destination $target -Force
    }
    foreach ($entry in $manifest.remove) {
        $target = Resolve-SafeTarget ([string]$entry)
        if (-not (Test-Path -LiteralPath $target -PathType Leaf)) { continue }
        $backup = Join-Path $backupRoot ([string]$entry).Replace("/", "\")
        New-Item -ItemType Directory -Path (Split-Path -Parent $backup) -Force | Out-Null
        Copy-Item -LiteralPath $target -Destination $backup -Force
        Remove-Item -LiteralPath $target -Force
        $removedFiles.Add([string]$entry)
    }
    Write-UpdateResult $true $manifest.version "Update completed. Verified $($manifest.files.Count) program files. Database and settings were preserved."
} catch {
    if ($backupRoot -and (Test-Path -LiteralPath $backupRoot)) {
        foreach ($path in $updatedFiles) {
            $backup = Join-Path $backupRoot $path.Replace("/", "\")
            $target = Resolve-SafeTarget $path
            if (Test-Path -LiteralPath $backup) { Copy-Item -LiteralPath $backup -Destination $target -Force }
        }
        foreach ($path in $removedFiles) {
            $backup = Join-Path $backupRoot $path.Replace("/", "\")
            $target = Resolve-SafeTarget $path
            if (Test-Path -LiteralPath $backup) { Copy-Item -LiteralPath $backup -Destination $target -Force }
        }
        foreach ($path in $newFiles) {
            $target = Resolve-SafeTarget $path
            if (Test-Path -LiteralPath $target -PathType Leaf) { Remove-Item -LiteralPath $target -Force }
        }
    }
    Write-UpdateResult $false "" $_.Exception.Message
    exit 1
} finally {
    $resolvedTemporary = [IO.Path]::GetFullPath($temporaryRoot)
    $systemTemporary = [IO.Path]::GetFullPath([IO.Path]::GetTempPath())
    if ($resolvedTemporary.StartsWith($systemTemporary, [StringComparison]::OrdinalIgnoreCase) -and (Test-Path -LiteralPath $resolvedTemporary)) {
        Remove-Item -LiteralPath $resolvedTemporary -Recurse -Force
    }
    if ($Relaunch) {
        $launcher = Join-Path $resolvedProject "deployment\Cinema-TMS-Admin.vbs"
        if (Test-Path -LiteralPath $launcher) {
            Start-Process -FilePath "$env:WINDIR\System32\wscript.exe" -ArgumentList @("`"$launcher`"") -WorkingDirectory $resolvedProject -WindowStyle Hidden
        }
    }
}
