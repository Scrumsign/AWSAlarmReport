---
title: Bedrock user prompt のコンパクト化テンプレ
date: 2026-05-18
status: sample
type: prompt-format-spec
scope: reporter-lambda user prompt
author: t.kimura@scrumsign.com
related:
  - ../../05/15/report-content-by-case/DRAFT.md
  - ../discord-embed-5w1h-refinement/PLAN.md
  - ../bedrock-opus-model-access-denied/INVESTIGATION.md
tags:
  - bedrock
  - prompt-design
  - cost-optimization
  - tokenization
---

# Bedrock user prompt のコンパクト化テンプレ

## 0. 目的

[`src/main.py`](../../../../src/main.py) が現在 Bedrock Converse に渡している
**user メッセージ**は、CloudWatch Logs Insights の生レスポンスを `json.dumps` で
そのまま貼り付けている。これが冗長な構造のためトークン消費が大きい:

- すべての行で `{"field": "<name>", "value": "..."}` の `"field"` / `"value"` キーが繰り返される
- 同じ field 名（`@timestamp`, `level`, `function_request_id` 等）が行数ぶん繰り返される
- JSON の引用符・ブレースが意味のないトークンを消費する
- 判断に貢献しないフィールド（`xray_trace_id`, `level`=常にERROR, `cold_start`=多くが false）がそのまま載る

本ドキュメントは**新しい user prompt の表現フォーマット**を確定させ、
[`src/utils/prompt.py`](../../../../src/utils/prompt.py) に実装する基準を示す。

---

## 1. 設計原則

| # | 原則 | 帰結 |
|---|---|---|
| 1 | LLM が判断に使うフィールドだけ載せる | `xray_trace_id` / `level` 等を落とす |
| 2 | 同じ情報を 2 回書かない | field 名はテンプレ側に固定、値だけ流し込む |
| 3 | 空欄・常に同じ値は省略 | `cold_start=false` は出さない、true の時だけ出す |
| 4 | スタックトレースは LLM の主原料なので無加工 | 行数や1行長さの切詰めはしない (Phase 2 で別途検討) |
| 5 | 行頭の番号・インデントで構造を視認可能に | LLM の attention が散らない |
| 6 | プレーンテキスト (markdown 風) で JSON ブレース回避 | トークン削減 |

---

## 2. 採用フォーマット (Before / After)

### 2.1 BEFORE（現状）

[`src/main.py:147-150`](../../../../src/main.py#L147-L150) が生成している現状の user 文字列:

```json
{"alarm": {"name": "TestAlarm", "timestamp": "2026-05-17T23:59:01.629+0000", "reason": "Threshold Crossed: 1 out of the last 1 datapoints [1.0 (17/05/26 23:54:00)] was greater than the threshold (0.0) (minimum 1 datapoint for OK -> ALARM transition)."}, "logs": [[{"field": "@timestamp", "value": "2026-05-17 23:54:00.123"}, {"field": "level", "value": "ERROR"}, {"field": "function_request_id", "value": "16b14e5f-81b6-4283-a267-6e7b72266ac0"}, {"field": "cold_start", "value": "false"}, {"field": "ship_name", "value": "sakura"}, {"field": "ship_timestamp", "value": "20260518080100"}, {"field": "input_key", "value": "inputFiles/sakura-20260518080100.zip"}, {"field": "phase", "value": "handler"}, {"field": "exception_name", "value": "KeyError"}, {"field": "message", "value": "failed to process ship payload"}, {"field": "exception", "value": "Traceback (most recent call last):\n  File \"/var/task/main.py\", line 87, in handler\n    payload = event['ship']['payload']\nKeyError: 'payload'"}, {"field": "xray_trace_id", "value": "1-6a0a5645-5a04d25a439c94e614937161"}]]}
```

= 1行あたり ~846 chars / ~338 tokens（[コスト分析セッション参照](../bedrock-opus-model-access-denied/INVESTIGATION.md)）。

### 2.2 AFTER（新フォーマット）

同じ情報を以下の形で投げる:

```
# Alarm
name:    TestAlarm
fired:   2026-05-17T23:59:01+00:00
reason:  Threshold Crossed: 1 out of the last 1 datapoints [1.0 (17/05/26 23:54:00)] was greater than the threshold (0.0) (minimum 1 datapoint for OK -> ALARM transition).

# Error logs (1件)

[1] 2026-05-17 23:54:00.123  req=16b14e5f-81b6-4283-a267-6e7b72266ac0
    ship=sakura  ts=20260518080100  input=inputFiles/sakura-20260518080100.zip
    phase=handler
    KeyError: failed to process ship payload
    trace:
      Traceback (most recent call last):
        File "/var/task/main.py", line 87, in handler
          payload = event['ship']['payload']
      KeyError: 'payload'
```

= ~600 chars / ~240 tokens 程度（**約 30% 削減見込み**、確定値は実装後に
`count_tokens` で再測定）。

---

## 3. フォーマット規約

### 3.1 Alarm セクション（先頭固定）

```
# Alarm
name:    {alarm_name}
fired:   {timestamp}
reason:  {reason}
```

- 3 行固定
- `name` / `fired` / `reason` のラベルは英小文字、コロン後にスペース 2 個（視覚整列）
- `reason` が空文字列の場合は `(none)` を入れる
- `reason` 内の改行はそのまま保持（CloudWatch reason は1行のことがほぼ全て）

### 3.2 Error logs セクション

```
# Error logs ({N}件)

[{i}] {timestamp}  req={function_request_id}{cold_start_marker}
    {context_line}
    phase={phase}
    {exception_name}: {message}
    trace:
      {exception_indented}
```

#### 3.2.1 ヘッダ行

- `[i]` は 1 始まり連番
- `timestamp` は `@timestamp` の値そのまま（"2026-05-17 23:54:00.123" 形式）
- `req=` は `function_request_id` の値そのまま（UUID 全長）。**なければ `req=?`**
- `cold_start_marker`:
  - `cold_start == "true"` のときだけ `  [cold_start]` を末尾に追加
  - `false` または欠落のときは何も出さない

#### 3.2.2 context 行

`ship_name`, `ship_timestamp`, `input_key` を半角スペース 2 個で繋ぐ:

```
    ship={ship_name}  ts={ship_timestamp}  input={input_key}
```

- 3 つともある時の例: `ship=sakura  ts=20260518080100  input=inputFiles/sakura-20260518080100.zip`
- 1 つでも欠ける場合は **その項目だけスキップ** (`ship=sakura  input=...` のように)
- 3 つすべて欠ける場合は **context 行自体を出さない**

#### 3.2.3 phase 行

```
    phase={phase}
```

- `phase` が無い場合はこの行を出さない

#### 3.2.4 exception 行

```
    {exception_name}: {message}
```

- 両方ある場合: `KeyError: failed to process ship payload`
- `exception_name` のみ: `KeyError`
- `message` のみ: `failed to process ship payload`（これは ERROR ログとしては稀）
- 両方無い場合は出さない

#### 3.2.5 trace ブロック

```
    trace:
      {exception_indented}
```

- `exception` フィールドの値を全文（無加工）でインデント 6 スペース付きで出す
- `exception` が無い場合は `trace:` 行ごと出さない
- Phase 2 で行数切詰めや末尾省略を入れる場合はここに集約する（本サンプルではスコープ外）

---

## 4. 落とすフィールド

| field | 落とす理由 |
|---|---|
| `level` | Insights 側で `filter status = "error"` 済みのため常に `ERROR`。LLM が判断に使う情報量ゼロ |
| `xray_trace_id` | Embed PLAN §6.2 で deeplink は呼び出し側で機械生成する方針。プロンプトには載せない |
| `@ptr` | 内部ポインタ、LLM には無意味（Insights が含めることがある） |

---

## 5. サンプル: 行数別の出力

### 5.1 N=0（早期 return 経路に入るのでそもそも LLM 呼ばれない）

該当なし。`src/main.py` の空ログ早期 return パスで処理される。

### 5.2 N=1

```
# Alarm
name:    HDW_Backend_Processor_0001-Errors
fired:   2026-05-17T23:59:01+00:00
reason:  Threshold Crossed: 1 datapoint [1.0] was greater than the threshold (0.0).

# Error logs (1件)

[1] 2026-05-17 23:54:00.123  req=16b14e5f-81b6-4283-a267-6e7b72266ac0
    ship=sakura  ts=20260518080100  input=inputFiles/sakura-20260518080100.zip
    phase=handler
    KeyError: failed to process ship payload
    trace:
      Traceback (most recent call last):
        File "/var/task/main.py", line 87, in handler
          payload = event['ship']['payload']
      KeyError: 'payload'
```

### 5.3 N=3（複数行、欠落フィールド混在）

```
# Alarm
name:    HDW_Backend_Processor_0001-Errors
fired:   2026-05-17T23:59:01+00:00
reason:  Threshold Crossed: 3 out of the last 5 datapoints were greater than the threshold (0.0).

# Error logs (3件)

[1] 2026-05-17 23:54:00.123  req=16b14e5f-81b6-4283-a267-6e7b72266ac0  [cold_start]
    ship=sakura  ts=20260518080100  input=inputFiles/sakura-20260518080100.zip
    phase=handler
    KeyError: failed to process ship payload
    trace:
      Traceback (most recent call last):
        File "/var/task/main.py", line 87, in handler
          payload = event['ship']['payload']
      KeyError: 'payload'

[2] 2026-05-17 23:55:01.245  req=27388da6-efde-4293-a68c-1d43958ed972
    ship=shimakaji  input=inputFiles/shimakaji-20260518080200.zip
    phase=handler
    ValueError: invalid timestamp format in payload
    trace:
      Traceback (most recent call last):
        File "/var/task/parser.py", line 42, in parse_ts
          dt = datetime.strptime(s, "%Y%m%d%H%M%S")
      ValueError: time data '2026-05-XX' does not match format '%Y%m%d%H%M%S'

[3] 2026-05-17 23:56:12.001  req=?
    ClientError: An error occurred (ThrottlingException) when calling the GetItem operation
    trace:
      botocore.exceptions.ClientError: An error occurred (ThrottlingException) ...
```

### 5.4 N=50（上限ケース）

行数だけ違うので構造は同じ。`# Error logs (50件)` のヘッダと `[1]` 〜 `[50]` が並ぶ。
入力トークンは `T_in ≒ 452(base) + 30%圧縮された N×per-row` で抑えられる。

---

## 6. トークン削減の実測

Bedrock `count_tokens` API（Sonnet 4.6, system_generic + user_text）で
mid 行サンプル（[コスト分析セッション](../bedrock-opus-model-access-denied/INVESTIGATION.md) と同じ）の
旧フォーマット vs 新フォーマットを直接比較した結果:

| N | 旧 chars | 新 chars | 旧 tokens | 新 tokens | 削減率 |
|---:|---:|---:|---:|---:|---:|
| 0 | 262 | 252 | 783 | 782 | 0.1% |
| 1 | 1,073 | 642 | 1,086 | 926 | 14.7% |
| 2 | 1,886 | 1,032 | 1,390 | 1,070 | 23.0% |
| 5 | 4,325 | 2,202 | 2,302 | 1,502 | **34.8%** |
| 10 | 8,390 | 4,154 | 3,822 | 2,222 | **41.9%** |
| 20 | 16,520 | 8,064 | 6,862 | 3,662 | **46.6%** |
| 50 | 40,910 | 19,794 | 15,982 | 7,982 | **50.1%** |

**新コスト式（線形回帰）**:

```
T_input(N) ≒ 780 + 144 × N        # 旧: 452 + 338×N — 傾きが約 0.43 倍に
```

per-row tokens が 338 → 144 と **約 57% 削減**。
N が大きいほど効果が大きく、上限ケース (N=50) ではほぼ半減する。

### 6.1 料金換算（mid 行, T_out=500 nominal）

| N | Sonnet 4.6 旧→新 | Opus 4.7 旧→新 |
|---:|---|---|
| 10 | ¥2.9 → ¥1.8 | ¥14.7 → ¥9.7 |
| 20 | ¥4.5 → ¥2.5 | ¥22.6 → ¥13.5 |
| 50 (上限) | ¥9.2 → ¥4.3 | ¥46 → ¥23 |

---

## 7. 実装に落とすときの契約

[`src/utils/prompt.py`](../../../../src/utils/prompt.py) に新規関数を追加:

```python
def render_prompt_user(
    alarm_name: str,
    timestamp: str,
    reason: str,
    log_rows: list[list[dict[str, str]]],
) -> str:
    """CloudWatch Alarm event + Insights 結果から Bedrock user メッセージを組み立てる。

    出力形式は docs/2026/05/18/prompt-compact-format/SAMPLE.md に準拠。
    冗長な JSON 構造を避け、ラベル付きプレーンテキストで圧縮する。
    """
```

[`src/main.py:147-150`](../../../../src/main.py#L147-L150) の `user_text = json.dumps(...)`
ブロックを `user_text = render_prompt_user(alarm_name, timestamp, reason, log_rows)` で置換する。

呼び出し側のロジック変更はそれだけ。プロンプトの中身（system 側）は
本サンプルのスコープ外。

---

## 8. オープン論点（本サンプルでは決めない）

- `exception` フィールドの長文切詰め（Phase 2 P2-2 として既出）
- ケース別 (timeout / dependency) でフォーマットを微調整するか（現状はケース判定なしで Generic 固定）
- フィールド順序（時系列で並べるか、severity で並べるか） — 現状は Insights の `sort @timestamp desc` の順
