"""Compatibility entry point: launch the safe desktop application."""
import runpy
from pathlib import Path

if __name__ == "__main__":
    runpy.run_path(str(Path(__file__).with_name("desktop_app.pyw")), run_name="__main__")
