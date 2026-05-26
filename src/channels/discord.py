from __future__ import annotations

from discord_webhook import DiscordEmbed, DiscordWebhook

from channels.base import Channel
from channels.message import Message

DISCORD_SEVERITY_COLOR: dict[str, int] = {
    "LOW": 0x2ECC71,    # green
    "MEDIUM": 0xF1C40F,  # yellow
    "HIGH": 0xE74C3C,   # red
}


def _post_prompt_attachment(
    webhook_url: str,
    alarm_name: str,
    system_prompt: str,
    user_text: str,
) -> None:
    """
    Bedrock に投げた完全 prompt (system + user) を Discord に添付ファイルとして
    別 webhook で投稿する。LLM レポート (5W1H embed) とは独立した execute で
    投げるためメッセージ本体やレポート内容と取り違える余地が無い。

    添付ファイルは「LLM がなぜそう答えたか」を後追い検証するためのもので、
    Bedrock 呼び出しに使った system / user 文字列と完全一致する。
    """
    parts = [
        "============================================================",
        "COMPLETE PROMPT SENT TO BEDROCK",
        "============================================================",
        "This file contains the exact system prompt and user prompt that",
        "the Reporter Lambda sent to Amazon Bedrock for analysis. Use this",
        "to debug why the LLM said what it said in the Discord embed",
        "report (in the accompanying notification message).",
        "",
        f"# Alarm: {alarm_name}",
        "",
        "============================================================",
        "SYSTEM PROMPT",
        "============================================================",
        system_prompt.strip(),
        "",
        "============================================================",
        "USER PROMPT",
        "============================================================",
        user_text.strip(),
    ]
    body = "\n".join(parts) + "\n"

    safe_name = "".join(c if c.isalnum() or c in "-_" else "_" for c in alarm_name)
    filename = f"{safe_name}-prompt.txt"

    webhook = DiscordWebhook(
        url=webhook_url,
        content="Complete prompt sent to Bedrock (verification attachment)",
    )
    webhook.add_file(file=body.encode("utf-8"), filename=filename)
    webhook.execute()


def _post_minimal_embed(
    webhook_url: str,
    environment_name: str,
    target_function_name: str,
    alarm_name: str,
    timestamp: str,
    reason: str,
    rows_count: int,
    extra_note: str,
    color: int,
) -> None:
    """
    LLM 分析なしでコア情報だけ Discord に通知する fallback / no-logs 共通経路。

    ``report-content-by-case`` DRAFT §4.5 の「LLM 失敗時は機械抽出のコア情報だけで
    通知を成立させる」を最小実装。空ログ早期 return と Bedrock 失敗 fallback の
    両方から呼ばれる。

    main 5W1H embed と同じ author / field レイアウト原則に揃え、絵文字を排して
    color で severity を表現する。
    """
    webhook = DiscordWebhook(url=webhook_url)
    embed = DiscordEmbed(title=extra_note[:256], color=color)
    embed.set_author(name=f"HDW Notify · {environment_name}")

    embed.add_embed_field(name="監視対象 Lambda", value=target_function_name, inline=True)
    embed.add_embed_field(name="発火 Alarm", value=alarm_name, inline=True)
    embed.add_embed_field(name="件数", value=f"{rows_count} 件", inline=True)

    embed.add_embed_field(name="Alarm reason", value=reason or "(none)", inline=False)
    embed.set_timestamp(timestamp)
    webhook.add_embed(embed)
    webhook.execute()


class DiscordChannel(Channel):
    """Discord Webhook を使ってアラーム通知を投稿するチャネル実装。

    DiscordEmbed を用いて severity に応じた色付き埋め込みを送信する。
    Discord 固有の UI（author、フィールドレイアウト、タイムスタンプ）は
    このクラス内に閉じており、Message データ構造には依存しない。
    """

    def __init__(
        self,
        webhook_url: str,
        environment_name: str,
        target_function_name: str,
    ) -> None:
        """
        Args:
            webhook_url: Discord Webhook の URL（環境変数 DISCORD_WEBHOOK_URL）。
            environment_name: embed の author 表示名に使う環境識別子。
            target_function_name: 監視対象 Lambda 名。embed フィールドに表示する。
        """
        self._webhook_url = webhook_url
        self._environment_name = environment_name
        self._target_function_name = target_function_name

    @property
    def id(self) -> str:
        return "discord"

    def send(self, message: Message) -> None:
        """Message を Discord Embed としてフォーマットし Webhook で投稿する。

        severity が DISCORD_SEVERITY_COLOR に存在しない場合はグレー（0x95A5A6）を使う。
        actions が空の場合は推奨アクションフィールドを省略する。
        """
        webhook = DiscordWebhook(url=self._webhook_url)
        color = DISCORD_SEVERITY_COLOR.get(message.severity, 0x95A5A6)
        embed = DiscordEmbed(title=message.title[:256], color=color)
        embed.set_author(name=f"HDW Notify · {self._environment_name}")

        embed.add_embed_field(
            name="監視対象 Lambda", value=self._target_function_name, inline=True
        )
        embed.add_embed_field(name="発火 Alarm", value=message.alarm_name, inline=True)

        embed.add_embed_field(
            name=f"原因仮説 (confidence: {message.confidence})",
            value=message.root_cause or "(不明)",
            inline=False,
        )

        if message.actions:
            embed.add_embed_field(
                name="推奨アクション",
                value="\n".join(f"- {a}" for a in message.actions),
                inline=False,
            )

        embed.set_timestamp(message.timestamp)
        webhook.add_embed(embed)
        webhook.execute()
