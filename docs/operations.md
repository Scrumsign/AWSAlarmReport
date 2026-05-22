# HDW Notify 運用ドキュメント

管理者・デプロイ担当者向けに、AWS / GitHub 側で何が設定されており、どこを触れば何が変わるかをまとめた運用メモ。コードの設計意図は [README.md](../README.md) / [CONTRIBUTING.md](../CONTRIBUTING.md) / `docs/2026/05/15/lambda-error-report-mvp/PLAN.md` を参照。

## 全体像

```
GitHub Actions (draft repo)
  └─► OIDC で IAM ロール assume
        └─► ECR push (new image)
        └─► Lambda update-function-configuration (env vars)
        └─► Lambda update-function-code (image)

CloudWatch Alarm
  └─► Lambda Action 直接 invoke
        └─► Reporter Lambda (HDW_Lambda_Notifier_0001)
              ├─► os.environ から設定取得
              ├─► CW Logs Insights クエリ
              ├─► Bedrock Converse (Claude Sonnet 4.6)
              └─► Discord Webhook 投稿
```

## AWS リソース一覧 (hdw-test: 088898720463 / ap-northeast-1)

### ECR

| 項目 | 値 |
|---|---|
| Repository | `hdw-notify` |
| URI | `088898720463.dkr.ecr.ap-northeast-1.amazonaws.com/hdw-notify` |
| 用途 | Reporter Lambda コンテナイメージ |

**重要**: ローカルからビルドする場合、Lambda は OCI index 形式を受け付けないため `docker buildx build --provenance=false` が必須（後述「ハマりどころ」参照）。GitHub Actions の `docker/build-push-action@v6` は `provenance: false` を明示済み。

### Lambda 関数

| 項目 | 値 |
|---|---|
| 関数名 | `HDW_Lambda_Notifier_0001` |
| ARN | `arn:aws:lambda:ap-northeast-1:088898720463:function:HDW_Lambda_Notifier_0001` |
| PackageType | `Image`（ECR `hdw-notify:bootstrap` から作成） |
| Architecture | `x86_64` |
| Timeout | 300 秒 |
| Memory | 512 MB |
| 実行ロール | `hdw-notify-execution-role` |
| handler | `main.main`（Dockerfile CMD で指定） |

**環境変数**（[deploy/config.yml](../deploy/config.yml) / [deploy/config-prod.yml](../deploy/config-prod.yml) と GHA Secret から CI が同期）:

| 名前 | ソース |
|---|---|
| `DISCORD_WEBHOOK_URL` | GHA Secret `DISCORD_WEBHOOK_URL` |
| `CLOUDWATCH_LOGS_GROUP` | config YAML `aws_cloudwatch_logs_group` |
| `CLOUDWATCH_LOGS_WINDOW_BEFORE_MIN` | config YAML `aws_cloudwatch_logs_window_before_min` |
| `CLOUDWATCH_LOGS_WINDOW_AFTER_MIN` | config YAML `aws_cloudwatch_logs_window_after_min` |
| `CLOUDWATCH_LOGS_QUERY_POLL_INTERVAL_SEC` | config YAML `aws_cloudwatch_logs_query_poll_interval_sec` |
| `BEDROCK_MODEL_ID` | config YAML `aws_bedrock_model_id` |
| `BEDROCK_MAX_TOKENS` | config YAML `aws_bedrock_max_tokens` |
| `BEDROCK_TEMPERATURE` | config YAML `aws_bedrock_temperature` |

### IAM ロール

#### 1. `hdw-notify-execution-role` (Lambda 実行ロール)

- ARN: `arn:aws:iam::088898720463:role/hdw-notify-execution-role`
- Trust: `lambda.amazonaws.com`
- Inline policy `hdw-notify-permissions`:
  - `logs:CreateLogGroup` / `logs:CreateLogStream` / `logs:PutLogEvents` (`arn:aws:logs:ap-northeast-1:088898720463:*`)
  - `ecr:GetDownloadUrlForLayer` / `ecr:BatchGetImage` / `ecr:GetAuthorizationToken` (`*`) ← Lambda image-based 起動に必要
  - `logs:StartQuery` on `log-group:/aws/lambda/HDW_Backend_Processor_0001:*` ← 監視対象ロググループへの Insights クエリ
  - `logs:GetQueryResults` / `logs:StopQuery` on `*` ← API 仕様上スコープ不可
  - `bedrock:InvokeModel` on inference profile `jp.anthropic.claude-sonnet-4-6` + 配下 foundation model `anthropic.claude-sonnet-4-*`

#### 2. `hdw-notify-test-deploy` (GitHub Actions OIDC デプロイロール)

- ARN: `arn:aws:iam::088898720463:role/hdw-notify-test-deploy`
- Trust: GitHub OIDC, `sub` を `StringEquals` で `repo:scrumsign-takuyakimura/HDW_Notify_Draft:environment:test` に固定
  - GitHub Environment `test` にバインドされた workflow run のみ assume 可能
  - 任意ブランチからの push / workflow_dispatch / PR からは assume 不可（environment 指定が無いと sub が一致しない）
- Inline policy `hdw-notify-deploy-permissions`（**更新のみ**、関数作成権限なし）:
  - `ecr:GetAuthorizationToken` (`*`)
  - ECR push 系 7 アクション on `repository/hdw-notify`
  - `lambda:GetFunction` / `lambda:GetFunctionConfiguration` / `lambda:UpdateFunctionConfiguration` / `lambda:UpdateFunctionCode` / `lambda:PublishVersion` on `function:HDW_Lambda_Notifier_0001`

別 environment（例: `production`）を扱うときは trust policy の `sub` 条件に `repo:OWNER/REPO:environment:<env>` を追記、別関数/別 ECR repo を扱うときは inline policy の Resource を拡張する。

## GitHub 設定 (`scrumsign-takuyakimura/HDW_Notify_Draft`)

### Environment `test`

| 種類 | 名前 | 値 |
|---|---|---|
| secret | `AWS_DEPLOY_ROLE_ARN` | `arn:aws:iam::088898720463:role/hdw-notify-test-deploy` |
| secret | `DISCORD_WEBHOOK_URL` | Discord webhook URL（機密） |
| var | `AWS_REGION` | `ap-northeast-1` |
| var | `ECR_REPOSITORY` | `hdw-notify` |
| var | `LAMBDA_FUNCTION_NAME` | `HDW_Lambda_Notifier_0001` |

本番 (`production` environment) は未整備。本番 Lambda / ECR / IAM ロール / `deploy/config-prod.yml` の値はすべて別アカウントで再構築予定。

### デプロイトリガ

- `test` ブランチへの push → Environment `test` を使って Lambda 更新
- `main` ブランチへの push → Environment `production` を使って Lambda 更新（未整備）

## デプロイフロー (`.github/workflows/deploy.yml`)

1. OIDC で `AWS_DEPLOY_ROLE_ARN` を assume
2. ECR ログイン
3. Docker buildx でイメージビルド（`provenance: false`）→ ECR へ `:${SHA}` と `:latest` で push
4. branch に応じた config YAML を `yq` で読み取り、GHA Secret `DISCORD_WEBHOOK_URL` と合成 → `update-function-configuration --environment` で Lambda 環境変数を更新
5. `update-function-code --publish` で Lambda 関数コードを新しいイメージに切り替え

`update-function-configuration` と `update-function-code` は Lambda 側で同時更新できないため、間に `wait function-updated` を挟む。

## 設定値の変更手順

| 変えたいもの | 触る場所 | 反映タイミング |
|---|---|---|
| 非機密 AWS 構成（log group、Bedrock パラメータ等） | `deploy/config.yml`（test） / `deploy/config-prod.yml`（prod）を編集 → 該当ブランチに push | 次回 CI デプロイ |
| Discord Webhook URL | GitHub Environment `test` の secret `DISCORD_WEBHOOK_URL` を更新 → ワークフロー再実行 | 次回 CI デプロイ |
| Insights クエリ / severity 色マップ / プロンプト | `src/main.py` 定数 / `src/utils/prompt.py` を編集 → push | 次回 CI デプロイ |
| Lambda タイムアウト / メモリ | AWS マネジメントコンソール or `aws lambda update-function-configuration --timeout/--memory-size`（CI ワークフローは触らない） | 手動更新時 |

## Bootstrap 手順（再現 / DR 用）

事故等で全部やり直すケースの手順（hdw-test アカウントを前提）。

1. ECR repo `hdw-notify` を作成（既存なのでスキップ可）
2. Lambda 実行ロール `hdw-notify-execution-role` を作成し、上記 inline policy `hdw-notify-permissions` を attach
3. ローカルから初回イメージを push:
   ```powershell
   aws sso login --profile hdw-test
   aws ecr get-login-password --region ap-northeast-1 --profile hdw-test `
     | docker login --username AWS --password-stdin 088898720463.dkr.ecr.ap-northeast-1.amazonaws.com
   docker buildx build --platform linux/amd64 --provenance=false --push `
     -t 088898720463.dkr.ecr.ap-northeast-1.amazonaws.com/hdw-notify:bootstrap `
     -t 088898720463.dkr.ecr.ap-northeast-1.amazonaws.com/hdw-notify:latest `
     -f docker/Dockerfile .
   ```
4. Lambda 関数を作成（環境変数は `DISCORD_WEBHOOK_URL=REPLACE_ON_CI_DEPLOY` 等のプレースホルダで OK、初回 CI デプロイで上書きされる）:
   ```powershell
   aws lambda create-function `
     --function-name HDW_Lambda_Notifier_0001 `
     --package-type Image `
     --code ImageUri=088898720463.dkr.ecr.ap-northeast-1.amazonaws.com/hdw-notify:bootstrap `
     --role arn:aws:iam::088898720463:role/hdw-notify-execution-role `
     --timeout 300 --memory-size 512 --architectures x86_64 `
     --environment file://env.json `
     --profile hdw-test --region ap-northeast-1
   ```
5. GitHub Actions OIDC デプロイロール `hdw-notify-test-deploy` を作成し、上記 trust + inline policy を attach
6. GitHub 側で Environment `test` を作成し、secrets / vars を登録
7. `test` ブランチに push して CI 起動 → Webhook URL を含む env vars が反映され、最新コードイメージに切り替わる
8. CloudWatch Alarm 側で Lambda Action ターゲットに当関数を指定（次節参照）

## CloudWatch Alarm 配線（未着手）

CW Alarm から Lambda Action で直接 invoke するには、Alarm 作成後に Lambda 側の resource-based policy で「該当 Alarm からの invoke」を許可する必要がある:

```powershell
aws lambda add-permission `
  --function-name HDW_Lambda_Notifier_0001 `
  --statement-id AllowCWAlarmInvoke `
  --action lambda:InvokeFunction `
  --principal lambda.alarms.cloudwatch.amazonaws.com `
  --source-arn arn:aws:cloudwatch:ap-northeast-1:088898720463:alarm:<ALARM_NAME> `
  --profile hdw-test --region ap-northeast-1
```

監視対象 Lambda（`HDW_Backend_Processor_0001`）の Errors メトリクスに対する Alarm を CW 側で作成し、Lambda Action として当 Notifier を指定する作業は別途必要。MVP 段階では未整備で、`PLAN.md` の YAML スニペットを起点に整備する想定。

## ハマりどころ

### OCI image manifest が Lambda で reject される

Docker Desktop (buildx) は既定で attestation manifest を付けた OCI index を作る。Lambda は Docker Image Manifest v2 のみ対応で OCI index を弾く（`InvalidParameterValueException: The image manifest, config or layer media type for the source image ... is not supported.`）。

**対処**: `docker buildx build --provenance=false ...` を必須にする。GitHub Actions の `docker/build-push-action@v6` では `provenance: false` を指定済み。ローカルから手動 push する場合も同様。

### Lambda 環境変数で `AWS_*` プレフィックスを避ける

Lambda は `AWS_LAMBDA_*` 等の予約環境変数があり、衝突した場合は関数作成自体が失敗する。本プロジェクトでは `CLOUDWATCH_LOGS_*` / `BEDROCK_*` のようにサービスドメインを直接プレフィックスにしている（`AWS_` を付けない）。GHA Variables 側は `AWS_*` のままだが、Lambda env var 名にマップする段階でプレフィックスを落としている。

### Webhook URL の漏洩リスク

`DISCORD_WEBHOOK_URL` は URL 単体で投稿権限を持つため、漏れた瞬間に第三者が任意のメッセージを投稿できる。漏洩した場合の対処は **Discord 側で当該 webhook を削除して新規発行** が唯一の解決策（Secrets を移しても URL 自体が無効化されるわけではない）。

### IAM 反映のタイムラグ

ロール作成直後に Lambda 関数を作ろうとすると、まれに role が「見つからない」エラーが返る（IAM の eventual consistency）。失敗したら数秒待ってリトライ。

## 関連ドキュメント

- 設計意図: [`docs/2026/05/15/lambda-error-report-mvp/PLAN.md`](2026/05/15/lambda-error-report-mvp/PLAN.md)
- ケース別レポート方針: [`docs/2026/05/15/report-content-by-case/DRAFT.md`](2026/05/15/report-content-by-case/DRAFT.md)
- 開発フロー / 設定値の扱い: [`CONTRIBUTING.md`](../CONTRIBUTING.md)
- セットアップ / デプロイ: [`README.md`](../README.md)
- 変更履歴: [`CHANGELOG.md`](../CHANGELOG.md)
