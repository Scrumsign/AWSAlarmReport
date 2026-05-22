# TODO: Phase A → B+C → E 実行タスク

> **位置づけ**: STEP を定義する **実行タスクリスト**。spec-driven-development の Tasks 段。
> 進捗管理が主目的。仕様変更やリスク追加は本ファイルではなく [SPEC.md](./SPEC.md) を更新する。
>
> **3 点セット**:
> - WHAT (要件・AC): [SPEC.md](./SPEC.md) ← **正準。全タスクの AC はこちらを参照**
> - HOW (設計判断): [PLAN.md](./PLAN.md)
> - STEP (本ファイル): 順序付き実行タスク + 進捗チェックボックス
>
> **参照補助**:
> - Phase D 移行時参考: [../test-harness-and-analyzer-split/PLAN.md](../test-harness-and-analyzer-split/PLAN.md)
> - Phase B 失敗モード F1-F10: [../prompt-improvement/DRAFT.md](../prompt-improvement/DRAFT.md)
> - Phase E 補助: [../cost-estimation/DRAFT.md](../cost-estimation/DRAFT.md)

---

## 影響ファイル一覧

| パス | 種別 | Phase | 由来 SPEC FR |
|---|---|---|---|
| [src/test.py](../../../../src/test.py) | NEW | A | FR-A-1, FR-A-2 |
| `src/fixtures/no_logs/{alarm.json,logs.jsonl,README.md}` | NEW | A | FR-A-3 |
| `src/fixtures/handler_value_error/{alarm.json,logs.jsonl,README.md}` | NEW (要マスキング) | A | FR-A-3, NFR-1 |
| [src/utils/prompt.py](../../../../src/utils/prompt.py) | MODIFY | B+C | FR-B-1〜FR-B-7, FR-C-3 |
| `src/context/hdw_ml_snapshot.md` | NEW (生成物) | C | FR-C-1 |
| `src/utils/hdw_ml_context.py` | NEW | C | FR-C-2 |
| `scripts/snapshot_hdw_ml.py` | NEW | C | FR-C-1 |
| `scripts/measure_t_system.py` | NEW | E | FR-E-1 |
| `scripts/measure_t_source.py` | NEW | E | FR-E-1 |
| `scripts/measure_t_logs.py` | NEW | E | FR-E-1 |
| [requirements.txt](../../../../requirements.txt) | MODIFY | E | NFR-6 |
| `docs/2026/05/18/mvp-followups-investigation/baselines/*.md` | NEW (生成物) | A/B+C | 改善ループ |
| `docs/2026/05/18/mvp-followups-investigation/results/cost-measurements-2026-05-19.md` | NEW (集計) | E | FR-E-4 |
| `docs/2026/05/18/mvp-followups-investigation/REPORT.md` | NEW (集約) | Step 4 | AC-G-2 |

import 方向: `test.py → utils/prompt.py → utils/hdw_ml_context.py`。`main.py` には触らない (NFR-2)。

---

## Pre-flight Checklist

着手前に **全部 ✓**:

- [ ] `aws sso login --profile hdw-test` 成功 → `aws sts get-caller-identity --profile hdw-test` で Account=088898720463 (P-2)
- [ ] env (PowerShell): `$env:AWS_PROFILE='hdw-test'`, `$env:AWS_REGION='ap-northeast-1'`, `$env:BEDROCK_MODEL_ID='jp.anthropic.claude-sonnet-4-6'`, `$env:BEDROCK_MAX_TOKENS='1024'`, `$env:PYTHONIOENCODING='utf-8'` (SPEC NFR-7)
- [ ] `Test-Path c:/Workspaces/HDW_ML` が True (P-1)
- [ ] `requirements.txt` に `anthropic` 追加 → `pip install -r requirements.txt` (NFR-6)
- [ ] Opus 4.7 AccessDenied 解消確認 ([../bedrock-opus-model-access-denied/](../bedrock-opus-model-access-denied/) 参照) — 未解消なら R-3 縮退策で進行
- [ ] `.gitignore` に `tmp/` が含まれる (NFR-5)

---

## 中間ファイル運用ルール

| ディレクトリ | 用途 | git |
|---|---|---|
| `tmp/phase-a/` | Phase A 試走中のメモ | 除外 |
| `tmp/phase-b-iters/` | Phase B 改善ループの diff / コストログ | 除外 |
| `tmp/phase-e/` | Phase E 測定スクリプトの中間出力 | 除外 |
| `tmp/raw/` | 本番ログ pull 結果 (マスキング前) | 除外 |
| `docs/.../baselines/` | Phase A/B baseline + iter 出力 (マスキング後) | コミット |
| `docs/.../results/` | Phase E 集計結果 | コミット |

**本番ログ昇格手順**: `tmp/raw/` に pull → 手動マスキング (NFR-1) → `src/fixtures/<case>/logs.jsonl` へコピー → `git status` 確認

---

## Step 1 — Phase A: テストハーネス構築 (所要 2h)

**SPEC**: FR-A-1, FR-A-2, FR-A-3, NFR-1, NFR-2
**Acceptance**: AC-A-1 〜 AC-A-6 ([SPEC.md §5.1](./SPEC.md))

### Task A-1: `src/test.py` 作成 (30m)
- [ ] PLAN.md §4 のコードを **そのまま** [src/test.py](../../../../src/test.py) に貼る (改変禁止 — FR-A-1 / NFR-2)
- [ ] import パス・関数名が既存 [src/utils/prompt.py](../../../../src/utils/prompt.py) と一致

### Task A-2: `src/fixtures/no_logs/` 3 点セット (10m)
- [ ] `alarm.json` を PLAN §5 通りに作成
- [ ] `logs.jsonl` を **空ファイル** で作成 (0 byte)
- [ ] `README.md` を PLAN §5 通りに作成

### Task A-3: `src/fixtures/handler_value_error/` 3 点セット + マスキング (20m)
- [ ] `alarm.json` を PLAN §5 通りに作成
- [ ] `logs.jsonl` を PLAN §5 から作成 + **以下 3 値をダミー置換** (NFR-1):
  - `function_arn` account 部: `920373030024` → `000000000000`
  - `function_request_id`: `e69ffb0e-b473-41a0-ac30-172a4ab91b74` → `00000000-0000-0000-0000-000000000001`
  - `xray_trace_id`: `1-69ef0328-78379ac7605571ed45e2ff86` → `1-00000000-000000000000000000000001`
- [ ] `README.md` を PLAN §5 通りに作成 (マスキング済み旨を 1 行追記)
- [ ] **検証**: `Select-String -Path src/fixtures/**/*.jsonl -Pattern '920373030024|e69ffb0e|69ef0328'` が 0 件

### Task A-4: 環境変数 + 認証確認 (15m)
- [ ] Pre-flight の env が現セッションにセット済み
- [ ] `aws sts get-caller-identity --profile hdw-test` で Account=088898720463
- [ ] `aws bedrock list-foundation-models --region ap-northeast-1 --profile hdw-test` で Sonnet 4.6 が見える

### Task A-5: 初回実行 + baseline 保存 (15m)
- [ ] `New-Item -ItemType Directory -Force docs/2026/05/18/mvp-followups-investigation/baselines`
- [ ] `python src/test.py 2>&1 | Tee-Object docs/2026/05/18/mvp-followups-investigation/baselines/2026-05-19-phase-a-baseline.md`
- [ ] exit code = 0

### Task A-6: 失敗時 buffer (30m)
- [ ] エラー出た場合のみ着手 (variable name typo / Insights 変換漏れ等)
- [ ] 修正後再走 → baseline 上書き

### Phase A 完了判定
- [ ] [SPEC.md §5.1](./SPEC.md) の AC-A-1 〜 AC-A-6 全て ✓
- [ ] [src/main.py](../../../../src/main.py) と [src/utils/prompt.py](../../../../src/utils/prompt.py) の `git diff` が空 (NFR-2)

→ baseline ファイルがコミット候補。

---

## Step 2 — Phase B+C: prompt 改修 + HDW_ML embed (所要 1-2 日)

**SPEC**: FR-B-1〜FR-B-7, FR-C-1〜FR-C-3, NFR-3, NFR-4
**Acceptance**: AC-B-F2/F5/F6/F7/F10 + AC-C-cache ([SPEC.md §5.2](./SPEC.md))

### 改善ループ運用 (各 Task 共通テンプレ)
各 Task 完了後、必ず以下を実施:
```powershell
$ts = Get-Date -Format "yyyyMMdd-HHmmss"
python src/test.py 2>&1 | Tee-Object "docs/2026/05/18/mvp-followups-investigation/baselines/$ts-iter-{n}-{打ち手名}.md"
# 直前 baseline と diff (差分を tmp/phase-b-iters/ に保存)
git diff --no-index baselines/<prev>.md baselines/<latest>.md > tmp/phase-b-iters/diff-{n}.txt
# 改善なし判定 → revert
git checkout src/utils/prompt.py
# usage を cost-log に追記 (NFR-4 予算管理)
Select-String -Path "baselines/$ts-*.md" -Pattern "outputTokens" >> tmp/phase-b-iters/cost-log.md
```

### Task B-0: baseline 確定 (5m)
- [ ] Phase A baseline (`2026-05-19-phase-a-baseline.md`) を「iter-0」として比較基準に固定
- [ ] 5 失敗モード (F2/F5/F6/F7/F10) について baseline の状態をメモ → `tmp/phase-b-iters/baseline-eval.md`

### Task B-1 (P7 → FR-B-1): `case_no_logs` 新設 (30m)
- [ ] [prompt.py](../../../../src/utils/prompt.py) に `render_prompt_case_no_logs()` を追加 (PLAN §9.1 文面)
- [ ] test.py 側 `_run_one` で fixture 名から case 切替 (no_logs → no_logs, 他 → generic)
- [ ] 再走 → **AC-B-F6 検証**: `no_logs` の `suggested_actions[0]` に「S3 確認」相当

### Task B-2 (P11 → FR-B-2): 哲学反転 (45m)
- [ ] [prompt.py:31-32](../../../../src/utils/prompt.py#L31-L32) 削除
- [ ] [prompt.py:42-56](../../../../src/utils/prompt.py#L42-L56) 削除
- [ ] 「監視対象 Lambda のソース該当箇所を file:line で引いてよい」追記
- [ ] 再走 → `suggested_actions` にコード修正提案 (例: `.get()` 切替) が許容

### Task B-3 (P4+P5 → FR-B-3): severity / confidence 境界 (30m)
- [ ] system に SPEC FR-B-3 の境界定義を追加
- [ ] 同 fixture を **3 回連投** → **AC-B-F5 検証**: severity / confidence 一定

### Task B-4 (P9 → FR-B-4): 時刻表記統一 (15m)
- [ ] SPEC FR-B-4 の文言を system に追記
- [ ] 再走 → diff で副作用なきこと確認

### Task C-1 (FR-C-1): `scripts/snapshot_hdw_ml.py` 新規 (45m)
- [ ] HDW_ML README + `src/**/*.py` を 1 ファイルに連結 (UTF-8 直書き)
- [ ] CLI: `python scripts/snapshot_hdw_ml.py --src c:/Workspaces/HDW_ML --out src/context/hdw_ml_snapshot.md`
- [ ] フォーマット: `## {relative path}\n\n\`\`\`python\n{content}\n\`\`\`\n\n` + 冒頭にディレクトリ tree (P1 兼ねる)
- [ ] 行数 / 推定トークン数を stderr に出力

### Task C-2 (FR-C-1): snapshot 生成 (10m)
- [ ] `python scripts/snapshot_hdw_ml.py` 実行 → `src/context/hdw_ml_snapshot.md` 生成
- [ ] サイズチェック: 想定 5,000〜8,000 tok 範囲内 (超過なら **R-2 縮退策** = Task B-6 へ)

### Task C-3 (FR-C-2): `src/utils/hdw_ml_context.py` 新規 (10m)
- [ ] モジュールロード時に snapshot を読み込み `HDW_ML_SOURCE_SNAPSHOT: str` を export

### Task C-4 (FR-B + FR-C-3): prompt.py に snapshot 連結 (15m)
- [ ] system prompt 末尾に `# 監視対象 Lambda のソースコード (HDW_ML)\n\n{HDW_ML_SOURCE_SNAPSHOT}` を連結
- [ ] 再走 → トークン数増を usage で確認 (T_in が +5,000〜8,000)

### Task C-5 (P1 → FR-C-1): ディレクトリ tree 追加 (15m)
- [ ] Task C-1 で snapshot 冒頭に含めた場合スキップ
- [ ] 別途必要なら system 先頭に `tree src/` 相当を追加

### Task C-6 (FR-C-3): `cachePoint` 配置 (30m)
- [ ] `test.py` の `client.converse(...)` 呼びで system を `[{"text": base}, {"cachePoint": {"type": "default"}}, {"text": snapshot}]` 構造に変更
- [ ] prompt.py 側で `render_prompt_system_base` と `render_prompt_system_source` を分離する選択肢も検討

### Task C-7 (FR-C-3): prompt caching 実機検証 (30m)
- [ ] 同 fixture を 2 回連続実行: `python src/test.py handler_value_error` × 2
- [ ] 1 回目: `cacheWriteInputTokens > 0`
- [ ] 2 回目: **AC-C-cache 検証** — `cacheReadInputTokens > 0`
- [ ] 動かない場合: **R-1 縮退策** = `T_cached=0` で Phase E 進行 + Open Q 記録

### Task B-5 (P6 → FR-B-5): `stack_trace` 構造化 (45m)
- [ ] [render_prompt_user](../../../../src/utils/prompt.py#L140) に `stack_trace` dict を読み取る分岐追加 (signature 後方互換維持)
- [ ] test.py の `_powertools_to_insights_row` で `stack_trace` を dict のまま渡せるよう調整
- [ ] 再走 → **AC-B-F2 検証 (1)**: root_cause の踏み込み深さ向上

### Task B-6 (P2): 関数シグネチャ抽出版 (任意, 30m, R-2 発動時のみ)
- [ ] C-2 snapshot が想定超過した場合のみ着手
- [ ] `scripts/snapshot_hdw_ml.py` に `--mode signatures` オプション追加 (def + docstring 1 行のみ抽出)
- [ ] P3 (全文 embed) と排他比較 → 効果差分を `tmp/phase-b-iters/p2-vs-p3.md` に記録

### Task B-7 (P10 → FR-B-6): 1-shot 出力例 (20m)
- [ ] system 末尾に出力例 1 件添付 (bias リスク考慮し 1 件のみ)
- [ ] 再走 → スキーマ準拠率を `parse_report` 例外発生回数で測定

### Task B-8 (P8 → FR-B-7): success_rows 比較指示 (文面のみ, 15m)
- [ ] system に「下に N 件の成功ログを参考として添付する場合がある」文面のみ仕込み
- [ ] **実データ供給は Phase D** (SPEC §2.2)

### Phase B+C 完了判定
- [ ] [SPEC.md §5.2](./SPEC.md) の AC-B-F2/F5/F6/F7/F10 + AC-C-cache 全て ✓
- [ ] caching 動かない場合 R-1 縮退策発動 + Open Q 記録
- [ ] **停止条件 (NFR-3)**: 上記全 ✓、または 2 巡で改善頭打ち → 機械的打ち切り
- [ ] 累積コストが NFR-4 予算 ($5/日) 内

---

## Step 3 — Phase E: コスト見積 (Step 2 と並走可, 所要 半日〜1 日)

**SPEC**: FR-E-1〜FR-E-4
**Acceptance**: AC-E-1 〜 AC-E-5 ([SPEC.md §5.3](./SPEC.md))
**前提**: Phase A 完了。E-2 のみ Phase C (Task C-2) 完了が前提。

### Task E-prep (NFR-6): anthropic SDK 追加 (15m)
- [ ] `requirements.txt` に `anthropic` 追記
- [ ] `pip install -r requirements.txt`
- [ ] `python -c "from anthropic import AnthropicBedrock; print(AnthropicBedrock(aws_region='ap-northeast-1'))"` 成功

### Task E-1 (C-1 → FR-E-1): T_system 測定 (30m)
- [ ] `scripts/measure_t_system.py` を PLAN §9.4 C-1 通り作成
- [ ] 実行: `python scripts/measure_t_system.py | Tee-Object tmp/phase-e/t_system.txt`
- [ ] 3 ケース (generic / timeout / dependency) のトークン数記録

### Task E-2 (C-2 → FR-E-1): T_source 測定 (15m, Phase C 完了後)
- [ ] `scripts/measure_t_source.py` を PLAN §9.4 C-2 通り作成
- [ ] 実行: `python scripts/measure_t_source.py | Tee-Object tmp/phase-e/t_source.txt`
- [ ] HDW_ML 全文の token 数記録

### Task E-3 (C-3 → FR-E-1): T_error_logs 線形係数 (45m)
- [ ] `scripts/measure_t_logs.py` を PLAN §9.4 C-3 通り作成
- [ ] N=1, 10, 50 で測定 → 線形近似 `T = a + b × N` の `a`, `b` を算出
- [ ] 結果を `tmp/phase-e/t_error_logs.md` に保存

### Task E-4 (C-4): 本番 sakura 成功ログ取得 + T_success_logs (45m)
- [ ] PLAN §9.4 末尾 CLI で `tmp/raw/sakura-success-logs.jsonl` 取得 (limit 50, 直近 7 日)
- [ ] マスキング (NFR-1) 適用後 `tmp/phase-e/sakura-success.jsonl`
- [ ] `scripts/measure_t_logs.py` を success ログにも適用 → 線形係数 `c`, `d`

### Task E-5 (C-5): T_out 平均 / 最大 (15m)
- [ ] Step 2 で蓄積した `baselines/*.md` から usage を集計:
  ```powershell
  Select-String -Path "docs/2026/05/18/mvp-followups-investigation/baselines/*.md" -Pattern "outputTokens"
  ```
- [ ] 平均 / 最大を `tmp/phase-e/t_out.md` に記録
- [ ] `max_tokens=1024` 頭打ち有無確認

### Task E-6 (C-6): モデル単価 web 確認 (30m)
- [ ] AWS Bedrock pricing: <https://aws.amazon.com/bedrock/pricing/>
- [ ] Anthropic pricing: <https://www.anthropic.com/pricing>
- [ ] Bedrock model ID 一覧: <https://docs.aws.amazon.com/bedrock/latest/userguide/models-supported.html>
- [ ] 取得日 **2026-05-19** / region **ap-northeast-1** / `jp.*` vs `global.*` 単価差確認
- [ ] 結果を `tmp/phase-e/pricing.md` に表で保存 (Haiku 4.5 / Sonnet 4.6 / Opus 4.7 × P_in / P_out / cache read / cache write)

### Task E-7 (C-7): prompt caching 実機検証
- [ ] **Step 2 Task C-7 と兼任**。同じ結果を使う

### Task E-8 (C-8): N_calls 想定値 (30m)
- [ ] **方法 A**: Alarm history → `describe-alarm-history` で月別集計
- [ ] **方法 B (fallback)**: `get-metric-statistics` で Lambda Errors metric 日次集計
- [ ] 結果を `tmp/phase-e/n_calls.md` に楽観 (最小月) / 想定 (中央値) / 悲観 (180 上限)

### Task E-9 (C-9): その他 AWS コスト (45m)
- [ ] Lambda: REPORT 行から Billed Duration 平均 → 月額計算
- [ ] Insights: 5 回測定の bytesScanned 平均 → 月額計算 (× 2 クエリ × N_calls)
- [ ] ECR: image size → `size_bytes / 10^9 × $0.10`
- [ ] CW Alarm: $0.10/月 固定
- [ ] Data transfer: Bedrock 同一 region $0, Discord webhook $0 と判定根拠記録
- [ ] 結果を `tmp/phase-e/aws-other.md` にまとめ

### Task E-10 (FR-E-4): 集計 (30m)
- [ ] `docs/2026/05/18/mvp-followups-investigation/results/cost-measurements-2026-05-19.md` を PLAN §9.4 末尾テンプレで作成
- [ ] 全 `tmp/phase-e/*.md` の確定値をテンプレに転記

### Task E-11 (FR-E-4): 月額レンジ表 (30m)
- [ ] SPEC FR-E-2 の計算式を適用
- [ ] 3 モデル × 3 シナリオ × cache 有無 = 18 セル
- [ ] 「1M tokens = アラート N 回」「想定運用で 1M 到達まで X ヶ月」算出
- [ ] 推奨モデル / 棄却モデルを理由付きで結論 (R-3 発動時は Opus 「測定不能」明記)

### Phase E 完了判定
- [ ] [SPEC.md §5.3](./SPEC.md) の AC-E-1 〜 AC-E-5 全て ✓

---

## Step 4 — 最終成果物まとめ

### Task R-1 (AC-G-2): `REPORT.md` 集約 (45m)
- [ ] `docs/2026/05/18/mvp-followups-investigation/REPORT.md` 新規作成
- [ ] 1 枚に Phase A 結果 / Phase B+C 結論 / Phase E 月額レンジ表を凝縮
- [ ] PLAN.md §9.5 横断オープン項目への回答を追記 (AC-G-3)

### Task R-2: PLAN.md / SPEC.md からのリンク (5m)
- [ ] PLAN.md 冒頭または末尾に「実行結果: [REPORT.md](./REPORT.md)」追記
- [ ] SPEC.md §0 改定履歴は実装で更新があった場合のみ追記

### Task R-3 (AC-G-4, AC-G-5): コミット前最終チェック (15m)
- [ ] `git status` で新規/変更ファイルが「影響ファイル一覧」と一致
- [ ] `tmp/` 配下が .gitignore で除外されている
- [ ] `Select-String -Path src/fixtures/**/*.jsonl -Pattern '920373030024|e69ffb0e|69ef0328'` で 0 件 (NFR-1)
- [ ] commit メッセージ案: `Phase A/B+C/E 実行: テストハーネス + prompt P1-P11 + コスト実測`

---

## 全体完了判定

[SPEC.md §5.4](./SPEC.md) の AC-G-1 〜 AC-G-5 を再確認:
- [ ] **AC-G-1**: 各 Phase の AC を全て満たす
- [ ] **AC-G-2**: `REPORT.md` が 3 Phase の結論を 1 枚に集約
- [ ] **AC-G-3**: PLAN.md §9.5 横断オープン項目への回答が REPORT.md に追記
- [ ] **AC-G-4**: `tmp/` 配下が誤コミットされていない
- [ ] **AC-G-5**: マスキング漏れ検査が 0 件

---

## 着手順推奨

1. **Pre-flight Checklist** (全 ✓)
2. **Step 1 Phase A**: A-1 → A-2 → A-3 → A-4 → A-5 → (A-6 は失敗時のみ)
3. **Step 2 Phase B+C**: B-0 → B-1 → B-2 → B-3 → B-4 → C-1 → C-2 → C-3 → C-4 → C-5 → C-6 → C-7 → B-5 → (B-6 は R-2 発動時のみ) → B-7 → B-8
4. **Step 3 Phase E** (Step 2 と並走可): E-prep → E-1 → E-3 → E-4 → E-5 → E-6 → E-8 → E-9 → E-2 (Phase C 完了後) → E-7 (Step 2 兼任) → E-10 → E-11
5. **Step 4**: R-1 → R-2 → R-3
6. **全体完了判定** 最終チェック

リスク発動時の対応は [SPEC.md §6](./SPEC.md) を参照。仕様変更が必要になったら [SPEC.md §7](./SPEC.md) のルールに従って先に SPEC を更新する。
