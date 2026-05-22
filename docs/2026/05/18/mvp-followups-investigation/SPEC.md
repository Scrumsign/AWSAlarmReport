# SPEC: MVP フォローアップ Phase A / B+C / E

> **位置づけ**: WHAT を定義する **仕様書**。本ファイルはバージョン管理対象で、変更時は必ず git history に意図を残す (commit message に "SPEC change: <理由>")。
>
> **対応文書**:
> - HOW (設計判断・採用根拠): [PLAN.md](./PLAN.md)
> - STEP (実行タスク・進捗): [TODO.md](./TODO.md)
>
> **方法論**: spec-driven-development。SPEC.md を最初に固め、PLAN.md / TODO.md は SPEC.md を満たすための手段。

---

## 0. 改定履歴

| Version | 日付 | 変更内容 | 起案者 |
|---|---|---|---|
| v1.0 | 2026-05-19 | 初版。PLAN.md §3-§9 から要件部分を抽出 | t.kimura |
| v1.1 | 2026-05-19 | R-3 (Opus 4.7 AccessDenied 懸念) を解消。`aws bedrock list-foundation-models` で `anthropic.claude-opus-4-7` がアクセス可能と確認。「測定不能」縮退策は不要 | t.kimura |
| v1.2 | 2026-05-19 | NFR-1 マスキング対象に `alarm.json` の `alarmArn` (account ID 部分) を追加。`alarmArn` も本番アカウント ID を含むため一貫性のため拡張 | t.kimura |
| v1.3 | 2026-05-19 | NFR-7 に `PYTHONIOENCODING=utf-8` 強制を追加。Phase A baseline 取得時に Windows ローカルで stdout cp932 → em-dash で UnicodeEncodeError が発生したため、ローカル/Lambda 両方で防御的に UTF-8 を強制。deploy/config{,−prod}.yml + .github/workflows/deploy.yml に反映済み | t.kimura |
| v1.4 | 2026-05-19 | **ドメイン文脈を SPEC に格上げ**。新セクション §1.1「監視対象 Lambda の運用前提」追加 (4 時間トリガー / エラー判定 = success ログなし / 2 パターン分類)。FR-B-1 を拡張し case テンプレを `no_logs` + `lambda_failure` の **2 本に再編成** (旧 generic / timeout / dependency は削除)。FR-B-2 (P11 コード言及 OK) と統合実施。main.py は backward-compat alias で吸収し Phase D まで不変 | t.kimura |
| v1.5 | 2026-05-19 | **fixture 採取規約を明文化** (新 FR-A-4)。alarm 発火前 30min の全ログ (filter なし) を本番アカウント (hanshin-t.kimura / 920373030024) から pull、NFR-1 v1.2 マスキング適用。main.py の時間窓を 5+1=6min → 30+0=30min に拡張 (deploy/config{,-prod}.yml 同期)。fixture と production を同じ窓で動作させ、LLM 評価と本番出力の意味的一致を担保。これに伴い cost 試算を実測ベースで再計算 | t.kimura |

---

## 1. 背景と目的

MVP ([../../15/lambda-error-report-mvp/PLAN.md](../../15/lambda-error-report-mvp/PLAN.md)) が一通り動いた前提で、次に着手する 3 テーマを実装する:

1. **テストハーネス構築 (Phase A)** — prompt 改善ループの土台。fixture ログを既存 prompt に流して Bedrock 出力を目視できる状態にする
2. **prompt 改善 + HDW_ML embed (Phase B+C)** — 失敗モードを潰し、HDW_ML 全文 context で具体性を上げる
3. **コスト見積 (Phase E)** — 月額レンジを実測ベースで出し責任者判断材料を作る

**ビジネスインパクト**: 現状 prompt の主観評価「微妙」を計測可能な改善に転換し、本番採用可否 (Phase D 着手判断) のための定量データを揃える。

### 1.1 監視対象 Lambda の運用前提 (v1.4 で追加)

prompt の精度はこのドメイン文脈を LLM に正しく伝えられるかに直結する。以下は **不変の前提** として system prompt に組み込む:

- **トリガー**: HDW_Backend_Processor_0001 は **4 時間に 1 回**、特定 S3 バケットへの ZIP アップロード (例 `inputFiles/<ship_name>-<ship_timestamp>.zip`) を契機に起動する
- **1 起動 = 1 ファイル処理**: ship_name (船名) + ship_timestamp で識別される単一 ZIP を入力とする
- **エラー判定基準**: 直近時間窓 (CloudWatch Alarm 発火時刻 ±N 分) 内に `status="success"` のログが **1 件も存在しない** こと
- **したがってエラーの根本パターンは 2 つに大別される**:
  - **(A) 起動形跡なし (`no_logs`)**: error / success どちらのログもない。S3 アップロード自体がなく Lambda が起動していない可能性が最有力。上流のアップロード処理失敗 / 船側送信遅延 / ログ配信遅延が候補
  - **(B) 起動して失敗 (`lambda_failure`)**: status="error" のログが存在し exception / stack_trace が取れる。コードバグ / 入力データ異常 / 設定欠落 / 外部依存障害のいずれか
- **Out of scope (本 SPEC では考慮しない第 3 パターン)**: cold start 失敗で powertools logger が動かず error ログも success ログも出ないケース。理論上はパターン (A) と区別不能なため、運用で頻発する場合のみ別途検討

---

## 2. スコープ

### 2.1 In Scope

| Phase | 対象 |
|---|---|
| A | `src/test.py` 新規, `src/fixtures/{no_logs,handler_value_error}/` 新規 |
| B+C | `src/utils/prompt.py` 改修 (P1〜P11 全部), HDW_ML snapshot 生成, prompt caching 検証 |
| E | コスト測定スクリプト群, `results/cost-measurements-2026-05-19.md` 生成, 月額レンジ表 |

### 2.2 Out of Scope (Phase D 委譲)

PLAN.md §2 で明示済み。本 SPEC では **要件として要求しない**:

- `src/analyzer.py` 抽出 / `LogRow` dataclass 導入
- `src/main.py` 大改修 (INSIGHTS_QUERY 2 本化, Bedrock invoke クロージャ化)
- 空ログ早期 return ([main.py:267-279](../../../../src/main.py#L267-L279)) の廃止
- `success_rows` (sakura 成功ログ context) の本番経路供給 (文面準備のみ可)
- 本番 Lambda への deploy 反映
- pytest / snapshot / schema 自動検証 / CI 統合

---

## 3. 機能要件

### 3.1 Phase A: テストハーネス

#### FR-A-1: fixture から prompt を生成し Bedrock を呼ぶ単一スクリプト
- **入力**: `src/fixtures/<case>/` ディレクトリ (alarm.json + logs.jsonl + README.md)
- **処理**: 既存 [src/utils/prompt.py](../../../../src/utils/prompt.py) の `render_prompt_system_base` / `render_prompt_case_generic` / `render_prompt_user` を **無改修で** 呼び出し、Bedrock Converse API を叩く
- **出力**: stdout に system prompt / user prompt / LLM raw output / usage を順に表示
- **CLI**: `python src/test.py` (全 fixture 流し) / `python src/test.py <case_name>` (1 件のみ)

#### FR-A-2: fixture フォーマット
- 各ケースは `alarm.json` + `logs.jsonl` (powertools 生 JSON 1 行 1 ログ) + `README.md` (シナリオ + LLM 期待回答) の 3 点セット
- `logs.jsonl` の powertools dict → Insights `[{field, value}]` 形式への変換を test.py 側で実施

#### FR-A-3: 初期 fixture 2 件
- **Case 1 `no_logs`**: 空ログ (S3 ファイル未アップ → Lambda 未起動シナリオ)
- **Case 2 `handler_value_error`**: 本番 2026-04-27 06:37 alarm の前 30 分の全ログ (v1.5 で拡張)
  - 旧版 (v1.0-v1.4): `ValueError: general_data is None` 単発 1 件
  - 新版 (v1.5): alarm 発火時刻 (06:37 UTC) の **前 30 分** の全ログ (success / info / error / cold_start 含む)
  - **マスキング必須フィールド**: NFR-1 v1.2 規約 (alarmArn / function_arn の account ID, function_request_id, xray_trace_id) を全行に適用

#### FR-A-4: fixture 採取規約 (v1.5 で新設)
- **ソース**: production アカウント (hanshin-t.kimura / 920373030024 / ap-northeast-1)
- **時間窓**: alarm 発火時刻 **の前 30 min** (過去 30min 〜 発火時刻)
- **フィルタ**: なし (全ログ — success / info / error / cold_start 等含む)
- **取得手段**: `aws logs start-query` + `get-query-results` (PLAN §9.1.追加 fixture CLI 参照)
- **マスキング**: NFR-1 v1.2 規約を **追加・変更なく** そのまま適用
- **1 fixture = 1 alarm event 単位**。複数 alarm を混ぜない
- **生ログの保管場所**: `tmp/raw/` (`.gitignore` で除外)。マスキング後のみ `src/fixtures/` にコミット

### 3.2 Phase B+C: prompt 改修 + HDW_ML embed

#### FR-B-1: case テンプレを 2 本に再編成 (v1.4)
- 旧 `render_prompt_case_generic` / `render_prompt_case_timeout` / `render_prompt_case_dependency` を削除
- 新規 `render_prompt_case_no_logs()`: パターン (A) 起動形跡なし用。S3 アップロード確認 / 上流処理失敗 / ログ配信遅延を仮説候補に
- 新規 `render_prompt_case_lambda_failure()`: パターン (B) 起動 + 失敗用。コードバグ / 入力データ異常 / 設定欠落 / 外部依存障害を切り分け
- 主要 case 判定: 呼び出し側で **log_rows が空かどうか** で機械的に分岐 (LLM に判定させない)
- main.py の `render_prompt_case_generic` 呼び出しは **backward-compat alias** で吸収 (Phase D で除去)

#### FR-B-2: 哲学反転 (P11, v1.4 で FR-B-1 と統合実施)
- 「コードベース固有の根本原因は知らない前提」削除
- 「suggested_actions コード言及禁止」削除
- 代わりに「監視対象 Lambda のソース該当箇所を file:line で引いてよい」を明記
- HDW_Backend_Processor_0001 単一 Lambda が対象であることを system prompt 冒頭で明示

#### FR-B-3: severity / confidence 境界明文化 (P4 + P5)
- severity: LOW=単発自己回復, MEDIUM=連続発生/データ欠落, HIGH=全件失敗/データ破損
- confidence: low=<50%, medium=50-80%, high=>80%

#### FR-B-4: 時刻表記統一指示 (P9)
- alarm = ISO 8601, log = powertools `YYYY-MM-DD HH:MM:SS,SSS+ZZZZ`, 両者は同一時刻系

#### FR-B-5: stack_trace 構造化 (P6)
- `render_prompt_user` に stack_trace dict 受けを追加 (signature 後方互換維持)

#### FR-B-6: 1-shot 出力例 (P10)
- system 末尾に出力例 1 件を添付 (bias リスク考慮し 1 件のみ)

#### FR-B-7: success_rows 比較指示の文面のみ (P8, 実データ供給は Phase D)
- system に「下に N 件の成功ログを参考として添付する場合がある」文面を仕込み

#### FR-C-1: HDW_ML snapshot 生成 (P1 + P3)
- `scripts/snapshot_hdw_ml.py` で HDW_ML README + `src/**/*.py` を 1 ファイルに連結
- 出力先: `src/context/hdw_ml_snapshot.md`
- snapshot 内にディレクトリ tree 相当 (path 一覧) を含めて P1 を兼ねる
- snapshot サイズが想定 (8k tok) を大幅超過時は P2 (シグネチャ + docstring 抽出版) へ縮退

#### FR-C-2: HDW_ML context モジュール
- `src/utils/hdw_ml_context.py` がモジュールロード時に snapshot を読み込み `HDW_ML_SOURCE_SNAPSHOT: str` を export

#### FR-C-3: prompt caching 適用
- Bedrock Converse API の system 配列に `cachePoint` ブロックを配置
- snapshot 部分を cache 対象とし、再呼び出し時に `cacheReadInputTokens > 0` が観測されること

### 3.3 Phase E: コスト見積

#### FR-E-1: トークン測定スクリプト群
- `scripts/measure_t_system.py`: system prompt のトークン数 (3 ケース generic/timeout/dependency)
- `scripts/measure_t_source.py`: HDW_ML snapshot のトークン数
- `scripts/measure_t_logs.py`: ログ件数 N に対する user prompt トークン線形係数 (N=1, 10, 50)

#### FR-E-2: コスト計算式
```
コスト/月 = N_calls × ( T_in   × P_in (model)
                      + T_out  × P_out(model)
                      - T_cached × P_in(model) × (1 - cache_discount) )
```
ここで:
- `T_in = T_system + T_source + T_alarm_meta + T_error_logs + T_success_logs`
- キャッシュ対象 = `T_system + T_source`
- `T_success_logs` の N = 50 (sakura 船別)

#### FR-E-3: 比較対象モデルとシナリオ
- モデル: Haiku 4.5 / Sonnet 4.6 / Opus 4.7 (Opus は AccessDenied 解消が前提)
- N_calls: 楽観 10 / 想定 30 / 悲観 180 (= 30 日 × 4 時間おき理論上限)
- cache 有無の両方を提示

#### FR-E-4: 成果物
- `results/cost-measurements-2026-05-19.md`: 全測定値 (T_system, T_source, T_*_logs, T_out, 単価, N_calls, AWS 他コスト)
- 月額レンジ表: 3 モデル × 3 シナリオ × cache 有無 = 18 セル
- 「1M tokens = アラート N 回」「想定運用で 1M tokens 到達まで X ヶ月」
- 推奨モデル / 棄却モデル + 理由

---

## 4. 非機能要件

### NFR-1: マスキング
- 本番ログを fixture 化する際、以下フィールドをダミー値に置換:
  - `logs.jsonl`: `function_arn` (account ID), `function_request_id`, `xray_trace_id`
  - `alarm.json`: `alarmArn` (account ID 部分) — v1.2 で追加
- ダミー値の規約:
  - account ID `920373030024` → `000000000000`
  - request_id (UUID) → `00000000-0000-0000-0000-000000000001`
  - xray trace_id `1-{8hex}-{24hex}` → `1-00000000-000000000000000000000001`
- コミット前検証: `Select-String -Path src/fixtures/**/* -Pattern '920373030024|<元 request_id>|<元 trace_id>'` が 0 件

### NFR-2: 既存コード不可侵 (Phase A)
- Phase A 完了時点で `src/main.py` および `src/utils/prompt.py` の **差分はゼロ**
- Phase B 以降で初めて prompt.py を改修する

### NFR-3: 改善ループの停止条件 (Phase B+C)
- 5 失敗モード (F2/F5/F6/F7/F10) がすべて目視で許容範囲
- または 2 巡しても改善頭打ちで機械的打ち切り
- 判定は人手のみ。snapshot / schema 自動検証は導入しない

### NFR-4: 予算ガード
- Phase B 改善ループの Bedrock 実呼び合計 1 巡 ≒ $0.5 想定
- 累積 usage を `tmp/phase-b-iters/cost-log.md` で追跡、$5/日 上限目安

### NFR-5: バージョン管理範囲
- コミット対象: `src/test.py`, `src/fixtures/`, `src/utils/prompt.py`, `src/context/hdw_ml_snapshot.md`, `src/utils/hdw_ml_context.py`, `scripts/*.py`, `requirements.txt`, `docs/.../baselines/`, `docs/.../results/`, `SPEC.md`, `TODO.md` 更新
- 除外: `tmp/` 配下 (`.gitignore` で担保)

### NFR-6: 依存追加
- `requirements.txt` に `anthropic` 追加 (Phase E の `count_tokens` 用)

### NFR-7: 認証 / 環境
- 全 Phase で `AWS_PROFILE=hdw-test` (Account 088898720463) を使用
- **fixture 採取時のみ** `AWS_PROFILE=hanshin-t.kimura` (Account 920373030024 / production) を使用 (FR-A-4)
- region: `ap-northeast-1`
- Bedrock model: `jp.anthropic.claude-sonnet-4-6` (Phase A baseline), 他モデルは Phase E で切替
- **stdout/stderr エンコーディング**: `PYTHONIOENCODING=utf-8` を強制 (v1.3 追加)
  - ローカル試走時: 実行コマンドで `$env:PYTHONIOENCODING='utf-8'` を設定
  - Lambda runtime: `deploy/config{,-prod}.yml` の `python_io_encoding: utf-8` キー + `.github/workflows/deploy.yml` の `PYTHONIOENCODING` mapping で投入
- **時間窓 (CLOUDWATCH_LOGS_WINDOW_BEFORE_MIN / _AFTER_MIN)** (v1.5 追加):
  - v1.0-v1.4: 5 + 1 = 6 min
  - v1.5: **30 + 0 = 30 min** (fixture と production が同じ窓で動作することを保証)
  - 設定ファイル: `deploy/config{,-prod}.yml`

---

## 5. Acceptance Criteria

### 5.1 Phase A 完了基準 (PLAN.md §7 準拠)
- AC-A-1: 全 2 fixture (no_logs, handler_value_error) が順に処理される
- AC-A-2: 各 fixture で `--- system prompt ---` / `--- user prompt ---` / `--- LLM raw output ---` が出る
- AC-A-3: `--- LLM raw output ---` が JSON parse 可能 (出力スキーマ準拠)
- AC-A-4: `usage` (inputTokens / outputTokens) が表示される
- AC-A-5: `no_logs` ケース: user prompt に `# Error logs (0件)` が出る
- AC-A-6: `handler_value_error` ケース: user prompt の trace 部分に `ValueError: general_data is None` が見える

### 5.2 Phase B+C 完了基準
- AC-B-F2: handler_value_error で root_cause が `main.py:62` レベルまで具体化 (HDW_ML embed 後)
- AC-B-F5: 3 回連投で severity / confidence が一貫 (B-3 完了後)
- AC-B-F6: no_logs で `suggested_actions[0]` に S3 確認言及 (B-1 完了後)
- AC-B-F7: generic 固定の弱点が `tmp/phase-b-iters/f7-notes.md` に文書化
- AC-B-F10: case_no_logs 反映後のヒント節が誤誘導していない
- AC-C-cache: `cacheReadInputTokens > 0` を 2 回目連投で確認 (動かない場合 R1 縮退策発動)

### 5.3 Phase E 完了基準
- AC-E-1: `T_system` (3 ケース) / `T_source` / `a, b` (error) / `c, d` (success) / `T_out_avg, T_out_max` が確定値で記録
- AC-E-2: 3 モデル × 3 シナリオ × cache 有無 = 18 セルの月額表が完成
- AC-E-3: 推奨モデル / 棄却モデルが理由付きで明記
- AC-E-4: 「1M tokens = アラート N 回」「1M 到達まで X ヶ月」が算出される
- AC-E-5: Opus 4.7 AccessDenied 未解消の場合は「測定不能」と明記し Haiku/Sonnet のみで結論

### 5.4 全体完了基準
- AC-G-1: 各 Phase の AC を全て満たす
- AC-G-2: `REPORT.md` が 3 Phase の結論を 1 枚に集約
- AC-G-3: PLAN.md §9.5 横断オープン項目への回答が REPORT.md に追記
- AC-G-4: `tmp/` 配下が誤コミットされていない
- AC-G-5: マスキング漏れ検査 (NFR-1) が 0 件

---

## 6. リスク / 前提

| ID | リスク or 前提 | 対応 |
|---|---|---|
| R-1 | `cachePoint` が `jp.*` で動かない | `T_cached=0` で再計算 + `global.*` prefix 検討 + Open Q 記録 |
| R-2 | HDW_ML snapshot サイズが想定 8k tok を大幅超過 | P2 (シグネチャ抽出版) へ縮退 |
| R-3 | ~~Opus 4.7 AccessDenied 未解消~~ → **v1.1 で解消済み** (2026-05-19 確認, Bedrock list-foundation-models で `anthropic.claude-opus-4-7` 利用可) | 縮退策不要。Phase E は Opus 4.7 を含めて測定 |
| R-4 | 改善判定の主観性 | NFR-3 の 2 巡固定打ち切りで機械的決着 |
| R-5 | 本番ログマスキング漏れ | NFR-1 検証で防ぐ |
| R-6 | Bedrock 実呼び予算超過 | NFR-4 のコストログで上限管理 |
| R-7 | Phase D 要素を誘惑で着手 | §2.2 Out of Scope を毎タスク着手前に再確認 |
| P-1 | HDW_ML リポジトリが `c:\Workspaces\HDW_ML` に存在する | 着手前に `Test-Path` で確認 |
| P-2 | AWS SSO で hdw-test プロファイルにログイン済み | 着手前に `aws sts get-caller-identity` で確認 |

---

## 7. SPEC 変更ルール

本 SPEC を変更する場合は以下を遵守:

1. 変更前に PLAN.md / TODO.md への波及を確認
2. §0 改定履歴に 1 行追加 (Version 採番 + 変更理由)
3. commit message に `SPEC change: <理由>` を含める
4. 変更が AC を緩める場合は理由を §6 リスクに移動 (緩めた結果のリスク明記)
5. Out of Scope への移動は PLAN.md 側にも反映
