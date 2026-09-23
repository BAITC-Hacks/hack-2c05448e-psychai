"""Windows no-terminal launcher for the local Money Graph demo."""

from __future__ import annotations

import ctypes
from pathlib import Path
import socket
import sys
import traceback


ROOT = Path(__file__).resolve().parent
OUT = ROOT / "out"


def launch() -> None:
    OUT.mkdir(exist_ok=True)
    with (OUT / "launcher.log").open("w", encoding="utf-8") as log:
        # pythonw.exe has no terminal streams; keep diagnostics in an ignored
        # local file and show a native Windows error dialog on failure.
        sys.stdout = log
        sys.stderr = log
        try:
            from run_pipeline import run
            from viewer import serve

            run(ROOT / "data", OUT)
            with socket.socket() as probe:
                probe.bind(("127.0.0.1", 0))
                port = probe.getsockname()[1]
            serve(ROOT / "data", OUT, "127.0.0.1", port, allow_shutdown=True)
        except Exception as exc:
            traceback.print_exc(file=log)
            log.flush()
            ctypes.windll.user32.MessageBoxW(
                None, f"Запуск не удался: {exc}\n\nПодробности: {OUT / 'launcher.log'}",
                "Граф денег", 0x10,
            )
            raise SystemExit(1) from None


if __name__ == "__main__":
    launch()
