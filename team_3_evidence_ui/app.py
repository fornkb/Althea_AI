"""Standalone Streamlit entry point for Team 3 (Evidence UI)."""
import os
from althea_evidence_ui.dashboard import render_app
from althea_evidence_ui.fixture_backend import FixtureBackend

settings = {
    "mode": os.environ.get("MODE", "fixture"),
    "data_dir": os.environ.get("DATA_DIR", "./data"),
    "max_verify_pairs": int(os.environ.get("MAX_VERIFY_PAIRS", "4")),
    "max_display_conflicts": 8,
}

backends = {
    "Sample demo (Offline Fixture)": lambda: FixtureBackend(settings),
}

if __name__ == "__main__":
    render_app(backends)
else:
    # When launched via `streamlit run app.py`
    render_app(backends)
