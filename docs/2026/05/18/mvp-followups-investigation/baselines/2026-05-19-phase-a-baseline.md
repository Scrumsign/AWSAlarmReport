================================================================================
=== handler_value_error
================================================================================

--- README ---
# handler_value_error

## シナリオ
本番 2026-04-27 06:36:52 に HDW_Backend_Processor_0001 で発生した
`ValueError: general_data is None` を再現。
main.py:62 で general_data が None だった場合に raise される箇所。
ship_name=sakura, ship_timestamp=20260427120100 の入力に対する処理。

## マスキング
本番値は SPEC.md NFR-1 v1.2 のダミー値規約で置換済み (account ID / request_id / xray_trace_id)。
規約詳細は [../../../../docs/2026/05/18/mvp-followups-investigation/SPEC.md](../../../../docs/2026/05/18/mvp-followups-investigation/SPEC.md) NFR-1 を参照。

## LLM に期待する回答
- root_cause_hypothesis に何が壊れたかの仮説 (general_data 取得元の何かが None)
- suggested_actions に該当 input_key の S3 オブジェクト確認等
- 現状 prompt はコード言及禁止なので、関数名・行番号への踏み込みは出ない想定
  (それを許可するのは Phase B)

--- system prompt ---

あなたはAWS Lambda障害分析の専門家です。
このアラートは事前判定で「Generic Exception (コード例外)」に分類されました。
error_class と error_message と stack trace から、原因を
  (a) コードバグ
  (b) 入力データ異常（特定のレコード/ファイルだけ失敗）
  (c) 環境変数・設定欠落（KeyError, ImportError 等）
のどれに分類できるか切り分け、もっともらしい順に仮説を挙げてください。
入力イベント要約が同梱されている場合は、特定データ依存の兆候も評価対象に含めてください。

# 役割
- 機械的に抽出済みのログ・メトリクスを読み、開発者が最初の30秒で
  「対応すべきか / 何が起きたか / どこを見るか」を判断できる材料を出す。
- ケース判定・件数集計・request_id 抽出・deeplink 生成は呼び出し側が
  既に済ませているため、それらの再計算や推測は不要。

# 制約
- 必ず下記JSON Schemaに従ってください。スキーマ外の出力は禁止。
- コードベース固有の根本原因は知らない前提で、仮説として複数提示してください。
  断定はせず、もっともらしさの順で並べる。
- 情報不足で判断できない場合は、捏造せず confidence: "low" と
  root_cause_hypothesis に「情報不足 — <何が足りないか>」と書いてください。

# summary
- 60文字以内、1行で「何が起きたか」。

# root_cause_hypothesis
- 200文字以内。優先順で複数仮説を可。

# suggested_actions の制約 (重要)
- 各項目 80文字以内、最大3件。
- 「即時対応」「調査手順」「恒久対策」の3段で並べる。
- AWS リソース / サービス操作レベルでのみ提案する。
  例: 「Lambda の Timeout 設定を 30s → 60s に引き上げる」
      「DynamoDB テーブル X の WCU を一時的に増やす」
      「IAM Role に s3:GetObject 権限が付与されているか確認する」
      「CloudWatch Logs Insights で同一 request_id のログ系列を確認する」
- 以下は禁止:
  - hdw-ingest のコード内の関数名・変数名・モジュール名・ファイル名の言及
  - 「<関数名>を修正する」「<変数名>に対する null チェックを追加する」のような
    コードベース固有の修正提案
  - 「リトライ処理を実装する」のような実装レベルの提案（AWS の retry config
    変更などサービス設定レベルなら可）

# ヒント
- 原因の一つとして、対象LambdaのS3にデータがアップロードされていない可能性がある
- 原因の一つとして、Lambdaの実行がうまくいっていない場合がある

# 出力スキーマ
{
  "summary": "60文字以内の1行要約",
  "severity": "LOW" | "MEDIUM" | "HIGH",
  "confidence": "low" | "medium" | "high",
  "root_cause_hypothesis": "原因仮説 (200文字以内、優先順で複数仮説可)",
  "suggested_actions": [
    "即時対応 (AWSリソース/サービス操作レベル, 80字以内)",
    "調査手順 (AWSリソース/サービス操作レベル, 80字以内)",
    "恒久対策 (AWSリソース/サービス操作レベル, 80字以内)"
  ]
}


--- user prompt ---
# Alarm
name:    hdw-backend-processor-0001-errors
fired:   2026-04-27T06:37:00.000+0000
reason:  Threshold Crossed: 1 datapoint [1.0] was greater than or equal to the threshold (1.0).

# Error logs (1件)

[1] 2026-04-27 06:36:52,801+0000  req=00000000-0000-0000-0000-000000000001
    ship=sakura  ts=20260427120100  input=inputFiles/sakura-20260427120100.zip
    phase=handler
    ValueError: lambda_handler failed
    trace:
      Traceback (most recent call last):
        File "/var/task/main.py", line 167, in lambda_handler
          main_function(pm, environment="lambdaproduction")
        File "/var/task/main.py", line 62, in main_function
          raise ValueError('general_data is None')
      ValueError: general_data is None

--- LLM raw output ---
```json
{
  "summary": "sakura向けZIPからgeneral_dataが取得できずValueErrorが発生",
  "severity": "MEDIUM",
  "confidence": "medium",
  "root_cause_hypothesis": "①S3上の inputFiles/sakura-20260427120100.zip が未アップロードまたは破損しており、general_dataの読み取りがNullになった可能性（最有力）。②ZIPは存在するが内部に期待されるデータファイルが含まれておらず、general_dataの抽出に失敗した可能性。③Lambda実行環境の一時的な問題によりS3読み取り自体が失敗した可能性。",
  "suggested_actions": [
    "即時対応: S3バケット上に inputFiles/sakura-20260427120100.zip が存在するか確認し、欠落の場合は再アップロードする",
    "調査手順: CloudWatch Logs Insights で request_id=00000000-0000-0000-0000-000000000001 の全ログを確認し、S3 GetObject の成否を特定する",
    "恒久対策: S3イベント通知またはS3 Inventoryを活用し、対象ZIPのアップロード完了をLambdaトリガー前に検証する仕組みを設ける"
  ]
}
```

--- usage --- {'inputTokens': 1395, 'outputTokens': 381, 'totalTokens': 1776, 'cacheReadInputTokens': 0, 'cacheWriteInputTokens': 0}
================================================================================
=== no_logs
================================================================================

--- README ---
# no_logs

## シナリオ
4 時間おきの起動枠で HDW_Backend_Processor_0001 が走った形跡がない。
直近時間窓に error / success どちらのログもない状態を再現する。
(S3 への入力ファイル未アップで Lambda がそもそも起動しなかった想定)

## LLM に期待する回答
- summary に「Lambda 未起動」または「ログなし」相当
- root_cause_hypothesis に「S3 入力ファイル未アップ」「アップロード処理の失敗」を仮説として
- suggested_actions に S3 確認系のアクションが入る

--- system prompt ---

あなたはAWS Lambda障害分析の専門家です。
このアラートは事前判定で「Generic Exception (コード例外)」に分類されました。
error_class と error_message と stack trace から、原因を
  (a) コードバグ
  (b) 入力データ異常（特定のレコード/ファイルだけ失敗）
  (c) 環境変数・設定欠落（KeyError, ImportError 等）
のどれに分類できるか切り分け、もっともらしい順に仮説を挙げてください。
入力イベント要約が同梱されている場合は、特定データ依存の兆候も評価対象に含めてください。

# 役割
- 機械的に抽出済みのログ・メトリクスを読み、開発者が最初の30秒で
  「対応すべきか / 何が起きたか / どこを見るか」を判断できる材料を出す。
- ケース判定・件数集計・request_id 抽出・deeplink 生成は呼び出し側が
  既に済ませているため、それらの再計算や推測は不要。

# 制約
- 必ず下記JSON Schemaに従ってください。スキーマ外の出力は禁止。
- コードベース固有の根本原因は知らない前提で、仮説として複数提示してください。
  断定はせず、もっともらしさの順で並べる。
- 情報不足で判断できない場合は、捏造せず confidence: "low" と
  root_cause_hypothesis に「情報不足 — <何が足りないか>」と書いてください。

# summary
- 60文字以内、1行で「何が起きたか」。

# root_cause_hypothesis
- 200文字以内。優先順で複数仮説を可。

# suggested_actions の制約 (重要)
- 各項目 80文字以内、最大3件。
- 「即時対応」「調査手順」「恒久対策」の3段で並べる。
- AWS リソース / サービス操作レベルでのみ提案する。
  例: 「Lambda の Timeout 設定を 30s → 60s に引き上げる」
      「DynamoDB テーブル X の WCU を一時的に増やす」
      「IAM Role に s3:GetObject 権限が付与されているか確認する」
      「CloudWatch Logs Insights で同一 request_id のログ系列を確認する」
- 以下は禁止:
  - hdw-ingest のコード内の関数名・変数名・モジュール名・ファイル名の言及
  - 「<関数名>を修正する」「<変数名>に対する null チェックを追加する」のような
    コードベース固有の修正提案
  - 「リトライ処理を実装する」のような実装レベルの提案（AWS の retry config
    変更などサービス設定レベルなら可）

# ヒント
- 原因の一つとして、対象LambdaのS3にデータがアップロードされていない可能性がある
- 原因の一つとして、Lambdaの実行がうまくいっていない場合がある

# 出力スキーマ
{
  "summary": "60文字以内の1行要約",
  "severity": "LOW" | "MEDIUM" | "HIGH",
  "confidence": "low" | "medium" | "high",
  "root_cause_hypothesis": "原因仮説 (200文字以内、優先順で複数仮説可)",
  "suggested_actions": [
    "即時対応 (AWSリソース/サービス操作レベル, 80字以内)",
    "調査手順 (AWSリソース/サービス操作レベル, 80字以内)",
    "恒久対策 (AWSリソース/サービス操作レベル, 80字以内)"
  ]
}


--- user prompt ---
# Alarm
name:    hdw-backend-processor-0001-errors
fired:   2026-04-27T12:05:00.000+0000
reason:  Threshold Crossed: 1 datapoint [1.0] was greater than or equal to the threshold (1.0).

# Error logs (0件)

--- LLM raw output ---
```json
{
  "summary": "エラーログ0件のためアラーム原因を特定不可",
  "severity": "LOW",
  "confidence": "low",
  "root_cause_hypothesis": "情報不足 — エラーログが0件のため具体的な例外・スタックトレースが確認できない。CloudWatch Metricsの誤検知、Lambda自体が未起動（S3へのデータ未着によるトリガー不発）、またはログ配信遅延・欠落の可能性がある。",
  "suggested_actions": [
    "即時対応: CloudWatch Alarmの履歴と対象Lambdaの直近Invocations/Errorsメトリクスを確認し誤検知か判断する",
    "調査手順: トリガー元S3バケットへの該当時刻のオブジェクト着信履歴をS3イベント通知ログ・CloudTrailで確認する",
    "恒久対策: Lambda実行ログのCloudWatch Logs配信遅延を考慮しアラーム評価期間を延長するか、ログ保持設定を見直す"
  ]
}
```

--- usage --- {'inputTokens': 1219, 'outputTokens': 335, 'totalTokens': 1554, 'cacheReadInputTokens': 0, 'cacheWriteInputTokens': 0}
