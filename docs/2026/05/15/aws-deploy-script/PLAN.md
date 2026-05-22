---
title: AWS デプロイ用 bash スクリプト (scripts/deploy.sh)
date: 2026-05-15
status: plan
type: tooling
scope: deploy
author: t.kimura@scrumsign.com
tags:
  - aws-lambda
  - ecr
  - docker
  - deploy
  - bash
  - local-deploy
requirements:
  - config.yml の内容を Lambda 非機密環境変数として投入
  - Discord webhook URL を Lambda 機密環境変数として投入
  - Lambda コンテナイメージを ECR に push
  - ECR から Lambda へデプロイ（イメージ URI 切替）
components:
  - scripts/deploy.sh
  - docker/Dockerfile
  - config.yml / config-prod.yml
decisions:
  runtime: bash (set -euo pipefail)
  config_source: YAML を yq で JSON 化し jq でマップ
  secret_source: 環境変数 DISCORD_WEBHOOK_URL から取得（コード非保管）
  image_build: docker buildx (linux/amd64)
  ordering: env (非機密) → env (機密) → ECR push → function-code 更新
related:
  - [[feedback_lambda_config_via_env_vars]]
  - ../lambda-error-report-mvp/PLAN.md
---

# AWS デプロイ用 bash スクリプト (scripts/deploy.sh)

## 1. 全体像・概要

### 目的

既存 GHA workflow [.github/workflows/deploy.yml](../../../../../.github/workflows/deploy.yml) が CI 経由で行っているデプロイ処理を、**ローカル/手動実行可能な bash スクリプト**として `scripts/deploy.sh` に切り出す。CI が落ちている時の緊急デプロイ、検証用イメージのテスト環境への push、hotfix の即時反映を可能にする。

### フロー

```
config.yml ──► (yq + jq)
                  │
                  ▼
              ENV_JSON ──► aws lambda update-function-configuration (非機密+機密)
                              │
                              ▼
                          function-updated 待機
                              │
$DISCORD_WEBHOOK_URL ─────────┘  ※ENV_JSON へ合流

Dockerfile ──► docker buildx build/push ──► ECR
                                              │
                                              ▼
                                       aws lambda update-function-code
                                              │
                                              ▼
                                       function-updated 待機
```

### 要件と担当ステップ

| 要件 | 担当 |
|---|---|
| ① config 内容を Lambda 非機密環境変数へ | Step 2 (yq + jq → update-function-configuration) |
| ② Discord webhook URL を Lambda 機密環境変数へ | Step 2 (同上、source は `$DISCORD_WEBHOOK_URL`) |
| ③ Lambda イメージを ECR に登録 | Step 3 (ecr get-login-password → docker push) |
| ④ ECR からデプロイ | Step 4 (update-function-code --image-uri) |

### スクリプト構成

| ステップ | 役割 |
|---|---|
| Step 0 | 前提検証 (必須コマンド・必須環境変数・引数) |
| Step 1 | パラメータ解決 (環境ごとの config / function 名 / ECR repo) |
| Step 2 | Lambda 環境変数の投入 (非機密 + 機密を 1 回の API で合流) |
| Step 3 | Docker イメージ build → ECR push |
| Step 4 | Lambda function code 更新 (新イメージへ切替) |

---

## 2. 各要素の詳細

### 2.1 ランタイム前提

```bash
#!/usr/bin/env bash
set -euo pipefail
```

**判断**: bash + `set -euo pipefail`。fish/zsh 依存はしない。
**理由**: GHA workflow と挙動を揃える / ローカルから WSL/Mac/Linux で素直に動く / 失敗を即座に止める。
**注**: Windows 環境では Git Bash か WSL で実行する想定。`yq` (mikefarah v4) / `jq` / `aws` / `docker` がパス上にあることを Step 0 で検証。

**メリット**: GHA 側ロジックの 1:1 移植が容易 / 暗黙の成功扱いを撲滅。
**デメリット**: PowerShell 直実行不可。
**代替案**: PowerShell スクリプト (.ps1) を別途用意、Makefile に同じ流れを書く。

---

### 2.2 入力パラメータ

| 入力 | 由来 | 必須 | 備考 |
|---|---|---|---|
| `--env` (test\|prod) または引数 1 | CLI | ◯ | 環境切替。test=config.yml / prod=config-prod.yml |
| `AWS_REGION` | 環境変数 | ◯ | 例: `ap-northeast-1` |
| `ECR_REGISTRY` | 環境変数または自動解決 | △ | `aws sts get-caller-identity` から組み立て可 |
| `ECR_REPOSITORY` | 環境変数 | ◯ | 例: `hdw-notify` |
| `LAMBDA_FUNCTION_NAME` | 環境変数 | ◯ | 例: `hdw-notify-reporter` |
| `DISCORD_WEBHOOK_URL` | 環境変数 | ◯ | 機密。.envrc / 1Password CLI 経由で注入を推奨 |
| `IMAGE_TAG` | 環境変数 | × | 既定: `git rev-parse --short HEAD` |

**判断**: 非機密パラメータは環境変数で受け取り、機密 (Webhook URL) も同様に環境変数。CLI 引数は環境セレクタ (`test`/`prod`) のみ。
**理由**: GHA の `vars` / `secrets` 渡しと対称 / .envrc / direnv で各人ローカル差を吸収できる / 引数地獄を避ける。
**注**: `DISCORD_WEBHOOK_URL` をシェル履歴に残さないため `direnv` / 1Password CLI / `read -s` 経由を推奨。スクリプト側では `printenv` 等で値を表示しない。

**メリット**: CI と同形 / シークレットを引数化しない。
**デメリット**: 初回ユーザーは「何を export すべきか」を README で読む必要あり。
**代替案**: 全部 `--flag` で受ける (発見性◎、CIとの双対性✕)、`.envrc` を必須化。

---

### 2.3 Step 2: Lambda 環境変数の投入

```bash
CONFIG_JSON=$(yq -o=json eval . "$CONFIG_FILE")

ENV_JSON=$(jq -n \
  --argjson c "$CONFIG_JSON" \
  --arg DISCORD_WEBHOOK_URL "$DISCORD_WEBHOOK_URL" \
  '{Variables: {
    DISCORD_WEBHOOK_URL: $DISCORD_WEBHOOK_URL,
    CLOUDWATCH_LOGS_GROUP: ($c.aws_cloudwatch_logs_group | tostring),
    CLOUDWATCH_LOGS_WINDOW_BEFORE_MIN: ($c.aws_cloudwatch_logs_window_before_min | tostring),
    CLOUDWATCH_LOGS_WINDOW_AFTER_MIN: ($c.aws_cloudwatch_logs_window_after_min | tostring),
    CLOUDWATCH_LOGS_QUERY_POLL_INTERVAL_SEC: ($c.aws_cloudwatch_logs_query_poll_interval_sec | tostring),
    BEDROCK_MODEL_ID: ($c.aws_bedrock_model_id | tostring),
    BEDROCK_MAX_TOKENS: ($c.aws_bedrock_max_tokens | tostring),
    BEDROCK_TEMPERATURE: ($c.aws_bedrock_temperature | tostring),
  }}')

aws lambda update-function-configuration \
  --function-name "$LAMBDA_FUNCTION_NAME" \
  --environment "$ENV_JSON" >/dev/null
aws lambda wait function-updated --function-name "$LAMBDA_FUNCTION_NAME"
```

**判断**: 非機密 (YAML 由来) と機密 (`$DISCORD_WEBHOOK_URL`) を **同一 `Variables` マップに合流**して 1 回の `update-function-configuration` で投入。
**理由**: Lambda 環境変数は KMS で透過暗号化されるため、API 層では非機密/機密の区別を持たない。アプリは `os.environ` 直叩き ([[feedback_lambda_config_via_env_vars]] に従う)。SSM/Secrets Manager を経由しないことで構成を増やさない。
**注**: `update-function-configuration` と `update-function-code` は同時実行不可。Step 2 完了後に `function-updated` を待ってから Step 4 へ進む。

**メリット**: 構成が薄い (SSM/SM 不要) / GHA workflow と完全に同形 / 値変更は YAML or `$DISCORD_WEBHOOK_URL` 差し替えのみで完結。
**デメリット**: コンソールから値が見えてしまう (KMS 復号権限ありの IAM プリンシパル限定)。秘匿性が要件化したら SSM SecureString / Secrets Manager へ昇格。
**代替案**: Webhook URL のみ SSM SecureString に格納し Lambda 側で取得 ([lambda-error-report-mvp PLAN](../lambda-error-report-mvp/PLAN.md) 当初案)。

---

### 2.4 Step 3: Docker build & ECR push

```bash
ECR_REGISTRY="${ECR_REGISTRY:-$(aws sts get-caller-identity --query Account --output text).dkr.ecr.${AWS_REGION}.amazonaws.com}"
IMAGE_URI="${ECR_REGISTRY}/${ECR_REPOSITORY}:${IMAGE_TAG}"
LATEST_URI="${ECR_REGISTRY}/${ECR_REPOSITORY}:latest"

aws ecr get-login-password --region "$AWS_REGION" \
  | docker login --username AWS --password-stdin "$ECR_REGISTRY"

docker buildx build \
  --platform linux/amd64 \
  --file docker/Dockerfile \
  --tag "$IMAGE_URI" \
  --tag "$LATEST_URI" \
  --push \
  .
```

**判断**: `docker buildx` で `linux/amd64` を明示 / `:${IMAGE_TAG}` と `:latest` の 2 タグで push。
**理由**: M1/M2 Mac でも Lambda が要求する amd64 で build できる / `:latest` は手元検証用、`:${IMAGE_TAG}` (git short sha) は本番デプロイ参照用としてイミュータブル運用。
**注**: ECR レポジトリは事前に作成済みの想定 (terraform/CloudFormation 側で管理)。`ECR_REGISTRY` を未指定なら `sts get-caller-identity` から組み立てる (アカウント取り違え防止のため明示指定が望ましい)。

**メリット**: arch ハマりを未然防止 / 一意 tag で「どのコミットが本番か」が追跡可能。
**デメリット**: `:latest` の上書きはコンソール検索時に紛らわしくなる場合あり。
**代替案**: `--push` 後に手動 `aws ecr describe-images` で確認、SHA digest pinning。

---

### 2.5 Step 4: Lambda function code 更新

```bash
aws lambda update-function-code \
  --function-name "$LAMBDA_FUNCTION_NAME" \
  --image-uri "$IMAGE_URI" \
  --publish \
  --output json > /tmp/update.json
aws lambda wait function-updated --function-name "$LAMBDA_FUNCTION_NAME"

jq -r '"Deployed version: \(.Version)\nImage: \(.ImageUri // .Code.ImageUri)"' /tmp/update.json
```

**判断**: `--publish` でバージョン固定し、結果 JSON からバージョン番号とイメージ URI を表示。
**理由**: 後でロールバックする時に `aws lambda update-alias --function-version` で前バージョンに戻せる / デプロイ後に何がデプロイされたかを stdout で残せる。
**注**: alias を使う運用 (例: `live` alias) に拡張する場合は本ステップの後に `update-alias` を追加。

**メリット**: 不可逆性が低い (バージョンが残る) / 出力で「何が出たか」が即座に分かる。
**デメリット**: バージョンが溜まる (古いものは AWS 側で自動削除されない、CW Logs と共に保管コストはわずか)。
**代替案**: alias 戦略を加えた blue/green、CodeDeploy。

---

### 2.6 失敗時の挙動と冪等性

- `set -euo pipefail` により途中失敗で即停止
- Step 2 失敗 → イメージは push されていないので影響なし
- Step 3 失敗 → Lambda 環境変数だけ更新されたが、code 側は旧イメージのまま動く (整合性あり)
- Step 4 失敗 → 環境変数とコードの組み合わせが旧コード × 新環境変数になる可能性あり。再実行で復旧可能
- 何度走らせても同じ結果 (image tag が同じなら同じイメージが参照される)

**判断**: ロールフォワード前提。トランザクション化はしない。
**理由**: Lambda は宣言的更新で、再実行で必ず収束する / 状態巻き戻しが必要な失敗は少なく、必要なら手動で `update-function-code --image-uri <旧tag>` を打てばよい。
**代替案**: trap で失敗時に直前バージョンへ戻すロールバック処理。MVP では入れない。

---

## 3. 想定 README 追加項目

`scripts/deploy.sh` 利用にあたって README へ追記する内容:

```
## ローカルからのデプロイ

# 前提
- aws CLI / docker / yq (mikefarah v4) / jq がインストール済み
- aws configure sso などで対象アカウントへの認証が完了している
- ECR レポジトリ・Lambda 関数は事前作成済み

# 環境変数 (推奨: direnv で .envrc 管理)
export AWS_REGION=ap-northeast-1
export ECR_REPOSITORY=hdw-notify
export LAMBDA_FUNCTION_NAME=hdw-notify-reporter
export DISCORD_WEBHOOK_URL=...  # 1Password CLI から取得を推奨

# 実行
./scripts/deploy.sh test    # config.yml を使用
./scripts/deploy.sh prod    # config-prod.yml を使用
```

---

## 4. 既存 GHA workflow との関係

| 項目 | `.github/workflows/deploy.yml` | `scripts/deploy.sh` |
|---|---|---|
| 認証 | OIDC で `AWS_DEPLOY_ROLE_ARN` を assume | ローカル shell の AWS credentials (SSO 等) |
| 環境変数の source | GHA `vars` / `secrets` | `export` した shell 環境変数 / direnv |
| trigger | push / workflow_dispatch | 人間が手動実行 |
| 用途 | 通常デプロイ | 緊急デプロイ・検証 |

**判断**: 両者を**併存**させ、ロジック (env 投入・build・code 更新の流れ) を同形に保つ。
**理由**: 「CI 落ちた時に何ができるか」が読みやすくなる / GHA 側を書き換えるとき、ローカルで先に試せる。

---

## 5. 参考

- [GHA workflow: .github/workflows/deploy.yml](../../../../../.github/workflows/deploy.yml)
- [Lambda error report MVP PLAN](../lambda-error-report-mvp/PLAN.md)
- [AWS CLI: update-function-configuration](https://docs.aws.amazon.com/cli/latest/reference/lambda/update-function-configuration.html)
- [AWS CLI: update-function-code](https://docs.aws.amazon.com/cli/latest/reference/lambda/update-function-code.html)
- [Docker buildx + Lambda container images](https://docs.aws.amazon.com/lambda/latest/dg/images-create.html)
