from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime


@dataclass(frozen=True)
class Message:
    """チャネル間で共有する通知メッセージのデータ構造。

    Bedrock の解析結果と CloudWatch アラームのメタ情報を一つにまとめ、
    各 Channel 実装（Discord / SES メール）がそれぞれのフォーマットで
    送信できるよう設計されている。frozen=True により不変オブジェクトとして扱う。

    Attributes:
        title: 通知タイトル（アラーム名 + 船名など）。
        severity: 重要度。HIGH / MEDIUM / LOW のいずれか。
        confidence: Bedrock 分析の確信度。high / medium / low のいずれか。
        root_cause: Bedrock が推定した根本原因の説明文。
        actions: 推奨アクションのリスト（Markdown 不可、プレーンテキスト）。
        alarm_name: CloudWatch アラーム名（生の値）。
        ship_name: アラーム名から抽出した船名。
        timestamp: アラーム発火時刻（UTC）。
    """

    title: str
    severity: str        # HIGH / MEDIUM / LOW
    confidence: str      # high / medium / low
    root_cause: str
    actions: list[str]
    alarm_name: str
    ship_name: str
    timestamp: datetime
