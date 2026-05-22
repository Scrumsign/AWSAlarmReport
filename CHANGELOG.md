# Changelog

このプロジェクトの主な変更点を記録します。

形式は [Keep a Changelog 1.1.0](https://keepachangelog.com/ja/1.1.0/) に、バージョニングは [Semantic Versioning 2.0.0](https://semver.org/lang/ja/) に従います。

## [Unreleased]

MVP 初版開発中。最初のリリースタグを切るまでの内容はすべて本セクションに集約します。

### Added

- Reporter Lambda エントリポイント `src/main.py`
  - 単一 handler `main(event, _context)`。`os.environ` から全設定を取得して実行
  - Alarm パース / 時間窓導出 / CloudWatch Logs Insights クエリ / Bedrock Converse / Discord 投稿の処理単位をコメントブロックで明示しつつインライン展開
- Logs Insights 固定クエリ定数 `INSIGHTS_QUERY`（アプリ内部ロジックとして `src/main.py` に保持）
- Bedrock Converse API 呼び出し
  - モデル: Claude Sonnet 4.6 (`jp.anthropic.claude-sonnet-4-6` inference profile)
  - JSON 形式レポート（`summary` / `severity` / `root_cause_hypothesis` / `suggested_actions`）
- Discord Webhook への Embed 投稿
  - severity → カラーのマッピング `DISCORD_SEVERITY_COLOR`（LOW=緑 / MEDIUM=黄 / HIGH=赤）
- プロンプト組み立て `src/utils/prompt.py`（`render_prompt_system_base` / `render_prompt_case_generic` / `render_prompt_case_timeout` / `render_prompt_case_dependency`）
- 環境別 config: `deploy/config.yml`（test）/ `deploy/config-prod.yml`（production）。非機密 AWS 構成（CloudWatch Logs / Bedrock パラメータ）の Source of Truth。CI/デプロイパイプライン専用ファイル（Lambda 実行時は参照しない）として `deploy/` 配下に集約
- Lambda コンテナイメージ用 `docker/Dockerfile`（handler `main.main`）
- GitHub Actions デプロイワークフロー `.github/workflows/deploy.yml`
  - OIDC で AWS 認証 → ECR push → Lambda 環境変数同期 → Lambda 関数コード更新の自動化
  - `test` ブランチ push → GitHub Environment `test` → テストアカウント `HDW_Lambda_Notifier_0001` を更新（`deploy/config.yml` 参照）
  - `main` ブランチ push → GitHub Environment `production` → 本番 Lambda を更新（`deploy/config-prod.yml` 参照）
  - 非機密 AWS 構成は config YAML から、機密 (`DISCORD_WEBHOOK_URL`) は GHA Secret から取得して `update-function-configuration --environment` で Lambda 環境変数へ投入
- 設計ドキュメント
  - [docs/2026/05/15/lambda-error-report-mvp/DRAFT.md](docs/2026/05/15/lambda-error-report-mvp/DRAFT.md)
  - [docs/2026/05/15/lambda-error-report-mvp/PLAN.md](docs/2026/05/15/lambda-error-report-mvp/PLAN.md)
  - [docs/2026/05/15/report-content-by-case/DRAFT.md](docs/2026/05/15/report-content-by-case/DRAFT.md)
- 開発者向けドキュメント: [README.md](README.md), [CONTRIBUTING.md](CONTRIBUTING.md)

### Notes / 未確定事項

- ケース別プロンプト分岐（タイムアウト・OOM 等）は未実装。現状は Generic ケース固定。
- IaC（CloudWatch Alarm / Lambda 本体定義）は未整備。`PLAN.md` の YAML スニペットを起点に別途整備予定（IAM ロールに必要な権限は `lambda:UpdateFunctionConfiguration` / `lambda:UpdateFunctionCode` / `lambda:GetFunction` ほか）。
- 単体テストは未追加（`pytest` は依存に含めるのみ）。

[Unreleased]: https://github.com/scrumsign/HDW_Notify/compare/HEAD
