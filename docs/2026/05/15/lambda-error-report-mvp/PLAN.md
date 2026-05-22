
# Lambda失敗ログ → LLM分析 → Discord通知 (MVP)

## 1. 全体像・概要

### アーキテクチャ図

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
                          ├─► SSM Parameter Store (Webhook URL取得)
                          └─► Discord Webhook (通知)
```

### 要件と担当コンポーネント

| 要件 | 担当 |
|---|---|
| ① LLM活用 | Bedrock Converse API (Claude Sonnet 4.6) |
| ② Discord連携 | Discord Incoming Webhook + SSM Parameter Store |
| ③ Lambda失敗時のログレポーティング | CW Alarm → Reporter Lambda → Logs Insights |

### 追加リソース（既存Lambdaを除く・計5つ）

CloudWatch Alarm / Lambda Permission / Reporter Lambda / IAM Role / SSM Parameter (SecureString)

---

## 2. 各要素の詳細

### 2.1 トリガー: CloudWatch Alarm

```yaml
ErrorsAlarm:
  Type: AWS::CloudWatch::Alarm
  Properties:
    AlarmName: hdw-ingest-errors
    MetricName: Errors
    Namespace: AWS/Lambda
    Dimensions: [{ Name: FunctionName, Value: hdw-ingest }]
    Statistic: Sum
    Period: 60
    EvaluationPeriods: 1
    DatapointsToAlarm: 1
    Threshold: 1
    ComparisonOperator: GreaterThanOrEqualToThreshold
    TreatMissingData: notBreaching
    AlarmActions: [!GetAtt ReporterFunction.Arn]
```

**判断**: Lambda Destinationsではなく **CloudWatch Alarm** を選択。
**理由**: 既存Lambdaに改修不要 / Throttle等の死角もカバー可 / 閾値抑止がインフラ層で完結。Alarmの「集計値しか持たない」弱点はReporter+LLMで補完。
**注**: 1分粒度・1件閾値で検知遅延≒1分。リアルタイム性が要件化したらDestinations追加可。

**メリット**: 既存Lambda無改修 / 閾値抑止が標準装備 / 同期・Throttle等の死角もカバー可。
**デメリット**: 検知遅延≒1分 / 集計値のみで「誰が落ちたか」は後段で特定要。
**代替案**: Lambda Destinations（個別追跡◎・既存Lambdaに `OnFailure` 設定要）、Logs Subscription Filter（リアルタイム・ノイズ多）。

---

### 2.2 Action: Lambda Direct Invoke

```yaml
ReporterPermission:
  Type: AWS::Lambda::Permission
  Properties:
    FunctionName: !Ref ReporterFunction
    Action: lambda:InvokeFunction
    Principal: lambda.alarms.cloudwatch.amazonaws.com
    SourceAccount: !Ref AWS::AccountId
    SourceArn: !GetAtt ErrorsAlarm.Arn
```

**判断**: SNSを挟まず Alarm → Lambda 直接invoke。
**理由**: 通知先がDiscord 1経路のみのためファンアウト不要 / リソース1個削減 / 将来SNSを差し込む形のリファクタは破壊的変更にならない。
**注**: principalは `lambda.alarms.cloudwatch.amazonaws.com`（他のCWイベント系と紛らわしい）。`SourceAccount` + `SourceArn` 両方指定がconfused deputy対策として現行AWS推奨。

**メリット**: リソース1個削減 / 遅延短縮（数十ms）/ IaC短縮。
**デメリット**: ファンアウト不可（複数Subscriber化時はSNS差し込み要）/ SNSのDeliveryメトリクスによる疎通切り分けは使えない。
**代替案**: SNS経由（メール等を後で追加する前提なら）、EventBridge Rule仲介（他AWSサービスへ連携拡張する前提なら）。

---

### 2.3 Compute: 自前 Reporter Lambda

```python
def handler(event, _):
    alarm = parse_alarm(event)                     # alarmName, time, state
    window = derive_time_window(alarm)             # state.timestamp ± N分

    logs = run_insights_query(
        log_group="/aws/lambda/hdw-ingest",
        query=ERROR_QUERY,
        start=window.start, end=window.end,
    )

    report = bedrock_converse(
        model="claude-sonnet-4-6",
        system=SYSTEM_PROMPT,
        messages=[{"role": "user", "content": format_input(alarm, logs)}],
    )

    post_to_discord(
        webhook_url=get_parameter("/hdw-notify/discord-webhook"),
        embed=build_embed(alarm, report),
    )
```

**判断**: Reporter Lambda 1個に責務集約（Step Functions / Bedrock Agents / DevOps Agent は選択外）。

**自前 vs AWS純正の比較**:

| 項目 | 自前 Reporter | AWS純正 (Investigations 等) | Step Functions |
|---|---|---|---|
| Discord連携 | **◎** | ✕ Slack/Email等のみ | ○ HTTP Task |
| プロンプト・ロジック自由度 | **◎** | △ | ○ |
| デバッグ速度 | **◎** | △ | ✕ ASLが重い |
| agenticループ拡張 | **◎** | △ | ✕ |
| コスト | **◎ <$1/月** | 不透明 | △ 状態遷移課金 |

**自前を選ぶ核心**: 純正 `CloudWatch Investigations` は **Discord通知に対応していない**ため要件②を単独で満たせない。要件3つを最低コスト・最高制御性で満たすには自前Lambdaが最適。Investigationsの結果を将来Reporterの入力として食わせる統合パスも残せる。

**メリット**: ロジック自由度・反復速度・低コスト・agentic拡張容易。
**デメリット**: 自前実装の運用負荷（コード保守・テスト）/ 純正機能を組み合わせる場合は別途連携実装要。
**代替案**: 上記比較表参照（AWS純正Investigations / Step Functions / Bedrock Agents / ECS）。

---

### 2.4 Log Query: CloudWatch Logs Insights

```
fields @timestamp, level, request_id, error_class, error_message, stack
| filter level in ["ERROR", "FATAL"]
| sort @timestamp desc
| limit 50
```

**判断**: 旧 Insights Query Language で開始（PPLは将来検討）。
**理由**: 既存ログがJSON化済みでフィールド抽出が綺麗 / MVPはJOIN/SubQuery不要 / PPLは必要になってから移行。
**時間窓**: `alarmData.state.timestamp` を中心に **−5分 〜 +1分**（Alarm評価期間+バッファ）。

**メリット**: 学習コスト低 / 既存JSONログとの相性◎ / MVP範囲では十分。
**デメリット**: JOIN / SubQuery不可 / 関数間相関分析が困難 / スキャン量課金（$0.005/GB）。
**代替案**: OpenSearch PPL（JOIN/SubQuery可・関数間相関に強い）、OpenSearch SQL（SQL慣れた人向け）、CW Live Tail（リアルタイム監視用途）。

---

### 2.5 LLM: Bedrock Converse API

```python
client.converse(
    # Sonnet 4.6 は cross-region inference profile 経由で呼び出す
    # 東京リージョン: jp.anthropic.claude-sonnet-4-6
    # グローバル:    global.anthropic.claude-sonnet-4-6
    modelId="jp.anthropic.claude-sonnet-4-6",
    system=[{"text": SYSTEM_PROMPT}],
    messages=[{"role": "user", "content": [{"text": prompt}]}],
    inferenceConfig={"maxTokens": 1024, "temperature": 0.2},
)
```

**判断**: Bedrock **Converse API** + **Claude Sonnet 4.6**（inference profile経由）。
**理由**: Converse APIはモデル切替容易・tool_use対応標準（agenticループ拡張に直結）/ Sonnet 4.6 は分析バランス良・1Mコンテキスト / 出力JSON強制（`{summary, severity, root_cause_hypothesis, suggested_actions}`）でDiscord Embed化が機械的に。
**注**: Sonnet 4.6 はベースmodelId直接呼びでなく **inference profile ID（`jp.` / `global.` prefix）** を指定する必要がある。MVPは単発呼び出し。tool_useループは後で system prompt と tools を渡すだけで有効化可能な形にしておく。

**メリット**: モデル切替容易（IDを変えるだけ）/ tool_use標準対応 / 1Mコンテキスト / cross-region inference で可用性◎。
**デメリット**: $3/$15 per Mtok（Sonnet）/ 出力品質はプロンプト次第 / inference profile仕様の理解が必要。
**代替案**: Claude Haiku 4.5（コスト約1/4・速度↑・分析力△）、Claude Opus 4.7（高品質・高コスト）、CW Logs Insights内蔵 Summarization（無料・カスタム不可）。

---

### 2.6 Notification: Discord Webhook

```python
requests.post(webhook_url, json={
    "embeds": [{
        "title": f"⚠ {alarm.name}",
        "description": report["summary"],
        "color": SEVERITY_COLOR[report["severity"]],
        "fields": [
            {"name": "原因仮説", "value": report["root_cause_hypothesis"]},
            {"name": "推奨アクション", "value": "\n".join(report["suggested_actions"])},
            {"name": "Insightsリンク", "value": insights_deeplink(window)},
        ],
        "timestamp": alarm.timestamp,
    }]
})
```

**判断**: Discord **Incoming Webhook**（Botは作らない）+ **SSM Parameter Store (SecureString)** で URL管理。
**理由**: 通知のみで双方向不要 / Bot常駐の運用負荷ゼロ / コードに直書きせずKMS暗号化保管。

#### シークレット保管先: Parameter Store vs Secrets Manager

| 項目 | **Parameter Store (SecureString)** ✅選択 | Secrets Manager |
|---|---|---|
| 月額 | **$0** (Standard, 4KB以下, 1万件まで) | $0.40/secret/月 |
| KMS暗号化 / IAM / 監査 | ◎ | ◎ |
| 自動ローテーション | ✕ | ◎ |
| クロスリージョン複製 / アカウント共有 | 限定的 | 容易 |
| 最大サイズ | 4KB | 64KB |

**Parameter Store を選んだ理由**: Discord側が自動ローテに非対応なのでSMの最大利点が活かせない / クロスリージョン・クロスアカウント要件なし / Webhook URL は ~120文字で4KB上限に余裕 / 機能同等で月$0.40節約。将来SMが必要になればIAM action変更程度で移行可。

#### セキュリティ注記 — 現状で十分安全な理由

| 攻撃ベクトル | 現実性 | 対策 |
|---|---|---|
| ブルートフォース | **不可能**（トークンが十分長いランダム文字列） | 不要 |
| **URL漏洩**（悪意あるパッケージ・ログ流出等） | 唯一の現実的リスク | Parameter Store + 最小IAM で対応済み |

既知のWebhook関連インシデントはすべて「URL漏洩」起因。本MVP構成で十分。OIDCプロキシ等の過剰対策は不要。

**メリット**: 認証不要・Bot不要で即時開通 / 運用負荷ゼロ / KMS暗号化+IAMで漏洩リスク低減。
**デメリット**: レート制限 **30 req/min/URL**（超過時429 + `Retry-After`）/ OIDC非対応 / URLが事実上のトークン。
**代替案**: Discord Bot（双方向通信が要件化した時のみ）、SES経由メール（チャンネル外通知）、AWS Chatbot経由 Slack/Teams（Discord非対応のため代替先として）。

---

### 2.7 IAM Role (Reporter用) - 最小権限

```yaml
ReporterRole:
  Type: AWS::IAM::Role
  Properties:
    AssumeRolePolicyDocument: { ... lambda.amazonaws.com 信頼 ... }
    Policies:
      - PolicyName: ReporterPolicy
        PolicyDocument:
          Statement:
            - Effect: Allow                                  # クエリ開始は LogGroup ARN で絞れる
              Action: logs:StartQuery
              Resource: !Sub "arn:aws:logs:*:*:log-group:/aws/lambda/hdw-ingest:*"
            - Effect: Allow                                  # 結果取得・停止はResource非対応のため "*" 必須
              Action: [logs:GetQueryResults, logs:StopQuery]
              Resource: "*"
            - Effect: Allow                                  # Bedrock 呼び出し（inference profile + foundation model 両方必要）
              Action: bedrock:InvokeModel
              Resource:
                - !Sub "arn:aws:bedrock:*::foundation-model/anthropic.claude-sonnet-4-6*"
                - !Sub "arn:aws:bedrock:*:${AWS::AccountId}:inference-profile/jp.anthropic.claude-sonnet-4-6"
                - !Sub "arn:aws:bedrock:*:${AWS::AccountId}:inference-profile/global.anthropic.claude-sonnet-4-6"
            - Effect: Allow                                  # Webhook URL取得 (Parameter Store)
              Action: ssm:GetParameter
              Resource: !Sub "arn:aws:ssm:${AWS::Region}:${AWS::AccountId}:parameter/hdw-notify/discord-webhook"
            - Effect: Allow                                  # SecureString復号 (default key使用時は不要)
              Action: kms:Decrypt
              Resource: !Sub "arn:aws:kms:${AWS::Region}:${AWS::AccountId}:key/<key-id>"
              Condition:
                StringEquals:
                  kms:ViaService: !Sub "ssm.${AWS::Region}.amazonaws.com"
```

**判断**: 対象LogGroup固定 / 特定モデル + inference profile限定 / SSM Parameter ARN固定で最小権限。
**理由**: 想定外の探索や呼び出しを物理的に防止＋コスト天井としても機能。
**注**: `logs:StopQuery` および `logs:GetQueryResults` はqueryId操作のため**Resource非対応**で `"*"` 必須。Sonnet 4.6 は inference profile経由で呼ぶため **foundation-model と inference-profile の両方** の権限が必要。

**メリット**: 最小権限 / モデル・LogGroup・SecretのARN固定でコスト天井としても機能。
**デメリット**: 対象モデル・LogGroup追加時にポリシー更新要 / inference profile の region prefix を変える場合も更新要。
**代替案**: ワイルドカード広い権限（運用楽・セキュリティ弱）、Permission Boundary追加層（より厳格に縛る場合）。

---

## 3. 拡張パス（MVP後の追加候補）

| 追加 | 効くタイミング |
|---|---|
| DDB dedupe (TTL付き) | 同一エラー連発で通知が溢れる時 |
| Agentic tool_useループ | 単発分析の精度に不満を感じた時 |
| S3 にmd保存 + DDBインデックス | 過去事例参照が要件化した時 |
| OpenSearch PPL移行 | 関数間相関JOIN等が要る時 |
| CW Alarm追加 (Throttles, Duration) | 容量・性能問題が顕在化した時 |
| Composite Alarm | メンテ時間中の抑止が要る時 |
| SES (メール) | Discord以外の通知先が要る時 |
| CW内蔵 Summarization 併用 | LLMコスト圧縮したい時 |

---

## 4. 想定コスト（月100アラーム想定）

| 項目 | 月額 |
|---|---|
| CW Alarm | $0.10 |
| Lambda invocations + duration | <$0.10 |
| Logs Insights クエリ (1GB scan/月) | <$0.50 |
| Bedrock (Sonnet, 100呼×2K入/0.5K出) | ~$0.80 |
| SSM Parameter Store (Standard) | $0 |
| **合計** | **~$1.5/月** |

---

## 5. 参考ドキュメント

- [Invoke a Lambda function from an alarm - Amazon CloudWatch](https://docs.aws.amazon.com/AmazonCloudWatch/latest/monitoring/alarms-and-actions-Lambda.html)
- [Amazon CloudWatch alarms adds AWS Lambda as an alarm state change action (2023-12)](https://aws.amazon.com/about-aws/whats-new/2023/12/amazon-cloudwatch-alarms-lambda-change-action/)
- [Bedrock Converse API - Tool use](https://docs.aws.amazon.com/bedrock/latest/userguide/tool-use-inference-call.html)
- [Amazon CloudWatch Logs Insights - PPL & Query Results Summarization (2025-06)](https://aws.amazon.com/about-aws/whats-new/2025/06/amazon-cloudwatch-logs-insights-query-results-summarization-opensearch-ppl-enhancements/)
- [SSM Parameter Store - SecureString parameters](https://docs.aws.amazon.com/systems-manager/latest/userguide/sysman-paramstore-securestring.html)
