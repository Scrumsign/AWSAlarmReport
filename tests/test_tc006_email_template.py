import sys
from datetime import datetime, timezone
from pathlib import Path

import pytest

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "src"))

from channels.email import SESEmailChannel
from channels.message import Message


def make_message(**kwargs) -> Message:
    defaults = dict(
        title="テスト通知",
        severity="HIGH",
        confidence="high",
        root_cause="原因",
        actions=[],
        alarm_name="hdw-sakura",
        ship_name="sakura",
        timestamp=datetime(2026, 5, 26, 10, 0, tzinfo=timezone.utc),
    )
    defaults.update(kwargs)
    return Message(**defaults)


def make_channel(mocker) -> SESEmailChannel:
    mocker.patch("channels.email._load_email_config", return_value=[])
    mocker.patch("channels.email.resolve_addresses", return_value=["a@x.com"])
    return SESEmailChannel("dev")


def test_to_html_contains_required_fields(mocker):
    msg = make_message(
        ship_name="sakura",
        severity="HIGH",
        timestamp=datetime(2026, 5, 26, 10, 0, tzinfo=timezone.utc),
        actions=["アクション1", "アクション2"],
    )
    html = make_channel(mocker)._to_html(msg)
    assert "sakura" in html
    assert "HIGH" in html
    assert "JST" in html
    assert "2026" in html
    assert "アクション1" in html
    assert "アクション2" in html


def test_to_plain_contains_required_fields(mocker):
    msg = make_message(
        ship_name="sakura",
        severity="LOW",
        timestamp=datetime(2026, 5, 26, 10, 0, tzinfo=timezone.utc),
        actions=["アクション1"],
    )
    plain = make_channel(mocker)._to_plain(msg)
    assert "sakura" in plain
    assert "LOW" in plain
    assert "JST" in plain
    assert "アクション1" in plain


def test_send_email_has_html_and_text_body(mocker, monkeypatch):
    monkeypatch.setenv("SES_FROM_ADDRESS", "alerts@scrumsign.com")
    mock_client = mocker.patch("channels.email.boto3.client")
    make_channel(mocker).send(make_message())
    body = mock_client.return_value.send_email.call_args[1]["Message"]["Body"]
    assert "Html" in body
    assert "Text" in body
