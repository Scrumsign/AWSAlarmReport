import sys
from datetime import datetime, timezone
from pathlib import Path

import pytest

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "src"))

from channels.discord import DISCORD_SEVERITY_COLOR, DiscordChannel
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


def make_discord_channel() -> DiscordChannel:
    return DiscordChannel(
        webhook_url="https://example.com",
        environment_name="test",
        target_function_name="hdw-test-fn",
    )


def test_discord_channel_send_calls_webhook(mocker):
    mock_execute = mocker.patch("channels.discord.DiscordWebhook.execute")
    make_discord_channel().send(make_message(severity="HIGH"))
    mock_execute.assert_called_once()


def test_to_embed_color_by_severity():
    ch = make_discord_channel()
    for sev, color in DISCORD_SEVERITY_COLOR.items():
        embed = ch._to_embed(make_message(severity=sev))
        assert embed.color == color


def test_to_embed_title_contains_business_summary():
    embed = make_discord_channel()._to_embed(make_message(business_summary="業務説明テスト"))
    assert "業務説明テスト" in embed.title


def test_to_embed_title_has_severity_ja_prefix():
    embed = make_discord_channel()._to_embed(make_message(severity="HIGH"))
    assert "重要" in embed.title
