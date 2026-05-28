import sys
from datetime import datetime, timezone
from pathlib import Path

import pytest

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "src"))

import main
from channels.discord import DiscordChannel
from channels.email import SESEmailChannel
from channels.message import Message
from main import Env, _build_channel_registry, _dispatch


def make_message(**kwargs) -> Message:
    defaults = dict(
        severity="HIGH",
        confidence="high",
        business_summary="テスト業務説明",
        root_cause="原因",
        business_action="確認してください",
        technical_observation="観測事実",
        technical_hypothesis="仮説",
        technical_actions=[],
        alarm_name="hdw-sakura",
        ship_name="sakura",
        timestamp=datetime(2026, 5, 26, tzinfo=timezone.utc),
        error_id="lambda_failure",
    )
    defaults.update(kwargs)
    return Message(**defaults)


def make_env() -> Env:
    return Env(
        discord_webhook_url="https://example.com",
        cross_account_role_arn="arn:aws:iam::123:role/test",
        cloudwatch_logs_query_poll_interval_sec=1.0,
        bedrock_model_id="model",
        bedrock_max_tokens=100,
        environment_name="test",
        target_function_name="hdw-test-fn",
    )


# --- static 確認 ---

def test_no_logs_pattern_not_in_main():
    src = Path(__file__).resolve().parents[1] / "src" / "main.py"
    assert "no_logs" not in src.read_text(encoding="utf-8")


def test_message_construct_in_main():
    src = Path(__file__).resolve().parents[1] / "src" / "main.py"
    assert "Message(" in src.read_text(encoding="utf-8")


def test_dispatch_referenced_in_main():
    src = Path(__file__).resolve().parents[1] / "src" / "main.py"
    assert "_dispatch" in src.read_text(encoding="utf-8")


def test_resolve_error_id_referenced_in_main():
    src = Path(__file__).resolve().parents[1] / "src" / "main.py"
    assert "_resolve_error_id" in src.read_text(encoding="utf-8")


# --- _dispatch ルーティング動作 ---

def test_dispatch_sends_to_all_registered_channels(mocker):
    mock_discord = mocker.MagicMock(spec=DiscordChannel)
    mock_email   = mocker.MagicMock(spec=SESEmailChannel)
    mocker.patch("main._load_error_profiles", return_value={
        "s3_data_missing": {"channels": ["discord", "email.dev"], "description": ""}
    })
    mocker.patch("main._build_channel_registry",
                 return_value={"discord": mock_discord, "email.dev": mock_email})
    _dispatch("hdw-sakura", make_message(), "s3_data_missing", make_env())
    mock_discord.send.assert_called_once()
    mock_email.send.assert_called_once()


def test_dispatch_fallback_discord_when_error_id_not_in_profiles(mocker, caplog):
    mock_discord = mocker.MagicMock(spec=DiscordChannel)
    mocker.patch("main._load_error_profiles", return_value={})
    mocker.patch("main._build_channel_registry", return_value={"discord": mock_discord})
    _dispatch("hdw-sakura", make_message(), "nonexistent_id", make_env())
    mock_discord.send.assert_called_once()
    assert caplog.records


def test_dispatch_continues_after_channel_exception(mocker):
    mock_discord = mocker.MagicMock(spec=DiscordChannel)
    mock_email   = mocker.MagicMock(spec=SESEmailChannel)
    mock_email.send.side_effect = Exception("SES error")
    mocker.patch("main._load_error_profiles", return_value={
        "s3_data_missing": {"channels": ["email.dev", "discord"], "description": ""}
    })
    mocker.patch("main._build_channel_registry",
                 return_value={"discord": mock_discord, "email.dev": mock_email})
    _dispatch("hdw-sakura", make_message(), "s3_data_missing", make_env())
    mock_discord.send.assert_called_once()


def test_dispatch_does_not_raise_on_all_channel_failure(mocker):
    mock_ch = mocker.MagicMock()
    mock_ch.send.side_effect = Exception("fail")
    mocker.patch("main._load_error_profiles", return_value={
        "s3_data_missing": {"channels": ["discord", "email.dev"], "description": ""}
    })
    mocker.patch("main._build_channel_registry",
                 return_value={"discord": mock_ch, "email.dev": mock_ch})
    _dispatch("hdw-sakura", make_message(), "s3_data_missing", make_env())


def test_unknown_channel_id_is_skipped_with_warning(mocker, caplog):
    mocker.patch("main._load_error_profiles", return_value={
        "s3_data_missing": {"channels": ["other_channel"], "description": ""}
    })
    mocker.patch("main._build_channel_registry", return_value={})
    _dispatch("hdw-sakura", make_message(), "s3_data_missing", make_env())
    assert caplog.records


# --- _build_channel_registry ---

def test_build_channel_registry_creates_ses_channel(mocker):
    mocker.patch("channels.email._load_email_config", return_value=[])
    registry = _build_channel_registry(["discord", "email.dev"], make_env())
    assert isinstance(registry.get("email.dev"), SESEmailChannel)
    assert registry["email.dev"]._group_id == "dev"


def test_build_channel_registry_skips_unknown_prefix(mocker):
    registry = _build_channel_registry(["unknown_channel"], make_env())
    assert registry.get("unknown_channel") is None
