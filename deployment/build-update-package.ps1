param(
    [string]$BaselineManifestPath = "",
    [string]$OutputDirectory = (Join-Path $PSScriptRoot "..\dist\updates")
)

$ErrorActionPreference = "Stop"
$projectRoot = (Resolve-Path (Join-Path $PSScriptRoot "..")).Path
$python = Join-Path $projectRoot ".python\python.exe"
if (-not (Test-Path -LiteralPath $python)) {
    $pythonCommand = Get-Command python -ErrorAction SilentlyContinue
    if (-not $pythonCommand) { throw "Python runtime is required." }
    $python = $pythonCommand.Source
}
$version = (& $python -c "from license_admin.version import __version__; print(__version__)" | Select-Object -Last 1).Trim()
$product = "cinema-tms-admin"
$packageName = "Cinema-TMS-Admin-Update-$version"
$temporaryRoot = Join-Path ([IO.Path]::GetTempPath()) ("CinemaTMSAdminUpdateBuild-" + [guid]::NewGuid().ToString("N"))
$packageRoot = Join-Path $temporaryRoot $packageName
$payloadRoot = Join-Path $packageRoot "payload"
$snapshotRoot = Join-Path $projectRoot "dist\update-manifests"

function Get-RelativeProjectPath([string]$FullPath) {
    $prefix = [IO.Path]::GetFullPath($projectRoot).TrimEnd("\") + "\"
    $resolved = [IO.Path]::GetFullPath($FullPath)
    if (-not $resolved.StartsWith($prefix, [StringComparison]::OrdinalIgnoreCase)) { throw "File escapes project: $FullPath" }
    return $resolved.Substring($prefix.Length).Replace("\", "/")
}

try {
    New-Item -ItemType Directory -Path $payloadRoot -Force | Out-Null
    $sourceFiles = [Collections.Generic.List[IO.FileInfo]]::new()
    foreach ($folder in @("license_admin", "deployment", "docs")) {
        Get-ChildItem -LiteralPath (Join-Path $projectRoot $folder) -File -Recurse -Force |
            Where-Object { $_.Extension -notin @(".pyc", ".pyo") -and $_.FullName -notmatch '\\__pycache__\\' } |
            ForEach-Object { $sourceFiles.Add($_) }
    }
    foreach ($name in @("pyproject.toml", "README.md", "requirements.txt", "TMS_ADMIN_HANDOFF.md")) {
        $file = Get-Item -LiteralPath (Join-Path $projectRoot $name) -ErrorAction SilentlyContinue
        if ($file) { $sourceFiles.Add($file) }
    }
    $snapshot = @($sourceFiles | ForEach-Object {
        [pscustomobject]@{
            path = Get-RelativeProjectPath $_.FullName
            size = $_.Length
            sha256 = (Get-FileHash -LiteralPath $_.FullName -Algorithm SHA256).Hash.ToLowerInvariant()
        }
    } | Sort-Object path)
    $baseline = @{}
    if ($BaselineManifestPath) {
        foreach ($entry in (Get-Content -LiteralPath (Resolve-Path -LiteralPath $BaselineManifestPath) -Raw -Encoding utf8 | ConvertFrom-Json).files) {
            $baseline[$entry.path] = $entry.sha256
        }
    }
    $changed = @($snapshot | Where-Object { -not $baseline.ContainsKey($_.path) -or $baseline[$_.path] -ne $_.sha256 })
    $currentPaths = @{}; foreach ($entry in $snapshot) { $currentPaths[$entry.path] = $true }
    $removed = @($baseline.Keys | Where-Object { -not $currentPaths.ContainsKey($_) } | Sort-Object)
    foreach ($entry in $changed) {
        $source = Join-Path $projectRoot $entry.path.Replace("/", "\")
        $target = Join-Path $payloadRoot $entry.path.Replace("/", "\")
        New-Item -ItemType Directory -Path (Split-Path -Parent $target) -Force | Out-Null
        Copy-Item -LiteralPath $source -Destination $target -Force
    }
    $manifest = [ordered]@{ schema = 1; product = $product; version = $version; created_at = [DateTime]::UtcNow.ToString("o"); files = $changed; remove = $removed }
    $manifest | ConvertTo-Json -Depth 5 | Set-Content -LiteralPath (Join-Path $packageRoot "update-manifest.json") -Encoding utf8
    New-Item -ItemType Directory -Path $OutputDirectory,$snapshotRoot -Force | Out-Null
    $snapshotManifest = [ordered]@{ schema = 1; product = $product; version = $version; files = $snapshot }
    $snapshotManifest | ConvertTo-Json -Depth 5 | Set-Content -LiteralPath (Join-Path $snapshotRoot "Cinema-TMS-Admin-$version-files.json") -Encoding utf8
    $zip = Join-Path ([IO.Path]::GetFullPath($OutputDirectory)) ($packageName + ".zip")
    if (Test-Path -LiteralPath $zip) { Remove-Item -LiteralPath $zip -Force }
    Compress-Archive -LiteralPath $packageRoot -DestinationPath $zip -CompressionLevel Optimal
    $checksum = (Get-FileHash -LiteralPath $zip -Algorithm SHA256).Hash.ToLowerInvariant()
    "$checksum  $([IO.Path]::GetFileName($zip))" | Set-Content -LiteralPath ($zip + ".sha256") -Encoding ascii
    Write-Host "Cinema TMS Admin update package created: $zip"
    Write-Host "SHA-256: $checksum"
    Write-Host "Changed files: $($changed.Count); removed files: $($removed.Count); data and settings included: False"
} finally {
    $resolvedTemporary = [IO.Path]::GetFullPath($temporaryRoot)
    $systemTemporary = [IO.Path]::GetFullPath([IO.Path]::GetTempPath())
    if ($resolvedTemporary.StartsWith($systemTemporary, [StringComparison]::OrdinalIgnoreCase) -and (Test-Path -LiteralPath $resolvedTemporary)) {
        Remove-Item -LiteralPath $resolvedTemporary -Recurse -Force
    }
}
