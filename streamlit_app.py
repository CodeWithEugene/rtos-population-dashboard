"""Streamlit Community Cloud entry point.

Streamlit Cloud defaults the "Main file path" to ``streamlit_app.py`` at the repo
root. The real dashboard lives in ``app/dashboard.py``; this thin shim runs it so
the default deploy path works without any extra configuration. ``runpy`` executes
the dashboard fresh on every Streamlit rerun, exactly as running it directly.
"""
import runpy
from pathlib import Path

_APP = Path(__file__).resolve().parent / "app" / "dashboard.py"
runpy.run_path(str(_APP), run_name="__main__")
