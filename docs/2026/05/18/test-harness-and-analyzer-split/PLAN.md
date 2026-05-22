# テストハーネス導入 + analyzer 切り出し PLAN

## 1. ゴール

- aws_lambda_powertools の JSON ログを JSONL fixture としてリポジトリ内に持つ
- 「ログ → 生成テキスト」のパイプラインを boto3 / discord_webhook 非依存の `src/analyzer.py` に切り出す
- `src/test.py` で「fixture → 実 LLM → 入出力 stdout」を一直線に流し、prompt 改善ループを目視で回せる土台にする

**非ゴール**: pytest 等のフレームワーク導入 / snapshot・schema 自動検証 / CI 統合 / Discord・boto3 境界のテスト / ケース分類器 / prompt 文面改善そのもの。

## 2. 構成

```
src/
  main.py            ← I/O orchestrator (Insights / Bedrock 呼び / Discord post)
  analyzer.py        ← NEW: ログ → 生成テキスト (boto3/discord 非依存)
  test.py            ← NEW: fixture を流し analyzer.run で LLM 叩いて stdout に出す
  fixtures/          ← フラット構造。サブシナリオが増えたらここに追加するだけ
    no_logs/         ← Case 1 (S3 にファイル未アップ → ログなし。固定 1 件)
      alarm.json
      logs.jsonl     (空)
      README.md
    handler_value_error/   ← Case 2 (Lambda 失敗。N 件に増える)
      alarm.json
      logs.jsonl
      README.md
  utils/prompt.py    ← 既存。render_prompt_user の引数を LogRow 受けに改修
```

import 方向: `main.py → analyzer.py → utils/prompt.py`。`analyzer.py` から `boto3` / `discord_webhook` の import は出ない。

## 3. analyzer.py の API

LLM 呼び出しは `InvokeLLM` Protocol で外から注入。production の main.py は Bedrock-bound 関数を、test.py も実 Bedrock 呼びを渡す。

`LogRow` フィールドは **本番ログ実物** ([src/fixtures/handler_value_error/logs.jsonl](../../../../src/fixtures/handler_value_error/logs.jsonl) の powertools 出力) と 1:1 対応:

```python
@dataclass(frozen=True)
class AlarmContext: name: str; timestamp: str; reason: str

@dataclass(frozen=True)
class LogRow:
    # powertools 標準
    timestamp: str               # "2026-04-27 06:47:48,051+0000" (ISO ではない powertools 固有書式)
    level: str                   # "ERROR" / "INFO" 等
    location: str | None         # "lambda_handler:178"
    message: str                 # "lambda_handler failed"
    service: str                 # "hdw-backend"
    cold_start: bool
    function_name: str
    function_memory_size: str    # "2048" (powertools が str で出す)
    function_arn: str
    function_request_id: str
    xray_trace_id: str | None

    # HDW 固有ビジネスコンテキスト
    ship_name: str | None        # "sakura" 等の船名
    ship_timestamp: str | None   # "20260427120100" (YYYYMMDDHHMMSS, ISO 8601 ではない)
    input_key: str | None        # "inputFiles/sakura-...zip"
    name_part: str | None
    event: str | None            # "lambda_complete"
    status: str | None           # "error" / "success"
    phase: str | None            # "handler"

    # 例外系 (status="error" の時のみ存在)
    exception: str | None        # 生 traceback 文字列
    exception_name: str | None   # "KeyError" / "ValueError"
    stack_trace: dict | None     # {type, value, module, frames: [{file,line,function,statement}]}

@dataclass(frozen=True)
class Report:
    summary: str; severity: str; confidence: str
    root_cause_hypothesis: str; suggested_actions: list[str]

class InvokeLLM(Protocol):
    def __call__(self, system: str, user: str) -> str: ...

def parse_alarm_event(event: dict) -> AlarmContext: ...
def parse_powertools_log(raw: dict) -> LogRow: ...
def render_prompts(alarm, rows) -> tuple[str, str]: ...
def parse_report(llm_text: str) -> Report: ...

def run(alarm, rows, invoke_llm) -> tuple[str, str, str, Report]:
    """戻り値 = (system, user, raw_llm_text, parsed_report)"""
```

## 4. fixture

各ケース 1 ディレクトリ、3 点セット (`alarm.json` + `logs.jsonl` + `README.md`)。`README.md` は「何のシナリオか / LLM に何を答えてほしいか」を 3〜5 行で記述。

| ケース | 想定 | 初期 fixture |
|---|---|---|
| **Case 1: 空ログ** | S3 ファイル未アップ → ログなし | `no_logs/` (1 件固定) |
| **Case 2: Lambda 失敗** | 実問題発生 → ログあり。サブパターンは無数 | `handler_value_error/` (本番 2026-04-27 の `ValueError: general_data is None` を使用) |

`logs.jsonl` は **powertools 生 JSON 1 行 1 ログ**。test.py は `src/fixtures/*/` を glob で全件拾うので、追加するだけで自動的に対象になる。

**Insights クエリ拡張**: 現状 [src/main.py:42-47](../../../../src/main.py#L42-L47) の `INSIGHTS_QUERY` は powertools フィールドのうち `level / cold_start / ship_name / ship_timestamp / input_key / phase / exception_name / message / exception / xray_trace_id` のみ投影。本 PLAN 採用にあたり、**LogRow 全フィールド分** (`location / service / function_name / function_memory_size / function_arn / name_part / event / status / stack_trace` を追加) に拡張する。

**Case 1 の扱い**: 現状 [main.py:267-279](../../../../src/main.py#L267-L279) の早期 return を廃止し、空ログでも Bedrock を呼ぶ。LLM は [prompt.py:57-59](../../../../src/utils/prompt.py#L57-L59) のヒント節を使って「S3 確認」を suggested_actions に出す。

## 5. test.py

LLM 常時呼び。オプションフラグなし。表示するだけで合否を返さない。

```bash
python src/test.py                          # src/fixtures/*/ を全件流す
python src/test.py handler_value_error      # 1 ケースだけ
```

env: `AWS_REGION` / `BEDROCK_MODEL_ID` / `BEDROCK_MAX_TOKENS` ([deploy/config.yml](../../../../deploy/config.yml) と同キー名)。Bedrock 認証は `aws sso login` 済み前提。

出力 (1 ケースあたり):

```
=== handler_value_error ===
--- README ---       (シナリオ説明)
--- AlarmContext --- (parse 結果)
--- LogRows (N 件) ---
--- system prompt ---
--- user prompt ---
--- LLM raw output ---
--- parsed Report ---
```

正常時 exit 0、fixture parse / Bedrock 失敗時は traceback で非 0。

## 6. main.py リファクタ

**analyzer.py へ移す**:
- AlarmContext 抽出 ([main.py:233-236](../../../../src/main.py#L233-L236))
- prompt 生成呼び出し ([main.py:282-283](../../../../src/main.py#L282-L283))
- Bedrock 応答 JSON parse ([main.py:293-294](../../../../src/main.py#L293-L294))
- powertools 行 → LogRow 変換 (現 [prompt.py:172-178](../../../../src/utils/prompt.py#L172-L178))

**main.py に残す**: env 読込 / 時間窓計算 / Insights I/O / Bedrock 呼び本体 (analyzer に渡す `invoke_llm` クロージャ) / Discord embed 構築 + post。

**削除**: 空ログ時の早期 return ([main.py:267-279](../../../../src/main.py#L267-L279))。

**utils/prompt.py 改修**: `render_prompt_user` 引数を `list[list[dict]]` → `list[LogRow]` に変更、内部の field/value→dict 変換を削除。

## 7. 段取り

| Step | 内容 | 並列 |
|---|---|---|
| 1 | analyzer.py: dataclass + 関数シグネチャだけ先に置く | — |
| 2 | parse_alarm_event / parse_powertools_log / parse_report 実装 | Step 5 と並列可 |
| 3 | utils/prompt.py の render_prompt_user を LogRow 受けに改修 + main.py 呼出更新 | — |
| 4 | analyzer.run() 実装 | — |
| 5 | src/fixtures/no_logs/ + handler_value_error/ 作成 (3 点セット ×2) | Step 1-4 と並列可 |
| 6 | src/test.py 実装 | Step 1-5 完了後 |
| 7 | main.py リファクタ (analyzer 経由 + 早期 return 廃止) | Step 6 完了後 |

## 8. オープン項目

- [ ] 本番ログを `src/fixtures/handler_value_error/` にコピーする際、`function_arn` / `function_request_id` / `xray_trace_id` / `input_key` の値をマスクするか実値のまま置くか (社内利用なら実値で可)
- [ ] `LogRow` 必須 / Optional の最終確定 (本番 ERROR ログでは `exception` / `exception_name` / `stack_trace` 揃ってるが、INFO ログでは Optional になる前提でよいか)
- [ ] Case 2 サブパターン追加 trigger: 運用で出会ったら都度追加 / 棚卸し的に既知パターンを先出し
- [ ] test.py 実 Bedrock 呼びの想定課金とローカル実行頻度 (コスト見積もり PLAN と接続)
- [ ] test.py の model ID を env 必須にするか、フォールバック値を持たせるか
- [ ] INSIGHTS_QUERY 拡張時、`stack_trace` (nested object) を Insights が dict のまま投影できるか (string flatten される可能性あり) — 拡張時に実機検証
