# コスト見積もり DRAFT

## 0. このドキュメントの位置づけ

`docs/2026/05/18/mvp-followups-investigation/DRAFT.md` の 3 テーマのうち **テーマ C (コスト見積もり)** の独立 DRAFT。

最終目的は「責任者が **本実装に進む / 改善する / 棚上げる** の判断ができる材料」を出すこと ([ISSUE.md](../../15/lambda-error-report-mvp/ISSUE.md) の Acceptance Criteria 4 つ目)。

本 DRAFT は **「何を測れば月額が出るか」を式として確定** することがゴール。具体的な数値はテーマ B (test-harness PLAN) が動いて fixture + render_prompts が揃った後で実測する。

---

## 1. ゴール / 非ゴール

### ゴール

- 月額コストの **計算式** と、その式に入る変数を確定する
- 各変数を測る・決める方法を列挙する
- 確定したい意思決定項目 (source embed yes/no、N 値、モデル選定) をオープンにして残す

### 非ゴール

- 本 DRAFT 内での数値確定 (実測はテーマ B 完了後)
- LLM 以外の細部最適化 (Lambda メモリ、ARM vs x86)
- 自動コストモニタリング基盤 (Budgets / Billing アラート) の構築

---

## 2. 計算式 (確定)

```
コスト/月 = N_calls
            × ( T_in × P_in(model)
              + T_out × P_out(model)
              - T_cached × P_in(model) × (1 - cache_discount) )
```

| 記号 | 意味 | 確定状況 |
|---|---|---|
| `N_calls` | 月間 Bedrock 呼び出し回数 | **180 回/月** (= 30 日 × 6 回/日。データ到着 4 時間おき × 全部失敗時の上限) |
| `T_in` | 1 呼あたり入力トークン総数 | §3 で測定 |
| `T_out` | 1 呼あたり出力トークン総数 | §3 で測定 (`max_tokens=1024` 上限) |
| `T_cached` | キャッシュヒット部分のトークン数 | §3 で算定 (static 部分のみ) |
| `P_in(model)` | モデル別入力単価 ($/Mtok) | §3 で確認 |
| `P_out(model)` | モデル別出力単価 ($/Mtok) | §3 で確認 |
| `cache_discount` | prompt cache 適用時の入力単価割引率 | §3 で確認 (Anthropic 公称 ~90%) |

### `T_in` の内訳構造

```
T_in = T_system + T_source + T_alarm_meta + T_error_logs + T_success_logs
```

| 部品 | 想定中身 | 静的/動的 | キャッシュ対象? |
|---|---|---|---|
| `T_system` | システムプロンプト ([prompt.py:17-73](../../../../src/utils/prompt.py#L17-L73)) | 静的 | ✅ |
| `T_source` | HDW_ML ソースコード embed (採用時のみ) | 静的 | ✅ |
| `T_alarm_meta` | Alarm 名・時刻・reason | 動的 | ✕ |
| `T_error_logs` | 失敗時エラーログ (最大 50 件 = Insights `limit 50` 上限) | 動的 | ✕ |
| `T_success_logs` | **直近成功時のログ N 件** (新規入力) | 動的 | ✕ |

`T_source` と `T_success_logs` の採用可否 / 値が **未確定の意思決定項目**。

---

## 3. 調査タスク

### C-1. `T_system` の実測

- **方法**: Python スクリプトで以下を実行
  ```python
  from anthropic import AnthropicBedrock
  from utils.prompt import render_prompt_system_base, render_prompt_case_generic
  client = AnthropicBedrock()  # boto3 認証経由
  system = render_prompt_system_base(*render_prompt_case_generic())
  count = client.messages.count_tokens(
      model="anthropic.claude-sonnet-4-6",
      system=system,
      messages=[{"role": "user", "content": "x"}],  # 最小ダミー
  )
  print(count.input_tokens)
  ```
- ケース別追加指示 (generic / timeout / dependency) を切替えてそれぞれ測定
- 出力: `T_system` の baseline + ケース差分 (例: timeout は +50 tok 等)

### C-2. `T_source` の評価

HDW_ML ソースコード ([c:/Workspaces/HDW_ML/src/](../../../../../HDW_ML/src/) 配下) を embed するか否か。

- HDW_ML 規模: 約 1,564 行 (Python: 1,200 行 + README 345 行) — token ざっくり 4,000〜8,000
- 採用パターンの比較で意思決定:
  - (a) tree + README のみ (~2,000 tok)
  - (b) README + 主要関数シグネチャ (~2,500 tok)
  - (c) **HDW_ML 全文 embed** (~5,000〜8,000 tok)
  - (d) embed しない
- **方法**:
  1. (a) は `tree -L 3 c:/Workspaces/HDW_ML/src/` 出力 + `README.md` を結合した文字列を作る
  2. (b) は Python AST で各 .py から関数シグネチャと docstring 1 行目を抽出 (`ast.parse` → `FunctionDef` を walk)
  3. (c) は `src/**/*.py` と `README.md` を順序付きで連結
  4. 各パターン文字列を C-1 と同じ `count_tokens` API に通して測定
- 出力: 4 パターン × トークン数 + サンプル出力テキスト (人が見て妥当性判断できる形)

### C-3. `T_error_logs` の実測

- **方法**:
  1. テーマ B の fixture (`src/fixtures/handler_value_error/logs.jsonl`) を行数 1 / 10 / 50 にそれぞれ調整
  2. `analyzer.parse_powertools_log` で `list[LogRow]` に変換
  3. `render_prompt_user(alarm, rows)` を呼んで user prompt 文字列を生成
  4. `client.messages.count_tokens(model=..., messages=[{"role":"user","content":user}])` で測定
  5. 1 / 10 / 50 の 3 点を結んで線形近似 (1 件あたり係数 = `(T_50 - T_1) / 49`)
- 出力: ログ件数 → トークン数の換算式 (例: `T_error_logs = 200 + 180 × N_rows`)

### C-4. `T_success_logs` の評価

**新規入力。「直近の成功時のログ N 件」を context として与える前提**。

- 取得元: HDW_ML が成功実行した時の powertools JSON 構造化ログ
- N の候補:
  - N=10 (軽量 / +1,000〜3,000 tok)
  - N=50 (Insights 上限と揃える / +5,000〜15,000 tok)
  - N=100 (重量 / +10,000〜30,000 tok)
  - **N=0** (今回見送り)
- **方法**:
  1. HDW_Backend_Processor_0001 の LogGroup に対して以下の Insights クエリを test 環境で実行
     ```
     fields @timestamp, level, function_request_id, cold_start, ship_name, ship_timestamp, input_key, phase, message
     | filter status = "success"
     | sort @timestamp desc
     | limit 100
     ```
  2. 結果を JSONL に export し、ローカルに `success_logs_sample.jsonl` として保存
  3. C-3 と同じ手順で N=10 / 50 / 100 にスライスしてトークン測定
  4. 1 件あたり係数 ≒ C-3 (失敗ログ) より小さいはず (trace がないため)
- 出力: 件数 → トークン数の換算式
- **同時に決めること**: success_logs を prompt のどこに挿入するか (system に静的 / user に動的 / 別 message として渡す)

### C-5. `T_out` の実測

- **方法**:
  1. テーマ B の `src/test.py` を全 fixture で実行 (実 Bedrock 呼び出し)
  2. `analyzer.run` を改修して Bedrock response の `usage` フィールドも返すよう拡張するか、test.py 側で response を直接受け取る形にする
  3. fixture 1 件あたり 3 回実行してばらつきを測定
  4. 平均・最大・最小を記録
- `max_tokens=1024` の妥当性判定基準:
  - 平均出力 < 512 → 上限を下げて天井圧縮可
  - 最大出力が 1024 で頭打ち → 出力が切れる可能性あり、上限引き上げ要否
- 出力: モデル × fixture × `usage` 表

### C-6. モデル単価 `P_in` / `P_out` 確認

AWS Bedrock 側の最新単価をモデル別に確定。Anthropic 公式と乖離あり得るので **AWS の pricing page を一次ソース** とする。

- **方法**:
  1. AWS Bedrock pricing page (`https://aws.amazon.com/bedrock/pricing/`) を開き、Anthropic Claude セクションから 3 モデル分の単価を抜き取る
  2. ap-northeast-1 / cross-region inference profile (`jp.` / `global.`) の単価差を確認 (リージョン跨ぎで割増あり)
  3. 取得した単価と取得日時を表で記録 (単価変動への対処として日付明示)
- Opus 4.7 については **test 環境で AccessDenied 履歴あり ([docs/2026/05/15/bedrock-opus-model-access-denied/](../../15/bedrock-opus-model-access-denied/))**:
  - 方法: test 環境で `aws bedrock list-foundation-models` と最小呼び出しテストを実行し、利用可否を判定
  - 不可の場合は比較表から除外し注釈を残す

### C-7. `cache_discount` 確認

- **方法**:
  1. AWS Bedrock の prompt caching ドキュメント (`https://docs.aws.amazon.com/bedrock/latest/userguide/prompt-caching.html`) を確認
  2. 対応モデル一覧で Sonnet 4.6 / Haiku 4.5 / Opus 4.7 と ap-northeast-1 / inference profile の組合せが含まれるか
  3. cache write 単価・cache read 単価・最小キャッシュサイズ (Anthropic は ~1024 tok 下限) を抽出
  4. test 環境で実 cache hit を発生させて `usage.cacheReadInputTokens` 等のメタを確認
- `T_cached = T_system + T_source` を cache に乗せる構成が成立するかを判定:
  - 成立: cache breakpoint を system block 末尾に置く Bedrock Converse API リクエスト構成例を併記
  - 不成立: cache なしの数値だけを採用し注釈を残す

### C-8. `N_calls` の前提確認

- **180 回/月** は「4 時間おき × 全部失敗」の上限値で確定
- 楽観・想定・悲観の 3 段で出すなら:
  - 楽観: ~10 回/月 (まれにしか失敗しない)
  - 想定: ~30 回/月 (週数回失敗)
  - 悲観: **180 回/月 (上限)**
- **方法 (想定値の根拠取り)**:
  1. `aws cloudwatch describe-alarm-history --alarm-name hdw-ingest-errors --history-item-type StateUpdate --max-items 1000` で直近 3 ヶ月の状態遷移を取得
  2. `OK → ALARM` 遷移の件数を月別に集計
  3. 月平均を想定値、最大月を悲観値、最小月を楽観値として採用
  4. 履歴が短い (Alarm 設定直後) なら、HDW_ML の Lambda Errors metric を直接 `aws cloudwatch get-metric-statistics` で同期間ぶん取得して代用

### C-9. その他 AWS コスト要素 (LLM 以外)

[lambda-error-report-mvp/PLAN.md §4](../../15/lambda-error-report-mvp/PLAN.md) の試算は 100 件想定で組まれていて値が変わるので再計算:

| 要素 | 試算方法 |
|---|---|
| CW Alarm | $0.10/月 (個数固定。Standard Alarm は 1 個あたり $0.10) |
| Lambda invoke + duration | 180 呼 × 平均 duration × 単価 |
| Logs Insights scan | 180 呼 × 1 クエリの bytesScanned × $0.005/GB |
| ECR storage | image size × $0.10/GB-月 |
| Data transfer | Bedrock / Discord 通信、無視可レベルか確認 |

- **方法**:
  - **Lambda invoke + duration**: test 環境の Reporter Lambda に対し `aws logs filter-log-events --filter-pattern "REPORT"` で過去数十呼の `Billed Duration` を集計、平均値を算出 → `180 × avg_ms / 1000 × $0.0000166667/GB-s × memory_GB` で月額
  - **Logs Insights scan**: test 環境で `get_query_results` の response に含まれる `statistics.bytesScanned` を 5 回ぶん取得して平均化 → `180 × avg_bytes / 10^9 × $0.005` で月額
  - **ECR storage**: `aws ecr describe-images --repository-name hdw-notify` で `imageSizeInBytes` を取得 → `size_GB × $0.10` で月額
  - **Data transfer**: Bedrock 同一リージョン呼び出しは無料、Discord (egress) は 1 呼 ~数 KB なので 180 × 数 KB ≒ 1MB/月 で実質 $0 と判定

---

## 4. 成果物の形

### 4.1 結論ページ (1 枚)

```
# HDW Notify コスト見積もり (結論)

## 前提
- N_calls = 180 回/月 (上限想定。楽観・想定値も併記)
- T_source = [採用パターン] / T_success_logs = N=[選定値]

## 月額レンジ (3 モデル × cache あり/なし)

|        | Haiku 4.5 | Sonnet 4.6 | Opus 4.7 |
|--------|-----------|------------|----------|
| cache なし | $X.XX | $Y.YY | $Z.ZZ |
| cache あり | $X.XX | $Y.YY | $Z.ZZ |

## LLM 以外
- AWS その他: $W.WW/月

## 推奨
- 想定運用での最有力モデル / 棄却すべきモデル / 注釈
```

### 4.2 詳細ページ

- §3 の C-1〜C-9 の測定根拠と raw データ
- token counter 結果・Bedrock invocation の `usage` を表で残す
- 計算式と代入値を全部書く (責任者が後追いできる形)

---

## 5. 確定したい意思決定項目 (オープン)

ここの選択次第で計算結果が桁レベルで変わる。本 DRAFT を PLAN に格上げするまでに確定したい。

- [ ] **D-1. `T_source` 採用パターン** (§3 C-2 の (a)〜(d)): HDW_ML ソースをどこまで embed するか
- [ ] **D-2. `T_success_logs` の N 値**: 10 / 50 / 100 / 0 のどれを基準とするか。0 (今回見送り) でも DRAFT の式は維持
- [ ] **D-3. 比較モデルスコープ**: Sonnet のみ深掘り / Sonnet + Haiku / 3 モデル全部
- [ ] **D-4. `N_calls` 想定値**: 上限 180 のみ / 楽観・想定・悲観の 3 段
- [ ] **D-5. prompt caching 採用前提とするか**: 採用 → 実装手順がコスト見積もりに加わる
- [ ] **D-6. Opus 4.7 利用可否**: AccessDenied 解消済みか

---

## 6. 既存試算との関係

[lambda-error-report-mvp/PLAN.md §4](../../15/lambda-error-report-mvp/PLAN.md) の **$1.5/月** は前提が違うため、**本 DRAFT で破棄** する。

具体的に何が違うか:
- 旧: 100 件/月 × 入力 2K tok / 出力 0.5K tok (根拠なし)
- 新: **180 件/月** (上限) × 入力 T_in (測定) / 出力 T_out (測定) で **source embed と success logs を含む**

旧試算が桁を 1〜2 桁過小評価していた可能性が高い。本 DRAFT の式で再計算した値が「責任者判断の正本」になる。
