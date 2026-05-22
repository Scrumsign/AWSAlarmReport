#!/usr/bin/env bash
#
# HDW Notify ローカルデプロイスクリプト
#
# 流れ:
#   1. deploy/config.yml / deploy/config-prod.yml の内容を Lambda 環境変数へ投入 (非機密)
#   2. $DISCORD_WEBHOOK_URL を Lambda 環境変数へ投入 (機密)
#   3. Docker イメージを build し ECR へ push
#   4. Lambda function code を新イメージへ切替
#
# 詳細: docs/2026/05/15/aws-deploy-script/PLAN.md
#
# 使い方:
#   ./scripts/deploy.sh test    # deploy/config.yml を使用
#   ./scripts/deploy.sh prod    # deploy/config-prod.yml を使用
#
# 必須環境変数:
#   AWS_REGION             例: ap-northeast-1
#   ECR_REPOSITORY         例: hdw-notify
#   LAMBDA_FUNCTION_NAME   例: hdw-notify-reporter
#   DISCORD_WEBHOOK_URL    Discord Incoming Webhook URL
#
# 任意環境変数:
#   ECR_REGISTRY           未指定なら sts get-caller-identity から組み立て
#   IMAGE_TAG              未指定なら git short SHA

set -euo pipefail

# ---------------------------------------------------------------------------
# Step 0: 前提検証
# ---------------------------------------------------------------------------

usage() {
  cat >&2 <<EOF
Usage: $0 <env>
  env: test | prod
EOF
  exit 1
}

[ $# -eq 1 ] || usage

ENV_NAME="$1"
case "$ENV_NAME" in
  test) CONFIG_FILE="deploy/config.yml" ;;
  prod) CONFIG_FILE="deploy/config-prod.yml" ;;
  *) usage ;;
esac

for cmd in aws docker yq jq git; do
  command -v "$cmd" >/dev/null 2>&1 || {
    echo "required command not found: $cmd" >&2
    exit 1
  }
done

: "${AWS_REGION:?env var AWS_REGION is required}"
: "${ECR_REPOSITORY:?env var ECR_REPOSITORY is required}"
: "${LAMBDA_FUNCTION_NAME:?env var LAMBDA_FUNCTION_NAME is required}"
: "${DISCORD_WEBHOOK_URL:?env var DISCORD_WEBHOOK_URL is required}"

REPO_ROOT="$(cd "$(dirname "$0")/.." && pwd)"
cd "$REPO_ROOT"

[ -f "$CONFIG_FILE" ] || {
  echo "config file not found: $CONFIG_FILE" >&2
  exit 1
}

# ---------------------------------------------------------------------------
# Step 1: パラメータ解決
# ---------------------------------------------------------------------------

ACCOUNT_ID="$(aws sts get-caller-identity --query Account --output text)"
ECR_REGISTRY="${ECR_REGISTRY:-${ACCOUNT_ID}.dkr.ecr.${AWS_REGION}.amazonaws.com}"
IMAGE_TAG="${IMAGE_TAG:-$(git rev-parse --short HEAD)}"
IMAGE_URI="${ECR_REGISTRY}/${ECR_REPOSITORY}:${IMAGE_TAG}"
LATEST_URI="${ECR_REGISTRY}/${ECR_REPOSITORY}:latest"

echo "==> Target"
echo "    env       : $ENV_NAME"
echo "    config    : $CONFIG_FILE"
echo "    region    : $AWS_REGION"
echo "    account   : $ACCOUNT_ID"
echo "    function  : $LAMBDA_FUNCTION_NAME"
echo "    image     : $IMAGE_URI"

# ---------------------------------------------------------------------------
# Step 2: Lambda 環境変数の投入 (非機密 + 機密)
# ---------------------------------------------------------------------------

echo "==> Step 2: Lambda 環境変数の投入"

CONFIG_JSON="$(yq -o=json eval . "$CONFIG_FILE")"

ENV_JSON="$(jq -n \
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
  }}')"

MISSING="$(echo "$ENV_JSON" | jq -r '.Variables | to_entries | map(select(.value == "null" or .value == "")) | map(.key) | join(",")')"
if [ -n "$MISSING" ]; then
  echo "missing required keys: $MISSING" >&2
  exit 1
fi

aws lambda update-function-configuration \
  --function-name "$LAMBDA_FUNCTION_NAME" \
  --region "$AWS_REGION" \
  --environment "$ENV_JSON" \
  --output json >/dev/null

aws lambda wait function-updated \
  --function-name "$LAMBDA_FUNCTION_NAME" \
  --region "$AWS_REGION"

echo "    環境変数を更新しました"

# ---------------------------------------------------------------------------
# Step 3: Docker build & ECR push
# ---------------------------------------------------------------------------

echo "==> Step 3: Docker build & ECR push"

aws ecr get-login-password --region "$AWS_REGION" \
  | docker login --username AWS --password-stdin "$ECR_REGISTRY"

docker buildx build \
  --platform linux/amd64 \
  --file docker/Dockerfile \
  --tag "$IMAGE_URI" \
  --tag "$LATEST_URI" \
  --provenance=false \
  --push \
  .

echo "    push 完了: $IMAGE_URI"

# ---------------------------------------------------------------------------
# Step 4: Lambda function code 更新
# ---------------------------------------------------------------------------

echo "==> Step 4: Lambda function code 更新"

UPDATE_JSON="$(mktemp)"
trap 'rm -f "$UPDATE_JSON"' EXIT

aws lambda update-function-code \
  --function-name "$LAMBDA_FUNCTION_NAME" \
  --region "$AWS_REGION" \
  --image-uri "$IMAGE_URI" \
  --publish \
  --output json > "$UPDATE_JSON"

aws lambda wait function-updated \
  --function-name "$LAMBDA_FUNCTION_NAME" \
  --region "$AWS_REGION"

jq -r '"    Deployed version: \(.Version)\n    Image          : \(.ImageUri // .Code.ImageUri)"' "$UPDATE_JSON"

echo "==> Done"
