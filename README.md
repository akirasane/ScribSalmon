<p align="center">
  <img src="assets/logo-wordmark.png" alt="ScribSalmon" height="96">
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
- **GPU note** - GPU transcription needs the NVIDIA driver plus CUDA 12 / cuDNN 9 libraries on PATH; otherwise ScribSalmon falls back to CPU automatically (Settings -> Device).
- **Two summary backends** - the local **Claude Code CLI** (uses your existing login, no API key) or the **Anthropic API**.
- **Thai accuracy presets** - Thai fine-tuned Whisper (Thonburian), `large-v3`, `large-v3-turbo`, custom model id/folder, and a *Names & terms* hint list.
- Salmon-coloured dark UI (React + Tailwind v4), custom logo and icons, dark title bar.

> Only record meetings where **all attendees consent**.

## Download (no setup)

1. Go to the [**Releases**](https://github.com/akirasane/ScribSalmon/releases/latest) page.
2. Download `ScribSalmon-vX.Y.Z-windows-x64.zip` and extract it anywhere.
3. Run `ScribSalmon.exe`.

Requirements: Windows 10/11 x64 with the **Microsoft Edge WebView2 Runtime** (preinstalled on Windows 11 and current Windows 10).
Windows SmartScreen may warn because the exe is unsigned - *More info -> Run anyway*.

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
| Whisper models | Hugging Face cache (`~\.cache\huggingface`) |

Each note folder contains `meta.json`, `rec_001.wav ...`, `transcript.txt`, `summary.md`.
Old `VoiceRecog` folders are migrated automatically on first launch.

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
tools/             make_icons.py - renders assets/logo.svg to PNGs, .ico and the web favicon
```

## Branding

- Edit `assets/logo.svg`, then `.venv\Scripts\python tools\make_icons.py` regenerates the PNGs, `.ico` and the web favicon.
- Theme colours are the `--color-*` tokens at the top of `web/src/index.css`.

## CI / releases

- [`ci.yml`](.github/workflows/ci.yml) - on every push/PR: TypeScript check + UI build, Python deps install + byte-compile.
- [`release.yml`](.github/workflows/release.yml) - on every push to `main`: reads [`VERSION`](VERSION); if release `v<VERSION>` does not exist yet it builds the UI, packages the app with PyInstaller ([`ScribSalmon.spec`](ScribSalmon.spec)), zips it and publishes a GitHub Release (tag created automatically) with generated notes. Same version = nothing happens.

- CI also has a `package` job that builds the frozen app with PyInstaller and runs `--selftest` (plain and with Mark-of-the-Web).
- Each release ships `SHA256SUMS.txt` (SHA-256 of the zip) and the zip contains `THIRD_PARTY_NOTICES.txt` (licenses of bundled dependencies, generated with `pip-licenses`) plus the project `LICENSE`.
- All GitHub Actions are pinned to full commit SHAs; [Dependabot](.github/dependabot.yml) opens weekly grouped update PRs for `github-actions`, `pip` and `npm` (`/web`).
- Recommended branch protection for `main`: require the status checks `web`, `python` and `package` to pass before merging.

Cut a release: bump `VERSION` (e.g. `1.0.1`), commit, push to `main`. That's it.

Build the package locally:

```powershell
cd web; npm ci; npm run build; cd ..
.venv\Scripts\pip install pyinstaller
.venv\Scripts\pyinstaller ScribSalmon.spec --noconfirm   # -> dist\ScribSalmon\ScribSalmon.exe
Copy-Item packaging\ScribSalmon.exe.config dist\ScribSalmon\   # lets it run from a downloaded zip
```

## Troubleshooting

- **"`claude` CLI not found"** - install Claude Code and log in, or switch Summary backend to API and add a key.
- **`Failed to resolve Python.Runtime.Loader.Initialize`** - Windows blocked the DLLs of a downloaded zip. Use release 1.0.1+, or run `Get-ChildItem -Recurse <folder> | Unblock-File` (or right-click the zip -> Properties -> Unblock *before* extracting).
- **Blank window** - install the [WebView2 Runtime](https://developer.microsoft.com/microsoft-edge/webview2/).
- **No system audio captured** - make sure audio is playing on the *default* output device.
- **Thai text is garbled** - choose the Thai preset, set Language = Thai, add Names & terms, then Refine + Check words.
- **UI not built** (running from source) - `cd web && npm install && npm run build`.

## Changelog

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
