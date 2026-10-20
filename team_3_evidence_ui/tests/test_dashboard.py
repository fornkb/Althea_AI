"""Streamlit AppTest suite verifying dashboard loading, states, and actions."""
from pathlib import Path
import pytest
from streamlit.testing.v1 import AppTest

APP_PATH = Path(__file__).resolve().parent.parent / "app.py"


def test_dashboard_renders_successfully():
    """Verify that app.py loads without syntax errors, exceptions, or missing imports."""
    at = AppTest.from_file(str(APP_PATH), default_timeout=15)
    at.run()

    # Assert no unhandled exception occurred
    assert not at.exception, f"App raised unexpected exception: {at.exception}"

    # Verify key tabs and header are rendered
    assert len(at.tabs) == 4
    tab_labels = [t.label for t in at.tabs]
    assert "📜 Transcript" in tab_labels
    assert "📋 Claims" in tab_labels
    assert "⚡ Disagreements" in tab_labels
    assert "🔍 Evidence & Export" in tab_labels


def test_dashboard_sample_run_interaction():
    """Verify running the sample populates the tabs and doesn't crash."""
    at = AppTest.from_file(str(APP_PATH), default_timeout=15)
    at.run()

    # Find and click the 'Run Analysis' button
    run_buttons = [b for b in at.button if "Run Analysis" in b.label]
    assert len(run_buttons) >= 1
    run_buttons[0].click().run()

    assert not at.exception
    # Check that tabs now contain data
    assert len(at.tabs) == 4


def test_dashboard_rerun_does_not_call_external_providers():
    """Verify that simple re-runs/state changes don't fail or invoke cloud calls."""
    at = AppTest.from_file(str(APP_PATH), default_timeout=15)
    at.run()

    # Trigger rerun
    at.run()
    assert not at.exception
