# テストハーネス導入 + analyzer 切り出し DRAFT

## 0. このドキュメントの位置づけ

`docs/2026/05/18/mvp-followups-investigation/DRAFT.md` の 3 テーマのうち **テーマ B (テスト環境)** の独立計画。残り 2 テーマ (prompt 改善 / コスト見積もり) はこのドキュメントの範囲外。

この DRAFT はまだ実装着手前の合意形成用。問題なければ `PLAN.md` に格上げする。

---

## 1. ゴール / 非ゴール

### ゴール

- aws_lambda_powertools の JSON ログを **mock データとして JSONL でリポジトリ内に持ち**、テストケース化する
- 「ログデータ → 生成テキスト」のパイプラインを **boto3 / discord_webhook 非依存** の独立モジュール `src/analyzer.py` に切り出す
- `tests/test.py` を JSONL fixture を読んで生成テキストを stdout に吐く **目視確認スクリプト** として用意し、prompt 改善ループを回せる土台を作る

### 非ゴール (今回はやらない・**将来も入れない**)

- prompt 文面の改善そのもの (テーマ A 側で別 PLAN)
- **pytest / unittest 等のテストフレームワーク導入** — LLM 出力は同入力でも揺れるし、prompt は「内容の妥当性」が本質なので等値 assert に意味はない。判定は常に人間が目で行う
- **snapshot 比較・JSON Schema assertion 等の自動検証レイヤ** — 同じ理由で導入しない。差分を機械が見ても prompt の良し悪しは判定できない。test.py は LLM 出力を表示するだけで、合否を返さない
- CI 統合 (`.github/workflows` への追加) — test.py は実 Bedrock を叩く前提なのでローカル実行のみ
- Discord webhook / boto3 boundary のテスト (analyzer の外側、後回し)
- ケース分類器 (generic / timeout / dependency 自動判定) の導入

---

## 2. 全体構成

```
src/
  main.py            ← 痩せた orchestrator: env 読込 → Insights → analyzer.run → Discord post
  analyzer.py        ← NEW: ログ → 生成テキスト の純パイプライン (boto3/discord 非依存)
  utils/
    prompt.py        ← 既存。テンプレ文字列素材 (変更最小)
tests/
  __init__.py
  test.py            ← fixture を流して生成テキストを stdout に出すスクリプト
  fixtures/
    case_handler_exception/
      alarm.json
      logs.jsonl
    case_timeout/
      alarm.json
      logs.jsonl
    case_dependency_failure/
      alarm.json
      logs.jsonl
    case_multi_rows/
      alarm.json
      logs.jsonl
    case_empty/
      alarm.json
      logs.jsonl
    ...
```

### 依存関係

```
main.py ──── imports ───► analyzer.py ──── imports ───► utils/prompt.py
   │                          ▲
   │                          │
   └─ boto3, discord_webhook  └─ (boto3/discord は import しない)

test.py ──── imports ───► analyzer.py
   │
   └─ JSONL fixtures を読み込み、analyzer.run(...) を invoke して結果を print
```

ポイント: `analyzer.py` から `boto3` / `discord_webhook` の import 行が完全に消える。LLM 呼び出しは関数注入 (§3 案 β)。

---

## 3. analyzer.py の責務と API

### 採用案: β (LLM 呼び注入式)

analyzer は「prompt 組立 + LLM 呼び + JSON parse」までを担当。Bedrock 固有の boto3 呼び出しは `invoke_llm` Callable として外から注入する。

### 公開関数の素案

```python
# src/analyzer.py

from typing import Callable, Protocol
from dataclasses import dataclass

@dataclass(frozen=True)
class AlarmContext:
    """CW Alarm event から抽出した最小情報。"""
    name: str
    timestamp: str   # ISO 8601
    reason: str

@dataclass(frozen=True)
class LogRow:
    """1 件のエラーログ。powertools JSON から projection 済み (§4 案 P)。"""
    timestamp: str
    request_id: str | None
    cold_start: bool
    ship_name: str | None
    ship_timestamp: str | None
    input_key: str | None
    phase: str | None
    exception_name: str | None
    message: str | None
    exception: str | None  # traceback

@dataclass(frozen=True)
class Report:
    """LLM 出力 JSON を parse した結果。"""
    summary: str
    severity: str  # LOW | MEDIUM | HIGH
    confidence: str  # low | medium | high
    root_cause_hypothesis: str
    suggested_actions: list[str]

class InvokeLLM(Protocol):
    """(system, user) → 生成テキスト の関数シグネチャ。"""
    def __call__(self, system: str, user: str) -> str: ...

# --- pure 関数群 ---

def parse_alarm_event(event: dict) -> AlarmContext: ...

def parse_powertools_log(raw: dict) -> LogRow:
    """powertools JSON ログ 1 行 → LogRow に変換。"""
    ...

def render_prompts(alarm: AlarmContext, rows: list[LogRow]) -> tuple[str, str]:
    """(system_prompt, user_prompt) を返す。utils/prompt.py を呼ぶだけの薄ラッパ。"""
    ...

def parse_report(llm_text: str) -> Report:
    """LLM 生成テキスト (JSON) → Report。スキーマ逸脱は例外。"""
    ...

# --- パイプライン本体 ---

def run(
    alarm: AlarmContext,
    rows: list[LogRow],
    invoke_llm: InvokeLLM,
) -> tuple[str, str, str, Report]:
    """
    ログから生成テキスト・Report まで一直線に通す。
    戻り値 = (system_prompt, user_prompt, raw_llm_text, parsed_report)
    """
    system, user = render_prompts(alarm, rows)
    raw = invoke_llm(system, user)
    report = parse_report(raw)
    return system, user, raw, report
```

### 設計上の重要点

- **boto3 を import しない**。`InvokeLLM` Protocol だけ定義し、main.py 側で Bedrock-bound な実装を渡す
- **LogRow は powertools JSON から直接 parse する**。Insights 結果形式 (`list[{field,value}]`) ではない (§4 案 P)
- **`run()` は LLM 出力の raw text もそのまま返す**。test.py で生成テキストを目視するため
- **既存の [src/utils/prompt.py](../../../../src/utils/prompt.py) は触らない**。`render_prompt_user` の入力型を `list[list[dict]]` から `list[LogRow]` に変える小改修だけ後で必要 (詳細は §6)

### main.py 側で必要な glue (例)

```python
# src/main.py (抜粋イメージ)
def _bedrock_invoke(system: str, user: str) -> str:
    resp = boto3.client("bedrock-runtime").converse(
        modelId=env.bedrock_model_id,
        system=[{"text": system}],
        messages=[{"role": "user", "content": [{"text": user}]}],
        inferenceConfig={"maxTokens": env.bedrock_max_tokens},
    )
    return resp["output"]["message"]["content"][0]["text"]

# 中略
alarm = analyzer.parse_alarm_event(event)
rows = [analyzer.parse_powertools_log(r) for r in fetched_logs]  # Insights→dict変換は main 側
_, _, _, report = analyzer.run(alarm, rows, invoke_llm=_bedrock_invoke)
```

---

## 4. fixture 設計

### 採用案: Y (2 ファイル分離) + P (powertools 生 JSON)

各テストケースを 1 ディレクトリ。中に `alarm.json` (CW Alarm event 全体) と `logs.jsonl` (powertools JSON ログ 1 行/entry)。

### alarm.json の例

```json
{
  "alarmArn": "arn:aws:cloudwatch:ap-northeast-1:088898720463:alarm:hdw-ingest-errors",
  "alarmData": {
    "state": {
      "value": "ALARM",
      "timestamp": "2026-05-18T03:12:00.000+0000",
      "reason": "Threshold Crossed: 1 datapoint [1.0 (18/05/26 03:11:00)] was greater than or equal to the threshold (1.0)."
    },
    "configuration": {
      "metrics": [...]
    }
  }
}
```

→ `event["alarmArn"]` と `event["alarmData"]["state"]["timestamp"]` / `["reason"]` を parse する現状コードと互換。

### logs.jsonl の例 (1 行 = 1 ログイベント)

```jsonl
{"timestamp": "2026-05-18 03:11:58.123", "level": "ERROR", "status": "error", "function_request_id": "abc-123", "cold_start": false, "ship_name": "SHIP_X", "ship_timestamp": "2026-05-18T03:00:00Z", "input_key": "ships/SHIP_X/2026-05-18.csv", "phase": "handler", "exception_name": "ValueError", "message": "invalid CSV row at line 42", "exception": "Traceback (most recent call last):\n  File ..."}
{"timestamp": "2026-05-18 03:11:57.001", "level": "ERROR", ...}
```

フィールド名は [src/main.py:42-47](../../../../src/main.py#L42-L47) の `INSIGHTS_QUERY` で `fields` 句に並んでいるキーと一致させる。

### ケース一覧 (初回作成分)

| ケース名 | ねらい | log 件数 | 特徴 |
|---|---|---|---|
| `case_handler_exception` | 典型: handler 例外 1 件 | 1 | `exception_name`, `exception` (trace) あり, cold_start=false |
| `case_cold_start_failure` | 典型: コールドスタート初回失敗 | 1 | cold_start=true |
| `case_timeout` | timeout 風 | 2-3 | exception フィールドなし, message のみ, 末尾停止系 |
| `case_dependency_failure` | AWS 依存失敗 | 1 | `exception_name=ClientError`, message に `AccessDenied` 等 |
| `case_multi_rows` | 同 request_id でフェーズ違い連鎖 | 10 | phase が複数段, 同 request_id |
| `case_high_volume` | Insights 上限・トークン上限負荷 | 50 | render_prompt_user のトークン圧迫を観察 |
| `case_empty` | log 0 件 (早期 return パス) | 0 | logs.jsonl 空ファイル |
| `case_missing_fields` | フィールド欠損耐性 | 3 | message のみ / trace のみ / 全部欠落 |

→ 全 8 ケース。最初は 3〜4 ケース (`handler_exception`, `timeout`, `empty`, `multi_rows`) から書いて、必要に応じて足す方針。

### fixture の作り方の方針

- 実 powertools 出力に寄せる: 既存 HDW_Backend_Processor_0001 の CW Logs から実物を 1〜2 件コピー、PII/機密だけ伏字化 → ベースに同型のバリエーションを生成
- **ユーザーへの依頼**: 実ログ 1〜2 件 (sanitize 済み) があると質が大幅に上がる。なくても架空データで開始は可能

---

## 5. test.py の動作仕様

### 位置づけ: **「ログ → LLM → 出力」を一直線に見るスクリプト**

prompt 改善のループは「fixture のログを LLM にかけて、出てきた出力が適切か目で確かめる → prompt を直す → 同じログで再実行して変化を見る」が本質。test.py は **このループを最短で回すための実行スクリプト**。

| 何をする | 何をしない |
|---|---|
| fixture を読む | pytest / unittest 等のフレームワークに乗せる |
| analyzer.run() を呼ぶ (= 実 LLM を叩く) | 出力に対する assert / snapshot diff / schema 検証 |
| 入出力と prompt を全部 stdout に並べる | 終了コードによる成否判定 |

判定するのは常に人間。スクリプトは情報を整理して見せるだけ。

`tests/` ディレクトリ配下に置くが「テストフレームワーク」ではない。「prompt 改善用の実行スクリプト + その入力データ置き場」と読む。

### 起動方法

```bash
python tests/test.py                            # 全 fixture を順に LLM へ流して出力
python tests/test.py case_handler_exception     # 1 ケースだけ
```

オプションフラグは原則設けない。**LLM 呼び出しは常時 ON**。Bedrock の認証は `aws sso login` 等で済んでいる前提で、`AWS_REGION` / `BEDROCK_MODEL_ID` / `BEDROCK_MAX_TOKENS` 等は環境変数経由で受ける ([deploy/config.yml](../../../../deploy/config.yml) と同じキー名)。

### 出力フォーマット (1 ケースあたり)

```
================================================================================
=== case_handler_exception
================================================================================

--- AlarmContext ---
AlarmContext(name='hdw-ingest-errors', timestamp='2026-05-18T03:12:00Z', reason='Threshold...')

--- LogRows (1 件) ---
LogRow(timestamp='2026-05-18 03:11:58.123', request_id='abc-123', ...)

--- system prompt ---
あなたはAWS Lambda障害分析の専門家です。
...

--- user prompt ---
# Alarm
name:    hdw-ingest-errors
...

--- LLM raw output ---
{"summary": "...", "severity": "HIGH", ...}

--- parsed Report ---
Report(summary='...', severity='HIGH', confidence='medium',
       root_cause_hypothesis='...',
       suggested_actions=['...', '...', '...'])
```

これだけ。終了コードは正常時 0、fixture parse / Bedrock 呼び出しに失敗したら traceback を出して非 0 で落ちる程度。

### 改善ループでの使い方 (想定)

1. `tests/fixtures/case_xxx/` に再現したいログをセット
2. `python tests/test.py case_xxx` で 1 回実行 → 出力を読む
3. 出力が「微妙」と感じたら [src/utils/prompt.py](../../../../src/utils/prompt.py) のテンプレを直す
4. 同じケースを再実行 → 変化を比較
5. 別ケースで副作用が出てないか `python tests/test.py` で全件流し確認

「prompt をどう直すか」「出力が適切か」の判定は人間。スクリプトはそこに口を出さない。

---

## 6. main.py のリファクタ範囲

[src/main.py](../../../../src/main.py) を「I/O 専属の orchestrator」に痩せさせる。

### 移動するもの (main.py → analyzer.py)

- AlarmContext 抽出ロジック (現 [main.py:233-236](../../../../src/main.py#L233-L236))
- prompt 生成呼び出し (現 [main.py:282-283](../../../../src/main.py#L282-L283))
- Bedrock 応答 JSON parse (現 [main.py:293-294](../../../../src/main.py#L293-L294))
- powertools JSON / Insights 行 → LogRow 変換 (現 [utils/prompt.py:172-178](../../../../src/utils/prompt.py#L172-L178) のインライン変換を昇格)

### main.py に残るもの

- 環境変数読込 (`Env.from_environ`)
- `derive_window` 相当 (時刻計算 — analyzer.py に移してもよいが I/O 設定の隣にあるほうが自然)
- `logs_client.start_query` → polling → `get_query_results` (Insights I/O)
- Bedrock 呼び出し本体 (analyzer に渡す `invoke_llm` クロージャとして実装)
- Discord embed 構築 + post (このフェーズでは現状コードを温存。embed 構築の analyzer 化はテーマ A or 後フェーズで検討)
- 空ログ / fallback のコントロールフロー

### `utils/prompt.py` への小改修

`render_prompt_user` の引数を `log_rows: list[list[dict[str, str]]]` から `rows: list[LogRow]` に変更。内部の field/value → dict 変換ロジックを削除し、LogRow 属性を直接参照。

これにより:
- analyzer.py が Insights 結果形式に依存しなくなる
- test.py から prompt を生成するときに「Insights 形式の dict をでっち上げる」必要がなくなる

---

## 7. 段取り (ステップ)

| Step | 内容 | 完了判定 |
|---|---|---|
| 1 | `src/analyzer.py` 新規作成: dataclass + 関数シグネチャだけ先に置く (中身は pass / NotImplemented) | mypy / import が通る |
| 2 | `parse_alarm_event` / `parse_powertools_log` / `parse_report` の 3 つの pure 関数を実装 | 単体で関数呼んだら期待 dataclass が返る |
| 3 | `utils/prompt.py` の `render_prompt_user` を `LogRow` 受け取りに改修 | 既存 main.py が壊れないよう main.py 側の呼び出しも同時更新 |
| 4 | `analyzer.run(...)` を実装 (薄い orchestration) | fake invoke_llm を渡すと最後まで通る |
| 5 | `tests/fixtures/case_*/` を 3〜4 ケース作成 | JSONL が powertools 出力と一致する形 |
| 6 | `tests/test.py` を実装 (fixture を読み analyzer.run で LLM 叩いて入出力を stdout に並べる) | コマンドラインから全 fixture 流せて Bedrock 応答が出力に乗る |
| 7 | `src/main.py` をリファクタして analyzer 経由に切り替え | 既存テスト環境デプロイで動作確認 |
| 8 | DRAFT を PLAN に格上げ・本ドキュメント archive | レビュー OK |

並列化可能: Step 1-2-3-4 (analyzer 側) と Step 5 (fixture 作成) は独立。Step 6 は 1-4 完了後。Step 7 は 6 まで終わってから。

---

## 8. オープン項目 (確定したいこと)

- [ ] 実 powertools ログサンプルを 1〜2 件もらえるか (sanitize 済みで OK)
- [ ] `LogRow` の **必須 / Optional フィールド** の取り扱い (powertools 出力で「常にある / たまにある」の境界確認)
- [ ] `case_high_volume` (50 件) の data は人手で書くと辛い → スクリプト生成にするか手書きを諦めて 10 件で代用するか
- [ ] test.py の実 Bedrock 呼び出しに対する 1 回 / 全件あたりの **想定課金** とローカル実行頻度の合意 (Sonnet 4.6 を ~8 ケース × 数千 token なら 1 回 $0.05 オーダー想定。実測はテーマ C で)
- [ ] test.py がデフォルトで読む model ID (env 未設定時のフォールバック値) を持たせるか、env 必須にするか

---

## 9. このドキュメントの採用済み判断 (議論経緯のサマリ)

| 論点 | 採用案 | 理由 |
|---|---|---|
| analyzer の境界 | **β (LLM 呼び注入)** | boto3 import を analyzer から完全排除する。production の main.py と test.py の両方が「ログ → analyzer.run → 出力」を共有し、Bedrock 呼び実装だけ別々に差し込む形にする |
| fixture 構造 | **Y (alarm.json + logs.jsonl 分離)** | alarm は dict、logs は行指向で粒度が違うため。diff も読みやすい |
| ログ JSON 形式 | **P (powertools 生 JSON)** | 「aws_lambda_powertools の JSON 化されたログ前提で mock」というユーザー方針に直結 |
| test.py 形式 | **prompt ダンプスクリプト** | テストフレームワーク・snapshot・schema 検証は一切入れない。fixture を流して prompt を stdout に出すだけ。判定は人間 |

これらは DRAFT → PLAN 化時に再確認する。
