#requires -Version 5.1
<#
End-to-end installer test: install to a temp dir (path with a space), selftest, upgrade in place,
uninstall, and check user data survives. Leaves nothing behind.
  ./installer/test-installer.ps1 -Setup installer\Output\ScribSalmon-Setup-1.4.0.exe
#>
param([Parameter(Mandatory)][string]$Setup)
$ErrorActionPreference = 'Stop'
$ProgressPreference = 'SilentlyContinue'

$Setup = (Resolve-Path $Setup).Path
$tmp = if ($env:RUNNER_TEMP) { $env:RUNNER_TEMP } else { $env:TEMP }
$installDir = Join-Path $tmp 'ss install'
$logDir = Join-Path $tmp 'ss-installer-logs'
New-Item -ItemType Directory -Force $logDir | Out-Null
$uninstKey = 'HKCU:\Software\Microsoft\Windows\CurrentVersion\Uninstall\{BED9A63F-69FD-4F73-9969-C560612805CD}_is1'

if ((Test-Path $installDir) -or (Test-Path $uninstKey)) {
    throw "Refusing to run: an install already exists ($installDir or $uninstKey)"
}

# CreateProcess (UseShellExecute=$false) never shows the SmartScreen prompt a ShellExecute would
function Run([string]$exe, [string[]]$arguments, [int]$timeoutMs = 600000) {
    $psi = [Diagnostics.ProcessStartInfo]::new($exe)
    $psi.UseShellExecute = $false
    foreach ($a in $arguments) { $psi.ArgumentList.Add($a) }
    $p = [Diagnostics.Process]::Start($psi)
    if (-not $p.WaitForExit($timeoutMs)) { $p.Kill(); throw "timeout running $exe" }
    return $p.ExitCode
}

function Show-LogTail([string]$log) {
    if (Test-Path $log) { Write-Host "--- tail of $log"; Get-Content $log -Tail 25 | ForEach-Object { Write-Host $_ } }
}

function Install([string]$name, [string[]]$extra) {
    $log = Join-Path $logDir "$name.log"
    $rc = Run $Setup (@('/VERYSILENT', '/SUPPRESSMSGBOXES', '/NORESTART', '/SP-', "/DIR=$installDir", "/LOG=$log") + $extra)
    Show-LogTail $log
    if ($rc -ne 0) { throw "setup ($name) exit code $rc" }
}

function Selftest([string]$name) {
    $out = Join-Path $logDir "$name.json"
    $rc = Run (Join-Path $installDir 'ScribSalmon.exe') @('--selftest', $out) 180000
    if (Test-Path $out) { Get-Content $out | ForEach-Object { Write-Host $_ } }
    if ($rc -ne 0) { throw "selftest ($name) exit code $rc" }
}

$appData = Join-Path $env:APPDATA 'ScribSalmon'
$docs = Join-Path ([Environment]::GetFolderPath('MyDocuments')) 'ScribSalmon'
$appDataExisted = Test-Path $appData
$docsExisted = Test-Path $docs
$sentinel1 = Join-Path $appData 'ci-sentinel.txt'
$sentinel2 = Join-Path $docs 'ci-sentinel\meta.json'
$localApp = Join-Path $env:LOCALAPPDATA 'ScribSalmon'
$localAppExisted = Test-Path $localApp
$sentinel3 = Join-Path $localApp 'gpu-libs\x\manifest.json'

try {
    # (1) mark the setup as downloaded from the Internet, like a browser would
    Set-Content -Path $Setup -Stream Zone.Identifier -Value "[ZoneTransfer]`r`nZoneId=3"

    # (3) install
    Install 'install' @()

    # (4) files
    foreach ($f in 'ScribSalmon.exe', 'ScribSalmon.exe.config', 'LICENSE', 'THIRD_PARTY_NOTICES.txt', 'unins000.exe') {
        if (-not (Test-Path (Join-Path $installDir $f))) { throw "missing after install: $f" }
    }
    Write-Host 'OK: expected files installed'

    # (5) the installer must not propagate the Mark-of-the-Web to installed files
    $marked = Get-ChildItem $installDir -Recurse -File | Where-Object {
        ($_.Name -eq 'ScribSalmon.exe.config' -or $_.Extension -eq '.dll') -and
        (Get-Item $_.FullName -Stream Zone.Identifier -ErrorAction SilentlyContinue)
    }
    if ($marked) { throw "Zone.Identifier present on: $(($marked | Select-Object -First 5).FullName -join ', ')" }
    Write-Host 'OK: no Zone.Identifier on installed files'

    # (6) selftest
    Selftest 'selftest-install'

    # (7) upgrade in place
    Install 'upgrade' @('/UPDATE')
    Selftest 'selftest-upgrade'

    # (8) user data sentinels
    New-Item -ItemType Directory -Force $appData | Out-Null
    Set-Content $sentinel1 'keep'
    New-Item -ItemType Directory -Force (Split-Path $sentinel2) | Out-Null
    Set-Content $sentinel2 '{}'
    New-Item -ItemType Directory -Force (Split-Path $sentinel3) | Out-Null
    Set-Content $sentinel3 '{}'

    # (9) uninstall
    $unins = Join-Path $installDir 'unins000.exe'
    $rc = Run $unins @('/VERYSILENT', '/SUPPRESSMSGBOXES', '/NORESTART')
    if ($rc -ne 0) { throw "uninstall exit code $rc" }
    $deadline = (Get-Date).AddMinutes(3)
    while ((Test-Path $installDir) -and ((Get-Date) -lt $deadline)) { Start-Sleep -Seconds 2 }
    if (Test-Path $installDir) {
        Write-Host 'Leftovers:'; Get-ChildItem $installDir -Recurse | Select-Object -First 30 | ForEach-Object { Write-Host $_.FullName }
        throw 'install dir still present after uninstall'
    }
    Write-Host 'OK: install dir removed'

    # (10) data kept, registration gone
    if (-not (Test-Path $sentinel1)) { throw 'settings sentinel deleted by uninstall' }
    if (-not (Test-Path $sentinel2)) { throw 'notes sentinel deleted by uninstall' }
    if (Test-Path $uninstKey) { throw 'uninstall registry key still present' }
    Write-Host 'OK: user data kept, uninstall key removed'
    if (Test-Path $sentinel3) { throw 'downloaded GPU libraries (gpu-libs) not removed by silent uninstall' }
    Write-Host 'OK: downloaded GPU libraries removed'
    Write-Host 'INSTALLER TEST PASSED'
}
finally {
    # (11) clean up everything this test created
    if (Test-Path $installDir) {
        $u = Join-Path $installDir 'unins000.exe'
        if (Test-Path $u) { try { Run $u @('/VERYSILENT', '/SUPPRESSMSGBOXES', '/NORESTART') 120000 | Out-Null } catch { } }
        Start-Sleep -Seconds 3
        Remove-Item $installDir -Recurse -Force -ErrorAction SilentlyContinue
    }
    Remove-Item $sentinel1 -Force -ErrorAction SilentlyContinue
    Remove-Item (Split-Path $sentinel2) -Recurse -Force -ErrorAction SilentlyContinue
    if (-not $appDataExisted) { Remove-Item $appData -Recurse -Force -ErrorAction SilentlyContinue }
    Remove-Item (Join-Path $localApp 'gpu-libs') -Recurse -Force -ErrorAction SilentlyContinue
    if (-not $localAppExisted) { Remove-Item $localApp -Recurse -Force -ErrorAction SilentlyContinue }
    if (-not $docsExisted) { Remove-Item $docs -Recurse -Force -ErrorAction SilentlyContinue }
    Remove-Item $uninstKey -Recurse -Force -ErrorAction SilentlyContinue
    Remove-Item $logDir -Recurse -Force -ErrorAction SilentlyContinue
}
