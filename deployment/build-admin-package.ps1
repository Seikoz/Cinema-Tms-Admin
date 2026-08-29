param(
    [string]$OutputDirectory = (Join-Path $PSScriptRoot "..\dist")
)

$ErrorActionPreference = "Stop"
$projectRoot = (Resolve-Path (Join-Path $PSScriptRoot "..")).Path
$runtimeRoot = Join-Path $projectRoot ".python"
$runtimePython = Join-Path $runtimeRoot "python.exe"
if (-not (Test-Path -LiteralPath $runtimePython)) { throw "Prepare the Cinema TMS Admin offline Python runtime before building the package." }
$escapedProjectRoot = $projectRoot.Replace("'", "''")
$versionText = (& $runtimePython -c "import sys; sys.path.insert(0, r'$escapedProjectRoot'); from license_admin.version import __version__; print(__version__)" | Select-Object -Last 1).Trim()
if (-not $versionText) { throw "Cinema TMS version could not be read." }
$packageName = "Cinema-TMS-Admin-$versionText-Windows-x64"
$temporaryRoot = Join-Path ([IO.Path]::GetTempPath()) ("CinemaTMSLicenseManager-" + [guid]::NewGuid().ToString("N"))
$bundleRoot = Join-Path $temporaryRoot $packageName
$outputRoot = [IO.Path]::GetFullPath($OutputDirectory)

try {
    New-Item -ItemType Directory -Path (Join-Path $bundleRoot "deployment"), (Join-Path $bundleRoot "data") -Force | Out-Null
    Copy-Item -LiteralPath $runtimeRoot -Destination $bundleRoot -Recurse -Force
    Copy-Item -LiteralPath (Join-Path $projectRoot "license_admin") -Destination $bundleRoot -Recurse -Force
    Copy-Item -LiteralPath (Join-Path $projectRoot "deployment\Cinema-TMS-Admin.vbs"), (Join-Path $projectRoot "deployment\Cinema-TMS-Admin.cmd"), (Join-Path $projectRoot "deployment\apply-update.ps1") -Destination (Join-Path $bundleRoot "deployment") -Force
    Copy-Item -LiteralPath (Join-Path $projectRoot "deployment\README.md") -Destination $bundleRoot -Force
    Get-ChildItem -LiteralPath $bundleRoot -Directory -Recurse -Filter "__pycache__" | Remove-Item -Recurse -Force
    Get-ChildItem -LiteralPath $bundleRoot -File -Recurse -Force |
        Where-Object { $_.Extension -in @(".pyc", ".pyo") } |
        Remove-Item -Force

    $manifestPath = Join-Path $bundleRoot "manager-manifest.json"
    $bundlePrefix = [IO.Path]::GetFullPath($bundleRoot).TrimEnd("\") + "\"
    $manifest = Get-ChildItem -LiteralPath $bundleRoot -File -Recurse -Force | Where-Object { $_.FullName -ne $manifestPath } | ForEach-Object {
        $fullPath = [IO.Path]::GetFullPath($_.FullName)
        if (-not $fullPath.StartsWith($bundlePrefix, [StringComparison]::OrdinalIgnoreCase)) { throw "Manager package file escapes its root: $fullPath" }
        [pscustomobject]@{
            path = $fullPath.Substring($bundlePrefix.Length).Replace("\", "/")
            size = $_.Length
            sha256 = (Get-FileHash -LiteralPath $fullPath -Algorithm SHA256).Hash.ToLowerInvariant()
        }
    }
    $manifest | ConvertTo-Json -Depth 3 | Set-Content -LiteralPath $manifestPath -Encoding utf8
    $bundleFiles = @(Get-ChildItem -LiteralPath $bundleRoot -File -Recurse -Force)
    Write-Host "License manager bundle files before archive: $($bundleFiles.Count)"
    if ($bundleFiles.Count -eq 0) { throw "License manager bundle contains no files before archive creation." }
    New-Item -ItemType Directory -Path $outputRoot -Force | Out-Null
    $zipPath = Join-Path $outputRoot ($packageName + ".zip")
    if (Test-Path -LiteralPath $zipPath) { Remove-Item -LiteralPath $zipPath -Force }
    & tar.exe -a -c -f $zipPath -C $temporaryRoot $packageName
    if ($LASTEXITCODE -ne 0) { throw "License manager ZIP creation failed with exit code $LASTEXITCODE." }
    Add-Type -AssemblyName System.IO.Compression.FileSystem
    $archive = [IO.Compression.ZipFile]::OpenRead($zipPath)
    try {
        $fileEntries = @($archive.Entries | Where-Object { $_.Length -gt 0 })
        $pythonEntry = $archive.Entries | Where-Object { $_.FullName -eq "$packageName/.python/python.exe" } | Select-Object -First 1
        $managerEntry = $archive.Entries | Where-Object { $_.FullName -eq "$packageName/license_admin/manager.pyw" } | Select-Object -First 1
        if ($fileEntries.Count -eq 0 -or -not $pythonEntry -or -not $managerEntry) {
            throw "License manager archive validation failed: runtime or manager source is missing."
        }
    } finally {
        $archive.Dispose()
    }
    Write-Host "License manager package created: $zipPath"
    Write-Host "Private signing key included: False"
} finally {
    $resolvedTemporary = [IO.Path]::GetFullPath($temporaryRoot)
    $systemTemporary = [IO.Path]::GetFullPath([IO.Path]::GetTempPath())
    if ($resolvedTemporary.StartsWith($systemTemporary, [StringComparison]::OrdinalIgnoreCase) -and (Test-Path -LiteralPath $resolvedTemporary)) {
        Remove-Item -LiteralPath $resolvedTemporary -Recurse -Force
    }
}
