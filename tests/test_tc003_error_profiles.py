import sys
from pathlib import Path

import pytest

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "src"))

import main


def test_load_error_profiles_structure():
    profiles = main._load_error_profiles()
    assert "s3_data_missing" in profiles
    entry = profiles["s3_data_missing"]
    assert "channels" in entry
    assert "description" in entry


def test_resolve_channel_ids_returns_channels():
    profiles = {"s3_data_missing": {"channels": ["discord", "email.dev"]}}
    result = main._resolve_channel_ids("s3_data_missing", profiles)
    assert "email.dev" in result


def test_resolve_channel_ids_fallback_on_unknown(caplog):
    profiles = {}
    result = main._resolve_channel_ids("nonexistent", profiles)
    assert result == ["discord"]
    assert caplog.records


def test_resolve_error_id_empty_logs():
    assert main._resolve_error_id("hdw-sakura", []) == "s3_data_missing"


def test_resolve_error_id_with_error_log():
    log_row = [{"field": "status", "value": "error"}]
    assert main._resolve_error_id("hdw-sakura", [log_row]) == "lambda_failure"


def test_resolve_error_id_logs_without_error(caplog):
    log_row = [{"field": "status", "value": "success"}]
    result = main._resolve_error_id("hdw-sakura", [log_row])
    assert result == "unknown"
    assert caplog.records


def test_resolve_error_id_unknown_alarm(caplog):
    result = main._resolve_error_id("other-system-alarm", [])
    assert result == "unknown_alarm"
    assert caplog.records
