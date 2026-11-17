"""pun.console: attività in parallelo, avanzamento, errori, link. Offline e veloce."""

from __future__ import annotations

import io
import re
import threading
import time
from pathlib import Path

import pytest

from pun import console as K

ANSI = re.compile(r"\x1b\[[0-9;?]*[A-Za-z]|\x1b\]8;;[^\x1b]*\x1b\\")


def test_jobs_run_in_parallel_and_return_results():
    con = K.Console(stream=io.StringIO(), live=False)
    started = threading.Barrier(2, timeout=2)   # entrambe devono essere attive insieme

    def job(v):
        def fn(t):
            started.wait()
            return v
        return fn

    res = con.run([K.Job("a", "A", job(1)), K.Job("b", "B", job(2))])
    assert res == {"a": 1, "b": 2}


def test_sequential_jobs_keep_order():
    seen = []
    con = K.Console(stream=io.StringIO(), live=False)
    con.run([K.Job(k, k, lambda t, k=k: seen.append(k)) for k in "xyz"], parallel=False)
    assert seen == ["x", "y", "z"]


def test_optional_failure_is_a_warning_required_failure_raises():
    out = io.StringIO()
    con = K.Console(stream=out, live=False)

    def boom(t):
        raise RuntimeError("HTTP 503")

    res = con.run([K.Job("ok", "Ok", lambda t: 1), K.Job("gas", "Gas TTF", boom)])
    assert res == {"ok": 1, "gas": None}
    assert "attenzione: Gas TTF: HTTP 503" in out.getvalue()
    with pytest.raises(RuntimeError):
        con.run([K.Job("prices", "Prezzi", boom, required=True)])


def test_plain_output_has_no_escape_codes_and_shows_summary():
    out = io.StringIO()
    con = K.Console(stream=out, live=False)
    con.step("Dati")
    con.run([K.Job("p", "Prezzi energia", lambda t: 7, summary=lambda v: f"{v} zone")])
    text = out.getvalue()
    assert "\x1b" not in text
    assert "✓ Prezzi energia  7 zone" in text


def test_live_board_draws_progress_and_cleans_up():
    out = io.StringIO()
    con = K.Console(stream=out, live=True, color=True)

    def slow(t):
        for i in range(3):
            t.update(i, 3, f"zona {i}")
            time.sleep(0.1)
        t.update(3, 3, "")
        return "ok"

    con.run([K.Job("p", "Prezzi energia", slow), K.Job("m", "Timestral", lambda t: time.sleep(0.2))])
    raw = out.getvalue()
    assert "\x1b[?25l" in raw and raw.rstrip().endswith("\x1b[?25h")  # cursore nascosto e poi ripristinato
    plain = ANSI.sub("", raw)
    assert "zona 1" in plain and "✓ Prezzi energia" in plain
    lines = [ln for ln in plain.splitlines() if ln.strip()]
    assert max(len(ln) for ln in lines) <= 120


def test_warn_while_board_is_live_prints_above_it():
    out = io.StringIO()
    con = K.Console(stream=out, live=True, color=False)

    def fn(t):
        con.warn("meteo lento")
        time.sleep(0.1)

    con.run([K.Job("w", "Meteo", fn)])
    assert "attenzione: meteo lento" in ANSI.sub("", out.getvalue())


def test_secs_and_link():
    assert K.secs(4.25) == "4,2 s" or K.secs(4.25) == "4,3 s"
    assert K.secs(102) == "1 min 42 s"
    url = K.file_uri(Path("data/out/index.html"))
    assert url.startswith("file:///") and url.endswith("/data/out/index.html")
    assert K.Console(stream=io.StringIO(), live=False).link(url) == url
    live = K.Console(stream=io.StringIO(), live=True).link(url)
    assert live == f"\x1b]8;;{url}\x1b\\{url}\x1b]8;;\x1b\\"
