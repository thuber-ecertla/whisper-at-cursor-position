# build_whisper_vulkan.ps1 — Build whisper-server.exe with the Vulkan backend (AMD/Intel/Nvidia GPUs)
# Prerequisites (winget):
#   winget install Kitware.CMake KhronosGroup.VulkanSDK
#   winget install Microsoft.VisualStudio.2022.BuildTools --override "--add Microsoft.VisualStudio.Workload.VCTools --includeRecommended --passive --wait"
# Not "Stop": in Windows PowerShell 5.1 that turns any native-tool stderr output into an error.
# Native commands are checked via $LASTEXITCODE instead.
$ErrorActionPreference = "Continue"

$ScriptDir  = $PSScriptRoot
$Tag        = "v1.9.4"
$SrcDir     = Join-Path $ScriptDir "whisper.cpp"
$BuildDir   = Join-Path $SrcDir "build"
$BinDir     = Join-Path $ScriptDir "bin"

# Tools installed in this session aren't on PATH yet — pick them up from the machine environment
if (-not $env:VULKAN_SDK) {
    $env:VULKAN_SDK = [Environment]::GetEnvironmentVariable("VULKAN_SDK", "Machine")
}
if (-not $env:VULKAN_SDK) { throw "Vulkan SDK not found (VULKAN_SDK is not set). Install KhronosGroup.VulkanSDK." }
$env:PATH = "$env:VULKAN_SDK\Bin;$env:ProgramFiles\CMake\bin;$env:PATH"
if (-not (Get-Command cmake -ErrorAction SilentlyContinue)) { throw "cmake not found. Install Kitware.CMake." }

if (-not (Test-Path $SrcDir)) {
    Write-Host "==> Cloning whisper.cpp $Tag..."
    git clone --depth 1 --branch $Tag https://github.com/ggml-org/whisper.cpp $SrcDir
    if ($LASTEXITCODE) { throw "git clone failed" }
}

Write-Host "==> Configuring (Vulkan SDK: $env:VULKAN_SDK)..."
cmake -S $SrcDir -B $BuildDir -G "Visual Studio 17 2022" -A x64 `
    -DGGML_VULKAN=ON -DWHISPER_BUILD_EXAMPLES=ON -DWHISPER_BUILD_TESTS=OFF -DBUILD_SHARED_LIBS=ON
if ($LASTEXITCODE) { throw "cmake configure failed" }

Write-Host "==> Building (this takes a few minutes)..."
cmake --build $BuildDir --config Release --target whisper-server -j
if ($LASTEXITCODE) { throw "cmake build failed" }

Write-Host "==> Copying binaries to $BinDir..."
New-Item -ItemType Directory -Force $BinDir | Out-Null
$Out = Join-Path $BuildDir "bin\Release"
Copy-Item (Join-Path $Out "whisper-server.exe"), (Join-Path $Out "*.dll") $BinDir -Force -ErrorAction Stop

Write-Host ""
Write-Host "Done: $BinDir\whisper-server.exe"
