# HDW Notify

Lambda失敗を CloudWatch Alarm 起点で検知し、CloudWatch Logs Insights で関連ログを集約、Bedrock (Claude Sonnet 4.6) で要約・原因仮説・推奨アクションを生成して Discord に通知する Reporter Lambda の実装。

詳細設計: [docs/2026/05/15/lambda-error-report-mvp/PLAN.md](docs/2026/05/15/lambda-error-report-mvp/PLAN.md)

## アーキテクチャ

```
S3 ─► [既存] 処理Lambda ─► CW Metrics (Errors)
                                  │
                                  ▼
                          CW Alarm (Errors >= 1)
                                  │  (Lambda Action 直接invoke)
                                  ▼
                          Reporter Lambda (自前)
                          ├─► Logs Insights (期間内ログ取得)
                          ├─► Bedrock Converse API (Claude)
                          └─► Discord Webhook (通知)
```

## リポジトリ構成

- `src/main.py` … Reporter Lambda エントリポイント（handler は `main.main`）。`os.environ` から設定値を取得して実行
- `src/utils/prompt.py` … `render_prompt_*` でシステムプロンプトを組み立て
- `deploy/config.yml` / `deploy/config-prod.yml` … 環境ごとの**非機密** AWS 構成（CloudWatch Logs / Bedrock パラメータ等）。デプロイ時に Lambda 環境変数へ投入される
- `requirements.txt` … Python依存
- `docker/` … デプロイ用 Dockerfile (AWS Lambda コンテナイメージ) / ローカル実行 (RIE) も可
- `docs/YYYY/MM/DD/` … 設計ドキュメント (`DRAFT.md` → `PLAN.md` の流れ)

設定値・シークレットはすべて Lambda 関数の環境変数に集約。投入経路は以下:

- **非機密 AWS 構成** → `deploy/config.yml` (test) / `deploy/config-prod.yml` (production) に記述 → デプロイ時に GitHub Actions が読み取って Lambda 環境変数へ反映
- **機密（Discord Webhook URL）** → GHA Secret → デプロイ時に Lambda 環境変数へ反映

Lambda 環境変数は AWS が保管時 KMS 暗号化するため Webhook URL もここに置く。

## 必要なもの

- Python 3.12+ (Lambda ランタイムに合わせる)
- AWS アカウント + 以下へのアクセス権:
  - 監視対象 Lambda の CloudWatch Logs Group
  - Bedrock (Claude Sonnet 4.6 inference profile: `jp.anthropic.claude-sonnet-4-6`)
- Discord Incoming Webhook URL

## セットアップ (ローカル)

1. リポジトリをクローン
2. 仮想環境作成 + 依存インストール

   ```powershell
   python -m venv .venv
   .venv\Scripts\Activate.ps1
   pip install -r requirements.txt
   ```

3. Lambda が `os.environ` から読む全変数（通常は GitHub Actions のデプロイで自動同期。ローカル単独で動かす場合のみ手動設定）:

   | 環境変数名 | 用途 | 値の出どころ（デプロイ時） | 例 |
   |---|---|---|---|
   | `DISCORD_WEBHOOK_URL` | Discord Incoming Webhook URL | GHA Secret `DISCORD_WEBHOOK_URL` | `https://discord.com/api/webhooks/...` |
   | `CLOUDWATCH_LOGS_GROUP` | 監視対象 Lambda のロググループ名 | config YAML `aws_cloudwatch_logs_group` | `/aws/lambda/hdw-ingest-dev` |
   | `CLOUDWATCH_LOGS_WINDOW_BEFORE_MIN` | Alarm 時刻からさかのぼる分数 (int) | config YAML `aws_cloudwatch_logs_window_before_min` | `5` |
   | `CLOUDWATCH_LOGS_WINDOW_AFTER_MIN` | Alarm 時刻から先に進む分数 (int) | config YAML `aws_cloudwatch_logs_window_after_min` | `1` |
   | `CLOUDWATCH_LOGS_QUERY_POLL_INTERVAL_SEC` | Insights クエリのポーリング間隔 秒 (float) | config YAML `aws_cloudwatch_logs_query_poll_interval_sec` | `1.0` |
   | `BEDROCK_MODEL_ID` | Bedrock inference profile ID | config YAML `aws_bedrock_model_id` | `jp.anthropic.claude-sonnet-4-6` |
   | `BEDROCK_MAX_TOKENS` | Bedrock 推論パラメータ (int) | config YAML `aws_bedrock_max_tokens` | `1024` |
   | `BEDROCK_TEMPERATURE` | Bedrock 推論パラメータ (float) | config YAML `aws_bedrock_temperature` | `0.2` |

4. ローカルから手動実行（テスト用）— AWS 資格情報（環境変数 or プロファイル）に加え、上記環境変数が必要

   ```python
   import os
   os.environ["DISCORD_WEBHOOK_URL"] = "<webhook url>"
   os.environ["CLOUDWATCH_LOGS_GROUP"] = "/aws/lambda/hdw-ingest-dev"
   # ... 残りも同様に

   import sys; sys.path.insert(0, "src")
   from main import main

   sample_event = {
       "alarmArn": "arn:aws:cloudwatch:ap-northeast-1:<account>:alarm:<name>",
       "alarmData": {"state": {"timestamp": "2026-05-15T14:00:00.000+0000", "reason": "test"}},
   }
   main(sample_event)
   ```

## デプロイ

GitHub Actions ([.github/workflows/deploy.yml](.github/workflows/deploy.yml)) が以下のブランチ push をトリガに ECR への image push と Lambda 更新を自動で行います:

- `test` ブランチ → GitHub Environment `test` を使用してテストアカウントの `HDW_Lambda_Notifier_0001` を更新
- `main` ブランチ → GitHub Environment `production` を使用して本番 Lambda を更新（本番側 IaC は別途整備予定）

デプロイジョブの流れ:

1. Docker イメージを ECR へ push
2. branch に応じた config YAML（`main` → `deploy/config-prod.yml` / `test` → `deploy/config.yml`）を読み取り、GHA Secret `DISCORD_WEBHOOK_URL` と合わせて `update-function-configuration` で Lambda 環境変数を更新
3. `update-function-code` で Lambda 関数コードを新しいイメージに更新

非機密の構成値だけ変えたい場合は対象 YAML を編集して再デプロイ、Webhook URL を変えたい場合は GHA Secret を更新して再デプロイすれば反映されます。

各 environment で必要な vars / secrets:

| 種類 | 名前 | 用途 |
|---|---|---|
| secrets | `AWS_DEPLOY_ROLE_ARN` | OIDC で assume するデプロイ用 IAM ロール ARN |
| secrets | `DISCORD_WEBHOOK_URL` | Lambda env var `DISCORD_WEBHOOK_URL` の出どころ |
| vars | `AWS_REGION` | デプロイ先リージョン |
| vars | `ECR_REPOSITORY` | image push 先 ECR リポジトリ名 |
| vars | `LAMBDA_FUNCTION_NAME` | 更新対象 Lambda 関数名 |

それ以外の非機密 AWS 構成値は `deploy/config.yml` / `deploy/config-prod.yml` に置きます（[#リポジトリ構成](#リポジトリ構成) 参照）。

Alarm / Lambda 本体（実行ロール・関数定義）は MVP 段階では未 IaC 化。初回作成と Alarm 配線は手動で実施しています。デプロイ用 IAM ロールは対象 Lambda 関数への `lambda:UpdateFunctionConfiguration` / `lambda:UpdateFunctionCode` / `lambda:GetFunction` を許可しておく必要があります。

## 開発状況

MVP 構築中。現時点のスコープと意思決定の根拠は [PLAN.md](docs/2026/05/15/lambda-error-report-mvp/PLAN.md) を参照。
