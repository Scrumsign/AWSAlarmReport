"""
fixture ログを既存 prompt 関数に流して Bedrock 出力を stdout にダンプする
prompt 改善ループ用スクリプト。

LLM 常時呼び・オプションフラグなし・自動判定なし。判定は人手。

stdout の他に、サンプル比較用に下記 .txt を書き出す:
    <SAMPLES_DIR>/<model_short>/<fixture>-input.txt   (system + user prompt)
    <SAMPLES_DIR>/<model_short>/<fixture>-output.txt  (LLM raw output)

usage:
    python src/test.py                          # 全 fixture を順に流す
    python src/test.py handler_value_error      # 1 ケースだけ

env:
    BEDROCK_MODEL_ID, BEDROCK_MAX_TOKENS, AWS_REGION (boto3 標準解決)
    SAMPLES_DIR (省略時は docs/2026/05/18/mvp-followups-investigation/samples/)
"""

from __future__ import annotations

import json
import os
import sys
from pathlib import Path

import boto3

# src/ が sys.path に入っている前提 (python src/test.py 実行で自然にそうなる)
from main import (
    ERROR_ID_SEVERITY,
    _format_log_rows_pretty,
    _load_error_profiles,
    _normalize_report,
    _resolve_error_id,
)
from utils.prompt import build_system_prompt, render_prompt_user

FIXTURES_DIR = Path(__file__).parent / "fixtures"
DEFAULT_SAMPLES_DIR = (
    Path(__file__).parent.parent
    / "docs" / "2026" / "05" / "18" / "mvp-followups-investigation" / "samples"
)


def _model_short(model_id: str) -> str:
    """
    BEDROCK_MODEL_ID をファイル名向けの短い識別子に変換する。

    例: "jp.anthropic.claude-opus-4-7" -> "opus-4-7"
        "anthropic.claude-sonnet-4-20250514-v1:0" -> "sonnet-4-20250514-v1-0"

    Anthropic / cross-region inference profile prefix を剥がし、
    `:` を `-` に置換してパス安全にする。
    """
    s = model_id
    for prefix in ("jp.anthropic.claude-", "anthropic.claude-", "us.anthropic.claude-", "global.anthropic.claude-"):
        if s.startswith(prefix):
            s = s[len(prefix):]
            break
    return s.replace(":", "-").replace(".", "-").replace("/", "-")


def _powertools_to_insights_row(d: dict) -> list[dict]:
    """
    powertools 生 JSON の 1 ログ dict を、Insights `get_query_results` の
    `[{"field":..., "value":...}, ...]` 形式に変換する。

    既存 `render_prompt_user` は Insights 形式 (= list[list[{field,value}]]) を
    受け取るため、fixture (raw JSON) を本番経路と同じ shape に揃える役割。

    変換ルール:
      - 'timestamp' → '@timestamp' (CW Insights の pseudo フィールド名に合わせる)
      - bool → "true" / "false" 文字列 (render_prompt_user が cold_start == "true" で
        判定するため)
      - dict / list → JSON 文字列 (stack_trace 等。現状 render_prompt_user は
        参照しないが、形式を壊さないよう保全)
      - None → 空文字 (フィールドごと省く)
    """
    out: list[dict] = []
    for k, v in d.items():
        if v is None:
            continue
        field = "@timestamp" if k == "timestamp" else k
        if isinstance(v, bool):
            value = "true" if v else "false"
        elif isinstance(v, (dict, list)):
            value = json.dumps(v, ensure_ascii=False)
        else:
            value = str(v)
        out.append({"field": field, "value": value})
    return out


def _load_fixture(case_dir: Path) -> tuple[dict, list[dict], str]:
    alarm = json.loads((case_dir / "alarm.json").read_text(encoding="utf-8"))
    logs_path = case_dir / "logs.jsonl"
    log_dicts: list[dict] = []
    if logs_path.exists() and logs_path.stat().st_size > 0:
        for line in logs_path.read_text(encoding="utf-8").splitlines():
            if line.strip():
                log_dicts.append(json.loads(line))
    readme = (case_dir / "README.md").read_text(encoding="utf-8")
    return alarm, log_dicts, readme


def _run_one(case_dir: Path, client, model_id: str, max_tokens: int, samples_dir: Path) -> None:
    print("=" * 80)
    print(f"=== {case_dir.name}")
    print("=" * 80)

    alarm_event, log_dicts, readme = _load_fixture(case_dir)
    print("\n--- README ---")
    print(readme.strip())

    alarm_name = alarm_event["alarmArn"].split(":")[-1]
    timestamp = alarm_event["alarmData"]["state"]["timestamp"]
    reason = alarm_event["alarmData"]["state"].get("reason", "")

    log_rows = [_powertools_to_insights_row(d) for d in log_dicts]

    # 本番フロー (main.py) と同じ手順で error_id を確定し system prompt を構築する
    error_id = _resolve_error_id(alarm_name, log_rows)
    profiles = _load_error_profiles()
    error_description = profiles.get(error_id, {}).get("description", "")
    system_prompt = build_system_prompt(error_id, error_description)
    formatted_logs = _format_log_rows_pretty(log_rows)
    user_prompt = render_prompt_user(alarm_name, timestamp, reason, formatted_logs, len(log_rows))

    print(f"\n--- error_id --- {error_id}  (severity={ERROR_ID_SEVERITY.get(error_id, 'MEDIUM')})")
    print("\n--- system prompt ---")
    print(system_prompt)
    print("\n--- user prompt ---")
    print(user_prompt)

    resp = client.converse(
        modelId=model_id,
        system=[{"text": system_prompt}],
        messages=[{"role": "user", "content": [{"text": user_prompt}]}],
        inferenceConfig={"maxTokens": max_tokens},
    )
    raw = resp["output"]["message"]["content"][0]["text"]
    usage = resp.get("usage", {})
    print("\n--- LLM raw output ---")
    print(raw)

    # 本番と同じ正規化を通し、通知に乗る最終フィールドを確認する
    try:
        normalized = _normalize_report(json.loads(raw))
        print("\n--- normalized (通知に乗る値) ---")
        print(json.dumps(normalized, ensure_ascii=False, indent=2))
    except (json.JSONDecodeError, TypeError) as e:
        print(f"\n--- normalize 失敗: {type(e).__name__}: {e}")

    print(f"\n--- usage --- {usage}")

    # サンプル比較用に input / output を .txt に書き出す。
    # input = system + user (model 非依存だが、cache / signature 差を残すため model_short 配下に同梱)
    # output = LLM raw text + usage 1 行
    samples_dir.mkdir(parents=True, exist_ok=True)
    input_path = samples_dir / f"{case_dir.name}-input.txt"
    output_path = samples_dir / f"{case_dir.name}-output.txt"
    input_path.write_text(
        f"=== system prompt ===\n{system_prompt}\n\n=== user prompt ===\n{user_prompt}\n",
        encoding="utf-8",
    )
    output_path.write_text(
        f"{raw}\n\n=== usage ===\n{json.dumps(usage, ensure_ascii=False)}\n",
        encoding="utf-8",
    )
    print(f"\n--- wrote --- {input_path}")
    print(f"--- wrote --- {output_path}")


def main() -> int:
    model_id = os.environ["BEDROCK_MODEL_ID"]
    max_tokens = int(os.environ["BEDROCK_MAX_TOKENS"])
    client = boto3.client("bedrock-runtime")

    base_dir = Path(os.environ["SAMPLES_DIR"]) if "SAMPLES_DIR" in os.environ else DEFAULT_SAMPLES_DIR
    samples_dir = base_dir / _model_short(model_id)

    if len(sys.argv) > 1:
        targets = [FIXTURES_DIR / sys.argv[1]]
    else:
        targets = sorted(d for d in FIXTURES_DIR.iterdir() if d.is_dir())

    for d in targets:
        _run_one(d, client, model_id, max_tokens, samples_dir)
    return 0


if __name__ == "__main__":
    sys.exit(main())
