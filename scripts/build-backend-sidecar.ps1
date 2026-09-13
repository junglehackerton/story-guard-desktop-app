$ErrorActionPreference = 'Stop'

$Root = Split-Path -Parent (Split-Path -Parent $MyInvocation.MyCommand.Path)
Set-Location $Root
$env:PYINSTALLER_CONFIG_DIR = if ($env:PYINSTALLER_CONFIG_DIR) { $env:PYINSTALLER_CONFIG_DIR } else { Join-Path $Root '.pyinstaller-config' }

$PyInstaller = Join-Path $Root '.venv\Scripts\pyinstaller.exe'
if (-not (Test-Path $PyInstaller)) {
  Write-Error 'PyInstaller is not installed. Run: .venv\Scripts\python.exe -m pip install -r backend\requirements.txt'
}

$TargetTriple = 'x86_64-pc-windows-msvc'
$BinaryDir = Join-Path $Root 'src-tauri\binaries'
$BuildDir = Join-Path $Root 'build\pyinstaller'
New-Item -ItemType Directory -Force -Path $BinaryDir, $BuildDir | Out-Null

& $PyInstaller `
  --clean `
  --onefile `
  --name "story-guard-backend-$TargetTriple" `
  --distpath $BinaryDir `
  --workpath $BuildDir `
  --specpath $BuildDir `
  --collect-binaries llama_cpp `
  backend/sidecar.py

$Output = Join-Path $BinaryDir "story-guard-backend-$TargetTriple.exe"
if (-not (Test-Path $Output)) {
  Write-Error "Sidecar build did not produce $Output"
}
Write-Output "Built $Output"
