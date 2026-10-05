#requires -Version 5.1
<#
Builds installer\Output\ScribSalmon-Setup-<Version>.exe with a pinned Inno Setup compiler.
Run after pyinstaller + the LICENSE / THIRD_PARTY_NOTICES.txt copy step.
  ./installer/build-installer.ps1 -Version 1.4.0
#>
param(
    [Parameter(Mandatory)][string]$Version,
    [string]$DistDir = 'dist\ScribSalmon',
    [string]$Iscc
)
$ErrorActionPreference = 'Stop'
$ProgressPreference = 'SilentlyContinue'

$InnoVersion = '6.7.3'
$InnoUrl = "https://github.com/jrsoftware/issrc/releases/download/is-6_7_3/innosetup-$InnoVersion.exe"
$InnoSha256 = '9C73C3BAE7ED48D44112A0F48E66742C00090BDB5BEF71D9D3C056C66E97B732'

$root = Split-Path -Parent $PSScriptRoot
$base = if ($env:RUNNER_TEMP) { $env:RUNNER_TEMP } else { $env:TEMP }

# ISCC.exe carries no version resource; installed Inno registers its version in the Uninstall key
function Get-IsccVersion([string]$path) {
    $dir = Split-Path -Parent $path
    foreach ($k in 'HKLM:\SOFTWARE\WOW6432Node\Microsoft\Windows\CurrentVersion\Uninstall\Inno Setup 6_is1',
                   'HKLM:\SOFTWARE\Microsoft\Windows\CurrentVersion\Uninstall\Inno Setup 6_is1',
                   'HKCU:\SOFTWARE\Microsoft\Windows\CurrentVersion\Uninstall\Inno Setup 6_is1') {
        $p = Get-ItemProperty $k -ErrorAction SilentlyContinue
        if ($p -and $p.InstallLocation -and ($p.InstallLocation.TrimEnd('\') -ieq $dir.TrimEnd('\'))) { return $p.DisplayVersion }
    }
    return 'unknown'
}

function Find-Iscc {
    if ($Iscc) { return $Iscc }
    $pinned = Join-Path $base "InnoSetup-$InnoVersion\ISCC.exe"
    if (Test-Path $pinned) { return $pinned }
    # a preinstalled compiler is fine only if it is exactly the pinned version
    foreach ($p in @("${env:ProgramFiles(x86)}\Inno Setup 6\ISCC.exe", "$env:ProgramFiles\Inno Setup 6\ISCC.exe")) {
        if ((Test-Path $p) -and ((Get-IsccVersion $p) -like "$InnoVersion*")) { return $p }
    }
    return $null
}

function Install-Inno {
    $dir = Join-Path $base "InnoSetup-$InnoVersion"
    $exe = Join-Path $base "innosetup-$InnoVersion.exe"
    Write-Host "Downloading Inno Setup $InnoVersion"
    Invoke-WebRequest -Uri $InnoUrl -OutFile $exe -UseBasicParsing
    $h = (Get-FileHash $exe -Algorithm SHA256).Hash
    if ($h -ne $InnoSha256) { throw "Inno Setup installer hash mismatch: $h" }
    $p = Start-Process $exe -ArgumentList '/VERYSILENT', '/SUPPRESSMSGBOXES', '/NORESTART', '/SP-', '/CURRENTUSER', "/DIR=$dir" -Wait -PassThru
    if ($p.ExitCode -ne 0) { throw "Inno Setup install failed: exit $($p.ExitCode)" }
    $iscc = Join-Path $dir 'ISCC.exe'
    if (-not (Test-Path $iscc)) { throw "ISCC.exe not found after install in $dir" }
    return $iscc
}

$compiler = Find-Iscc
if (-not $compiler) {
    try { $compiler = Install-Inno }
    catch {
        Write-Warning "Pinned download failed ($_); falling back to chocolatey"
        choco install innosetup --version=$InnoVersion -y --no-progress
        if ($LASTEXITCODE -ne 0) { throw 'choco install innosetup failed' }
        $compiler = "${env:ProgramFiles(x86)}\Inno Setup 6\ISCC.exe"
    }
}
if (-not (Test-Path $compiler)) { throw "ISCC not found: $compiler" }
Write-Host "Using $compiler (Inno Setup $(Get-IsccVersion $compiler))"

$dist = if ([IO.Path]::IsPathRooted($DistDir)) { $DistDir } else { Join-Path $root $DistDir }
$dist = (Resolve-Path $dist).Path
$numeric = (($Version -split '[-+]')[0]) + '.0'

& $compiler /Qp "/DAppVersion=$Version" "/DAppVersionNumeric=$numeric" "/DDistDir=$dist" (Join-Path $root 'installer\ScribSalmon.iss')
if ($LASTEXITCODE -ne 0) { throw "ISCC failed: exit $LASTEXITCODE" }
Get-ChildItem (Join-Path $root 'installer\Output') -Filter 'ScribSalmon-Setup-*.exe' | ForEach-Object { Write-Host "Built $($_.FullName) ($($_.Length) bytes)" }
