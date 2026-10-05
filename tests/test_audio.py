import wave

import numpy as np

from app.audio import BLOCK, Recorder, pick_cut


def loud(n, gap=None):
    r = [0.3] * n
    if gap is not None:
        r[gap] = 0.0
    return r


def test_no_cut_before_min():
    assert pick_cut(loud(39, gap=20), 40, 100) is None


def test_no_cut_without_pause_before_max():
    assert pick_cut(loud(70), 40, 100) is None


def test_pause_chosen_over_end():
    assert pick_cut(loud(60, gap=52), 40, 100) == 53


def test_hard_cut_at_max_picks_quietest():
    r = [0.3] * 100
    r[70] = 0.2
    assert pick_cut(r, 40, 100) == 71


def test_ties_pick_last_min_block():
    r = [0.3] * 100
    r[50] = r[80] = 0.0
    assert pick_cut(r, 40, 100) == 81
    assert pick_cut(r[:60], 40, 100) == 51


def test_pause_in_first_four_seconds_ignored():
    r = loud(60)
    r[10] = 0.0
    assert pick_cut(r, 40, 100) is None


class _Src:
    def __init__(self, blocks):
        self.blocks, self.error = list(blocks), None

    def drain(self):
        out, self.blocks = self.blocks, []
        return np.concatenate(out) if out else np.zeros(0, np.float32)

    def is_alive(self):
        return bool(self.blocks)


def test_recorder_cuts_at_pause_and_flushes_tail(tmp_path, monkeypatch):
    sig = np.full(BLOCK * 100, 0.3, np.float32)
    sig[BLOCK * 52:BLOCK * 53] = 0.0
    chunks = []
    wav = tmp_path / "x.wav"
    rec = Recorder(wav, True, False, chunks.append, lambda m: None)
    wf = wave.open(str(wav), "wb")
    wf.setnchannels(1)
    wf.setsampwidth(2)
    wf.setframerate(16000)
    rec._wf = wf
    # one 10 s drain, then the source dies
    rec._sources = [_Src([sig])]
    monkeypatch.setattr("app.audio.time.sleep", lambda s: None)
    rec._run()
    assert [len(c) for c in chunks] == [BLOCK * 53, BLOCK * 47]
    with wave.open(str(wav)) as w:
        assert w.getnframes() == len(sig)
