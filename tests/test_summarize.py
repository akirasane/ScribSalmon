"""Characterization of app.summarize (current behavior); no network, `_ask` is monkeypatched."""
import json

import pytest

from app import summarize


def test_parse_items_plain_json():
    assert summarize._parse_items('{"items":[{"original":"a"}]}') == [{"original": "a"}]


def test_parse_items_fenced():
    raw = '```json\n{"items":[{"original":"a","options":["b"]}]}\n```'
    assert summarize._parse_items(raw)[0]["original"] == "a"


def test_parse_items_prose_around():
    raw = 'Sure! Here you go: {"items":[{"original":"x"}]} Hope that helps.'
    assert summarize._parse_items(raw) == [{"original": "x"}]


def test_parse_items_no_json_raises_value_error():
    with pytest.raises(ValueError):
        summarize._parse_items("nothing to see here")


def test_parse_items_invalid_json_raises_value_error():
    with pytest.raises(ValueError):  # json.JSONDecodeError subclasses ValueError
        summarize._parse_items("{not json}")


def test_parse_items_non_dict_returns_empty():
    assert summarize._parse_items('{"x": 1}') == []
    assert summarize._parse_items("[1, 2] {}") == []  # braces found, but the object has no items


def test_build_prompt_placeholder_and_append():
    assert summarize.build_prompt("Summarize: {transcript} END", "TXT") == "Summarize: TXT END"
    assert summarize.build_prompt("Summarize", "TXT") == "Summarize\n\nTRANSCRIPT:\nTXT"


def test_build_prompt_empty_template_uses_default():
    out = summarize.build_prompt("  ", "TXT")
    assert out.startswith("You are a meeting-minutes assistant")
    assert out.endswith("TRANSCRIPT:\nTXT")


def test_summarize_empty_transcript_raises():
    with pytest.raises(ValueError):
        summarize.summarize("  ", "api", "k", "m")


def test_review_filters_and_shapes_items(monkeypatch):
    transcript = "hello wrold this is a test of the sistem today"
    reply = json.dumps({"items": [
        {"original": "wrold", "options": ["world", "world", "wrold", " word ", "a", "b"], "reason": "typo"},
        {"original": "not in transcript", "options": ["x"]},
        {"original": "sistem", "options": []},
        {"original": "wrold", "options": ["dup"]},
        {"original": "sistem", "options": ["system"], "reason": "r" * 500},
    ]})
    seen = {}

    def fake_ask(prompt, backend, api_key, model, max_tokens=4096):
        seen["prompt"] = prompt
        return reply

    monkeypatch.setattr(summarize, "_ask", fake_ask)
    items = summarize.review(transcript, "api", "k", "m", vocabulary="Acme")
    assert "Acme" in seen["prompt"] and seen["prompt"].endswith(transcript)
    assert [i["original"] for i in items] == ["wrold", "sistem"]
    assert items[0]["options"] == ["world", "word", "a"]
    assert items[0]["before"] == "hello " and items[0]["after"].startswith(" this is")
    assert len(items[1]["reason"]) == 120


def test_review_empty_transcript_raises():
    with pytest.raises(ValueError):
        summarize.review("", "api", "k", "m")
