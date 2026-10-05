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
- **Import WAV** - add an existing 16-bit PCM `.wav` to a note.
- **Refine** - re-transcribes the whole recording in one pass (more accurate than live chunks).
- **Check words** - Claude flags garbled phrases (typical for Thai); you pick option 1-3, keep the original, or type your own.
- **Summary** - numbered Overview / Key Points / Decisions / Action Items / Open Questions / Needs Review. The prompt is **Thai-aware and fully editable** (globally and per note).
- **Two transcription engines** - local `faster-whisper` (offline, GPU used automatically if CUDA is available) or OpenAI Whisper API.
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
| Notes | `Documents\ScribSalmon\<timestamp>\` |
| Settings (incl. API keys, plain JSON) | `%APPDATA%\ScribSalmon\settings.json` |
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
main_qt.py         previous PySide6 UI, kept as a fallback (needs PySide6 from requirements.txt)
tools/             make_icons.py - renders assets/logo.svg to PNGs, .ico and the web favicon
```

## Branding

- Edit `assets/logo.svg`, then `.venv\Scripts\python tools\make_icons.py` regenerates the PNGs, `.ico` and the web favicon.
- Theme colours are the `--color-*` tokens at the top of `web/src/index.css`.

## CI / releases

- [`ci.yml`](.github/workflows/ci.yml) - on every push/PR: TypeScript check + UI build, Python deps install + byte-compile.
- [`release.yml`](.github/workflows/release.yml) - on a `v*` tag: builds the UI, packages the app with PyInstaller ([`ScribSalmon.spec`](ScribSalmon.spec)), zips it and publishes a GitHub Release with auto-generated notes.

Cut a release:

```powershell
git tag v1.0.1
git push origin v1.0.1
```

Build the package locally:

```powershell
cd web; npm ci; npm run build; cd ..
.venv\Scripts\pip install pyinstaller
.venv\Scripts\pyinstaller ScribSalmon.spec --noconfirm   # -> dist\ScribSalmon\ScribSalmon.exe
```

## Troubleshooting

- **"`claude` CLI not found"** - install Claude Code and log in, or switch Summary backend to API and add a key.
- **Blank window** - install the [WebView2 Runtime](https://developer.microsoft.com/microsoft-edge/webview2/).
- **No system audio captured** - make sure audio is playing on the *default* output device.
- **Thai text is garbled** - choose the Thai preset, set Language = Thai, add Names & terms, then Refine + Check words.
- **UI not built** (running from source) - `cd web && npm install && npm run build`.

## Changelog

### 1.0.0
First release: notes CRUD, record/stop (system + mic), live or after-stop transcription, Refine, Check words, Thai-aware editable summary prompt, Claude Code CLI backend, Thai fine-tuned Whisper preset, salmon theme, logo and icons.

## License

[MIT](LICENSE)
