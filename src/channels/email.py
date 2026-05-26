from __future__ import annotations

import os
from pathlib import Path
from zoneinfo import ZoneInfo

import boto3
import yaml
from aws_lambda_powertools import Logger

from channels.base import Channel
from channels.message import Message

logger = Logger()


def resolve_addresses(group_id: str, entries: list[dict]) -> list[str]:
    """
    email.yaml のエントリリストから group_id に対応する宛先アドレスリストを返す。

    group_id が存在しない場合は WARNING を出して空リストを返す。
    """
    by_id = {e["id"]: e for e in entries}
    entry = by_id.get(group_id)
    if entry is None:
        logger.warning(
            "email group not found in email.yaml", extra={"group_id": group_id}
        )
        return []
    return list(entry.get("add", []))


def _load_email_config() -> list[dict]:
    """
    config/email.yaml を読み込んでエントリリストを返す。

    Lambda 環境では LAMBDA_TASK_ROOT/config/、ローカルではプロジェクトルートの
    config/ を参照する（_load_alarm_log_groups と同じパス解決ロジック）。
    """
    if "LAMBDA_TASK_ROOT" in os.environ:
        config_dir = Path(os.environ["LAMBDA_TASK_ROOT"]) / "config"
    else:
        # src/channels/email.py → parents[2] = プロジェクトルート
        config_dir = Path(__file__).resolve().parents[2] / "config"
    return yaml.safe_load((config_dir / "email.yaml").read_text(encoding="utf-8"))


class SESEmailChannel(Channel):
    def __init__(self, group_id: str) -> None:
        self._group_id = group_id
        entries = _load_email_config()
        self._addresses = resolve_addresses(group_id, entries)

    @property
    def id(self) -> str:
        return f"email.{self._group_id}"

    def send(self, message: Message) -> None:
        if not self._addresses:
            logger.warning(
                "no email addresses for group, skipping",
                extra={"group_id": self._group_id},
            )
            return
        boto3.client("ses").send_email(
            Source=os.environ["SES_FROM_ADDRESS"],
            Destination={"ToAddresses": self._addresses},
            Message={
                "Subject": {"Data": message.title, "Charset": "UTF-8"},
                "Body": {
                    "Html": {"Data": self._to_html(message), "Charset": "UTF-8"},
                    "Text": {"Data": self._to_plain(message), "Charset": "UTF-8"},
                },
            },
        )

    def _to_html(self, message: Message) -> str:
        jst = message.timestamp.astimezone(ZoneInfo("Asia/Tokyo"))
        actions_html = "".join(f"<li>{a}</li>" for a in message.actions)
        return (
            f"<h2>[{message.severity}] {message.title}</h2>"
            f"<p><b>対象</b>: {message.ship_name}</p>"
            f"<p><b>検知時刻</b>: {jst:%Y-%m-%d %H:%M JST}</p>"
            f"<p><b>原因推定</b>: {message.root_cause}</p>"
            f"<ul>{actions_html}</ul>"
        )

    def _to_plain(self, message: Message) -> str:
        jst = message.timestamp.astimezone(ZoneInfo("Asia/Tokyo"))
        actions = "\n".join(f"- {a}" for a in message.actions)
        return (
            f"[{message.severity}] {message.title}\n"
            f"対象: {message.ship_name}\n"
            f"検知時刻: {jst:%Y-%m-%d %H:%M JST}\n"
            f"原因推定: {message.root_cause}\n"
            f"推奨アクション:\n{actions}"
        )
