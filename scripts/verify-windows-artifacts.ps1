$ErrorActionPreference = 'Stop'

$Root = Split-Path -Parent (Split-Path -Parent $MyInvocation.MyCommand.Path)
$Sidecar = Join-Path $Root 'src-tauri\binaries\story-guard-backend-x86_64-pc-windows-msvc.exe'
$Installers = Join-Path $Root 'src-tauri\target\release\bundle\nsis'

if (-not (Test-Path $Sidecar)) {
  throw "Windows sidecar not found: $Sidecar"
}
$installerFiles = @(Get-ChildItem -Path $Installers -Filter '*.exe' -File -ErrorAction SilentlyContinue)
if ($installerFiles.Count -eq 0) {
  throw "NSIS installer not found in $Installers"
}

Write-Output "Windows sidecar: $($Sidecar) ($((Get-Item $Sidecar).Length) bytes)"
foreach ($installer in $installerFiles) {
  $hash = (Get-FileHash -Algorithm SHA256 $installer.FullName).Hash
  Write-Output "Installer: $($installer.FullName) ($($installer.Length) bytes) SHA256 $hash"
}
