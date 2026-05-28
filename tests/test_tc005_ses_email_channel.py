import sys
from datetime import datetime, timezone
from pathlib import Path

import pytest

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "src"))

from channels.email import SESEmailChannel
from channels.message import Message


def make_message(**kwargs) -> Message:
    defaults = dict(
        severity="HIGH",
        confidence="high",
        business_summary="テスト業務説明",
        root_cause="原因",
        technical_observation="観測事実",
        technical_hypothesis="仮説",
        actions=[],
        alarm_name="hdw-sakura",
        ship_name="sakura",
        timestamp=datetime(2026, 5, 26, tzinfo=timezone.utc),
        error_id="lambda_failure",
    )
    defaults.update(kwargs)
    return Message(**defaults)


def test_ses_channel_id(mocker):
    mocker.patch("channels.email._load_email_config", return_value=[])
    ch = SESEmailChannel("dev")
    assert ch.id == "email.dev"


def test_ses_send_calls_send_email(mocker, monkeypatch):
    monkeypatch.setenv("AWS_SES_FROM_ADDRESS", "alerts@scrumsign.com")
    mocker.patch("channels.email._load_email_config", return_value=[])
    mocker.patch("channels.email.resolve_addresses", return_value=["a@x.com"])
    mock_client = mocker.patch("channels.email.boto3.client")
    SESEmailChannel("dev").send(make_message())
    call_kwargs = mock_client.return_value.send_email.call_args[1]
    assert call_kwargs["Source"] == "alerts@scrumsign.com"
    assert "a@x.com" in call_kwargs["Destination"]["ToAddresses"]


def test_ses_send_skips_when_no_addresses(mocker, caplog):
    mocker.patch("channels.email._load_email_config", return_value=[])
    mocker.patch("channels.email.resolve_addresses", return_value=[])
    mock_client = mocker.patch("channels.email.boto3.client")
    SESEmailChannel("missing").send(make_message())
    mock_client.return_value.send_email.assert_not_called()
    assert caplog.records
