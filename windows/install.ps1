# install.ps1 — Set up the Windows version: venv, model download, Startup shortcut
# Run build_whisper_vulkan.ps1 first (or drop a prebuilt whisper-server.exe + DLLs into .\bin).
# -Groq: transcribe in the cloud through Groq's API instead - no build, no model download.
param(
    [string]$Model = "large-v3",   # ggml model name, see https://huggingface.co/ggerganov/whisper.cpp
    [switch]$NoStartup,
    [switch]$Groq
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

if ($Groq) {
    Write-Host "==> Groq backend (cloud transcription)"
    $Key = [Environment]::GetEnvironmentVariable("GROQ_API_KEY", "User")
    if (-not $Key) { $Key = $env:GROQ_API_KEY }
    if (-not $Key) {
        $Key = "$(Read-Host 'Paste your Groq API key (https://console.groq.com/keys)')".Trim()
        if (-not $Key) { throw "no API key entered" }
        if ($Key -notlike "gsk_*") { Write-Warning "Groq keys normally start with gsk_ - double-check it." }
        [Environment]::SetEnvironmentVariable("GROQ_API_KEY", $Key, "User")
        Write-Host "    GROQ_API_KEY saved as a user environment variable"
    }
    [Environment]::SetEnvironmentVariable("WHISPER_BACKEND", "groq", "User")
    # Already-running processes (this shell, Explorer) keep their old environment; set it here too
    $env:GROQ_API_KEY = $Key
    $env:WHISPER_BACKEND = "groq"
} else {
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
if ($Groq) {
    Write-Host "  Backend: Groq (set WHISPER_BACKEND=local in your user environment variables to switch back)"
} elseif ($Model -ne "large-v3") {
    Write-Host "  (set WHISPER_MODEL=$Model in your user environment variables)"
}
Write-Host ""
Write-Host "The tray icon lands in the overflow (^). Drag it onto the taskbar to keep it visible."
