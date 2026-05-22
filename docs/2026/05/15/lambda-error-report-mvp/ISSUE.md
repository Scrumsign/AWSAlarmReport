## 概要
AWS のエラー通知発生時に、関連ログを Claude で要約し Discord に通知する PoC を実装する。

エラー → ログ収集 → 要約 → Discord 通知 までの最小構成を動かし、運用に耐えるかを判断する。

---

## ゴール (PoC)
- AWS でエラーが発生した際に、関連ログを自動収集し、Claude による要約結果を Discord チャンネルに投稿する
- 担当者が Discord 通知を見るだけで、エラーの概要と原因仮説を把握できる状態にする

---

## 構成イメージ

```
[エラー発生]
   ↓
[CloudWatch Alarm / SNS]
   ↓
[Lambda]
   ├─ CloudWatch Logs から関連ログ取得
   ├─ Claude API でログ要約
   └─ Discord Webhook へ投稿
```

> **実装上の設計変更 (2026-05-19 時点)**: SNS は採用せず、CloudWatch Alarm が Lambda を **直接 invoke** する構成に変更。Alarm event を Lambda が直接受け取る (src/main.py)。SNS を挟まない分シンプルでレイテンシも短い。

---

## タスク

### 事前準備
- [ ] PoC 対象とするエラー(対象サービス・対象アラーム)を 1 つ決める
- [ ] Discord に PoC 用チャンネル & Webhook URL を用意
- [ ] Claude API キー(または Bedrock 利用権限)の確保
- [ ] 必要な IAM ロール / 権限の整理(Lambda → CloudWatch Logs read, Secrets Manager read 等)

### 実装
- [ ] SNS → Lambda のトリガー設定
- [ ] Lambda 実装
  - [ ] SNS メッセージから対象リソース・発生時刻を抽出
  - [ ] CloudWatch Logs から該当時刻前後 ±N 分のログを取得(filter pattern 検討)
  - [ ] ログを Claude へ送って要約(プロンプト設計)
  - [ ] 要約結果を Discord Webhook へ投稿
- [ ] シークレット(API キー / Webhook URL)を Secrets Manager or 環境変数 + KMS で管理

### プロンプト設計
- [ ] 要約フォーマットを固定化
  - 例: `エラー概要 / 発生時刻 / 想定原因 / 関連ログ抜粋 / 推奨される次アクション`
- [ ] トークン上限を考慮したログの前処理(切り詰め / フィルタ)

### Discord 通知フォーマット
- [ ] Embed を使った見やすいレイアウト
- [ ] 重要度(色)・タイムスタンプ・該当 LogGroup へのリンクを含める

### 動作確認
- [ ] テストエラーを意図的に発生させて、通知までの一連の動作を確認
- [ ] ログ量が多い場合の挙動を確認(切り詰め・要約品質)
- [ ] 通知遅延・コストを計測

---

## 完了条件 (Acceptance Criteria)
- [ ] 対象エラー発生 → Discord にClaude要約が投稿される、までが自動で動作している
- [ ] 要約内容が一次調査の役に立つレベルになっている(人手評価)
- [ ] 想定コスト(月額)・遅延時間が記録されている
- [ ] 本実装に進むか / 改善点 / 棚上げかの判断材料がまとまっている

---

## 非対応 (Out of Scope)
- 複数エラーパターンへの対応(PoC では 1 種類に限定)
- GitHub Issue 自動起票などの追加アクション
- ログ以外のリソース(メトリクス、トレース等)の参照
- 本番運用に耐える冗長化・監視

---

## 参考
- AWS SNS → Lambda 連携
- CloudWatch Logs Insights / FilterLogEvents API
- Anthropic API もしくは Amazon Bedrock (Claude)
- Discord Webhook