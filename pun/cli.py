"""Riga di comando: `pun build`, `pun backtest`.

Esempi:
    uv run pun backtest --profile public
    uv run pun build --profile public            # pagina in site/
    uv run pun build --profile local             # pagina in data/out/
"""

from __future__ import annotations

import argparse
import os
import sys
import time
import warnings
from datetime import date, datetime
from pathlib import Path

# niente barre di download di Hugging Face sopra le nostre
os.environ.setdefault("HF_HUB_DISABLE_PROGRESS_BARS", "1")
os.environ.setdefault("TRANSFORMERS_VERBOSITY", "error")

from . import build as Bd  # noqa: E402
from . import console as K  # noqa: E402

PROFILE_IT = {"public": "pagina pubblica", "local": "pagina locale"}


def main(argv: list[str] | None = None) -> int:
    warnings.filterwarnings("ignore")
    for stream in (sys.stdout, sys.stderr):  # console Windows: evita errori su "≈", "€"
        if hasattr(stream, "reconfigure"):
            stream.reconfigure(encoding="utf-8")
    ap = argparse.ArgumentParser(prog="pun", description="Previsione del PUN con Timestral")
    sub = ap.add_subparsers(dest="cmd", required=True)
    for name in ("build", "backtest"):
        sp = sub.add_parser(name)
        sp.add_argument("--profile", choices=["public", "local"], default="public")
        sp.add_argument("--data-dir", type=Path, default=Bd.ROOT / "data")
        sp.add_argument("--out", type=Path, default=None)
        sp.add_argument("--quick", action="store_true", help="backtest ridotto (poche emissioni)")
    sub.choices["build"].add_argument("--max-backtest-age", type=int, default=7,
                                      help="giorni dopo cui il backtest viene rifatto")
    a = ap.parse_args(argv)

    p = Bd.profile(a.profile, a.data_dir, a.out)
    cache = a.data_dir / "cache"
    bt_path = a.data_dir / f"backtest-{p.name}.json"
    con = K.get()
    t0 = time.monotonic()
    try:
        return _run(a, p, cache, bt_path, con, t0)
    except KeyboardInterrupt:
        con.print()
        con.print("  interrotto")
        return 130


def _run(a, p, cache: Path, bt_path: Path, con: K.Console, t0: float) -> int:
    when = datetime.now().strftime("%d/%m/%Y %H:%M")
    if a.cmd == "backtest":
        con.header("Previsione PUN", f"backtest · {PROFILE_IT[p.name]} · {when}")
        con.plan(2)
        res = Bd.run_backtest(p, cache, bt_path, quick=a.quick, con=con)
        h, d = res["hourly"][res["hourly_model"]], res["daily"][res["daily_model"]]
        _done(con, t0, [
            ("Orario", f"{Bd.model_name(res['hourly_model'])} · errore a 7 giorni "
                       f"{Bd._it(h['mae_7'] / 1000, 3)} €/kWh"),
            ("3 mesi", f"{Bd.model_name(res['daily_model'])} · errore a 90 giorni {Bd._it(d['mae_90'] / 1000, 3)} €/kWh"),
        ], bt_path)
        return 0

    bt = Bd.load_backtest(bt_path)
    age = (date.today() - date.fromisoformat(bt["as_of"])).days if bt else None
    stale = age is None or age > a.max_backtest_age
    con.header("Previsione PUN", f"{PROFILE_IT[p.name]} · {when}")
    con.plan(3 + 2 * stale)
    if stale:
        con.warn("backtest assente" if age is None else f"backtest di {age} giorni fa: lo rifaccio")
        Bd.run_backtest(p, cache, bt_path, quick=a.quick, con=con)
    data = Bd.build(p, cache, bt_path, con=con)
    con.step("Pagina")
    page = Bd.render(data, p.out_dir)
    con.print("    " + con.paint("✓", K.LIME) + " " + str(page))
    tm = data["tomorrow"]
    cheap = ", ".join(f"{a:02d}–{b:02d}" for a, b in tm["cheap"])
    rows = [
        ("Domani", f"media {Bd._it(tm['mean'], 3)} €/kWh · ore più economiche {cheap}"
                   + ("" if tm["kind"] == "actual" else " (previsione)")),
        ("Fonte", data["source_label"]),
        ("Modelli", f"{Bd.model_name(data['model']['hourly'])} (orario) · "
                    f"{Bd.model_name(data['model']['daily'])} (12 mesi)"),
    ]
    if "gas_ttf" in data:
        g = data["gas_ttf"]
        rows.insert(1, ("Gas TTF", f"{Bd._it(g['eur_mwh'], 2)} €/MWh · chiusura del "
                                   f"{Bd._dm(date.fromisoformat(g['date']))}"))
    _done(con, t0, rows, page)
    return 0


def _done(con: K.Console, t0: float, rows: list[tuple[str, str]], target: Path) -> None:
    """Riepilogo finale su stdout, con il link cliccabile al file."""
    out = sys.stdout
    con = K.Console(stream=out)  # colori e link solo se stdout è un terminale
    con.print(stream=out)
    con.print("  " + con.paint("✓", K.LIME, bold=True) + " " +
              con.paint(f"Fatto in {K.secs(time.monotonic() - t0)}", K.INK, bold=True), stream=out)
    con.print(stream=out)
    for k, v in rows:
        con.print("    " + con.paint(k.ljust(8), K.DIM) + " " + v, stream=out)
    url = K.file_uri(target)
    con.print(stream=out)
    con.print("    " + con.paint("→", K.LIME) + " " + con.paint(con.link(url), K.LIME), stream=out)
    con.print(stream=out)


if __name__ == "__main__":
    raise SystemExit(main())
