"""
Tests for scripts/run_pipeline.py's _run() fatal/non-fatal step behavior.

Regression coverage for a real bug caught before it shipped: validate_ml_comps_
valuation.py deliberately returns exit code 1 when the current month's
re-validation gate fails (an expected, non-error outcome for an additive,
non-trading-critical experimental sub-model) — but _run()'s original behavior
was to sys.exit() the whole pipeline on ANY non-zero code, which would have
silently skipped train_model/run_backtest/score_live (the actual live-trading
refresh) every time ml_comps' calibration merely dipped for a month.
"""
from __future__ import annotations

import sys
from pathlib import Path
from unittest.mock import MagicMock

import pytest

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))
sys.path.insert(0, str(Path(__file__).resolve().parent.parent / "scripts"))

import run_pipeline as rp  # noqa: E402


def _mock_result(returncode: int):
    r = MagicMock()
    r.returncode = returncode
    return r


def test_fatal_step_exits_on_nonzero(monkeypatch):
    monkeypatch.setattr(rp.subprocess, "run", lambda *a, **k: _mock_result(1))
    with pytest.raises(SystemExit) as exc:
        rp._run(["fake", "cmd"], "fatal step", fatal=True)
    assert exc.value.code == 1


def test_fatal_step_no_exit_on_success(monkeypatch):
    monkeypatch.setattr(rp.subprocess, "run", lambda *a, **k: _mock_result(0))
    elapsed = rp._run(["fake", "cmd"], "fatal step", fatal=True)
    assert elapsed >= 0.0


def test_nonfatal_step_does_not_exit_on_failure(monkeypatch):
    """The actual regression: a non-fatal step's failure must not raise SystemExit,
    so the caller's subsequent steps still run."""
    monkeypatch.setattr(rp.subprocess, "run", lambda *a, **k: _mock_result(1))
    elapsed = rp._run(["fake", "cmd"], "non-fatal step", fatal=False)
    assert elapsed >= 0.0  # returned normally, no exception


def test_nonfatal_step_default_is_still_fatal(monkeypatch):
    """fatal defaults to True — existing steps' behavior is unchanged unless
    explicitly opted into fatal=False."""
    monkeypatch.setattr(rp.subprocess, "run", lambda *a, **k: _mock_result(1))
    with pytest.raises(SystemExit):
        rp._run(["fake", "cmd"], "default step")


def test_dry_run_skips_subprocess_entirely(monkeypatch):
    called = []
    monkeypatch.setattr(rp.subprocess, "run", lambda *a, **k: called.append(1) or _mock_result(0))
    elapsed = rp._run(["fake", "cmd"], "dry step", dry_run=True)
    assert elapsed == 0.0
    assert called == []
