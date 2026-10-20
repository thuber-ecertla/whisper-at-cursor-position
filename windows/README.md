# whisper-at-cursor-position — Windows

Press **F2**, speak, press **F2** again. The transcript is typed wherever your cursor is.
Runs Whisper on your GPU through [whisper.cpp](https://github.com/ggml-org/whisper.cpp) + Vulkan, so AMD, Nvidia and Intel cards all work.

## How it works

- `whisper_tray.py` — tray app. Starts `whisper-server.exe` with the model pre-loaded in VRAM, listens for the hotkey, records the microphone and types the result via `SendInput`.
- `server.py` — starts/stops `whisper-server.exe` (localhost only). It's tied to a Job Object, so it never outlives the tray app, even if the app crashes.
- `overlay.py` — the floating pill at the bottom of the screen: **● Recording 0:04**, **Transcribing…**. It's click-through and never takes focus.
- `typer.py` — types Unicode text directly (accents, ¿, ñ, emoji) regardless of keyboard layout.

## Requirements

- Windows 10/11, Python 3.9+
- A GPU with a Vulkan driver (the regular AMD/Nvidia/Intel driver includes it)
- To build whisper.cpp:
  ```powershell
  winget install Kitware.CMake KhronosGroup.VulkanSDK
  winget install Microsoft.VisualStudio.2022.BuildTools --override "--add Microsoft.VisualStudio.Workload.VCTools --includeRecommended --passive --wait"
  ```

## Installation

```powershell
cd windows
.\build_whisper_vulkan.ps1     # builds bin\whisper-server.exe (a few minutes)
.\install.ps1                  # venv, downloads the model (~3 GB), adds a Startup shortcut
```

`install.ps1` options: `-Model large-v3-turbo` (or `medium`, `small`, …) and `-NoStartup`.

No GPU? Instead of building, unzip `whisper-bin-x64.zip` from the [whisper.cpp releases](https://github.com/ggml-org/whisper.cpp/releases) into `windows\bin\`. The app itself doesn't change.

## Usage

| Key | Effect |
|-----|--------|
| `F2` | Start recording / stop and transcribe |
| `Esc` | Cancel the current recording (only captured while recording) |

The app lives in the notification area. New icons land in the overflow (**^**). Drag it onto the taskbar if you want it always visible. The icon is gray while loading, white when ready, red while recording and amber while transcribing. Right-click → **Quit** to exit, or **Open log**.

Start it manually (no console window):
```powershell
.\venv\Scripts\pythonw.exe whisper_tray.py
```
Or with a console to watch the log live:
```powershell
.\venv\Scripts\python.exe whisper_tray.py
```

Log: `%LOCALAPPDATA%\whisper-at-cursor\whisper.log`

## Configuration

Set these as user environment variables (System → Advanced → Environment Variables), then restart the app:

| Variable | Default | |
|----------|---------|-|
| `WHISPER_MODEL` | `large-v3` | Must match a `models\ggml-<name>.bin` file |
| `WHISPER_LANG` | `auto` | `auto`, or force one: `es`, `en`, … |
| `WHISPER_HOTKEY` | `f2` | Any [keyboard](https://github.com/boppreh/keyboard#api) hotkey, e.g. `ctrl+shift+space` |
| `WHISPER_PORT` | `8178` | Local port for whisper-server |

## Limitations

- While an app running **as administrator** is focused, Windows blocks both the hotkey and the typing from a non-admin process.
- The hotkey is swallowed, so F2 no longer reaches other apps (e.g. rename in Explorer, edit cell in Excel). Pick another key with `WHISPER_HOTKEY` if you need F2.
- A few programs (some games, remote desktop clients) ignore synthesized Unicode input.
