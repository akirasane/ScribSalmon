import json
import re
import shutil
import subprocess
import sys
import tempfile

import anthropic

DEFAULT_PROMPT = """You are a meeting-minutes assistant. Below is a raw speech-to-text transcript of a meeting.
Write the summary in the SAME language as the meeting (Thai transcript -> Thai, English -> English; mixed -> mostly the dominant language, keep English technical terms and names as they are).

IMPORTANT - the transcript is machine-generated and often broken, especially Thai:
- Some Thai words are wrong: similar-sounding words, split or merged words, or meaningless phrases
  (ภาษาไทยบางคำที่ถอดเสียงมาอาจเป็นคำมั่วๆ).
- Before summarizing, silently repair them: infer the intended word from sentence structure, topic and
  surrounding context, and use the corrected wording in the summary.
- If you are not reasonably sure, do NOT invent. Keep the best guess, mark it with (?) and list it under
  "Needs Review" (see below).
- Never change numbers, dates, names or amounts unless the context clearly proves they were misheard.

Output Markdown with exactly these sections:

## Overview
2-3 sentences: purpose and outcome.

## Key Points
A numbered list (1., 2., 3., ...). Each item: a short bold title, then indented sub-points
(1.1, 1.2, ...) giving the detail: who said what, reasons, numbers, dates, trade-offs.

## Decisions
Numbered list of decisions made. Write "None" if there were none.

## Action Items
Numbered list: task - owner (if mentioned) - due date (if mentioned).

## Open Questions
Numbered list of unresolved issues. Write "None" if there were none.

## Needs Review
Only if some wording was uncertain. A numbered list; for each item quote the original transcript phrase,
then give 1-3 candidate corrections, e.g.
1. "original phrase" -> (a) candidate one (b) candidate two (c) candidate three
Write "None" if nothing was uncertain.

Rules: do not invent facts that are not supported by the transcript.

"""

REVIEW_PROMPT = """You are proofreading a machine speech-to-text transcript of a meeting (often Thai, sometimes mixed with English).
The recognizer frequently produces wrong words: similar-sounding words, broken word boundaries, or nonsense phrases.

Find the phrases that are most likely WRONG or meaningless. For each one, infer from the sentence structure and the
surrounding context what was probably said, and offer 1 to 3 candidate replacements, most likely first.

Return ONLY a JSON object, with no markdown fences and no other text:
{"items":[{"original":"<exact text copied from the transcript>","options":["<best>","<alt 2>","<alt 3>"],"reason":"<very short, English>"}]}

Rules:
- "original" MUST be copied character-for-character from the transcript (a short span, 2-60 characters, not a whole paragraph).
- Each option is a replacement for that span only (same language as the original).
- At most 20 items, most important first. Skip anything that is probably already correct.
- Do not "fix" style or grammar of correct speech. Do not change numbers/names unless clearly misheard.
- If nothing looks wrong return {"items":[]}.
{vocab}
TRANSCRIPT:
"""


def build_prompt(template: str, transcript: str) -> str:
    """Template may contain {transcript}; otherwise the transcript is appended after it."""
    t = (template or "").strip() or DEFAULT_PROMPT.strip()
    if "{transcript}" in t:
        return t.replace("{transcript}", transcript)
    return f"{t}\n\nTRANSCRIPT:\n{transcript}"


def cli_path():
    return shutil.which("claude")


def _ask_cli(prompt: str, timeout: int = 900) -> str:
    """Run the local Claude Code CLI headless (uses its existing login). Prompt goes via stdin."""
    exe = cli_path()
    if not exe:
        raise ValueError("`claude` CLI not found on PATH. Install Claude Code and log in, or use the API key.")
    cmd = [exe, "-p", "--output-format", "text", "--setting-sources", "local",
           "--tools", "", "--disable-slash-commands", "--no-session-persistence"]
    kw = {"creationflags": 0x08000000} if sys.platform == "win32" else {}  # no console flash
    # neutral cwd: no project CLAUDE.md picked up
    r = subprocess.run(cmd, input=prompt, capture_output=True, text=True, encoding="utf-8",
                       timeout=timeout, cwd=tempfile.gettempdir(), **kw)
    if r.returncode != 0 or not r.stdout.strip():
        raise RuntimeError(f"claude CLI failed (exit {r.returncode}): {(r.stderr or r.stdout).strip()[:500]}")
    return r.stdout.strip()


def _ask_api(prompt: str, api_key: str, model: str, max_tokens: int = 4096) -> str:
    if not api_key:
        raise ValueError("Anthropic API key missing (Settings).")
    client = anthropic.Anthropic(api_key=api_key)
    msg = client.messages.create(model=model, max_tokens=max_tokens,
                                 messages=[{"role": "user", "content": prompt}])
    return "".join(b.text for b in msg.content if b.type == "text")


def _ask(prompt: str, backend: str, api_key: str, model: str, max_tokens: int = 4096) -> str:
    """backend: 'cli' | 'api' | 'auto' (CLI if installed, else API key)."""
    if backend == "auto":
        backend = "cli" if cli_path() else "api"
    if backend == "cli":
        return _ask_cli(prompt)
    return _ask_api(prompt, api_key, model, max_tokens)


def summarize(transcript: str, backend: str, api_key: str, model: str, prompt: str = "") -> str:
    if not transcript.strip():
        raise ValueError("Transcript is empty.")
    return _ask(build_prompt(prompt, transcript), backend, api_key, model)


# ------------------------------------------------------------------ human review of garbled words
def _parse_items(raw: str) -> list:
    s = raw.strip()
    s = re.sub(r"^```(?:json)?\s*|\s*```$", "", s)
    i, j = s.find("{"), s.rfind("}")
    if i < 0 or j < 0:
        raise ValueError("Claude did not return a review list. Try again.")
    data = json.loads(s[i:j + 1])
    return data.get("items", []) if isinstance(data, dict) else []


def review(transcript: str, backend: str, api_key: str, model: str, vocabulary: str = "") -> list:
    """Ask Claude which phrases look mis-transcribed. Returns UI-ready items:
    [{original, options[1-3], reason, before, after}] (only spans that really occur in the transcript)."""
    if not transcript.strip():
        raise ValueError("Transcript is empty.")
    vocab = f"\nKnown names/terms that may appear (spell them exactly like this): {vocabulary.strip()}\n" if vocabulary.strip() else ""
    raw = _ask(REVIEW_PROMPT.replace("{vocab}", vocab) + transcript, backend, api_key, model, max_tokens=4096)
    items, seen = [], set()
    for it in _parse_items(raw):
        orig = str(it.get("original", ""))
        idx = transcript.find(orig) if orig else -1
        opts = []
        for o in it.get("options", []):
            o = str(o).strip()
            if o and o != orig and o not in opts:
                opts.append(o)
        if idx < 0 or not opts or orig in seen:
            continue
        seen.add(orig)
        items.append({
            "original": orig,
            "options": opts[:3],
            "reason": str(it.get("reason", ""))[:120],
            "before": transcript[max(0, idx - 45):idx].replace("\n", " "),
            "after": transcript[idx + len(orig):idx + len(orig) + 45].replace("\n", " "),
        })
    return items[:20]
