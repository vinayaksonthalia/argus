"""Shared test fixtures: everything runs offline against recorded fixtures."""

from __future__ import annotations

import json
from datetime import datetime, timezone
from pathlib import Path

import pytest

from argus.evals import load_alert, make_replay_deps
from argus.models import Alert, InvestigationState, TimeWindow

FIXTURE_DIR = Path(__file__).resolve().parent.parent / "fixtures" / "incident-1"


@pytest.fixture
def fixture_dir() -> Path:
    return FIXTURE_DIR


@pytest.fixture
def alert_payload() -> dict:
    return json.loads((FIXTURE_DIR / "alert.json").read_text())


@pytest.fixture
def alert(alert_payload) -> Alert:
    return load_alert(FIXTURE_DIR)


@pytest.fixture
def deps():
    return make_replay_deps(FIXTURE_DIR)


@pytest.fixture
def window() -> TimeWindow:
    return TimeWindow(
        start=datetime(2026, 7, 14, 1, 42, tzinfo=timezone.utc),
        end=datetime(2026, 7, 14, 2, 30, tzinfo=timezone.utc),
    )


@pytest.fixture
def state(alert, window) -> InvestigationState:
    s = InvestigationState(investigation_id="inv-test", alert=alert)
    s.service = "catalog"
    s.window = window
    return s
