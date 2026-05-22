# PROBLEM: LLM レポーティングの現状課題 (2026-05-19)

> **スコープ**: 本ファイルは **LLM 呼び出し → Discord 投稿用 JSON 生成** の領域に限定。
> Lambda インフラ / Discord 投稿層 / CloudWatch Alarm 連携の課題は対象外。
>
> **入力ソース**:
> - [results/cost-rough-estimate-2026-05-19.md](./results/cost-rough-estimate-2026-05-19.md) v1.5
> - [samples/{haiku,sonnet,opus}-*/](./samples/) (3 モデル × 2 fixture)
> - [SPEC.md](./SPEC.md) v1.5

---

## 1. モデル選定が確定できない

3 モデル稼働するが、**選択根拠が出力 1 ケース比較に依拠** していて意思決定材料が薄い。

| 観点 | Haiku 4.5 | Sonnet 4.6 | Opus 4.7 |
|---|---|---|---|
| 想定 30 calls/月 | $0.37 | $0.88 | $4.53 |
| 悲観 180 calls/月 | $2.24 | $5.31 | $27.20 |
| handler_value_error output | **1001 tok (max=1024 寸前)** | 477 tok | 373 tok |
| 推論深さ | 浅い (要冗長) | 中程度 | 深い (retry 認識 + NG file 関連付け) |

**問題点**:
- 品質差が「文章の踏み込み深さ」という主観評価でしか測れていない
- blind eval (LLM 名隠して人手スコア) を取っていないので bias 排除できない
- handler_value_error 1 ケースの結果で結論を出すには標本数不足

---

## 2. コストレンジが広く、判断不能ゾーンがある

`楽観 / 想定 / 悲観` 幅 = **18 倍** (10 〜 180 calls)、モデル幅 = **20 倍** (Haiku 〜 Opus)。組み合わせで月額が $0.37 〜 $46 まで散らばる。

| 不確実性 | 月額への影響 |
|---|---|
| N_calls 想定 vs 悲観 | 6 倍 (30 → 180) |
| モデル選択 Haiku vs Opus | 12 倍 |
| prompt caching 動作可否 | 1.8 倍 (Opus 悲観 $25 → $46) |
| `jp.*` profile 実単価 (未確認) | 1.2 〜 1.5 倍 |
| HDW_ML snapshot サイズ超過 | 1.3 倍想定 |

→ **判断のための定数 (N_calls, caching, 実単価) が固まらないと採算ラインを引けない**。

---

## 3. prompt caching 未検証 = Opus 採用判断が止まる

SPEC R-1 のまま:

- `jp.anthropic.claude-opus-4-7` で `cachePoint` ブロックが動くか実機検証が必要
- 動かない場合 Opus 悲観が $25 → $46/月 (Claude Pro 2 ヶ月分) に張り付く
- HDW_ML embed (Phase C) を入れるとさらに膨らむ

**現状**: 全 3 モデルの usage で `cacheReadInputTokens: 0`。caching 経路は **1 回も発火していない**。

---

## 4. 入力トークン量がログ件数で線形拡大する制御不能性

fixture 拡張 (1 件 → 85 件) で input が **5.9 倍** に膨らんだ実績。

| 状況 | input tok | コスト影響 |
|---|---|---|
| 1-log fixture | 1,395 | baseline |
| 85-log fixture (本番 30min 全件) | 7,441-8,210 | +5.9 倍 |
| + HDW_ML embed (7000) | 14,441-15,210 | +10 倍 |
| 仮に 200-log alarm 発火 | ~17,000 | +12 倍 |

**問題点**:
- Insights `limit 50` がガードレールだが、log 1 行が長い (powertools 構造化) と limit 内でもトークンが膨張
- max_tokens=1024 で output 切詰めが Haiku で既に発生 → 取捨選択能力に依存
- 「入力ログ X 件のとき月額 Y」の予測式が立てられていない

---

## 5. fixture が 1 シナリオに特化 → 汎用性評価不能

現状の fixture:
- `no_logs` (起動形跡なし)
- `handler_value_error` (sakura ZIP の ValueError、3 retry、+ INIT timeout)

**カバーできていないパターン**:
- KeyError / AttributeError / TypeError 等 別 exception
- 外部依存障害 (S3 GetObject NoSuchKey, DynamoDB throttle 等)
- タイムアウト中の途中状態
- 複数 ship 同時失敗
- 部分成功 (5 ship 中 1 失敗)

→ prompt の `case_lambda_failure` 文面が (b1)-(b4) を網羅指示しているが、**実シナリオで検証していない指示**。

---

## 6. 出力品質に関する観察済みの個別問題

### 6.1 Haiku 4.5 の output 頭打ち
- handler_value_error で output = 1001/1024 tok (max 寸前)
- 確実に切れている場合 JSON schema 逸脱 → `main.py:299` の fallback ([_post_minimal_embed](../../../../src/main.py#L191)) 発動
- max_tokens 引き上げが現実解だが、コスト・遅延への影響未測定

### 6.2 Opus 4.7 でも関連事象抽出に取りこぼし
- handler_value_error fixture には **冒頭で `INIT_REPORT Status: timeout`** が含まれる (cold start 10s 上限超過)
- Opus 4.7 の root_cause / suggested_actions ともに **この timeout に触れていない**
- ValueError の連鎖だけ取り上げて、その前段の cold start init 失敗を素通り

### 6.3 ヒント節と case 分離の検証不足
- prompt.py の `case_no_logs` で S3 確認を明示、`case_lambda_failure` で 4 分類 (b1-b4) を提示
- これが LLM 出力に与える誘導効果が **1 ケースずつしか検証されていない** (F10)

### 6.4 JSON schema 厳格性の検証不足
- 3 モデルとも今回 JSON 形式は守った
- ただし日本語混入率 / 改行コード / コードブロック装飾 (```json) の有無 等は parse 戦略次第で fragility
- `main.py:294` の `json.loads(report_text)` は単純パース → ``` 装飾だと失敗

---

## 7. 運用判断のための未収集データ

LLM レポーティング層の評価に必要だが未取得:

| データ | 取得手段 | 影響 |
|---|---|---|
| **N_calls 実測** (過去 3 ヶ月の Alarm history or Lambda Errors metric) | TODO E-8 (CloudWatch CLI) | 想定値 30 の妥当性確認 |
| **prompt caching 実機動作** (cacheReadInputTokens > 0) | TODO C-7 (test.py × 2 回連投) | Opus 4.7 採用判断 |
| **Bedrock 応答遅延** (1 call にかかる実時間) | test.py に計時追加 | UX 影響 (alarm 発火から Discord 通知までの体感) |
| **JSON schema 逸脱率** | test.py を 3 モデル × N 回繰り返し parse_report 例外発生数集計 | fallback 発動頻度の見積もり |
| **複数 fixture での品質安定性** | 新 fixture 追加 (KeyError / timeout / multi-ship 等) | case_lambda_failure 文面の妥当性検証 |

---

## 8. 現状の総合判定 (LLM レポーティング層のみ)

**書ける部分**:
- 想定運用 (30 calls/月) なら **どのモデルもコスト的に無視できる**
- Opus 4.7 出力品質は「人間が読める一次調査メモ」レベルに到達 (1 ケース確認)
- prompt は SPEC v1.4 で 2-pattern (`no_logs` / `lambda_failure`) に整理済み、ドメイン文脈も system に格上げ済み

**書けない / 言い切れない部分**:
- 「Sonnet で十分」か「Opus が必要」かの **品質差金額換算** ($3.5/月差) が比較データ不足で出せない
- prompt caching が動かないと Opus 悲観 $46/月 = **採算ラインが微妙**
- 多シナリオでの汎用性 (KeyError / timeout 等) が未検証で **本番採用後の品質保証ができない**
- Haiku の output 切詰めリスクが定量化されていない

---

## 9. 次に潰すべき優先順位 (LLM レポーティング層に限る)

1. **C-7 (prompt caching 実機検証)** — Opus 採用判断のブロッカー
2. **複数 fixture 追加** (KeyError / dependency / timeout 各 1 ケース) — 汎用性確認
3. **3 モデル × 同 fixture を 3 回連投** — F5 (severity/confidence 揺らぎ) の定量化
4. **E-8 (N_calls 実測)** — 想定 30 の根拠固め
5. **遅延計測** — test.py に `time.perf_counter` 追加して 3 モデル比較
6. **JSON schema 逸脱率測定** — 上記 3 回連投の副産物として集計可能

これらが揃った段階で REPORT.md (TODO §10 Step 4) を書ける。
