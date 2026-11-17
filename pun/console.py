"""Uscita in console: fasi numerate, attività in parallelo con barre di avanzamento, link cliccabile.

Nel terminale le attività si aggiornano sul posto (una riga ciascuna). Senza terminale
(log di GitHub Actions, test, output rediretto) stampa righe semplici: una all'avvio e una
alla fine di ogni attività. NO_COLOR disattiva i colori. Nessuna dipendenza esterna.

    con = get()
    con.step("Dati")
    res = con.run([Job("prezzi", "Prezzi energia", lambda t: scarica(progress=t.update))])
"""

from __future__ import annotations

import os
import shutil
import sys
import threading
import time
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any, Callable

# palette "Notte" della pagina: lime = fatto, ambra = avviso, rosso = errore
LIME, AMBER, RED = (200, 241, 105), (240, 185, 85), (240, 105, 95)
INK, DIM = (232, 232, 228), (128, 128, 124)
SPIN = "⠋⠙⠹⠸⠼⠴⠦⠧⠇⠏"
BAR = 20
LABEL = 30


def _isatty(stream) -> bool:
    try:
        return stream.isatty()
    except (AttributeError, ValueError):
        return False


def _enable_vt(stream) -> bool:
    """Sequenze ANSI attive? Su Windows le abilita sulla console (cmd, PowerShell, VS Code)."""
    if not _isatty(stream):
        return False
    if os.name != "nt":
        return os.environ.get("TERM") != "dumb"
    try:
        import ctypes
        k = ctypes.windll.kernel32
        h = k.GetStdHandle(-12 if stream is sys.__stderr__ else -11)
        mode = ctypes.c_uint32()
        if not k.GetConsoleMode(h, ctypes.byref(mode)):
            return False
        return bool(k.SetConsoleMode(h, mode.value | 0x0004))  # ENABLE_VIRTUAL_TERMINAL_PROCESSING
    except Exception:  # noqa: BLE001 - console senza supporto: modalità semplice
        return False


def secs(s: float) -> str:
    """4,2 s · 1 min 42 s"""
    if s < 60:
        return f"{s:.1f} s".replace(".", ",")
    m, s = divmod(int(round(s)), 60)
    return f"{m} min {s:02d} s"


def file_uri(path: Path) -> str:
    return Path(path).resolve().as_uri()


@dataclass
class Task:
    label: str
    total: int | None = None          # None = durata indeterminata (es. Timestral)
    done: int = 0
    detail: str = ""
    summary: str = ""
    state: str = "wait"               # wait, run, ok, skip, fail
    t0: float = 0.0
    t1: float = 0.0

    def update(self, done: int | None = None, total: int | None = None, detail: str | None = None) -> None:
        """Callback di avanzamento: progress(fatti, totale, dettaglio)."""
        if total is not None:
            self.total = total
        if done is not None:
            self.done = done
        if detail is not None:
            self.detail = detail

    def skip(self, why: str) -> None:
        self.state, self.summary = "skip", why

    @property
    def elapsed(self) -> float:
        return ((self.t1 or time.monotonic()) - self.t0) if self.t0 else 0.0


@dataclass
class Job:
    key: str
    label: str
    fn: Callable[[Task], Any]
    total: int | None = None
    required: bool = False            # se fallisce, il comando si ferma
    summary: Callable[[Any], str] | None = None
    task: Task = field(init=False)

    def __post_init__(self):
        self.task = Task(self.label, self.total)


class Console:
    def __init__(self, stream=None, live: bool | None = None, color: bool | None = None):
        self._stream = stream
        self._live, self._color = live, color
        self.lock = threading.RLock()
        self.tasks: list[Task] = []
        self.drawn = 0
        self.steps_total = 0
        self.step_n = 0
        self.t0 = time.monotonic()

    # flusso risolto al momento: i test sostituiscono sys.stderr
    @property
    def out(self):
        return self._stream or sys.stderr

    @property
    def live(self) -> bool:
        if self._live is None:
            self._live = _enable_vt(self.out)
        return self._live

    @property
    def color(self) -> bool:
        if self._color is None:
            self._color = self.live and "NO_COLOR" not in os.environ
        return self._color

    def paint(self, text: str, rgb=None, bold: bool = False) -> str:
        if not self.color or not text:
            return text
        codes = (["1"] if bold else []) + ([f"38;2;{rgb[0]};{rgb[1]};{rgb[2]}"] if rgb else [])
        return f"\x1b[{';'.join(codes)}m{text}\x1b[0m" if codes else text

    def link(self, url: str, text: str | None = None) -> str:
        """Link cliccabile (OSC 8) che mostra l'URL stesso: cliccabile anche dove OSC 8 manca."""
        text = text or url
        if not self.live:
            return text
        return f"\x1b]8;;{url}\x1b\\{text}\x1b]8;;\x1b\\"

    # ------------------------------------------------------------ righe semplici
    def print(self, line: str = "", stream=None) -> None:
        with self.lock:
            s = stream or self.out
            if self.drawn and s is self.out:   # sopra il pannello delle attività
                s.write(f"\x1b[{self.drawn}F\x1b[J")
                self.drawn = 0
            s.write(line + "\n")
            s.flush()
            if self.tasks and self.live:
                self._draw()

    def header(self, title: str, sub: str = "") -> None:
        self.print()
        self.print("  " + self.paint("■", LIME) + " " + self.paint(title, INK, bold=True) +
                   (self.paint("  ·  " + sub, DIM) if sub else ""))

    def plan(self, n: int) -> None:
        self.steps_total, self.step_n = n, 0

    def step(self, title: str) -> None:
        self.step_n += 1
        n = f"{self.step_n}/{self.steps_total}" if self.steps_total else str(self.step_n)
        self.print()
        self.print("  " + self.paint(n, DIM) + "  " + self.paint(title, INK, bold=True))

    def warn(self, msg: str) -> None:
        self.print("    " + self.paint("!", AMBER, bold=True) + " " + self.paint(f"attenzione: {msg}", AMBER)
                   if self.color else f"attenzione: {msg}")

    # ------------------------------------------------------------- attività
    def run(self, jobs: list[Job], parallel: bool = True) -> dict[str, Any]:
        """Esegue le attività (in parallelo o in fila) mostrando l'avanzamento.

        Il risultato di un'attività fallita è None; se era `required` l'errore viene rilanciato
        dopo aver chiuso il pannello. Thread daemon: Ctrl+C interrompe subito."""
        results: dict[str, Any] = {}
        errors: dict[str, BaseException] = {}

        def work(job: Job) -> None:
            t = job.task
            t.state, t.t0 = "run", time.monotonic()
            if not self.live:
                self.print(f"    … {t.label}")
            try:
                v = job.fn(t)
                results[job.key] = v
                if t.state == "run":
                    t.state = "ok"
                    if job.summary and v is not None:
                        t.summary = job.summary(v)
            except BaseException as e:  # noqa: BLE001 - riportato sotto
                errors[job.key] = e
                t.state, t.summary = "fail", str(e)[:120]
            finally:
                t.t1 = time.monotonic()
                if not self.live:
                    self.print(self._plain(t))

        def sequence(js: list[Job]) -> None:
            for j in js:
                work(j)

        threads = ([threading.Thread(target=work, args=(j,), daemon=True) for j in jobs] if parallel
                   else [threading.Thread(target=sequence, args=(jobs,), daemon=True)])
        with self.lock:
            self.tasks = [j.task for j in jobs]
        if self.live:
            self.out.write("\x1b[?25l")  # nasconde il cursore
        try:
            for th in threads:
                th.start()
            i = 0
            while any(th.is_alive() for th in threads):
                if self.live:
                    with self.lock:
                        self._draw(i)
                    i += 1
                time.sleep(0.08)
            if self.live:
                with self.lock:
                    self._draw(i)
        finally:
            with self.lock:
                if self.live:
                    self.out.write("\x1b[?25h")
                    self.out.flush()
                self.tasks, self.drawn = [], 0
        for j in jobs:
            e = errors.get(j.key)
            if e is not None and j.required:
                raise e
            if e is not None and not isinstance(e, Exception):
                raise e  # KeyboardInterrupt e simili
            if e is not None:
                self.warn(f"{j.label}: {e}")
        return {j.key: results.get(j.key) for j in jobs}

    def _plain(self, t: Task) -> str:
        mark = {"ok": "✓", "skip": "–", "fail": "✗"}.get(t.state, "·")
        extra = f"  {t.summary}" if t.summary else ""
        return f"    {mark} {t.label}{extra}  ({secs(t.elapsed)})"

    def _bar(self, t: Task, frame: int) -> list[tuple[str, Any]]:
        if t.total:
            k = round(BAR * min(t.done, t.total) / t.total)
            return [("━" * k, LIME), ("─" * (BAR - k), DIM)]
        pos = frame % (2 * (BAR - 4))  # blocco che scorre avanti e indietro
        pos = pos if pos < BAR - 4 else 2 * (BAR - 4) - pos
        return [("─" * pos, DIM), ("━" * 4, LIME), ("─" * (BAR - 4 - pos), DIM)]

    def _line(self, t: Task, frame: int, width: int, lw: int = LABEL) -> str:
        icon = {"wait": ("·", DIM), "run": (SPIN[frame % len(SPIN)], LIME), "ok": ("✓", LIME),
                "skip": ("–", DIM), "fail": ("✗", RED)}[t.state]
        segs: list[tuple[str, Any]] = [("    ", None), icon, (" ", None), (t.label.ljust(lw)[:lw], INK), ("  ", None)]
        if t.state == "run":
            segs += self._bar(t, frame)
            if t.total:
                segs.append((f"  {t.done}/{t.total}".ljust(8), DIM))
            segs.append(("  " + t.detail if t.detail else "", DIM))
        elif t.state == "ok" and not t.summary and t.total:
            segs += [("━" * BAR, LIME), (f"  {t.total}/{t.total}", DIM)]
        else:
            segs.append((t.summary, RED if t.state == "fail" else DIM))
        right = secs(t.elapsed) if t.t0 else ""
        used = sum(len(s) for s, _ in segs)
        room = width - 1 - len(right) - 2
        out, n = [], 0
        for s, c in segs:  # tronca senza spezzare i colori
            s = s[: max(0, room - n)]
            n += len(s)
            out.append(self.paint(s, c) if c else s)
        pad = " " * max(2, width - 1 - min(used, room) - len(right))
        return "".join(out) + pad + self.paint(right, DIM)

    def _draw(self, frame: int = 0) -> None:
        width = max(40, min(shutil.get_terminal_size((100, 20)).columns, 120))
        buf = f"\x1b[{self.drawn}F" if self.drawn else ""
        lw = max([LABEL] + [min(len(t.label), 44) for t in self.tasks])  # etichette allineate
        for t in self.tasks:
            buf += "\x1b[2K" + self._line(t, frame, width, lw) + "\n"
        self.drawn = len(self.tasks)
        self.out.write(buf)
        self.out.flush()


_CON = Console()


def get() -> Console:
    return _CON


def warn(msg: str) -> None:
    _CON.warn(msg)
