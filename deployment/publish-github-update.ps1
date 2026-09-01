param(
    [switch]$SkipTests,
    [switch]$SkipSourcePush
)

$ErrorActionPreference = "Stop"
$projectRoot = (Resolve-Path (Join-Path $PSScriptRoot "..")).Path
$repository = "Seikoz/Cinema-Tms-Updates"
$python = Join-Path $projectRoot ".python\python.exe"
if (-not (Test-Path -LiteralPath $python)) { throw "Cinema TMS Admin Python runtime was not found: $python" }
if (-not (Get-Command git -ErrorAction SilentlyContinue)) { throw "Git is required." }
$ghCommand = Get-Command gh -ErrorAction SilentlyContinue
$portableGh = [IO.Path]::GetFullPath((Join-Path $projectRoot "..\Tools\GitHubCLI\gh.exe"))
$gh = if ($ghCommand) { $ghCommand.Source } elseif (Test-Path -LiteralPath $portableGh) { $portableGh } else { "" }
if (-not $gh) { throw "GitHub CLI is required. Install it or place gh.exe at: $portableGh" }

Push-Location $projectRoot
try {
    if ((git status --porcelain).Count -ne 0) { throw "Commit all source changes before publishing." }
    if ((git branch --show-current).Trim() -ne "main") { throw "Publish from the main branch." }
    $version = (& $python -c "from license_admin.version import __version__; print(__version__)" | Select-Object -Last 1).Trim()
    if (-not $version) { throw "Cinema TMS Admin version could not be read." }

    if (-not $SkipTests) {
        & $python -m unittest discover -s automated_tests -p "test_*.py"
        if ($LASTEXITCODE -ne 0) { throw "Cinema TMS Admin tests failed." }
    }
    & (Join-Path $PSScriptRoot "build-update-package.ps1")
    if ($LASTEXITCODE -ne 0) { throw "Update package build failed." }

    $package = Join-Path $projectRoot "dist\updates\Cinema-TMS-Admin-Update-$version.zip"
    $checksum = "$package.sha256"
    if (-not (Test-Path -LiteralPath $package) -or -not (Test-Path -LiteralPath $checksum)) {
        throw "Verified update assets were not created."
    }

    & $gh auth status --hostname github.com
    if ($LASTEXITCODE -ne 0) { throw "Sign in on this development PC with: gh auth login" }

    if (-not $SkipSourcePush) {
        git fetch origin main
        if ($LASTEXITCODE -ne 0) { throw "Source fetch failed." }
        $counts = (git rev-list --left-right --count origin/main...HEAD).Trim() -split '\s+'
        if ([int]$counts[0] -gt 0) { throw "origin/main has commits missing locally. Pull before publishing." }
        git push origin main
        if ($LASTEXITCODE -ne 0) { throw "Source push failed." }
    }

    $sourceTag = "v$version"
    $head = (git rev-parse HEAD).Trim()
    $tagCommit = (git rev-list -n 1 $sourceTag 2>$null | Select-Object -Last 1)
    if ($tagCommit) {
        if ($tagCommit.Trim() -ne $head) { throw "$sourceTag already points to a different commit." }
    } else {
        git tag -a $sourceTag -m "Cinema TMS Admin $version"
        if ($LASTEXITCODE -ne 0) { throw "Source tag creation failed." }
    }
    if (-not $SkipSourcePush) {
        git push origin $sourceTag
        if ($LASTEXITCODE -ne 0) { throw "Source tag push failed." }
    }

    $releaseTag = "admin-v$version"
    & $gh release view $releaseTag --repo $repository *> $null
    if ($LASTEXITCODE -ne 0) {
        $arguments = @("release", "create", $releaseTag, "--repo", $repository, "--title", "Cinema TMS Admin $version", "--notes", "Cinema TMS Admin verified online update package.")
        if ($version -match "(?:a|b|rc)\d+$") { $arguments += "--prerelease" }
        & $gh @arguments
        if ($LASTEXITCODE -ne 0) { throw "GitHub Release creation failed." }
    }
    & $gh release upload $releaseTag $package $checksum --repo $repository --clobber
    if ($LASTEXITCODE -ne 0) { throw "GitHub Release asset upload failed." }
    Write-Host "Published Cinema TMS Admin $version to $repository ($releaseTag)."
} finally {
    Pop-Location
}
