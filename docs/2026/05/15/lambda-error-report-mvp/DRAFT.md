---
title: Lambda失敗ログ → LLM分析 → Discord通知 (MVP)
date: 2026-05-15
status: draft
type: architecture
scope: mvp
author: t.kimura@scrumsign.com
tags:
  - aws-lambda
  - cloudwatch-alarm
  - bedrock
  - claude
  - discord
  - log-analysis
  - reporting
requirements:
  - LLM活用
  - Discord連携
  - Lambda失敗時のログレポーティング
components:
  - cloudwatch-alarm
  - reporter-lambda
  - bedrock-converse-api
  - cloudwatch-logs-insights
  - discord-webhook
  - ssm-parameter-store
decisions:
  trigger: cloudwatch-alarm-direct-lambda-invoke
  compute: self-built-reporter-lambda
  notification: discord-webhook
  llm: bedrock-converse-claude-sonnet-4-6
estimated_cost_usd_per_month: 1.5
---

# Lambda失敗ログ → LLM分析 → Discord通知 (MVP)

## 1. 全体像・概要

### アーキテクチャ図

```
┌─────────────────────────────────────────────────────────────────┐
│                                                                  │
│   S3 ─► [既存] 処理Lambda ─► CloudWatch Metrics (Errors)         │
│                                       │                          │
│                                       ▼                          │
│                              ┌─────────────────┐                 │
│                              │  CW Alarm       │                 │
│                              │  Errors >= 1    │                 │
│                              └─────────────────┘                 │
│                                       │                          │
│                            (Lambda Action 直接invoke)            │
│                                       │                          │
│                                       ▼                          │
│                              ┌─────────────────┐                 │
│                              │ Reporter Lambda │                 │
│                              │ (自前)          │                 │
│                              └─────────────────┘                 │
│                                       │                          │
│            ┌──────────────────────────┼──────────────────────┐   │
│            ▼                          ▼                      ▼   │
│   ┌───────────────┐         ┌───────────────┐        ┌──────────┐│
│   │ Logs Insights │         │ Bedrock       │        │ Secrets  ││
│   │ (期間内ログ)  │         │ Converse API  │        │ Manager  ││
│   └───────────────┘         │ (Claude)      │        │ (WebHook)││
│                             └───────────────┘        └──────────┘│
│                                       │                          │
│                                       ▼                          │
│                              ┌─────────────────┐                 │
│                              │ Discord Webhook │                 │
│                              └─────────────────┘                 │
│                                                                  │
└─────────────────────────────────────────────────────────────────┘
```

### 要件マッピング

| 要件 | 担当コンポーネント |
|---|---|
| ① LLM活用 | Bedrock Converse API (Claude) |
| ② Discord連携 | Discord Webhook (Secrets Manager管理) |
| ③ Lambda失敗時のログレポーティング | CW Alarm → Reporter Lambda → Logs Insights |

### 追加リソース一覧（既存Lambdaを除く）

| リソース | 個数 | 役割 |
|---|---|---|
| CloudWatch Alarm | 1 | トリガー |
| Lambda Permission | 1 | Alarm→Lambda許可 |
| Reporter Lambda | 1 | 分析・通知の実行主体 |
| IAM Role (Reporter用) | 1 | Logs/Bedrock/Parameter Store権限 |
| SSM Parameter (SecureString) | 1 | Discord Webhook URL保持 |

→ **追加5リソース**で完結。SAMで1テンプレ、デプロイ即完了レベル。

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
    AlarmActions:
      - !GetAtt ReporterFunction.Arn
```

> **要件**: ③ Lambda失敗時のレポーティング
>
> **判断**: Lambda Destinationsではなく **CloudWatch Alarm** を採用
>
> **根拠**:
> - 既存処理Lambdaに**改修を入れない**（Destinationsだと `OnFailure` 設定が要る）
> - Throttle/Concurrency問題など、Destinationsでは拾えない**死角もカバー可能**（将来Alarm追加で拡張）
> - 閾値・連続N回などの**ノイズ抑止がインフラ層で完結**
> - Alarmの「集計値しか持たない」弱点は後段のReporter+LLMで補完できる前提

> **注**: 1分粒度・1件閾値で **検知遅延≒1分**。リアルタイム性が今後要件化したらDestinations経路を追加する余地あり。

---

### 2.2 Action: Lambda Direct Invoke

```yaml
ReporterPermission:
  Type: AWS::Lambda::Permission
  Properties:
    FunctionName: !Ref ReporterFunction
    Action: lambda:InvokeFunction
    Principal: lambda.alarms.cloudwatch.amazonaws.com   # ← 重要
    SourceAccount: !Ref AWS::AccountId
    SourceArn: !GetAtt ErrorsAlarm.Arn                  # Confused Deputy対策
```

> **要件**: 構成のシンプルさ（管理しやすさ）
>
> **判断**: SNSを挟まず **Alarm → Lambda 直接invoke**
>
> **根拠**:
> - 通知先がDiscord 1経路のみ。SNSのファンアウトは**現時点で不要**
> - リソース1個（SNS Topic）削減、IAM/Subscription管理も削減
> - 遅延も数十ms短縮
> - 将来メール等でファンアウトが要件化したら、SNS差し込みは破壊的変更にならない

> **注**: principalは `lambda.alarms.cloudwatch.amazonaws.com`（`events.`や`sns.`と紛らわしいので注意）。`SourceAccount` + `SourceArn` 両方指定が**現行AWS推奨**（confused deputy対策）。

---

### 2.3 Compute: 自前Reporter Lambda

```python
# 疑似コード
def handler(event, _):
    alarm = parse_alarm(event)              # alarmName, time, state, configuration
    window = derive_time_window(alarm)      # ALARM遷移時刻を中心に±N分

    logs = run_insights_query(              # Logs Insights API
        log_group="/aws/lambda/hdw-ingest",
        query=ERROR_QUERY,
        start=window.start, end=window.end,
    )

    report = bedrock_converse(              # Bedrock Converse API
        model="claude-sonnet-4-6",
        system=SYSTEM_PROMPT,
        messages=[{"role": "user", "content": format_input(alarm, logs)}],
    )

    post_to_discord(                        # Webhook POST
        webhook_url=get_secret("discord-webhook"),
        embed=build_embed(alarm, report),
    )
```

> **要件**: ①LLM活用 + ②Discord連携 + ③ログレポーティング を1か所に集約
>
> **判断**: **自前Reporter Lambda** で全責務を担う（Step Functions / Bedrock Agents / DevOps Agentは採用しない）

#### 自前 vs AWS純正の比較（なぜ自前か）

| 項目 | 自前Reporter | AWS純正(Investigations/DevOps Agent) | Step Functions |
|---|---|---|---|
| Discord連携 | **◎ 自由** | ✕ Slack/Email等のみ | ○ HTTP Task必要 |
| プロンプト/ロジックのカスタム | **◎** | △ 制約あり | ○ |
| デバッグ・反復速度 | **◎** | △ | ✕ ASLが重い |
| 将来のagenticループ実装 | **◎ 自然** | △ 純正の範囲内 | ✕ Choice地獄 |
| コスト | **◎ 月$1未満** | コスト体系不透明 | △ 状態遷移課金 |
| AWS純正機能の取り込み余地 | **○ 後で食わせられる** | — | △ |

**自前を選んだ核心的な理由**:
- 純正の `CloudWatch Investigations` は強力だが **Discord通知に対応していない** ため要件②が満たせない
- 要件3つ（LLM/Discord/Lambda失敗）を**最低コスト・最高制御性**で満たすには自前Lambdaが最適
- 将来Investigationsの**結果を入力として食わせる**形での統合は十分可能（破壊的変更にならない）

> **MVP段階で「入れない」もの**（後で容易に追加可能）:
> - DDB dedupe → 必要になったら追加
> - Agentic tool_useループ → MVPは単発Bedrock呼び出し
> - S3レポート保存 → 履歴参照が要件化したら追加
> - 過去レポート検索ツール → S3保存とセット

---

### 2.4 Log Query: CloudWatch Logs Insights

```
fields @timestamp, level, request_id, error_class, error_message, stack
| filter level in ["ERROR", "FATAL"]
| sort @timestamp desc
| limit 50
```

> **要件**: ③ レポーティングのインプット = ログ取得
>
> **判断**: **旧Insights Query Language** で開始（OpenSearch PPLは将来検討）
>
> **根拠**:
> - 既存ログがJSON化済みでフィールド抽出が綺麗に効く
> - MVPでは**JOIN/SubQuery不要**（単一LogGroupの該当期間ERROR列挙で十分）
> - PPLは強力だが学習コストあり、**必要になってから移行**
>
> **時間窓**: `alarmData.state.timestamp` を中心に **−5分 〜 +1分** を取得（Alarm評価期間+バッファ）

---

### 2.5 LLM: Bedrock Converse API

```python
client.converse(
    modelId="anthropic.claude-sonnet-4-6-20260101-v1:0",
    system=[{"text": SYSTEM_PROMPT}],
    messages=[{
        "role": "user",
        "content": [{"text": f"Alarm: {alarm}\n\nLogs:\n{logs_json}"}],
    }],
    inferenceConfig={"maxTokens": 1024, "temperature": 0.2},
)
```

> **要件**: ① LLM活用
>
> **判断**: Bedrock **Converse API**（InvokeModel APIでなく）+ **Claude Sonnet 4.6**
>
> **根拠**:
> - Converse APIはモデル切替が容易、tool_use対応も標準（**将来agenticループへ拡張容易**）
> - Sonnet 4.6 は分析タスクにバランス良い（Haiku 4.5への切替もmodelId変えるだけ）
> - 出力をJSON強制（`{summary, severity, root_cause_hypothesis, suggested_actions}`）してDiscord Embed化を機械的に
>
> **MVPは単発呼び出し**。tool_useループは**後で system prompt と tools 渡すだけで有効化可能**な形にしておく。

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

> **要件**: ② Discord連携
>
> **判断**: Discord **Incoming Webhook**（Botは作らない）
>
> **根拠**:
> - 通知のみで双方向不要 → Webhookで十分
> - Bot常駐の運用負荷ゼロ
> - WebhookURLは **SSM Parameter Store (SecureString)** で管理（コードに直書きしない、KMS暗号化）

> **シークレット保管先の選定 — Parameter Store vs Secrets Manager**:
>
> | 項目 | **Parameter Store (SecureString)** ✅採用 | Secrets Manager |
> |---|---|---|
> | 月額 | **$0**（Standard, 4KB以下, 1万件まで無料） | $0.40/secret/月 + API呼び出し課金 |
> | KMS暗号化 | ◎（default key or CMK） | ◎（default key or CMK） |
> | IAMアクセス制御 | ◎ | ◎ |
> | 監査 (CloudTrail) | ◎ | ◎ |
> | 自動ローテーション | ✕ | ◎ |
> | クロスリージョン複製 | 手動 | 自動 |
> | クロスアカウント resource policy | 限定的 | 容易 |
> | 最大サイズ | 4KB | 64KB |
>
> **Parameter Store を選んだ根拠**:
> - 自動ローテーションは**Discord側が非対応**のため Secrets Manager の最大の利点が活かせない
> - クロスリージョン/クロスアカウント要件なし
> - Webhook URLは~120文字なので4KB上限は余裕
> - 暗号化・IAM・監査などのセキュリティ機能は両者で同等
> - **月$0.40の節約 × 機能的に同等** ⇒ Parameter Store が合理的選択
>
> 将来「自動ローテが要件化」「複数アカウント間で共有が必要」となった場合は Secrets Manager への移行を検討（IAM action名の変更程度で済む）。

> **セキュリティ注記 — 現状の構成で十分安全である根拠**:
>
> Discord WebhookはOIDC等のフェデレーションに非対応で、URL自体がトークンとして機能する古典的モデル。一見不安に見えるが、現実の攻撃ベクトルは限定的。
>
> | 攻撃ベクトル | 現実性 | 対策状況 |
> |---|---|---|
> | **ブルートフォース** (URLトークン推測) | **現実的に不可能** — トークンが十分長いランダム文字列のため総当たりが計算量的に成立しない | 対策不要 |
> | **URL漏洩** (悪意あるnpm/PyPI/RubyGemsパッケージへのハードコード、コード公開時の混入、ログ流出等) | **これが唯一の現実的リスク** | Secrets Manager管理＋IAMアクセス制御で対応済み |
>
> → 既知のWebhook関連インシデントはすべて「URL漏洩」起因。**ブルートフォースによる侵害の事例はほぼ皆無**。
>
> したがって本MVPの構成（Secrets Manager + 最小IAM）で十分。OIDCプロキシ等の過剰な対策は不要。

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
            - Effect: Allow                                  # Logs Insights実行
              Action: [logs:StartQuery, logs:GetQueryResults, logs:StopQuery]
              Resource: !Sub "arn:aws:logs:*:*:log-group:/aws/lambda/hdw-ingest:*"
            - Effect: Allow                                  # Bedrock呼び出し
              Action: bedrock:InvokeModel
              Resource: !Sub "arn:aws:bedrock:*::foundation-model/anthropic.claude-sonnet-4-6*"
            - Effect: Allow                                  # Webhook URL取得 (Parameter Store)
              Action: ssm:GetParameter
              Resource: !Sub "arn:aws:ssm:${AWS::Region}:${AWS::AccountId}:parameter/hdw-notify/discord-webhook"
            - Effect: Allow                                  # SecureString復号 (KMS default key使用時は不要)
              Action: kms:Decrypt
              Resource: !Sub "arn:aws:kms:${AWS::Region}:${AWS::AccountId}:key/<key-id>"
              Condition:
                StringEquals:
                  kms:ViaService: !Sub "ssm.${AWS::Region}.amazonaws.com"
```

> **要件**: 信頼性 / セキュリティ
>
> **判断**: **対象LogGroup固定 / 特定モデル限定** で最小権限
>
> **根拠**:
> - エージェントLambdaがLogsを広く読めるのはリスク → 対象LogGroupに**ARN絞り込み**
> - Bedrockは特定モデルARNに絞れる → 想定外モデル呼び出しの防止＋コスト天井
> - Logs書き込み権限はLambda標準ロールから自動付与

---

## 3. 拡張パス（MVP後の追加候補）

MVPを動かして「足りない」が見えてからの追加リスト。**MVPには入れない**。

| 追加 | 効くタイミング |
|---|---|
| DDB dedupe (TTL付き) | 同一エラー連発で通知が溢れる時 |
| Agentic tool_useループ | 単発分析の精度に不満を感じた時 |
| S3にmd保存 + DDBインデックス | 「過去事例を引きたい」要件が出た時 |
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
| Logs Insights クエリ | <$0.50 (1GB scan/月想定) |
| Bedrock (Sonnet, 100呼び出し×2K入力/0.5K出力) | ~$0.80 |
| SSM Parameter Store (SecureString, Standard tier) | **$0** |
| **合計** | **~$1.5/月** |

---

## 5. 参考ドキュメント

- [Invoke a Lambda function from an alarm - Amazon CloudWatch](https://docs.aws.amazon.com/AmazonCloudWatch/latest/monitoring/alarms-and-actions-Lambda.html)
- [Amazon CloudWatch alarms adds AWS Lambda as an alarm state change action (2023-12)](https://aws.amazon.com/about-aws/whats-new/2023/12/amazon-cloudwatch-alarms-lambda-change-action/)
- [Bedrock Converse API - Tool use](https://docs.aws.amazon.com/bedrock/latest/userguide/tool-use-inference-call.html)
- [Amazon CloudWatch Logs Insights launches Query Results Summarization and OpenSearch PPL enhancements (2025-06)](https://aws.amazon.com/about-aws/whats-new/2025/06/amazon-cloudwatch-logs-insights-query-results-summarization-opensearch-ppl-enhancements/)
