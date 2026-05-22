# handler_value_error

## シナリオ (SPEC v1.5 で拡張)
本番 2026-04-27 06:07-06:37 UTC (alarm 発火時刻 06:37 の **前 30 分**) の全ログ **85 件**。
hanshin-t.kimura profile (production 920373030024) から `aws logs start-query` で取得し、
SPEC NFR-1 v1.2 規約でマスキング適用済み。

### 観測されたインシデントの流れ
- **06:33:22 UTC**: cold start で `INIT_REPORT Status: timeout` (10s init 上限超過)
- **06:33:30-36**: Lambda 起動成功、s3 download / extraction / main_function 開始まで進行
- **06:33:36**: `ValueError: general_data is None` at `main.py:62` (lambda_handler:178 で re-raise)
- その後 Lambda が **3 回連続失敗** (06:33:36 → 06:34:39 → 06:36:52)
  - 同一 ship: `sakura` / ship_timestamp: `20260427120100`
  - 同一 input_key: `inputFiles/sakura-20260427120100.zip`
  - 実行時間: 13s → 4s → 4s (cold start → warm)
  - Max Memory: 425-444MB (上限 2048MB に余裕)

### ログ構成
- `INFO`: 69 件 (handler 経路の処理ステップ: s3 download / extraction / 設定読込 等)
- `ERROR`: 3 件 (ValueError x3 = retry)
- `RUNTIME`: 13 件 (Lambda 環境出力: INIT_REPORT / START / END / REPORT / `[ERROR]` traceback)

## マスキング
SPEC NFR-1 v1.2 + FR-A-4 (採取規約) 準拠でダミー値置換済み。
- account ID / function_request_id / xray_trace_id

## LLM に期待する回答 (5 失敗モード視点)
- **パターン分類**: (B) lambda_failure
- **F2 (root_cause 浅さ)**: `main.py:62` の `general_data is None` 判定への踏み込み
  - 仮説優先順:
    1. (b2) ZIP 内に general_data 該当ファイル/キーが欠落 (入力データ異常)
    2. (b1) general_data 取得ロジックのバグ
    3. INIT_REPORT timeout を関連事象として認識できればなお良い
- **F5 (severity/confidence 一貫性)**: 同一 root_cause を 3 回繰り返している → confidence: medium-high 妥当
- **F6 (S3 言及)**: 該当 input_key の中身検証を suggested_actions に
- **F7 (timeout 兆候)**: 冒頭の INIT timeout を読み取れるか
- **F10 (ヒント節)**: 「S3 にデータがアップロードされていない可能性」のヒントは ここでは誤誘導 (S3 ファイル自体は存在し処理に着手している)

## 履歴
- v1.0 (2026-05-19 朝): ValueError 単発 1 件のみ
- v1.5 (2026-05-19 午後): 本番 30min 窓の全ログ 85 件に拡張 (本ファイル)
