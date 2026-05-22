import sys
from pathlib import Path


sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "src"))

import main  # noqa: E402


def test_extract_ship_name_from_production_alarm_name():
    assert main._extract_ship_name_from_alarm_name("hdw-sakura") == "sakura"
    assert main._extract_ship_name_from_alarm_name("hdw-shimakaji") == "shimakaji"


def test_extract_ship_name_from_test_alarm_name():
    assert main._extract_ship_name_from_alarm_name("hdw-sakura-test") == "sakura"


def test_extract_ship_name_rejects_aggregate_or_legacy_alarm_name():
    assert main._extract_ship_name_from_alarm_name("TestAlarm") is None
    assert main._extract_ship_name_from_alarm_name("hdw-backend-processor-0001-errors") is None
    assert main._extract_ship_name_from_alarm_name("hdw-Sakura") is None


def test_build_ship_logs_insights_query_filters_by_ship_name_only():
    query = main._build_ship_logs_insights_query("sakura")

    assert '| filter ship_name = "sakura"' in query
    assert 'status = "error"' not in query
    assert "| limit 200" in query
