from __future__ import annotations

import os
from pathlib import Path
from zoneinfo import ZoneInfo

import boto3
import yaml
from aws_lambda_powertools import Logger

from channels.base import Channel
from channels.message import CONFIDENCE_JA, SEVERITY_JA, Message

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
    """Amazon SES を使ってアラーム通知メールを送信するチャネル実装。

    email.yaml で定義したグループ ID に対応する宛先リストを初期化時に解決し、
    HTML + プレーンテキストのマルチパートメールを SES で送信する。
    送信元アドレスは環境変数 AWS_SES_FROM_ADDRESS から取得する。
    """

    def __init__(self, group_id: str) -> None:
        """
        Args:
            group_id: email.yaml で定義した宛先グループの ID（例: ``"scrumsign"``）。
        """
        self._group_id = group_id
        entries = _load_email_config()
        self._addresses = resolve_addresses(group_id, entries)

    @property
    def id(self) -> str:
        return f"email.{self._group_id}"

    def send(self, message: Message) -> None:
        """Message を HTML / プレーンテキストのマルチパートメールで送信する。

        宛先アドレスが空の場合は WARNING を出力してスキップする。
        送信元は環境変数 AWS_SES_FROM_ADDRESS で指定する。
        """
        if not self._addresses:
            logger.warning(
                "no email addresses for group, skipping",
                extra={"group_id": self._group_id},
            )
            return
        severity_ja = SEVERITY_JA.get(message.severity, message.severity)
        subject = f"[{severity_ja}] {message.business_summary}"[:128]
        boto3.client("ses").send_email(
            Source=os.environ["AWS_SES_FROM_ADDRESS"],
            Destination={"ToAddresses": self._addresses},
            Message={
                "Subject": {"Data": subject, "Charset": "UTF-8"},
                "Body": {
                    "Html": {"Data": self._to_html(message), "Charset": "UTF-8"},
                    "Text": {"Data": self._to_plain(message), "Charset": "UTF-8"},
                },
            },
        )

    def _to_html(self, message: Message) -> str:
        """Message を HTML メール本文に変換して返す。タイムスタンプは JST に変換する。"""
        jst = message.timestamp.astimezone(ZoneInfo("Asia/Tokyo"))
        severity_ja = SEVERITY_JA.get(message.severity, message.severity)
        confidence_ja = CONFIDENCE_JA.get(message.confidence, message.confidence)
        actions_html = "".join(f"<li>{a}</li>" for a in message.technical_actions)
        return (
            f"<h2>[{severity_ja}] {message.business_summary}</h2>"
            f"<p><b>対象船舶</b>: {message.ship_name}</p>"
            f"<p><b>検知時刻</b>: {jst:%Y-%m-%d %H:%M JST}</p>"
            f"<p><b>原因の見立て</b>: {message.root_cause}</p>"
            f"<p><b>ご対応のお願い</b>: {message.business_action}</p>"
            f"<hr>"
            f"<h3>技術詳細</h3>"
            f"<p><b>エラー種別</b>: {message.error_id}</p>"
            f"<p><b>発生状況</b>: {message.technical_observation}</p>"
            f"<p><b>原因分析</b>（確度: {confidence_ja}）: {message.technical_hypothesis}</p>"
            f"<p><b>対応の提案（技術）</b>:</p>"
            f"<ul>{actions_html}</ul>"
        )

    def _to_plain(self, message: Message) -> str:
        """Message をプレーンテキストのメール本文に変換して返す。タイムスタンプは JST に変換する。"""
        jst = message.timestamp.astimezone(ZoneInfo("Asia/Tokyo"))
        severity_ja = SEVERITY_JA.get(message.severity, message.severity)
        confidence_ja = CONFIDENCE_JA.get(message.confidence, message.confidence)
        actions = "\n".join(f"- {a}" for a in message.technical_actions)
        return (
            f"[{severity_ja}] {message.business_summary}\n"
            f"対象船舶: {message.ship_name}\n"
            f"検知時刻: {jst:%Y-%m-%d %H:%M JST}\n"
            f"\n"
            f"原因の見立て:\n{message.root_cause}\n"
            f"\n"
            f"ご対応のお願い:\n{message.business_action}\n"
            f"\n"
            f"--- 技術詳細 ---\n"
            f"エラー種別: {message.error_id}\n"
            f"発生状況: {message.technical_observation}\n"
            f"原因分析（確度: {confidence_ja}）: {message.technical_hypothesis}\n"
            f"対応の提案（技術）:\n{actions}"
        )
