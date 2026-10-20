# install.ps1 — Set up the Windows version: venv, model download, Startup shortcut
# Run build_whisper_vulkan.ps1 first (or drop a prebuilt whisper-server.exe + DLLs into .\bin).
param(
    [string]$Model = "large-v3",   # ggml model name, see https://huggingface.co/ggerganov/whisper.cpp
    [switch]$NoStartup
)
# Not "Stop": in Windows PowerShell 5.1 that turns any native-tool stderr output into an error.
# Native commands are checked via $LASTEXITCODE instead.
$ErrorActionPreference = "Continue"

$ScriptDir = $PSScriptRoot
$Venv      = Join-Path $ScriptDir "venv"
$ModelDir  = Join-Path $ScriptDir "models"
$ModelFile = Join-Path $ModelDir "ggml-$Model.bin"

Write-Host "==> Creating virtual environment..."
if (-not (Test-Path $Venv)) { py -3 -m venv $Venv }
& "$Venv\Scripts\python.exe" -m pip install --upgrade pip
& "$Venv\Scripts\python.exe" -m pip install -r (Join-Path $ScriptDir "requirements.txt")
if ($LASTEXITCODE) { throw "pip install failed" }

if (-not (Test-Path $ModelFile)) {
    Write-Host "==> Downloading model $Model..."
    New-Item -ItemType Directory -Force $ModelDir | Out-Null
    curl.exe -L --fail -o "$ModelFile.part" "https://huggingface.co/ggerganov/whisper.cpp/resolve/main/ggml-$Model.bin"
    if ($LASTEXITCODE) { throw "model download failed" }
    Move-Item "$ModelFile.part" $ModelFile -ErrorAction Stop
}

if (-not (Test-Path (Join-Path $ScriptDir "bin\whisper-server.exe"))) {
    Write-Warning "bin\whisper-server.exe is missing - run build_whisper_vulkan.ps1."
}

if (-not $NoStartup) {
    Write-Host "==> Adding Startup shortcut..."
    $Lnk = Join-Path ([Environment]::GetFolderPath("Startup")) "Whisper at Cursor.lnk"
    $Shell = New-Object -ComObject WScript.Shell
    $Sc = $Shell.CreateShortcut($Lnk)
    $Sc.TargetPath       = "$Venv\Scripts\pythonw.exe"
    $Sc.Arguments        = "`"$(Join-Path $ScriptDir 'whisper_tray.py')`""
    $Sc.WorkingDirectory = $ScriptDir
    $Sc.Description      = "Whisper voice input (F2)"
    $Sc.Save()
    Write-Host "    $Lnk"
}

Write-Host ""
Write-Host "Done! Start it now with:"
Write-Host "  & `"$Venv\Scripts\pythonw.exe`" `"$ScriptDir\whisper_tray.py`""
if ($Model -ne "large-v3") { Write-Host "  (set WHISPER_MODEL=$Model in your user environment variables)" }
Write-Host ""
Write-Host "The tray icon lands in the overflow (^). Drag it onto the taskbar to keep it visible."
