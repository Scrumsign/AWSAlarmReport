# Phase A: テストケース最小 PLAN

## 1. ゴール

`src/test.py` と `src/fixtures/` だけで「fixture ログを既存 prompt に流して Bedrock 出力を目視」できる状態にする。**既存コード (`main.py` / `utils/prompt.py`) には触らない**。

所要見積もり: **約 2 時間** (test.py 1h + fixture 30m + 動作確認 30m)。

## 2. 非ゴール (今回やらない・別フェーズに分離)

| 項目 | 分離先 |
|---|---|
| prompt.py の哲学 shift (コード言及 OK / case_no_logs 等) | Phase B |
| HDW_ML source embed (snapshot + context.py) | Phase C |
| `success_rows` (sakura 船成功ログ context) 追加 | Phase D |
| `analyzer.py` 抽出 + `LogRow` dataclass | Phase D |
| `main.py` 大改修 (INSIGHTS_QUERY 2 本化 / 早期 return 廃止 / Bedrock invoke クロージャ化) | Phase D |
| prompt caching (`cachePoint`) 検証 | Phase B-D いずれか |
| コスト実測 (`T_in` / `T_out` / モデル比較 / 月額) | Phase E |
| pytest / snapshot / schema 自動検証 | 永久に非ゴール |
| CI 統合 | 永久に非ゴール |

旧版 PLAN (analyzer.py 抽出を前提とした統合版) は git 履歴に残るので、Phase B-E 着手時に参照する。

## 3. 構成 (最終形)

```
src/
  test.py             ← NEW (この PLAN の唯一の新規実装)
  fixtures/           ← NEW
    no_logs/
      alarm.json
      logs.jsonl      (空)
      README.md
    handler_value_error/
      alarm.json
      logs.jsonl      (本番 2026-04-27 ValueError 実物)
      README.md
  main.py             ← 無改修
  utils/prompt.py     ← 無改修
  utils/__init__.py   ← 無改修
```

`test.py` は既存 [src/utils/prompt.py](../../../../src/utils/prompt.py) の `render_prompt_system_base` / `render_prompt_case_generic` / `render_prompt_user` をそのまま呼ぶ。

## 4. `src/test.py` 全文

```python
"""
fixture ログを既存 prompt 関数に流して Bedrock 出力を stdout にダンプする
prompt 改善ループ用スクリプト。

LLM 常時呼び・オプションフラグなし・自動判定なし。判定は人手。

usage:
    python src/test.py                          # 全 fixture を順に流す
    python src/test.py handler_value_error      # 1 ケースだけ

env:
    BEDROCK_MODEL_ID, BEDROCK_MAX_TOKENS, AWS_REGION (boto3 標準解決)
"""

from __future__ import annotations

import json
import os
import sys
from pathlib import Path

import boto3

# src/ が sys.path に入っている前提 (python src/test.py 実行で自然にそうなる)
from utils.prompt import (
    render_prompt_case_generic,
    render_prompt_system_base,
    render_prompt_user,
)

FIXTURES_DIR = Path(__file__).parent / "fixtures"


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


def _run_one(case_dir: Path, client, model_id: str, max_tokens: int) -> None:
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

    system_prompt = render_prompt_system_base(*render_prompt_case_generic())
    user_prompt = render_prompt_user(alarm_name, timestamp, reason, log_rows)

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
    print(f"\n--- usage --- {usage}")


def main() -> int:
    model_id = os.environ["BEDROCK_MODEL_ID"]
    max_tokens = int(os.environ["BEDROCK_MAX_TOKENS"])
    client = boto3.client("bedrock-runtime")

    if len(sys.argv) > 1:
        targets = [FIXTURES_DIR / sys.argv[1]]
    else:
        targets = sorted(d for d in FIXTURES_DIR.iterdir() if d.is_dir())

    for d in targets:
        _run_one(d, client, model_id, max_tokens)
    return 0


if __name__ == "__main__":
    sys.exit(main())
```

## 5. fixture 内容

### `src/fixtures/no_logs/alarm.json`

```json
{
  "alarmArn": "arn:aws:cloudwatch:ap-northeast-1:920373030024:alarm:hdw-backend-processor-0001-errors",
  "alarmData": {
    "state": {
      "value": "ALARM",
      "timestamp": "2026-04-27T12:05:00.000+0000",
      "reason": "Threshold Crossed: 1 datapoint [1.0] was greater than or equal to the threshold (1.0)."
    }
  }
}
```

### `src/fixtures/no_logs/logs.jsonl`

空ファイル (0 行)。

### `src/fixtures/no_logs/README.md`

```markdown
# no_logs

## シナリオ
4 時間おきの起動枠で HDW_Backend_Processor_0001 が走った形跡がない。
直近時間窓に error / success どちらのログもない状態を再現する。
(S3 への入力ファイル未アップで Lambda がそもそも起動しなかった想定)

## LLM に期待する回答
- summary に「Lambda 未起動」または「ログなし」相当
- root_cause_hypothesis に「S3 入力ファイル未アップ」「アップロード処理の失敗」を仮説として
- suggested_actions に S3 確認系のアクションが入る
```

### `src/fixtures/handler_value_error/alarm.json`

```json
{
  "alarmArn": "arn:aws:cloudwatch:ap-northeast-1:920373030024:alarm:hdw-backend-processor-0001-errors",
  "alarmData": {
    "state": {
      "value": "ALARM",
      "timestamp": "2026-04-27T06:37:00.000+0000",
      "reason": "Threshold Crossed: 1 datapoint [1.0] was greater than or equal to the threshold (1.0)."
    }
  }
}
```

### `src/fixtures/handler_value_error/logs.jsonl`

本番 2026-04-27 06:36:52 取得の `ValueError: general_data is None` 実物を 1 行に整形:

```jsonl
{"level":"ERROR","location":"lambda_handler:178","message":"lambda_handler failed","timestamp":"2026-04-27 06:36:52,801+0000","service":"hdw-backend","cold_start":false,"function_name":"HDW_Backend_Processor_0001","function_memory_size":"2048","function_arn":"arn:aws:lambda:ap-northeast-1:920373030024:function:HDW_Backend_Processor_0001","function_request_id":"e69ffb0e-b473-41a0-ac30-172a4ab91b74","ship_name":"sakura","ship_timestamp":"20260427120100","input_key":"inputFiles/sakura-20260427120100.zip","name_part":"sakura-20260427120100","event":"lambda_complete","status":"error","phase":"handler","exception":"Traceback (most recent call last):\n  File \"/var/task/main.py\", line 167, in lambda_handler\n    main_function(pm, environment=\"lambdaproduction\")\n  File \"/var/task/main.py\", line 62, in main_function\n    raise ValueError('general_data is None')\nValueError: general_data is None","exception_name":"ValueError","stack_trace":{"type":"ValueError","value":"general_data is None","module":"builtins","frames":[{"file":"/var/task/main.py","line":167,"function":"lambda_handler","statement":"main_function(pm, environment=\"lambdaproduction\")"},{"file":"/var/task/main.py","line":62,"function":"main_function","statement":"raise ValueError('general_data is None')"}]},"xray_trace_id":"1-69ef0328-78379ac7605571ed45e2ff86"}
```

### `src/fixtures/handler_value_error/README.md`

```markdown
# handler_value_error

## シナリオ
本番 2026-04-27 06:36:52 に HDW_Backend_Processor_0001 で発生した
`ValueError: general_data is None` を再現。
main.py:62 で general_data が None だった場合に raise される箇所。
ship_name=sakura, ship_timestamp=20260427120100 の入力に対する処理。

## LLM に期待する回答
- root_cause_hypothesis に何が壊れたかの仮説 (general_data 取得元の何かが None)
- suggested_actions に該当 input_key の S3 オブジェクト確認等
- 現状 prompt はコード言及禁止なので、関数名・行番号への踏み込みは出ない想定
  (それを許可するのは Phase B)
```

## 6. 段取り

| Step | 内容 | 所要 |
|---|---|---|
| 1 | `src/test.py` を §4 の通り作成 | 30m |
| 2 | `src/fixtures/no_logs/` の 3 ファイル作成 | 10m |
| 3 | `src/fixtures/handler_value_error/` の 3 ファイル作成 (logs.jsonl は §5 の本番実物) | 20m |
| 4 | 環境変数セット (`BEDROCK_MODEL_ID=jp.anthropic.claude-sonnet-4-6`, `BEDROCK_MAX_TOKENS=1024`, `AWS_REGION=ap-northeast-1`) + Bedrock 認証確認 (`aws sso login --profile <bedrock 用>`) | 15m |
| 5 | `python src/test.py` で全件実行、stdout を眺める | 15m |
| 6 | 失敗箇所があれば修正 (variable name typo / Insights 変換漏れ等) | 30m (buffer) |

**合計: 2 時間** (Step 6 の buffer 込み)。

## 7. 動作確認の観点

`python src/test.py` 完走時に **以下が成立していれば OK**:

- [ ] 全 fixture (2 件) が順に処理される
- [ ] 各 fixture で `--- system prompt ---` / `--- user prompt ---` / `--- LLM raw output ---` が出る
- [ ] `--- LLM raw output ---` が JSON で parse 可能な形 (出力スキーマ準拠)
- [ ] `usage` (inputTokens / outputTokens) が表示される
- [ ] `no_logs` ケース: user prompt に `# Error logs (0件)` が出る (空ログでも Bedrock 呼び結果が出る)
- [ ] `handler_value_error` ケース: user prompt の trace 部分に `ValueError: general_data is None` が見える

**「LLM 出力の良し悪し」は判定対象外** (それは Phase B の prompt 改善ループの範疇)。

## 8. オープン項目

- [ ] **Bedrock 認証どの profile を使うか** — 現状 deploy/config は `hdw-test` (088898720463) 環境想定。test.py をローカル実行する際に同じ profile か、別に切るか
- [ ] **test.py 実行時の AccessDenied** が出た場合、IAM role の `bedrock:InvokeModel` をローカル IAM user に付与する必要があるか確認
- [ ] **`handler_value_error/logs.jsonl` の本番値マスキング** — `function_arn` / `function_request_id` / `xray_trace_id` を実値のまま git に置くか、マスクするか (社内利用なら実値で OK の見込み)
- [ ] **fixture 追加 trigger** — KeyError 系 (本番で 4/27 に 2 件発生) や他のサブケースを Phase A 中に増やすか、Phase B 以降に分離するか

## 9. 後続フェーズ概要

Phase A 完了後、ユーザーの体感次第で次フェーズを選ぶ。順序固定しない。各フェーズの **方針と採用済み判断** は議論で確定済みなので、着手判断のトリガーだけが残っている。

### 9.1 Phase B: prompt 改善

**目的**: test.py の出力を眺めて「微妙」と感じる箇所を [src/utils/prompt.py](../../../../src/utils/prompt.py) の直接編集 → 再走 → 目視比較のループで削っていく。

**採用済み判断 (議論で確定)**:

| 領域 | 判断 |
|---|---|
| コードベース言及 | **OK (むしろ推奨)**。理由: この Notify Lambda は HDW_ML 専属の分析役で、対象が単一 Lambda に固定されているため、関数名・モジュール名・行番号への踏み込みが有用 |
| 断定 | **維持して禁止**。仮説は複数提示、`confidence` で不確実性を表明 |
| ヒント節 ([prompt.py:57-59](../../../../src/utils/prompt.py#L57-L59)) | Case 別に再構成し `render_prompt_case_no_logs()` を新設。「ログ 0 件なら S3 確認を促す」を明示化 |

**`prompt.py` の主要改修箇所**:

- [prompt.py:31-32](../../../../src/utils/prompt.py#L31-L32) 「コードベース固有の根本原因は知らない前提で」→ **削除**
- [prompt.py:42-56](../../../../src/utils/prompt.py#L42-L56) suggested_actions の縛り (コード言及禁止) → **削除**、代わりに「監視対象 Lambda のソース該当箇所を file:line で引いてよい」を追記
- ヒント節をケース別に分離

**改修後の system prompt 骨子** (前回 PLAN §4.3 で書き下した素材):

```
# 制約
- 監視対象は単一 Lambda (HDW_ML) なので、ソースコード固有の関数名・モジュール名・
  行番号・変数名に踏み込んだ仮説と提案を歓迎する。
- ただし「断定」はせず、もっともらしさの順に複数仮説を並べること。
  確信度は confidence フィールドで表明する。

# suggested_actions の制約
- AWS リソース操作レベル / HDW_ML コード修正レベル 両方歓迎。
  例: 「store.py:87 の frontend_paths['data'][key] 参照を .get() に切替えて
       KeyError 耐性を上げる」
```

**優先する失敗モード (F1-F10 から絞った 5 件)**:

| ID | 失敗モード | 検証手順 |
|---|---|---|
| F2 | root_cause_hypothesis が浅い (例外名繰り返しレベル) | `handler_value_error` で main.py:62 まで掘れているか目視 |
| F5 | severity / confidence の付け方が一貫しない | 同 fixture を 3 回流して揺らぎを観察 |
| F6 | 空ログ (Case 1) に対し S3 確認の言及が出ない | `no_logs` で `suggested_actions[0]` に「S3 〜確認」相当があるか |
| F7 | generic 固定なので timeout / dependency 系で精度落ち | サブシナリオ fixture を追加して比較 |
| F10 | ヒント節が生硬で誤誘導 | Case 別再構成後に再評価 |

**改善ループ手順 (具体実施)**:

```bash
# Step 1: baseline 取得
export BEDROCK_MODEL_ID=jp.anthropic.claude-sonnet-4-6
export BEDROCK_MAX_TOKENS=1024
export AWS_PROFILE=hdw-test
mkdir -p docs/2026/05/18/mvp-followups-investigation/baselines
python src/test.py 2>&1 | tee docs/2026/05/18/mvp-followups-investigation/baselines/$(date +%Y%m%d-%H%M%S)-baseline.md

# Step 2: F2-F10 の 1 件選択 + 仮説立て (例: F2 = root_cause が浅い)
#   → §9.1.改善提案カタログ から該当する打ち手を 1 つ選ぶ

# Step 3: prompt.py 直接編集 (該当行を修正)

# Step 4: 再走 + diff
python src/test.py 2>&1 | tee docs/2026/05/18/mvp-followups-investigation/baselines/$(date +%Y%m%d-%H%M%S)-iter-N.md
diff -u baselines/<前回>.md baselines/<今回>.md | less   # diff 結果を目視

# Step 5: 改善判定 → keep か git checkout src/utils/prompt.py で revert

# Step 6: 別の F に進む or 打ち手を追加で重ねる
```

**停止条件**: 5 つの失敗モードすべてが「目視で許容範囲」、または 2 巡しても改善が頭打ち。判定は人手、snapshot ツールは入れない。

**所要見積もり**: 1 巡 = 30 分〜1 時間 (rendering + Bedrock × 全 fixture)。2-3 巡で半日〜1 日。

**着手トリガー**: Phase A 完了後、出力を眺めて「微妙」と感じたら即着手。

### 9.1.改善提案カタログ (予想効果 + 副作用 + 検証方法)

何を `prompt.py` に追加すると何が良くなるか、の仮説リスト。改善ループの「次の一手」候補。**実証はループ内で行う**。

| # | 提案 | 効く失敗モード | 予想効果 | 副作用 (トークン / リスク) | 検証方法 |
|---|---|---|---|---|---|
| **P1** | system prompt 末尾に HDW_ML の **ディレクトリ tree** (`src/` 配下の .py 一覧) を追加 | F2, F7 | LLM が stack trace の `/var/task/main.py` から該当モジュールを推測できる | +200-500 tok、メンテ負担小 | `handler_value_error` で root_cause に `main.py:62` への言及が出るか目視 |
| **P2** | 主要関数のシグネチャ + docstring 1 行を抽出して embed (tree より具体、全文より軽量) | F2 | 「main_function は何をするか」を LLM が把握 | +1,500-2,500 tok | P1 と同じ。深さの違いを比較 |
| **P3** | HDW_ML 全文 embed (Phase C 本体) | F2, F7 | 完全な context。file:line + 周辺コード参照 | +5,000-8,000 tok、caching 必須 | 同 fixture で root_cause が `main.py:62 の general_data 取得元` 等まで具体化するか |
| **P4** | **severity の境界を明文化** ("LOW=単発自己回復, MEDIUM=連続発生/データ欠落, HIGH=全件失敗/データ破損") | F5 | severity 揺らぎ減 | +50 tok、誤分類時 fallback なし | 同 fixture を 3 回流して severity が一定になるか |
| **P5** | **confidence の境界を明文化** ("low=<50%, medium=50-80%, high=>80%") | F5 | confidence の意味が安定 | +50 tok | P4 と同じ |
| **P6** | `stack_trace` (構造化 dict) を user prompt に追加 (現状は `exception` の生 traceback 文字列のみ) | F2 | file/line/function/statement が機械可読で出る → LLM が file:line を引きやすい | +50 tok/行、`render_prompt_user` 改修 | trace 表示形式の前後で root_cause の踏み込み深さ比較 |
| **P7** | `case_no_logs` 用テンプレ新設 (現 ヒント節を case 別に分離) | F6, F10 | 空ログ時に確実に「S3 確認」が出る | なし | `no_logs` で `suggested_actions[0]` が S3 確認か目視 |
| **P8** | success_rows との比較指示 ("下に N 件の成功ログ。差分から原因推測") | F2 | 例外がない時の比較基準が定義される | +N×100 tok (success_logs 件数依存) | sakura 船別 success_logs 追加後の root_cause の質を比較 |
| **P9** | **時刻表記の統一指示** ("alarm は ISO 8601、log は powertools `YYYY-MM-DD HH:MM:SS,SSS+ZZZZ`。両者は同一時刻系") | F2, F5 | 時系列推論ミス減 | +30 tok | timeout 系 fixture 追加後に検証 |
| **P10** | 出力フォーマット例 (1-shot) を system 末尾に添付 | F2, F5 | スキーマ準拠率と出力深さが安定 | +200-400 tok、bias リスク | スキーマ逸脱率を `parse_report` の例外発生回数で測定 |
| **P11** | "コードベース固有提案 OK" を明示 + 例を 2-3 個追加 (現状の禁止節 [prompt.py:50-56](../../../../src/utils/prompt.py#L50-L56) を反転) | F2 | suggested_actions が AWS 操作レベルに張り付かず、コード修正提案も出る | コード提案の品質次第で逆効果リスク | suggested_actions に `.get()` への切替や None チェック等が含まれるか |

**着手順序の推奨** (低コスト・低リスク順):

1. **P7** (case_no_logs) — 副作用なし、F6 に直撃。最初に潰す
2. **P11** (philosophy shift) — 文面差し替えだけ、Phase B の核
3. **P4 + P5** (severity / confidence 境界) — まとめて入れる
4. **P9** (時刻表記統一) — 小コストで入れる
5. **P1** (tree) → 効くなら **P3** (全文) へ昇格 (= Phase C 着手判断)
6. **P6** (stack_trace) — `render_prompt_user` 改修要 (Phase D の signature 変更とまとめると効率的)
7. **P8** (success_rows 比較指示) — success_rows 取得実装 (Phase D) とセット
8. **P2 / P10** — 必要を感じたら追加

### 9.1.追加 fixture を採取する CLI 手順

Phase A の 2 件で物足りなくなったら、本番から追加 fixture を取る。

```bash
# Step 1: 過去 30 日のエラーログ全件を取得 (handler_value_error / handler_keyerror 等のサブ分類用)
END=$(date +%s)
START=$((END - 2592000))
QUERY_ID=$(aws logs start-query \
  --profile hanshin-t.kimura --region ap-northeast-1 \
  --log-group-name /aws/lambda/HDW_Backend_Processor_0001 \
  --start-time $START --end-time $END \
  --query-string 'fields @timestamp, @message | filter status = "error" | sort @timestamp desc | limit 100' \
  --query queryId --output text)
sleep 10
aws logs get-query-results --profile hanshin-t.kimura --region ap-northeast-1 \
  --query-id $QUERY_ID --output json > /tmp/error-logs.json

# Step 2: 結果を眺めて exception_name で分類 (jq でグルーピング)
jq -r '.results[][] | select(.field == "@message") | .value | fromjson | .exception_name' /tmp/error-logs.json | sort | uniq -c

# Step 3: 各 exception_name から代表 1 件選んで src/fixtures/<scenario>/logs.jsonl にコピー
```

判明している既存パターン (本番 2026-04-27 観測):
- `KeyError: 'tracking'` at `module/store.py:87` (FrontendDataStore.__init__) — 3 件連発
- `ValueError: general_data is None` at `main.py:62` — 1 件 (Phase A で fixture 化済み)

→ `handler_keyerror_tracking/` を追加して Case 2 のバリエーションを増やすのが自然な次の一歩。

### 9.2 Phase C: HDW_ML source embed

**目的**: Phase B の prompt で「もっとコード掘らせたい」と判断したら、HDW_ML 全文を system prompt に埋め込んで LLM に渡す。

**採用済み判断**:

| 項目 | 値 | 根拠 |
|---|---|---|
| 同梱粒度 | **HDW_ML 全文 embed** | HDW_ML は ~1,564 行 ≒ 5,000〜8,000 tok と小さく viable |
| 配置 | `src/context/hdw_ml_snapshot.md` (build/保守時に再生成) | static file。`hdw_ml_context.py` がモジュールロード時に読み込み |
| キャッシュ | **prompt caching 適用** (system block 末尾に `cachePoint`) | 静的部分の課金を ~90% カット (Anthropic 公称) |

**追加ファイル**:

- `scripts/snapshot_hdw_ml.py` — HDW_ML の README + `src/**/*.py` を 1 ファイルに連結 (生成方法は前 PLAN 版 §4.5 を参照、UTF-8 直接書き込み)
- `src/context/hdw_ml_snapshot.md` — 生成物 (git に commit するか deploy 時生成か未決定 — §9.5 オープン)
- `src/utils/hdw_ml_context.py` — `HDW_ML_SOURCE_SNAPSHOT: str` を export

**`prompt.py` 側の改修**: system prompt の末尾に `# 監視対象 Lambda のソースコード (HDW_ML)\n\n{HDW_ML_SOURCE_SNAPSHOT}` を連結。Bedrock Converse API の system 配列で `cachePoint` ブロックを置く。

**事前検証必須項目**:

- **`cachePoint` が `jp.anthropic.claude-sonnet-4-6` (inference profile 経由) で動くか**。動かないなら caching 抜きで運用 (コスト試算は悪化)
- HDW_ML 更新時の snapshot 再生成 trigger (deploy フック / 手動 / cron)

**所要見積もり**: 半日 (実装 2-3h + cachePoint 検証 1-3h + やり直しリスク buffer)。

**着手トリガー**: Phase B で「コードまで踏み込んだ仮説」が出てこないと感じたら。

### 9.3 Phase D: 本番反映 (analyzer.py 抽出 + main.py 改修)

**目的**: Phase B / C の改善を production の Lambda に反映する。

**スコープ**:

- `src/analyzer.py` 新設 (boto3/discord 非依存、`InvokeLLM` Protocol で LLM 注入)
- `LogRow` dataclass で型整理
- `src/main.py` 改修:
  - AlarmContext 抽出を `analyzer.parse_alarm_event` に置換
  - INSIGHTS_QUERY を全フィールド投影に拡張 (現状 `level / cold_start / ship_name / ship_timestamp / input_key / phase / exception_name / message / exception / xray_trace_id` のみ → `location / service / function_name / function_memory_size / function_arn / name_part / event / status / stack_trace` を追加)
  - 成功ログ取得を追加 (**sakura 船など同一 ship_name 優先で 50 件**)
  - **空ログ早期 return ([main.py:267-279](../../../../src/main.py#L267-L279)) を廃止** — Case 1 も LLM に通して `render_prompt_case_no_logs()` を発動
  - Bedrock 呼びを `_bedrock_invoke` クロージャに分離し `analyzer.run` へ渡す

**事前検証必須項目**:

- INSIGHTS_QUERY 拡張時、`stack_trace` (nested object) を Insights が dict のまま返すか string flatten するか — `parse_powertools_log` 側に `json.loads` fallback を入れて両対応
- 成功ログのフィールド構成確認 (本番から INFO ログ 1 件取得して `parse_powertools_log` 必須項目が揃うか)

**所要見積もり**: 1-2 日 (analyzer.py 2-3h + prompt.py signature 変更 1-2h + main.py 大改修 3-5h + test 環境 deploy 検証 1-2h + buffer)。

**着手トリガー**: Phase B / C の改善が production にも欲しい、と判断したら。Phase A / B だけで満足なら本フェーズは不要 (本番は現状の prompt のままで運用継続)。

### 9.4 Phase E: コスト実測

**目的**: Sonnet 4.6 / Haiku 4.5 / Opus 4.7 の月額レンジを実測ベースで出し、責任者が **本実装に進む / 改善する / 棚上げる** を判断できる材料を出す。

**計算式 (確定)**:

```
コスト/月 = N_calls × ( T_in   × P_in (model)
                      + T_out  × P_out(model)
                      - T_cached × P_in(model) × (1 - cache_discount) )
```

**採用済み判断**:

| 記号 | 値 |
|---|---|
| `N_calls` | **楽観 10 / 想定 30 / 悲観 180** (= 30 日 × 4 時間おき) の 3 段で出す |
| `T_in` 内訳 | `T_system + T_source + T_alarm_meta + T_error_logs + T_success_logs` |
| キャッシュ対象 | `T_system + T_source` (Phase C 採用時のみ) |
| `T_success_logs` の N | **50** (Insights `limit 50` と揃える、sakura 船 別) |
| 比較モデル | **Haiku 4.5 / Sonnet 4.6 / Opus 4.7** (Opus 利用可否は事前確認 — [test 環境 AccessDenied 履歴](../bedrock-opus-model-access-denied/) 解消済みか) |

**未確定変数 (Phase E で確定させるもの)**:

| 変数 | 確定方法 | 着手前の予測 |
|---|---|---|
| `T_system` | C-1 で測定 | 800〜1,200 tok |
| `T_source` (Phase C 採用時のみ) | C-2 で測定 | 5,000〜8,000 tok |
| `T_error_logs(N)` の線形係数 | C-3 で測定 | ~200 tok/行 (powertools 1 ログあたり) |
| `T_success_logs(N)` の線形係数 | C-4 で測定 | ~100 tok/行 (trace なしのため少なめ) |
| `T_out` 平均 / 最大 | C-5 で測定 | 平均 400-600 tok、`max_tokens=1024` で頭打ちは想定外 |
| `P_in` / `P_out` (3 モデル) | **C-6 で web 確認** | 後述 |
| `cache_discount` 率 + 最小サイズ | C-7 で確定 | Anthropic 公称 ~90% off (cache read)、最小 1024 tok 想定 |
| `N_calls` 想定値 | C-8 で過去実績から決定 | 楽観 10 / 想定 30 / 悲観 180 (180 は理論上限) |
| Lambda / Insights / ECR コスト | C-9 で測定 | 合計 ~$1/月 想定 |

### 9.4.具体実施手順

#### C-1: `T_system` 測定 (system プロンプトのトークン)

```python
# scripts/measure_t_system.py (新規)
import sys
sys.path.insert(0, "src")
from anthropic import AnthropicBedrock
from utils.prompt import (
    render_prompt_system_base,
    render_prompt_case_generic,
    render_prompt_case_timeout,
    render_prompt_case_dependency,
)

client = AnthropicBedrock(aws_region="ap-northeast-1")
MODEL = "anthropic.claude-sonnet-4-20250514-v1:0"  # base model ID (count_tokens 用)

for case_name, case_fn in [
    ("generic",    render_prompt_case_generic),
    ("timeout",    render_prompt_case_timeout),
    ("dependency", render_prompt_case_dependency),
]:
    system = render_prompt_system_base(*case_fn())
    resp = client.messages.count_tokens(
        model=MODEL, system=system,
        messages=[{"role": "user", "content": "x"}],
    )
    print(f"T_system ({case_name}) = {resp.input_tokens} tok")
```

**実行**: `AWS_PROFILE=hdw-test python scripts/measure_t_system.py`

**抽出値**: `T_system (generic)` を baseline として採用。timeout / dependency のケース差分も記録。

#### C-2: `T_source` 測定 (HDW_ML snapshot のトークン)

```python
# scripts/measure_t_source.py
import sys
sys.path.insert(0, "src")
from anthropic import AnthropicBedrock
from utils.hdw_ml_context import HDW_ML_SOURCE_SNAPSHOT   # Phase C 完了が前提

client = AnthropicBedrock(aws_region="ap-northeast-1")
resp = client.messages.count_tokens(
    model="anthropic.claude-sonnet-4-20250514-v1:0",
    system=HDW_ML_SOURCE_SNAPSHOT,
    messages=[{"role": "user", "content": "x"}],
)
print(f"T_source = {resp.input_tokens} tok")
```

**抽出値**: HDW_ML 全文の token 数。`T_source × P_in × (1 - cache_discount)` で caching 適用後のコスト寄与を計算。

#### C-3 / C-4: ログ件数 → トークンの線形係数

```python
# scripts/measure_t_logs.py
import json, sys
sys.path.insert(0, "src")
from anthropic import AnthropicBedrock
from utils.prompt import render_prompt_user
# Phase A の test.py から _powertools_to_insights_row を再利用
from test import _powertools_to_insights_row

client = AnthropicBedrock(aws_region="ap-northeast-1")
MODEL = "anthropic.claude-sonnet-4-20250514-v1:0"

# fixture から powertools dict を読む (handler_value_error の 1 件をテンプレに複製)
with open("src/fixtures/handler_value_error/logs.jsonl") as f:
    base_log = json.loads(f.readline())

for n in [1, 10, 50]:
    log_dicts = [base_log] * n   # 同じログを N 回複製 (近似測定)
    log_rows = [_powertools_to_insights_row(d) for d in log_dicts]
    user = render_prompt_user("test-alarm", "2026-04-27T06:37:00Z", "test", log_rows)
    resp = client.messages.count_tokens(
        model=MODEL, messages=[{"role": "user", "content": user}],
    )
    print(f"N={n}: user prompt = {resp.input_tokens} tok")
```

**抽出値**: N=1, 10, 50 の 3 点から線形近似 `T = a + b × N`。係数 `b` を保存。

**C-4** は同じスクリプトで `INSIGHTS_QUERY_SUCCESS` 相当の本番 sakura 成功ログを 50 件取得 (CLI は §9.4 末尾参照) → `_powertools_to_insights_row` に流して測定。

#### C-5: `T_out` 平均 / 最大

Phase B 改善ループの test.py 実行時、stdout の `--- usage ---` 行を `tee` で記録しておけば事後集計で取れる:

```bash
python src/test.py 2>&1 | tee /tmp/test-run.log
grep -A 0 "outputTokens" /tmp/test-run.log
```

**抽出値**: fixture × 3 回実行ぶんの outputTokens 平均と最大。`max_tokens=1024` で頭打ちしているか確認 (最大値が 1023 に張り付くなら拡張要検討)。

#### C-6: `P_in / P_out` モデル単価 (web 確認)

**一次ソース** (AWS pricing page と Anthropic pricing page で乖離あり得るため両方確認):

- AWS Bedrock pricing: <https://aws.amazon.com/bedrock/pricing/>
- Anthropic API pricing: <https://www.anthropic.com/pricing>
- Bedrock 上の Anthropic モデル ID 一覧: <https://docs.aws.amazon.com/bedrock/latest/userguide/models-supported.html>

**抽出値** (取得日時付きで記録):

```markdown
取得日: 2026-05-18 (PLAN 着手時に各自更新)
| モデル | P_in ($/Mtok) | P_out ($/Mtok) | cache read ($/Mtok) | cache write ($/Mtok) |
| Haiku 4.5  | $? | $? | $? | $? |
| Sonnet 4.6 | $? | $? | $? | $? |
| Opus 4.7   | $? | $? | $? | $? |
```

ap-northeast-1 と cross-region inference profile (`jp.` / `global.`) で **単価差がある可能性** があるので region 表記も必須。

#### C-7: prompt caching 検証

**ドキュメント**: <https://docs.aws.amazon.com/bedrock/latest/userguide/prompt-caching.html>

**実機検証**:

```bash
# 同じ system block を続けて 2 回 test.py で叩き、2 回目の usage に cacheReadInputTokens が出るか確認
AWS_PROFILE=hdw-test BEDROCK_MODEL_ID=jp.anthropic.claude-sonnet-4-6 BEDROCK_MAX_TOKENS=1024 \
  python src/test.py handler_value_error 2>&1 | tee /tmp/run1.log
AWS_PROFILE=hdw-test BEDROCK_MODEL_ID=jp.anthropic.claude-sonnet-4-6 BEDROCK_MAX_TOKENS=1024 \
  python src/test.py handler_value_error 2>&1 | tee /tmp/run2.log

# 2 回目 usage に cacheReadInputTokens が出ているか
grep -E "cacheReadInputTokens|cacheWriteInputTokens|inputTokens" /tmp/run2.log
```

**確認項目**:
- `cachePoint` ブロックを system に置いた呼び出しが **エラーにならない** か (= `jp.` prefix で caching 対応している)
- 2 回目で `cacheReadInputTokens > 0` になるか
- 1 回目で `cacheWriteInputTokens > 0` になるか
- 最小サイズ要件 (Anthropic 公称 1024 tok) を満たしているか — `T_system + T_source` が下限超えるか

**caching 不可だった場合**: `T_cached = 0` として計算式適用。コスト試算が悪化する (Sonnet 入力 1M tok ぶんが 1/10 にならない)。

#### C-8: `N_calls` 想定値 (過去実績から決定)

**前提**: 現状 production に Alarm がまだデプロイされていない可能性が高い (MVP PLAN.md は仕様のみ)。Alarm history が取れない場合、Lambda Errors metric を直接読む。

**方法 A: Alarm history (Alarm デプロイ済みの場合)**:

```bash
aws cloudwatch describe-alarm-history \
  --profile hanshin-t.kimura --region ap-northeast-1 \
  --alarm-name hdw-backend-processor-0001-errors \
  --history-item-type StateUpdate \
  --start-date 2026-02-18T00:00:00Z \
  --end-date 2026-05-18T00:00:00Z \
  --max-items 1000 \
  --query 'AlarmHistoryItems[?HistorySummary==`Alarm updated from OK to ALARM`].Timestamp' \
  --output text | wc -l
```

**抽出値**: 直近 3 ヶ月の `OK → ALARM` 遷移回数を月別に集計 (jq で月ごと grouping)。

**方法 B: Lambda Errors metric (Alarm 未デプロイの場合)**:

```bash
aws cloudwatch get-metric-statistics \
  --profile hanshin-t.kimura --region ap-northeast-1 \
  --namespace AWS/Lambda --metric-name Errors \
  --dimensions Name=FunctionName,Value=HDW_Backend_Processor_0001 \
  --statistics Sum \
  --start-time 2026-02-18T00:00:00Z \
  --end-time 2026-05-18T00:00:00Z \
  --period 86400 \
  --output json | jq -r '.Datapoints | sort_by(.Timestamp) | .[] | [.Timestamp, .Sum] | @tsv'
```

**抽出値**: 日次の Errors 合計 → 月集計 → 楽観 (最小月) / 想定 (中央値) / 悲観 (最大月、上限 180)。

#### C-9: その他 AWS コスト要素

**Lambda invoke + duration** (Reporter Lambda の実行):

```bash
# test 環境の Reporter Lambda の REPORT 行から Billed Duration を集計
END=$(date +%s)000
START=$(( (END/1000) - 604800 ))000   # 直近 7 日
aws logs filter-log-events \
  --profile hdw-test --region ap-northeast-1 \
  --log-group-name /aws/lambda/hdw-notify-reporter \
  --filter-pattern "REPORT" \
  --start-time $START --end-time $END \
  --max-items 50 --output json \
  | jq -r '.events[].message' | grep -oE 'Billed Duration: [0-9]+' | awk '{sum+=$3; n++} END {print "avg ms:", sum/n}'
```

**抽出値**: 平均 billed_duration_ms。月額 = `N_calls × avg_ms / 1000 × $0.0000166667/GB-s × memory_GB` (memory はデプロイ設定参照、現状仮: 512MB or 1024MB)。

**Logs Insights scan 量**:

```bash
# 1 クエリの bytesScanned を 5 回測定して平均
for i in 1 2 3 4 5; do
  QID=$(aws logs start-query --profile hanshin-t.kimura --region ap-northeast-1 \
    --log-group-name /aws/lambda/HDW_Backend_Processor_0001 \
    --start-time $((( $(date +%s) - 360 ))) --end-time $(date +%s) \
    --query-string 'fields @timestamp | filter status = "error" | limit 50' \
    --query queryId --output text)
  sleep 5
  aws logs get-query-results --profile hanshin-t.kimura --region ap-northeast-1 \
    --query-id $QID --query 'statistics.bytesScanned' --output text
done
```

**抽出値**: 平均 bytesScanned × 2 (error + success 2 クエリぶん)。月額 = `N_calls × 2 × avg_bytes / 10^9 × $0.005`。

**ECR storage**:

```bash
aws ecr describe-images \
  --profile hdw-test --region ap-northeast-1 \
  --repository-name hdw-notify \
  --query 'imageDetails[*].imageSizeInBytes' --output text
```

**抽出値**: 最新 image size。月額 = `size_bytes / 10^9 × $0.10`。

**Data transfer**:

- Bedrock 同一リージョン呼び出し: $0 (無料)
- Discord webhook (egress): 1 通知 ~数 KB × 180 ≒ ~1MB/月 → $0 と判定

**CW Alarm**:

- Standard Alarm 1 個固定 → $0.10/月

#### C-4 用: 本番 sakura 成功ログ取得 (補助コマンド)

C-4 の入力データを本番から取る:

```bash
END=$(date +%s)
START=$((END - 604800))   # 直近 7 日
QID=$(aws logs start-query \
  --profile hanshin-t.kimura --region ap-northeast-1 \
  --log-group-name /aws/lambda/HDW_Backend_Processor_0001 \
  --start-time $START --end-time $END \
  --query-string 'fields @timestamp, @message | filter status = "success" and ship_name = "sakura" | sort @timestamp desc | limit 50' \
  --query queryId --output text)
sleep 10
aws logs get-query-results --profile hanshin-t.kimura --region ap-northeast-1 \
  --query-id $QID --output json \
  | jq -r '.results[][] | select(.field == "@message") | .value' \
  > /tmp/sakura-success-logs.jsonl
```

`/tmp/sakura-success-logs.jsonl` を C-4 スクリプトの入力に渡す。

### 9.4.測定結果テンプレ

`docs/2026/05/18/mvp-followups-investigation/results/cost-measurements-<日付>.md` に以下を保存:

```markdown
# コスト測定結果 (2026-05-XX)

## 確定値
- T_system = XXX tok
- T_source = XXX tok
- T_error_logs(N) = a + b × N (a=XXX, b=XXX)
- T_success_logs(N) = c + d × N (c=XXX, d=XXX)
- T_out (avg / max) = XXX / XXX tok
- cache_discount = XX% (Anthropic 公称 90%, 実機検証で確認)

## モデル単価 (取得日: 2026-05-XX, リージョン: ap-northeast-1)
| モデル | P_in | P_out | cache read | cache write |
| Haiku 4.5  | $X.XX | $X.XX | $X.XX | $X.XX |
...

## N_calls 想定値
| シナリオ | 件/月 | 根拠 |
| 楽観     | X    | 直近 3 ヶ月の最小月 |
| 想定     | X    | 直近 3 ヶ月の中央値 |
| 悲観     | 180  | 理論上限 (4 時間おき×30 日) |

## その他 AWS コスト (合計 $X.XX/月)
- Lambda: $X.XX
- Insights: $X.XX
- ECR: $X.XX
- CW Alarm: $0.10
```

**成果物**:

```
# HDW Notify コスト・運用判断材料

## 月額レンジ
| モデル | 楽観 (10件/月) | 想定 (30件/月) | 悲観 (180件/月) |
| Haiku 4.5  (cache あり) | $X.XX | $X.XX | $X.XX |
| Sonnet 4.6 (cache あり) | $X.XX | $X.XX | $X.XX |
| Opus 4.7   (cache あり) | $X.XX | $X.XX | $X.XX |
| (cache なし参考)         | ...   | ...   | ...   |

## 1M tokens の意味
- Sonnet 4.6 で入力 1M tokens = 約 N 回のアラート相当
- 月 N 件発火想定で 1M tokens に到達するのは X ヶ月後

## 推奨 / 棄却モデル
- 想定運用での最有力: ?
- 棄却すべき: ? (理由付き)
```

詳細ページに raw データ (`count_tokens` 結果 / Bedrock invocation の `usage` 全件 / 計算式と代入値) を残す。格納先: `docs/2026/05/18/mvp-followups-investigation/{results,baselines}/`。

**所要見積もり**: 半日〜1 日。Phase B の test.py 実行で C-1/C-3/C-4/C-5 が同時に拾えるので、Phase B と並行可。

**着手トリガー**: Phase A 以降いつでも。**Phase B と並走させると効率が良い** (test.py 1 回で改善ループと usage 計測の両方が進む)。

### 9.5 横断オープン項目

- [ ] HDW_ML snapshot 更新の trigger ルール (deploy ごと / 手動 / cron) — Phase C 着手時に決める
- [ ] 本番ログ fixture の値マスキング方針 (社内利用なら実値で可) — Phase A 着手時に決める
- [ ] Insights が `stack_trace` (nested object) をどう投影するか実機検証 — Phase D 着手時に検証
- [ ] Opus 4.7 利用可否確認 ([test 環境の AccessDenied](../bedrock-opus-model-access-denied/) が解消済みか) — Phase E 着手前に確認
- [ ] Phase B の改善ループに割く時間予算 (1 巡何時間想定で何巡まで回すか)
- [ ] Case 2 サブパターンの追加 trigger (運用で出会ったら / 棚卸し)
- [ ] test.py 実 Bedrock 呼び合計の予算上限 (1 巡で fixture × モデル数 × 3 回 ≒ $0.5 程度を目安)
- [ ] Phase B / C / D / E の **着手順序** — Phase A 結果を見てから決める
