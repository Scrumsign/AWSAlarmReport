"""
HDW Notify エントリポイント。

クライアントアカウントの CloudWatch Alarm → SNS Topic → 自社 Lambda の経路で起動し、
STS AssumeRole 経由でクライアント側 CloudWatch Logs を取得 → LLM 分析 → Discord 通知する。

設計方針:

* **全変数は Lambda 環境変数から ``os.environ`` で取得する**。
  Lambda の環境変数は KMS で保管時暗号化され、コールドスタート時にランタイムへ
  復号注入されるため、コード上は普通の文字列として読める。値変更は
  ``aws lambda update-function-configuration --environment`` で反映する
  （関数コードの再ビルドは不要）。
* 環境変数への投入は GitHub Actions のデプロイジョブが ``secrets`` / ``vars`` を
  読んで実行する。Lambda 側からは ``os.environ`` だけが入力源。
* アプリ内部ロジック（Insights クエリ・severity 色マップ）は本ファイル定数で持つ。
"""

from __future__ import annotations

import dataclasses
import json
import os
import re
import time
import urllib.parse
from datetime import datetime, timedelta, timezone
from pathlib import Path
from typing import Any

import boto3
import yaml
from aws_lambda_powertools import Logger
from botocore.exceptions import BotoCoreError, ClientError
from discord_webhook import DiscordEmbed, DiscordWebhook

from utils.prompt import (
    render_prompt_case_lambda_failure,
    render_prompt_system_base,
    render_prompt_user,
)

logger = Logger()


INSIGHTS_QUERY_TEMPLATE = """\
fields @timestamp, @message, level, function_request_id, cold_start, ship_name, ship_timestamp, input_key, phase, exception_name, message, exception, xray_trace_id
| filter ship_name = "{ship_name}"
| sort @timestamp desc
| limit 200
"""
"""
Reporter が常用する Logs Insights クエリ（アプリ内部ロジック）。

Lambda 側は aws_lambda_powertools.Logger 出力の JSON 構造化ログで、AlarmName から
抽出した ``ship_name`` と同じ対象イベントを抽出する。
フィールドは HDW_Backend_Processor_0001 の実ログに準拠:

* ``status`` … ``"error"`` / ``"success"``（Metric Filter のキー）
* ``phase`` … 失敗箇所のフェーズ（``handler`` など）
* ``ship_name`` / ``ship_timestamp`` / ``input_key`` … 処理対象の識別子
* ``exception_name`` / ``exception`` … 例外クラスと traceback 文字列
* ``function_request_id`` / ``xray_trace_id`` … トレース用
"""

DISCORD_SEVERITY_COLOR: dict[str, int] = {
    "LOW": 0x2ECC71,    # green
    "MEDIUM": 0xF1C40F,  # yellow
    "HIGH": 0xE74C3C,   # red
}
"""
severity → Discord Embed カラー (10 進 RGB) マップ（アプリ内部ロジック）。
"""

INSIGHTS_QUERY_TIMEOUT_SEC = 60.0
"""
CloudWatch Logs Insights の完了待ち上限秒数。
"""

SHIP_LOG_WINDOW_MIN = 330
"""
per-ship Alarm 発火時に取得する実行ログの時間窓（過去 5 時間 30 分）。
"""

ALARM_NAME_RE = re.compile(r"^hdw-(?P<ship_name>[a-z][a-z0-9]*)(?:-test)?$")
"""
alarm-naming-convention v1.0.0 の per-ship AlarmName 形式。
"""


def _load_alarm_log_groups() -> dict[str, list[str]]:
    """
    config/alarm_log_groups.yml を読み込み AlarmName → log group list の dict を返す。

    Lambda 実行環境では Docker image に同梱された ``/var/task/config/alarm_log_groups.yml``
    を、ローカル実行ではプロジェクトルートの ``config/alarm_log_groups.yml`` を参照する。
    本ファイルは Lambda 起動時 (モジュールロード時) に 1 回だけ読み込まれ、以降は
    プロセス内の dict をそのまま使う。値変更はコード再ビルド + 再デプロイが必要。
    """
    if "LAMBDA_TASK_ROOT" in os.environ:
        config_dir = Path(os.environ["LAMBDA_TASK_ROOT"]) / "config"
    else:
        config_dir = Path(__file__).resolve().parents[1] / "config"
    with open(config_dir / "alarm_log_groups.yml", encoding="utf-8") as f:
        loaded = yaml.safe_load(f) or {}
    return {str(k): list(v) for k, v in loaded.items()}


_ALARM_LOG_GROUPS: dict[str, list[str]] = _load_alarm_log_groups()
"""
モジュールロード時に解決された AlarmName → log group list の dict。
値は list だが、現実装は先頭 1 件 (``[0]``) のみをクエリ対象として使う。
"""


@dataclasses.dataclass(slots=True, frozen=True)
class Env:
    """
    Lambda 環境変数から読み込んだ設定一式。

    各フィールドは ``os.environ`` の同名キー（大文字スネークケース）に対応する。
    値の型変換はここで一度だけ行い、以降のロジックは型付きフィールドだけを使う。
    """

    discord_webhook_url: str
    cross_account_role_arn: str
    external_id: str
    cloudwatch_logs_query_poll_interval_sec: float
    bedrock_model_id: str
    bedrock_max_tokens: int
    environment_name: str
    target_function_name: str

    @classmethod
    def from_environ(cls) -> "Env":
        return cls(
            discord_webhook_url=os.environ["DISCORD_WEBHOOK_URL"],
            cross_account_role_arn=os.environ["CROSS_ACCOUNT_ROLE_ARN"],
            external_id=os.environ["EXTERNAL_ID"],
            cloudwatch_logs_query_poll_interval_sec=float(
                os.environ["CLOUDWATCH_LOGS_QUERY_POLL_INTERVAL_SEC"]
            ),
            bedrock_model_id=os.environ["BEDROCK_MODEL_ID"],
            bedrock_max_tokens=int(os.environ["BEDROCK_MAX_TOKENS"]),
            environment_name=os.environ["ENVIRONMENT_NAME"],
            target_function_name=os.environ["TARGET_FUNCTION_NAME"],
        )


JST = timezone(timedelta(hours=9))


def _format_window_jst(start: datetime, end: datetime) -> str:
    """
    集計時間窓を ``HH:MM–HH:MM JST`` の形で返す。

    Embed の機械事実 (When) フィールド用。受信者は同じ場所で常に同じ
    フォーマットを見るため、月日や秒は省く（footer に絶対時刻があるため）。
    """
    s = start.astimezone(JST)
    e = end.astimezone(JST)
    return f"{s.strftime('%H:%M')}–{e.strftime('%H:%M')} JST"


def _format_jst(timestamp_iso: str) -> str:
    """
    ISO 8601 タイムスタンプ文字列を ``YYYY-MM-DD HH:MM:SS JST`` で返す。

    footer の絶対時刻表示用。``Z`` サフィックス対応のため
    ``+00:00`` への置換を行ってから ``datetime.fromisoformat`` に渡す。
    """
    dt = datetime.fromisoformat(timestamp_iso.replace("Z", "+00:00"))
    return dt.astimezone(JST).strftime("%Y-%m-%d %H:%M:%S JST")


def _extract_region_from_alarm_arn(alarm_arn: str | None) -> str | None:
    """
    CloudWatch Alarm ARN から AWS region ID を取り出す。

    SNS Message の ``Region`` は表示名になる場合があるため、API 呼び出し用には
    ARN の region セグメントを優先する。
    """
    if not alarm_arn:
        return None
    parts = alarm_arn.split(":")
    if len(parts) >= 4 and parts[2] == "cloudwatch" and parts[3]:
        return parts[3]
    return None


def _extract_ship_name_from_alarm_name(alarm_name: str) -> str | None:
    """
    per-ship AlarmName (``hdw-<ship-name>`` / ``hdw-<ship-name>-test``) から船名を返す。

    命名規約に合わない旧 Alarm / 集約 Alarm は ``None`` として扱い、呼び出し元で
    fallback 通知に倒す。
    """
    match = ALARM_NAME_RE.fullmatch(alarm_name)
    if not match:
        return None
    return match.group("ship_name")


def _build_ship_logs_insights_query(ship_name: str) -> str:
    """
    ``ship_name`` で絞り込む Logs Insights クエリを組み立てる。

    ``ship_name`` は _extract_ship_name_from_alarm_name() の正規表現を通った
    小文字英数字のみなので、Insights 文字列へ直接埋め込める。
    """
    return INSIGHTS_QUERY_TEMPLATE.format(ship_name=ship_name)


def _normalize_report(report: dict[str, Any]) -> dict[str, Any]:
    """
    LLM 応答を Discord 投稿で扱う最小スキーマに正規化する。

    JSON としては読めてもキー欠落や enum 逸脱があるケースを、通知欠落にせず
    安全な既定値へ丸める。
    """
    severity = str(report.get("severity") or "MEDIUM").upper()
    if severity not in DISCORD_SEVERITY_COLOR:
        severity = "MEDIUM"

    actions = report.get("suggested_actions")
    if not isinstance(actions, list):
        actions = []

    return {
        "summary": str(report.get("summary") or "LLM 分析結果の要約を取得できませんでした")[:256],
        "severity": severity,
        "confidence": str(report.get("confidence") or "low"),
        "root_cause_hypothesis": str(report.get("root_cause_hypothesis") or "(不明)"),
        "suggested_actions": [str(action) for action in actions[:3]],
    }


def _extract_first_request_id(log_rows: list[list[dict[str, str]]]) -> str | None:
    """
    Logs Insights 結果の先頭行から ``function_request_id`` を取り出す。

    無ければ ``None``。footer の代表 request_id 表示用で、複数行のうち
    どの行を代表として出すかは「先頭 = 最新（``sort @timestamp desc``）」を採る。
    """
    if not log_rows:
        return None
    for item in log_rows[0]:
        if item.get("field") == "function_request_id":
            return item.get("value")
    return None


def _cw_encode_log_group(log_group: str) -> str:
    """
    CloudWatch コンソールの URL フラグメント内で log group 名のスラッシュを
    ``$252F`` に二重エンコードする（コンソール側のカスタムエンコード仕様）。
    """
    return log_group.replace("/", "$252F")


def _build_deeplinks_markdown(
    env: "Env", log_group: str, region: str, start: datetime, end: datetime
) -> str:
    """
    CloudWatch Logs / Insights / Metrics への deeplink を
    ``[Logs](url) · [Insights](url) · [Metrics](url)`` の Markdown で返す。

    Embed の「詳細リンク」field 用。URL エンコードはコンソールの
    フラグメント内仕様 (``$252F`` / ``$3F`` 等) に従う。Insights / Metrics の
    URL は最小限の事前入力のみ（時間窓・log group / 関数名）で、運用観察を経て
    必要なら強化する（PLAN §10 残課題）。

    cross-account-architecture v1.0.0 以降は log_group / region を引数で受け取る
    (LOG_GROUP_MAP による動的解決と、SNS Message の Region に追従するため)。
    """
    encoded_lg = _cw_encode_log_group(log_group)
    start_unix = int(start.timestamp())
    end_unix = int(end.timestamp())

    logs_url = (
        f"https://{region}.console.aws.amazon.com/cloudwatch/home"
        f"?region={region}#logsV2:log-groups/log-group/{encoded_lg}"
    )
    insights_url = (
        f"https://{region}.console.aws.amazon.com/cloudwatch/home"
        f"?region={region}#logsV2:logs-insights"
        f"$3FqueryDetail$3D~(end~{end_unix}~start~{start_unix}"
        f"~timeType~'ABSOLUTE~unit~'seconds~source~(~'{encoded_lg}))"
    )
    fn_encoded = urllib.parse.quote(env.target_function_name, safe="")
    metrics_url = (
        f"https://{region}.console.aws.amazon.com/cloudwatch/home"
        f"?region={region}#metricsV2:graph=~();query=AWS*2fLambda%20"
        f"FunctionName%3D{fn_encoded}"
    )
    return f"[Logs]({logs_url}) · [Insights]({insights_url}) · [Metrics]({metrics_url})"


def _format_log_rows_pretty(log_rows: list[list[dict[str, str]]]) -> str:
    """
    Insights クエリ結果を Bedrock に渡しやすい整形済みテキストへ変換する。

    function_request_id 単位で session グルーピングし、各 session は header
    1 行 + 本文に絞り込む。各行で繰り返される冗長フィールド (service /
    function_name / function_arn / ship_name / function_request_id 等) は
    本文に出さず、connection-specific extras のみ inline kv で表示する。
    location と event-specific 情報は @message JSON から抽出する
    (Insights クエリで @message を fields に含める前提)。

    可読性と LLM の解釈精度の両方を狙い、以下の追加圧縮を行う:
      - 連続する同じ (location, message) を ``(×N)`` に圧縮
      - 巨大な message (>500 chars or 改行 >5) を要約表示に置換
    """
    parsed_rows: list[dict[str, Any]] = []
    for row in log_rows:
        f = {item["field"]: item["value"] for item in row if "field" in item and "value" in item}
        raw_msg = f.get("@message", "")
        event_fields: dict[str, Any] = {}
        try:
            event_fields = json.loads(raw_msg) if raw_msg else {}
        except (json.JSONDecodeError, TypeError):
            event_fields = {}
        parsed_rows.append({
            "timestamp": f.get("@timestamp") or event_fields.get("timestamp") or "?",
            "request_id": f.get("function_request_id") or event_fields.get("function_request_id") or "(no-request-id)",
            "level": (f.get("level") or event_fields.get("level") or "INFO").upper()[:4],
            "location": event_fields.get("location", ""),
            "message": event_fields.get("message", "") or f.get("message", ""),
            "event_fields": event_fields,
        })

    parsed_rows.sort(key=lambda r: r["timestamp"])
    sessions: dict[str, list[dict[str, Any]]] = {}
    for r in parsed_rows:
        sessions.setdefault(r["request_id"], []).append(r)

    drop_keys = {
        "service", "function_name", "function_memory_size", "function_arn",
        "ship_name", "name_part", "xray_trace_id", "cold_start",
        "ship_timestamp", "input_key", "function_request_id",
        "level", "location", "message", "timestamp",
    }

    out: list[str] = []
    n = len(sessions)
    for i, (req_id, rows) in enumerate(sessions.items(), 1):
        started_at = rows[0]["timestamp"]
        out.append("=" * 64)
        out.append(f"Session {i}/{n}  ·  request_id={req_id}")
        out.append(f"  started_at: {started_at}")
        out.append("=" * 64)

        prev_key: tuple[str, str] | None = None
        dup_count = 0
        body: list[str] = []

        def flush_dup() -> None:
            if dup_count > 1 and body:
                body[-1] = body[-1] + f"  (×{dup_count})"

        for r in rows:
            ts = r["timestamp"]
            level = r["level"]
            loc = r["location"] or ""
            msg = r["message"] or ""

            if len(msg) > 500 or msg.count("\n") > 5:
                msg = f"[truncated: {len(msg)} chars / {msg.count(chr(10))} lines]"

            extras = {
                k: v for k, v in r["event_fields"].items()
                if k not in drop_keys and v not in (None, "", [], {})
            }
            extras_str = ""
            if extras:
                kv_pairs = []
                for k, v in extras.items():
                    val_str = str(v)
                    if len(val_str) > 200:
                        val_str = val_str[:200] + "..."
                    kv_pairs.append(f"{k}:{val_str}")
                extras_str = "  {" + ", ".join(kv_pairs) + "}"

            line = f"[{ts}] {level:<4} {loc}  {msg}{extras_str}".rstrip()

            cur_key = (loc, msg)
            if cur_key == prev_key:
                dup_count += 1
                continue
            flush_dup()
            dup_count = 1
            prev_key = cur_key
            body.append(line)

        flush_dup()
        out.extend(body)
        out.append("")

    while out and out[-1] == "":
        out.pop()
    return "\n".join(out)


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

    # 識別子 (Lambda / Alarm / 件数) を main 5W1H embed と同じ並びで inline 表示
    embed.add_embed_field(name="監視対象 Lambda", value=target_function_name, inline=True)
    embed.add_embed_field(name="発火 Alarm", value=alarm_name, inline=True)
    embed.add_embed_field(name="件数", value=f"{rows_count} 件", inline=True)

    embed.add_embed_field(name="Alarm reason", value=reason or "(none)", inline=False)
    embed.set_timestamp(timestamp)
    webhook.add_embed(embed)
    webhook.execute()


@logger.inject_lambda_context(log_event=True)
def main(event: dict[str, Any], _context: Any = None) -> dict[str, Any]:
    """
    Lambda エントリ。環境変数から設定を取り Alarm 処理を実行する。

    ``_context`` は Lambda 署名互換のため受けるだけで未使用。ローカルから直接
    呼び出して動作確認することも可能（必要な環境変数を事前にセットしておく）。
    """

    # --- Lambda 環境変数から全変数取得 ---
    env = Env.from_environ()

    # --- SNS Message からアラーム情報を取り出す ---
    # CloudWatch Alarm Action は SNS Publish を経由するため、Lambda は
    # SNS イベント形式 (Records[0].Sns.Message に Alarm の JSON が文字列で入る) を受ける。
    sns_message: dict[str, Any] = json.loads(event["Records"][0]["Sns"]["Message"])
    alarm_name: str = sns_message["AlarmName"]
    client_account_id: str = sns_message["AWSAccountId"]
    client_region: str = (
        _extract_region_from_alarm_arn(sns_message.get("AlarmArn"))
        or os.environ.get("AWS_REGION", "ap-northeast-1")
    )
    timestamp: str = sns_message["StateChangeTime"]
    reason: str = sns_message.get("NewStateReason", "")

    # --- Alarm 発火時刻から過去 5 時間 30 分の時間窓を導出 ---
    center = datetime.fromisoformat(timestamp.replace("Z", "+00:00"))
    start = center - timedelta(minutes=SHIP_LOG_WINDOW_MIN)
    end = center
    logger.append_keys(alarm=alarm_name, client_account=client_account_id)
    logger.info("alarm received", extra={"timestamp": timestamp, "region": client_region})

    # --- alarm-naming-convention に従い AlarmName から ship_name を抽出 ---
    ship_name = _extract_ship_name_from_alarm_name(alarm_name)
    if not ship_name:
        logger.warning("alarm name does not match per-ship convention", extra={"alarm_name": alarm_name})
        _post_minimal_embed(
            webhook_url=env.discord_webhook_url,
            environment_name=env.environment_name,
            target_function_name=env.target_function_name,
            alarm_name=alarm_name,
            timestamp=timestamp,
            reason=reason,
            rows_count=0,
            extra_note="AlarmName が per-ship 命名規約 (hdw-<ship>[-test]) に一致しません",
            color=0xF1C40F,  # yellow
        )
        return {"ok": True, "alarm": alarm_name, "skipped": "invalid_alarm_name"}
    logger.append_keys(ship_name=ship_name)

    # --- アラーム名からロググループを解決 (config/alarm_log_groups.yml) ---
    # config 値は list で持つが、現実装は先頭 1 件のみクエリする (将来 N 件並列化の余地)。
    log_groups = _ALARM_LOG_GROUPS.get(alarm_name) or []
    if not log_groups:
        logger.warning("no log group mapped", extra={"alarm_name": alarm_name})
        _post_minimal_embed(
            webhook_url=env.discord_webhook_url,
            environment_name=env.environment_name,
            target_function_name=env.target_function_name,
            alarm_name=alarm_name,
            timestamp=timestamp,
            reason=reason,
            rows_count=0,
            extra_note="config/alarm_log_groups.yml に該当アラームの登録がありません",
            color=0xF1C40F,  # yellow
        )
        return {"ok": True, "alarm": alarm_name, "skipped": "no_log_group_mapped"}
    log_group = log_groups[0]

    # --- クライアントアカウントの Logs Insights を読むために AssumeRole ---
    try:
        sts_response = boto3.client("sts").assume_role(
            RoleArn=env.cross_account_role_arn,
            RoleSessionName=f"hdw-notify-{_context.aws_request_id}",
            ExternalId=env.external_id,
            DurationSeconds=900,
        )
        creds = sts_response["Credentials"]
        logger.info(
            "assumed cross-account role",
            extra={"assumed_role_arn": sts_response["AssumedRoleUser"]["Arn"]},
        )
    except (BotoCoreError, ClientError) as e:
        logger.exception("assume_role failed; posting minimal fallback embed")
        _post_minimal_embed(
            webhook_url=env.discord_webhook_url,
            environment_name=env.environment_name,
            target_function_name=env.target_function_name,
            alarm_name=alarm_name,
            timestamp=timestamp,
            reason=reason,
            rows_count=0,
            extra_note=f"クライアントログ取得用 AssumeRole 失敗: {type(e).__name__}",
            color=0xE74C3C,  # red
        )
        return {"ok": True, "alarm": alarm_name, "fallback": "assume_role_failed"}

    # --- CloudWatch Logs Insights で対象船舶の実行ログを取得 ---
    logs_client = boto3.client(  # tmp credentials でクライアント側 Logs API を叩く
        "logs",
        region_name=client_region,
        aws_access_key_id=creds["AccessKeyId"],
        aws_secret_access_key=creds["SecretAccessKey"],
        aws_session_token=creds["SessionToken"],
    )
    query_id: str = logs_client.start_query(  # 非同期クエリ起動 → queryId を取得
        logGroupName=log_group,
        startTime=int(start.timestamp()),
        endTime=int(end.timestamp()),
        queryString=_build_ship_logs_insights_query(ship_name),
    )["queryId"]
    logger.info("insights query started", extra={"query_id": query_id, "ship_name": ship_name})
    log_rows: list[list[dict[str, str]]] = []
    query_deadline = time.monotonic() + INSIGHTS_QUERY_TIMEOUT_SEC
    while True:
        query_result = logs_client.get_query_results(queryId=query_id)  # 完了状態をポーリング
        query_status = query_result["status"]
        if query_status == "Complete":
            log_rows = query_result.get("results", [])
            break
        if query_status in ("Failed", "Cancelled", "Timeout"):
            logger.warning("insights query failed", extra={"status": query_status})
            _post_minimal_embed(
                webhook_url=env.discord_webhook_url,
                environment_name=env.environment_name,
                target_function_name=env.target_function_name,
                alarm_name=alarm_name,
                timestamp=timestamp,
                reason=reason,
                rows_count=0,
                extra_note=f"CloudWatch Logs Insights 取得失敗: {query_status}",
                color=0xF1C40F,  # yellow
            )
            return {
                "ok": True,
                "alarm": alarm_name,
                "fallback": "insights_query_failed",
                "query_status": query_status,
            }
        if time.monotonic() >= query_deadline:
            logger.warning("insights query timed out", extra={"query_id": query_id})
            _post_minimal_embed(
                webhook_url=env.discord_webhook_url,
                environment_name=env.environment_name,
                target_function_name=env.target_function_name,
                alarm_name=alarm_name,
                timestamp=timestamp,
                reason=reason,
                rows_count=0,
                extra_note="CloudWatch Logs Insights 取得がタイムアウトしました",
                color=0xF1C40F,  # yellow
            )
            return {"ok": True, "alarm": alarm_name, "fallback": "insights_query_timeout"}
        # 次のポーリングまで待機（Insights は数秒〜数十秒かかるため）
        time.sleep(env.cloudwatch_logs_query_poll_interval_sec)
    logger.info(
        "insights query done",
        extra={"status": query_result["status"], "rows": len(log_rows)},
    )

    # --- 空ログなら Bedrock を呼ばずに最小通知して終了 ---
    if not log_rows:
        _post_minimal_embed(
            webhook_url=env.discord_webhook_url,
            environment_name=env.environment_name,
            target_function_name=env.target_function_name,
            alarm_name=alarm_name,
            timestamp=timestamp,
            reason=reason,
            rows_count=0,
            extra_note=f"直近 5 時間 30 分に ship_name={ship_name} の実行ログがありません",
            color=0x95A5A6,  # gray
        )
        logger.info("skipped bedrock; no ship logs")
        return {"ok": True, "alarm": alarm_name, "severity": "INFO", "skipped": "no_logs"}

    # --- Bedrock prompt を構築 (Bedrock 呼び出しと Discord 添付で同一文字列を共有) ---
    system_prompt: str = render_prompt_system_base(*render_prompt_case_lambda_failure())
    formatted_logs: str = _format_log_rows_pretty(log_rows)
    user_text: str = render_prompt_user(alarm_name, timestamp, reason, formatted_logs, len(log_rows))

    # --- Bedrock に投げた完全 prompt を Discord に添付 (検証用) ---
    # Bedrock 呼び出しの直前に、これから投げる system + user 文字列をそのまま
    # 添付ファイルとして Discord に投稿する。LLM レポート embed とは独立した
    # webhook execute なのでレポート内容と混ざらない。
    # 検証用の add-on のため、例外で本来の LLM レポート経路を巻き添えにしないよう
    # try/except でガードし、失敗時は warning ログのみで継続する。
    try:
        _post_prompt_attachment(
            webhook_url=env.discord_webhook_url,
            alarm_name=alarm_name,
            system_prompt=system_prompt,
            user_text=user_text,
        )
    except Exception:
        logger.exception("prompt attachment failed (non-fatal); continuing main flow")

    # --- Bedrock で LLM 分析（対象船舶の実行ログを渡す） ---
    try:
        bedrock_response = boto3.client("bedrock-runtime").converse(  # Claude に分析依頼
            modelId=env.bedrock_model_id,
            system=[{"text": system_prompt}],
            messages=[{"role": "user", "content": [{"text": user_text}]}],
            inferenceConfig={
                "maxTokens": env.bedrock_max_tokens,
            },
        )
        report_text: str = bedrock_response["output"]["message"]["content"][0]["text"]
        report: dict[str, Any] = _normalize_report(json.loads(report_text))
        logger.info(
            "bedrock analyzed",
            extra={"severity": report.get("severity", ""), "model": env.bedrock_model_id},
        )
    except (BotoCoreError, ClientError, json.JSONDecodeError, KeyError) as e:
        # Bedrock 失敗 / JSON 逸脱 / 想定外スキーマ — どれも通知欠落を避けるため
        # fallback embed を投げて正常 return する（再 raise しないことで Lambda 非同期
        # invocation のリトライを止め、失敗ログの3倍積もりを抑止する）。
        logger.exception("bedrock analysis failed; posting minimal fallback embed")
        _post_minimal_embed(
            webhook_url=env.discord_webhook_url,
            environment_name=env.environment_name,
            target_function_name=env.target_function_name,
            alarm_name=alarm_name,
            timestamp=timestamp,
            reason=reason,
            rows_count=len(log_rows),
            extra_note=f"LLM 分析失敗のためコア情報のみ通知: {type(e).__name__}",
            color=0xF1C40F,  # yellow (MEDIUM 相当)
        )
        return {"ok": True, "alarm": alarm_name, "severity": "MEDIUM", "fallback": True}

    # --- Discord 通知投稿 (Discord embed 4 階層レイアウト: author / title / fields / footer) ---
    # title は LLM summary を昇格 (人間が最初に読むべき情報)。
    # 監視対象 Lambda 名と発火 Alarm 名は inline field でラベル付き横並びにして
    # 「2 つの似た文字列」を視覚的に分離する。color が severity の唯一のシグナル。
    webhook = DiscordWebhook(url=env.discord_webhook_url)
    embed = DiscordEmbed(
        title=report["summary"][:256],
        color=DISCORD_SEVERITY_COLOR.get(report["severity"], 0x95A5A6),
    )
    embed.set_author(name=f"HDW Notify · {env.environment_name}")

    # 識別子 3 つを inline で横並び (PC で 3 列、モバイルで縦積みでもラベルで判別可)
    embed.add_embed_field(name="監視対象 Lambda", value=env.target_function_name, inline=True)
    embed.add_embed_field(name="発火 Alarm", value=alarm_name, inline=True)
    embed.add_embed_field(name="件数", value=f"{len(log_rows)} 件", inline=True)

    # 数値メタ (集計時間窓は phrase 性質のため 1 行を専有させる)
    embed.add_embed_field(
        name="集計時間窓", value=_format_window_jst(start, end), inline=False
    )

    # LLM 解釈 (Why) — confidence を field 名に併記
    confidence = report.get("confidence", "low")
    embed.add_embed_field(
        name=f"原因仮説 (confidence: {confidence})",
        value=report.get("root_cause_hypothesis", "(不明)"),
        inline=False,
    )

    # LLM 解釈 (How) — AWS-level / コード修正レベルのアクション
    actions = report.get("suggested_actions") or []
    if actions:
        embed.add_embed_field(
            name="推奨アクション",
            value="\n".join(f"- {a}" for a in actions),
            inline=False,
        )

    # 機械事実 (How: 深掘り動線)
    embed.add_embed_field(
        name="詳細リンク",
        value=_build_deeplinks_markdown(env, log_group, client_region, start, end),
        inline=False,
    )

    # footer: 代表 request_id (絶対時刻は timestamp で Discord がクライアントローカル表示)
    representative_request_id = _extract_first_request_id(log_rows) or "(なし)"
    embed.set_footer(text=f"req-id: {representative_request_id}")
    embed.set_timestamp(timestamp)
    webhook.add_embed(embed)
    webhook.execute()  # Discord に Embed を POST
    logger.info("discord notified")

    return {
        "ok": True,
        "alarm": alarm_name,
        "severity": report.get("severity", ""),
    }
