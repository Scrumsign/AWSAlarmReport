# コントリビューションガイド

HDW Notify への変更を行う際の指針をまとめます。詳細な背景・設計判断は [PLAN.md](docs/2026/05/15/lambda-error-report-mvp/PLAN.md) を参照してください。

## 開発フロー

1. **イシュー / 設計の確認**
   - 新機能・仕様変更は、まず `docs/YYYY/MM/DD/<slug>/DRAFT.md` で論点を書き出し、合意が取れたら `PLAN.md` に昇格させる流れを基本とします。
   - 小さなバグ修正・リファクタリングは DRAFT を省略可。コミット / PR の説明で意図が伝わる粒度に留めてください。

2. **ブランチ運用**
   - リリースは `release/vX.X.X`（[SemVer](https://semver.org/lang/ja/)）で切ります。バージョン番号は MAJOR / MINOR / PATCH の意味に従って付与してください。
   - `main` への push をトリガに GitHub Actions が ECR への image push と Lambda 更新まで自動で実行します（[デプロイ](#デプロイ)節参照）。`main` への merge ＝ 本番反映である点に注意してください。

## ローカル環境

セットアップ手順は [README.md](README.md) の「セットアップ (ローカル)」を参照。要点だけ抜粋:

```powershell
python -m venv .venv
.venv\Scripts\Activate.ps1
pip install -r requirements.txt
```

- Python 3.12+（Lambda ランタイムに合わせる）
- AWS 認証情報は環境変数（`AWS_PROFILE` / `AWS_REGION`）またはローカル `.env` で渡す
- 設定値・シークレット（Discord Webhook URL 含む）は本番では Lambda 環境変数、ローカルでは事前に `os.environ` に投入してから実行

ローカル実行時は `src/main.py:main()` にサンプル Alarm event を渡して呼び出します（呼び出し側で event dict と必要な環境変数を用意）。

## コードスタイル

- 言語: Python 3.12。型ヒントは原則必須（公開 API・モジュール境界）。
- import 順序: 標準ライブラリ → サードパーティ → ローカル（`from utils...`、`src` を PYTHONPATH に含める前提の absolute import）。
- フォーマット: PEP 8 ベース。改行・空行・命名は既存コード（`src/main.py`, `src/utils/`）に揃えます。
- docstring: 公開関数・クラスには Google スタイルの docstring を付ける（既存実装が参考）。「何をするか」ではなく「**なぜそうしているか**」「呼び出し側が知るべき制約」を書く。
- コメント: 何をしているかではなく、なぜそうなっているか（非自明な制約・回避策・前提）を残す。コードを読めば分かることは書かない。

### 関数設計の指針

- **関数型ベースを意識する**: 副作用よりも再代入（イミュータブルな値の組み立て）を優先する。状態を書き換えるより、新しい値を返して受け取る側で束ね直す形を基本とする。
- **関数は「データ変換 / 生成」の単位で区切る**: 処理フロー（手順の分割）で関数を切らない。入力 → 出力のマッピングや、特定のデータ構造を生成する単位で 1 関数にする。フロー的な順序付けは呼び出し側に集約する。
- **副作用呼び出しには必ずコメントを付ける**: I/O・外部 API 呼び出し・グローバル状態の書き換え等、副作用を伴う行には「**何が起きるか**（例: CloudWatch Logs Insights クエリ起動 / Discord に POST）」と「**何のために呼ぶか**（例: Alarm 時刻周辺のログ取得のため）」を 1 行で添える。純粋な変換にはコメント不要。

## 設定値の扱い

- **すべての設定値・シークレットは Lambda 関数の環境変数に集約**。Lambda 実行時に `src/main.py:main()` が `os.environ` から取得する。
- Lambda 環境変数への投入は GitHub Actions のデプロイジョブが以下の経路で行う（`.github/workflows/deploy.yml`）:
  - **非機密 AWS 構成** → `deploy/config.yml` (test) / `deploy/config-prod.yml` (production) → デプロイジョブが該当 YAML を読み取って Lambda env var にマップ
  - **機密（Webhook URL）** → GHA Secret `DISCORD_WEBHOOK_URL` → そのまま Lambda env var へ
- 新しい設定値を増やす場合は (1) `src/main.py:main()` の `os.environ` 取得・パース行、(2) `deploy/config.yml` / `deploy/config-prod.yml` 双方、(3) `deploy.yml` の同期ステップ、(4) `README.md` の対応表、を同時に更新する。
- **アプリ内部ロジック（Insights クエリ・severity 色マップ・プロンプト等）は config YAML に出さない**。Python 定数 / モジュールで保持する（例: `src/main.py:INSIGHTS_QUERY`、`src/main.py:DISCORD_SEVERITY_COLOR`、`src/utils/prompt.py`）。「環境ごとに変えたいか」を切り分けの基準にする。
- ローカル実行時も `os.environ` から読むため、`deploy/config.yml` / `deploy/config-prod.yml` の値と Webhook URL を事前に環境変数へ投入してから `src/main.py:main()` を呼び出す。

## テスト

- 単体テストは `pytest` 前提（`requirements.txt` に同梱）。
- boto3 クライアントは `src/main.py:main()` の中で都度生成されます。テストでは `monkeypatch` で `main.main` 自体、または `boto3.client` の戻り値をスタブに差し替える運用とします（モジュールレベルのキャッシュは置きません）。環境変数も `monkeypatch.setenv` で揃える。
- 統合テスト（実 AWS リソース必要）は CI では実行しません。手元での確認手順を PR に記載してください。

## デプロイ

- `main` への push で GitHub Actions（[.github/workflows/deploy.yml](.github/workflows/deploy.yml)）が動作し、ECR への image push と Lambda 更新まで自動で行われます。
- 認証は OIDC（`secrets.AWS_DEPLOY_ROLE_ARN`）。デプロイ先の `LAMBDA_FUNCTION_NAME` / `ECR_REPOSITORY` / `AWS_REGION` は GitHub Environment `production` の variables で管理。
- IaC（Alarm / Lambda 本体）は MVP 段階では未整備。`PLAN.md` の YAML スニペットを起点に別途整備予定。

## CHANGELOG の更新

- ユーザ影響のある変更（仕様・通知内容・設定キー・運用手順）は [CHANGELOG.md](CHANGELOG.md) の `Unreleased` セクションに追記してください。
- 形式は [Keep a Changelog](https://keepachangelog.com/ja/1.1.0/) に従います（`Added` / `Changed` / `Deprecated` / `Removed` / `Fixed` / `Security`）。
- リリースタグを切るタイミングで `Unreleased` をバージョン付きセクションに昇格させます。

## 質問・相談

実装方針で迷ったら、PR を出す前に `DRAFT.md` を書いて議論を立ち上げてください。MVP 段階のため、後戻りコストよりも合意形成の速度を優先します。
