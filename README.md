<p align="center">
  <img src="assets/icon-salmon-dark-256.png" alt="ScribSalmon" width="128">
</p>

<h1 align="center">ScribSalmon</h1>

<p align="center">
  Windows meeting-notes app: capture system audio + microphone, transcribe (live or after you stop),
  then get a numbered, editable Claude summary. Built with Thai in mind.
</p>

<p align="center">
  <a href="https://github.com/akirasane/ScribSalmon/actions/workflows/ci.yml"><img src="https://github.com/akirasane/ScribSalmon/actions/workflows/ci.yml/badge.svg" alt="CI"></a>
  <a href="https://github.com/akirasane/ScribSalmon/releases/latest"><img src="https://img.shields.io/github/v/release/akirasane/ScribSalmon" alt="Latest release"></a>
  <img src="https://img.shields.io/badge/platform-Windows%2010%2F11-blue" alt="Windows">
  <img src="https://img.shields.io/badge/license-MIT-green" alt="MIT">
</p>

---

## Features

- **Notes list** - create, search, edit, rename, delete, export to Markdown. Each note is a plain folder on disk.
- **Record / Stop** - captures **system audio (WASAPI loopback)** and **microphone** at once, mixed to 16 kHz mono. Works with Teams, Zoom, Meet, browser calls, anything you can hear.
- **Live or after-stop transcription** - transcribe in ~6 s chunks while recording, or record only and transcribe after Stop.
- **Import audio (WAV/MP3/M4A/FLAC/OGG...)** - add an existing audio file to a note.
- **Refine** - re-transcribes the whole recording in one pass (more accurate than live chunks).
- **Check words** - Claude flags garbled phrases (typical for Thai); you pick option 1-3, keep the original, or type your own.
- **Summary** - numbered Overview / Key Points / Decisions / Action Items / Open Questions / Needs Review. The prompt is **Thai-aware and fully editable**.
- **Two transcription engines** - local `faster-whisper` (offline, GPU used automatically if available) or OpenAI Whisper API.
- **GPU note** - GPU transcription needs an NVIDIA driver (528.33+) and the cuBLAS 12 libraries, which Settings -> GPU can download in one click (see [GPU acceleration](#gpu-acceleration)); otherwise ScribSalmon falls back to CPU automatically (Settings -> Device). cuDNN is not needed.
- **Two summary backends** - the local **Claude Code CLI** (uses your existing login, no API key) or the **Anthropic API**.
- **Thai accuracy presets** - Thai fine-tuned Whisper (Thonburian), `large-v3`, `large-v3-turbo`, custom model id/folder, and a *Names & terms* hint list.
- Salmon-coloured dark UI (React + Tailwind v4), custom logo and icons, dark title bar.

> Only record meetings where **all attendees consent**.

## Download

Go to the [**Releases**](https://github.com/akirasane/ScribSalmon/releases/latest) page and pick one:

**Installer (recommended)** - `ScribSalmon-Setup-X.Y.Z.exe`

1. Run it. It installs for the current user only (`%LOCALAPPDATA%\Programs\ScribSalmon`, no admin rights) and adds a Start menu entry (desktop shortcut optional).
2. Start ScribSalmon from the Start menu. Future versions are offered inside the app (see [Updates](#updates)).
3. To uninstall use *Settings -> Apps -> ScribSalmon*. Your notes (`Documents\ScribSalmon`) are kept; the uninstaller asks whether to also delete settings (including saved API keys) in `%APPDATA%\ScribSalmon`.

Upgrading from 1.3.0 (zip): 1.3.0 cannot update itself, so install 1.4.0 once with the installer. Your notes and settings are picked up automatically; you can then delete the old extracted folder.

**Portable zip** - `ScribSalmon-vX.Y.Z-windows-x64.zip`: extract anywhere and run `ScribSalmon.exe`. No updater; download new versions yourself.

`SHA256SUMS.txt` on each release lists the SHA-256 of both files (`Get-FileHash <file>` to compare).

Requirements: Windows 10/11 x64 with the **Microsoft Edge WebView2 Runtime** (preinstalled on Windows 11 and current Windows 10).
Windows SmartScreen may warn because the installer and exe are unsigned - *More info -> Run anyway*.

For summaries you need **one** of:
- [Claude Code](https://claude.com/claude-code) installed and logged in (`claude` on `PATH`), or
- an Anthropic API key (Settings).

The first local transcription downloads the selected Whisper model from Hugging Face (`small` ~ 500 MB; Thai fine-tuned medium ~ 1.5 GB).

## Run from source

Requirements: Windows, Python 3.12, Node.js 20.19+ (22 recommended).

```powershell
py -3.12 -m venv .venv
.venv\Scripts\pip install -r requirements.txt
cd web
npm install
npm run build
cd ..
.venv\Scripts\python main.py
```

### Develop the UI (hot reload)

```powershell
cd web
npm run dev                         # http://127.0.0.1:5173 - works in a normal browser with a mock backend
.venv\Scripts\python main.py --dev  # real backend, UI served by Vite, devtools enabled
```

`npm run typecheck` runs the TypeScript check.

## Usage

1. **New note** (sidebar) -> optionally rename it.
2. Pick sources in the control bar: **System** and/or **Mic**, and whether to transcribe **live**.
3. **Record**, then **Stop**. You can record several parts into the same note or add a WAV.
4. If you recorded without live mode, transcription runs after Stop.
5. Improve the text: **Refine** for a single-pass re-transcription, **Check words** to fix garbled phrases.
6. **Summarize** to generate the Markdown summary. Edit either pane freely - changes are saved to disk.
7. **Export** writes the note as `.md`.

## Settings

| Setting | Meaning |
|---|---|
| Engine | `local` (faster-whisper) or `openai` (Whisper API) |
| Language | Auto-detect, Thai, or English. **Set Thai for Thai meetings.** |
| Local Whisper model | `tiny` ... `large-v3-turbo`, or the Thai fine-tuned preset |
| Custom model | Any faster-whisper model id / folder; overrides the dropdown |
| Names & terms | People / products / jargon, passed to Whisper and the word check as a hint |
| Summary backend | `auto` (CLI if installed, else API), `cli`, or `api` |
| Summary prompt | Editable; use `{transcript}` as a placeholder, otherwise the transcript is appended. Empty = built-in default |
| Claude model | Model used for the API backend (default `claude-sonnet-5-5`) |
| API keys | Anthropic / OpenAI. Also read from `ANTHROPIC_API_KEY` / `OPENAI_API_KEY` |

## Better Thai accuracy

- Settings -> Local Whisper model: `large-v3-turbo`, `large-v3`, or **Thai fine-tuned medium** (Thonburian Whisper). Set Language to **Thai** rather than Auto.
- Fill **Names & terms** with the spellings you want.
- Use **Refine** after recording, then **Check words**.
- The default summary prompt repairs obviously broken Thai from context and lists doubtful phrases under *Needs Review*.

## Where data lives

| What | Location |
|---|---|
| Notes | `ScribSalmon\<timestamp>\` inside your Windows Documents folder (OneDrive-redirected locations are honored); set `SCRIBSALMON_DATA_DIR` to use any other folder |
| Settings (API keys encrypted with Windows DPAPI) | `%APPDATA%\ScribSalmon\settings.json` |
| Log files (rotating, secrets redacted) | `%APPDATA%\ScribSalmon\logs\scribsalmon.log` (plus `crash.log` for native crashes) |
| Downloaded NVIDIA GPU libraries (optional) | `%LOCALAPPDATA%\ScribSalmon\gpu-libs` |
| Whisper models | Hugging Face cache (`~\.cache\huggingface`) |

Each note folder contains `meta.json`, `rec_001.wav ...`, `transcript.txt`, `summary.md`.
Old `VoiceRecog` folders are migrated automatically on first launch.

The installed app lives in `%LOCALAPPDATA%\Programs\ScribSalmon`; nothing is written there at runtime, so uninstalling or updating never touches your notes or settings.

## GPU acceleration

The only requirements are an NVIDIA GPU with a driver of version 528.33 or newer and the **cuBLAS 12** libraries. cuDNN is **not** used and you do not need to install the CUDA toolkit.

- **One click:** *Settings -> GPU -> Download GPU libraries* downloads 553 MB (about 735 MB on disk) from PyPI (the `nvidia-cublas-cu12` package, published by NVIDIA). The download is pinned to an exact size and SHA-256, and is stored in `%LOCALAPPDATA%\ScribSalmon\gpu-libs`. If you already have a CUDA 12 toolkit on PATH, nothing needs downloading.
- **Licence:** these libraries are covered by the [NVIDIA CUDA EULA](https://docs.nvidia.com/cuda/eula/index.html), not by this project's MIT licence. ScribSalmon does not redistribute them; they are fetched from NVIDIA's package at your click, and the licence text is saved next to them. Uninstalling ScribSalmon offers to remove them.
- **Privacy:** the app contacts the network for this only when you click the download button.

How **Device** behaves:

| Device | Behaviour |
|---|---|
| Auto | Uses the NVIDIA GPU (float16) when CTranslate2 sees a CUDA device and cuBLAS 12 is found (in our folder or from a CUDA 12 toolkit on PATH). Any CUDA error while loading, warming up or transcribing falls back to the CPU (int8) and shows a toast with the reason. |
| CPU | Never touches the GPU. |
| CUDA | Shows an error instead of falling back to the CPU. |

## Updates

- On launch, **at most once a day**, and only if **Settings -> Check for updates on launch** is on, ScribSalmon makes one unauthenticated HTTPS GET to `api.github.com/repos/akirasane/ScribSalmon/releases/latest` with the User-Agent `ScribSalmon/<version>`. GitHub sees your IP address and the app version; nothing else is sent. Use **Check now** in Settings to check on demand.
- If a newer release exists, a banner offers **Update**, **What's new**, **Skip this version** or dismiss. Nothing is downloaded until you click **Update**.
- The installer is downloaded only from this project's GitHub release, verified against its SHA-256 (from `SHA256SUMS.txt` and the GitHub asset digest), and only run when you click **Restart & update** (not while recording or transcribing). ScribSalmon then closes, the installer runs, and the app relaunches.
- Zip/portable copies and source runs are not self-updated: the banner only links to the release page. The same applies if a release has no installer.
- **Security note:** the installer is unsigned, so updates are always user-initiated and never silent. The checksum verifies that the download is intact and matches what the release published; it does not prove who built it (both come from the same GitHub release).

## Architecture

```
main.py            pywebview window (WebView2) loading web/dist, taskbar icon, dark title bar
app/core.py        controller: recording, transcription queue, summaries, notes CRUD (UI-independent)
app/api.py         JS bridge: window.pywebview.api.*  ->  {ok, data|error}; pushes events via window.__pyEmit
app/audio.py       WASAPI loopback + mic capture, mixing to 16 kHz mono
app/transcribe.py  engines: faster-whisper (local) / OpenAI Whisper
app/summarize.py   Claude CLI or Anthropic API: summary prompt + "Check words" review
app/sessions.py    one folder per note
app/settings.py    settings.json + data folder resolution
web/src            React + TypeScript + Tailwind v4 UI (bridge.ts = Python bridge, mock.ts = browser fake)
tools/             make_dark_icon.py - builds the dark app icon (PNGs + .ico) from assets/source/salmon-icon-light.png
```

## Branding

- The app icon is the **dark** salmon tile: `assets/icon.ico` (exe, installer, taskbar), `web/public/logo.png` + `favicon.ico` (in-app logo, favicon). The light original is kept as `assets/icon-salmon-light-*`.
- To regenerate the dark variant from `assets/source/salmon-icon-light.png`: `pip install -r requirements-dev.txt`, then `.venv\Scripts\python tools\make_dark_icon.py` (and copy `icon-salmon-dark.ico` over `assets/icon.ico`, `icon-salmon-dark-256.png` over `web/public/logo.png`).
- Theme colours are the `--color-*` tokens at the top of `web/src/index.css`.

## CI / releases

- [`ci.yml`](.github/workflows/ci.yml) - on every push/PR: TypeScript check + UI build, Python deps install + byte-compile.
- [`release.yml`](.github/workflows/release.yml) - on every push to `main`: reads [`VERSION`](VERSION); if release `v<VERSION>` does not exist yet it builds the UI, packages the app with PyInstaller ([`ScribSalmon.spec`](ScribSalmon.spec)), zips it, builds the Inno Setup installer ([`installer/ScribSalmon.iss`](installer/ScribSalmon.iss)) and publishes a GitHub Release (tag created automatically) with generated notes. Same version = nothing happens.

- CI also has a `package` job that builds the frozen app with PyInstaller and runs `--selftest` (plain and with Mark-of-the-Web), then builds the installer and tests it end to end (silent install, selftest of the installed app, upgrade in place, uninstall keeps notes and settings).
- Each release ships `ScribSalmon-v<version>-windows-x64.zip`, `ScribSalmon-Setup-<version>.exe` and `SHA256SUMS.txt` (SHA-256 of both, LF line endings, `<hash>  <name>`; the release job verifies it with `sha256sum -c` before publishing). The zip contains `THIRD_PARTY_NOTICES.txt` (licenses of bundled dependencies, generated with `pip-licenses`) plus the project `LICENSE`.
- All GitHub Actions are pinned to full commit SHAs; [Dependabot](.github/dependabot.yml) opens weekly grouped update PRs for `github-actions`, `pip` and `npm` (`/web`).
- Recommended branch protection for `main`: require the status checks `web`, `python` and `package` to pass before merging.

Cut a release: bump `VERSION` (e.g. `1.0.1`), commit, push to `main`. That's it.

Build the package locally:

```powershell
cd web; npm ci; npm run build; cd ..
.venv\Scripts\pip install pyinstaller
.venv\Scripts\pyinstaller ScribSalmon.spec --noconfirm   # -> dist\ScribSalmon\ScribSalmon.exe
Copy-Item packaging\ScribSalmon.exe.config dist\ScribSalmon\   # lets it run from a downloaded zip
# installer (needs Inno Setup 6; LICENSE and THIRD_PARTY_NOTICES.txt must be in dist\ScribSalmon)
.\installer\build-installer.ps1 -Version (Get-Content VERSION -Raw).Trim()   # -> installer\Output\ScribSalmon-Setup-<version>.exe
```

## Troubleshooting

- **"`claude` CLI not found"** - install Claude Code and log in, or switch Summary backend to API and add a key.
- **`Failed to resolve Python.Runtime.Loader.Initialize`** - Windows blocked the DLLs of a downloaded zip. Use release 1.0.1+, or run `Get-ChildItem -Recurse <folder> | Unblock-File` (or right-click the zip -> Properties -> Unblock *before* extracting).
- **Blank window** - install the [WebView2 Runtime](https://developer.microsoft.com/microsoft-edge/webview2/). The installer warns if it is missing.
- **SmartScreen: "Windows protected your PC"** - the installer and exe are unsigned. Click *More info -> Run anyway*. Optionally compare the file's SHA-256 with `SHA256SUMS.txt` from the release.
- **Installer says ScribSalmon is still running** - close the app (check the system tray / Task Manager) and click *Retry*.
- **Update banner never appears** - check that *Check for updates on launch* is on in Settings, use *Check now*, and make sure `api.github.com` is reachable (proxy or firewall). Zip/portable copies only get a link to the release page, not a self-update.
- **"GPU unavailable, using CPU"** - open *Settings -> GPU*. It shows what is missing (NVIDIA driver older than 528.33, or the cuBLAS 12 libraries) and offers **Download GPU libraries**. A CUDA 13 toolkit alone does not help: CTranslate2 needs the CUDA **12** cuBLAS.
- **Still stuck / reporting a bug** - click **Copy diagnostics** in *Settings -> GPU* and paste the result into the issue (secrets and your user name are redacted), or attach `%APPDATA%\ScribSalmon\logs\scribsalmon.log`.
- **No system audio captured** - make sure audio is playing on the *default* output device.
- **Thai text is garbled** - choose the Thai preset, set Language = Thai, add Names & terms, then Refine + Check words.
- **UI not built** (running from source) - `cd web && npm install && npm run build`.

## Changelog

### 1.4.2
New salmon app icon in a dark variant, used everywhere (exe, installer, taskbar, in-app logo, favicon).

### 1.4.1
Log file and one-click GPU setup.

- **GPU:** Settings -> GPU shows whether an NVIDIA GPU, a recent enough driver and the cuBLAS 12 libraries were found, and why the CPU is being used if not. One click on **Download GPU libraries** fetches the NVIDIA cuBLAS 12 libraries (553 MB) so you no longer need to install the CUDA toolkit. cuDNN is not required.
- **Fallback:** with Device = Auto, ScribSalmon no longer loads a model into GPU memory just to discard it when the libraries are missing; it goes straight to the CPU and tells you the reason, with a shortcut to Settings -> GPU.
- **Logging:** a rotating log file (`%APPDATA%\ScribSalmon\logs\scribsalmon.log`) records startup, GPU detection and errors (never transcripts, notes or API keys). **Copy diagnostics** in Settings puts a redacted report on the clipboard for bug reports; **Open log folder** opens the logs.
- **Uninstall:** the uninstaller offers to delete the downloaded GPU libraries.

### 1.4.0
Installer and built-in update check.

- **Installer:** new per-user Windows installer (`ScribSalmon-Setup-<version>.exe`, Inno Setup, installs to `%LOCALAPPDATA%\Programs\ScribSalmon`, no admin rights needed) with Start menu / optional desktop shortcut and a normal uninstaller. Uninstall keeps your notes and settings. The portable zip is still published.
- **Updates:** on launch (at most once a day, can be turned off in Settings) ScribSalmon checks GitHub Releases for a newer version and shows a banner. Nothing is downloaded or installed until you click; the installer is SHA-256 verified before it runs, and the app restarts after the update.
- **Releases:** `SHA256SUMS.txt` now covers both the zip and the installer and uses LF line endings (1.3.0 used CRLF); the release workflow verifies it before publishing.
- **Upgrading from 1.3.0:** 1.3.0 has no updater, so install 1.4.0 once by hand (see Download); you can then delete the old zip folder.

### 1.3.0
Hardening and reliability release (includes everything that was planned as 1.1.0 and 1.2.0).

- **Security:** note ids validated (a crafted id could delete the whole Documents folder); links open in your browser and the window can't be navigated away; content-security policy; API keys encrypted with Windows DPAPI and never sent back to the UI; Claude CLI runs in a private folder with the transcript delimited.
- **Reliability:** no silent mock backend; GPU falls back to CPU automatically (new Device setting); recording start/stop races fixed; audio device errors shown instead of a stuck "Recording"; autosave no longer overwrites live chunks or a fresh summary; edits flushed on close; atomic writes with a settings backup; Refine waits for queued transcription.
- **Features:** import mp3/m4a/flac/ogg/mp4; Cancel for Refine / Summarize / Check words; "N s behind" indicator and automatic after-Stop fallback when live transcription lags; live chunks cut at pauses instead of mid-word; summaries are no longer silently truncated; version shown in Settings.
- **Fixes:** numbers no longer collapsed ("100000000"); quiet speech no longer dropped; export filename valid on Windows; Check words fixes the right occurrence; OneDrive-redirected Documents folder supported; faster note list/search.
- **Build/CI:** removed the old Qt UI; pytest + ruff; the packaged exe is self-tested (including a downloaded-zip scenario); hashed lockfile; SHA-pinned actions; checksums and third-party notices in releases.

### 1.0.1
Fix: app failed to start when extracted from a downloaded zip (`Failed to resolve Python.Runtime.Loader.Initialize`).

### 1.0.0
First release: notes CRUD, record/stop (system + mic), live or after-stop transcription, Refine, Check words, Thai-aware editable summary prompt, Claude Code CLI backend, Thai fine-tuned Whisper preset, salmon theme, logo and icons.

## License

[MIT](LICENSE)
