# MVP フォローアップ 調査計画 DRAFT

## 0. このドキュメントの位置づけ

PLAN を書くための **調査** の計画。実装計画 (PLAN) の前段。

MVP ([docs/2026/05/15/lambda-error-report-mvp/PLAN.md](../../15/lambda-error-report-mvp/PLAN.md)) が一通り動いた前提で、次に着手する 3 テーマ:

1. **prompt 改善** — 現状の prompt 出力が「微妙」という主観評価を、計測可能な改善ループに落とす
2. **テスト環境構築** — 現状 tests/ ディレクトリすら存在しないので、何をどの層でテストするか定義する
3. **コスト感の見積もり** — PLAN §4 の概算 ($1.5/月) を、実トークン実測値で再計算し責任者判断の材料にする

各テーマで「何を調べる / 誰に聞く / 何を成果物として出す」を先に決めるのがこの DRAFT の目的。

---

## 1. 共通: 先に答えてほしい質問 (ユーザー宛)

調査の方向を確定するため、以下を確認したい。**ここが決まらないと無駄な調査をする可能性が高い**。

### 1.1 prompt 改善について

- **Q1-1.** 「prompt が微妙」と感じた具体的な出力例はあるか? (Discord に届いた実例 / Bedrock 直叩きの実例 / 想像ベース)
- **Q1-2.** 何が微妙か? 候補:
  - (a) summary / root_cause_hypothesis の内容が浅い・的外れ
  - (b) suggested_actions が AWS 操作レベルになっていない (コード言及してしまう)
  - (c) confidence の付け方が一貫しない
  - (d) ケース分類器を導入していないので generic 固定で当たり外れがある
  - (e) JSON 形式逸脱の頻度
  - (f) 日本語の口調・冗長さ
  - (g) その他
- **Q1-3.** 評価方法の希望: 人手のラベル付け (eval セット作成) か、サンプル数件をその場で見て判断するか
- **Q1-4.** prompt 改善のスコープ: system prompt のみ / user prompt 整形 ([prompt-compact-format](../prompt-compact-format/)) のチューニングも含む / ケース分類器導入まで含む

### 1.2 テスト環境について

- **Q2-1.** 「テスト環境」の指すもの。候補 (複数可):
  - (a) ユニットテスト = pytest + モック (Bedrock / Logs Insights / Discord を mock)
  - (b) ローカル E2E = サンプル alarm event JSON を `main.py` に流す手元実行
  - (c) AWS sandbox E2E = `hdw-test` アカウント (088898720463) に実 Lambda をデプロイして実イベントで通す
  - (d) prompt eval harness = 過去ログサンプル × prompt バリアント の評価基盤
- **Q2-2.** Bedrock 呼び出しを「テストで本当に呼ぶか / record-replay でモックするか」の方針希望
- **Q2-3.** Discord 通知のテスト先 — サンドボックスチャネルは別途用意済みか? (Webhook URL を 1 本追加する形でよいか)
- **Q2-4.** CI を回す前提か (GitHub Actions に pytest job を追加するか) / ローカル実行できればよいか

### 1.3 コスト見積もりについて

- **Q3-1.** 「1M トークンが入力何回分か」の出し方の希望:
  - (a) 現状の prompt.py が出す system + user の **実トークン数** を `tiktoken` 相当で実測して 1M / 平均 を出す
  - (b) AWS の CloudWatch / Bedrock 利用ログから過去分の `inputTokenCount` を集計
  - (c) 両方
- **Q3-2.** 月間アラート発火想定数の前提値 (PLAN §4 は 100/月)。現状の hdw-ingest の実エラー頻度を見て補正するか?
- **Q3-3.** モデル比較対象: Sonnet 4.6 単独 / Sonnet 4.6 vs Haiku 4.5 / Sonnet vs Haiku vs Opus 4.7 まで
- **Q3-4.** コスト指標として何を出す: 月額のみ / アラート 1 件あたり / 1M トークン消費に達するまでの想定日数 / 全部

---

## 2. テーマ A: prompt 改善 — 調査タスク

ゴール: 「今の prompt の何が壊れているか」を再現可能な形で記述し、改善案 (PLAN) を書ける状態にする。

### A-1. 現状の prompt と出力の棚卸し

- [ ] [src/utils/prompt.py](../../../../src/utils/prompt.py) の system / user テンプレートを引用付きで DRAFT に書き出す
- [ ] 既存 LLM 出力例を集める:
  - test 環境の CloudWatch Logs で `bedrock analyzed` のログから過去の `output.message.content` を抽出 (要: Logs Insights query)
  - 過去 Discord チャンネルにポストされた Embed を 5–10 件サンプリング (運用者ヒアリング or Discord ログ参照)
- [ ] 各サンプルに「何が微妙か」のタグを Q1-2 のカテゴリに沿って手作業で振る

### A-2. 失敗パターンの特定

- [ ] 上記タグ集計で、最頻の失敗パターンを 1〜2 個に絞る
- [ ] それが prompt の文面起因か / 入力ログ整形起因か / モデル能力起因かを切り分ける
  - 切り分け方: 同じログを (i) 現状 prompt, (ii) prompt 改良案, (iii) Opus 4.7 にぶつけて出力比較

### A-3. ケース分類器の要否判断

- [ ] [src/main.py:282](../../../../src/main.py#L282) は `render_prompt_case_generic()` 固定。timeout / dependency 用テンプレートが死蔵されている事実を確認
- [ ] 過去アラート 5〜10 件を timeout / dependency / generic に手作業で分類し、generic 固定で精度がどれだけ落ちているか定性評価
- [ ] 分類器 (alarm metric 名 + 直前ログの heuristic) を導入する場合の入出力仕様を素描

### A-4. prompt eval harness の最小設計

- [ ] 入力: `(alarm_event, log_rows, expected_tags)` のフィクスチャ JSON 集
- [ ] 実行: prompt バリアント × フィクスチャ で Bedrock 呼び出し → 出力 JSON 保存
- [ ] 評価軸: (a) JSON スキーマ準拠率, (b) suggested_actions のコード言及 NG ワードヒット率, (c) summary 文字数 60 字上限遵守率, (d) 人手スコア
- [ ] テーマ B (テスト環境) と統合可能か検討 (= eval harness を pytest に乗せるか)

### 成果物

- `docs/2026/05/18/mvp-followups-investigation/prompt-current-state.md` (現状サンプル + 失敗タグ集計)
- 次フェーズで書く `prompt-improvement/PLAN.md` の骨子

---

## 3. テーマ B: テスト環境 — 調査タスク

ゴール: 「どの層で何をテストするか」の戦略を 1 枚にまとめ、最初に書くテストの優先順位を決める。

### B-1. テスト対象の棚卸し

- [ ] [src/main.py](../../../../src/main.py) の関数を「外部 I/O あり / なし」で分類:
  - **pure (mock 不要)**: `_format_window_jst`, `_format_jst`, `_extract_first_request_id`, `_cw_encode_log_group`, `_build_deeplinks_markdown`, `render_prompt_user`, `render_prompt_system_base`, `render_prompt_case_*`
  - **I/O あり**: `main` (boto3 logs / bedrock-runtime, discord_webhook, os.environ), `_post_minimal_embed` (discord_webhook)
- [ ] 各層の優先度判定 (pure はコスパ高く最優先 / I/O は moto + responses で次点 / E2E は最後)

### B-2. ツール選定の調査

- [ ] pytest + pytest-mock の前提でよいか確認 (requirements.txt に追加するか)
- [ ] AWS モック方針:
  - (a) `moto` で boto3 を丸ごとモック
  - (b) `botocore.stub.Stubber` で個別 stub
  - (c) `unittest.mock.patch` で `boto3.client` ごと差し替え
  - → コスト感と読みやすさで (c) → (b) → (a) の順で検討
- [ ] Discord webhook モック: `responses` ライブラリで `webhook.execute()` の HTTP 層を捕捉する形がよさそうか確認
- [ ] Bedrock の record-replay 方針: `vcr.py` 相当のスナップショットを git に入れるか (機密性確認: prompt 内に hdw-ingest のログが残るので公開リポなら要マスキング)

### B-3. ローカル E2E 用 sample event 整備

- [ ] CloudWatch Alarm から実際に送られてくる event JSON の形を AWS docs と Lambda 実ログから再現
  - [ ] test 環境の CloudWatch Logs で `aws lambda invoke` 履歴を漁って実 event を 1 つ pickle
- [ ] その event を `python -m src.main` 相当で叩けるよう `scripts/local_invoke.py` の有無を確認 (なければ作る方針)

### B-4. AWS sandbox 環境の現状確認

- [ ] [deploy/config.yml](../../../../deploy/config.yml) を見ると test 用 config は既存 (hdw-test 088898720463, Lambda `HDW_Backend_Processor_0001` 監視)
- [ ] 確認事項:
  - [ ] test 環境の Reporter Lambda は既にデプロイされているか
  - [ ] test 用 Discord チャンネル & Webhook URL が存在するか (Q2-3 と重複)
  - [ ] テスト用に意図的にエラーを発生させる手段はあるか (例: `HDW_Backend_Processor_0001` に invalid input を投げる仕組み)

### B-5. CI 統合の要否

- [ ] `.github/workflows/` を確認 (存在するか / pytest job を増やせるか)
- [ ] Bedrock を呼ぶテストは CI で実行するか / ローカルのみか (コスト & secret 配布の観点)

### 成果物

- `docs/2026/05/18/mvp-followups-investigation/test-strategy-survey.md` (層別マトリクス + ツール選定理由)
- 次フェーズで書く `test-environment/PLAN.md` の骨子

---

## 4. テーマ C: コスト見積もり — 調査タスク

ゴール: 「Sonnet 4.6 で月 N 件運用したらいくらか / 1M トークンが入力何回分か」を実測値ベースで出す。

### C-1. 入力トークン実測

- [ ] 計測対象: `render_prompt_system_base(*render_prompt_case_generic())` の出力 (system prompt) + `render_prompt_user(...)` の出力 (user prompt)
- [ ] 計測ツール: Anthropic 公式 token counter (Bedrock の `count_tokens` API or anthropic SDK の `count_tokens`)。tiktoken は Claude 系で誤差出るので避ける
- [ ] 入力サンプル:
  - (a) 最小: log_rows = 1 件 (短い exception)
  - (b) 典型: log_rows = 10 件 (平均的な hdw-ingest ログ 1 行 ~300 トークン想定)
  - (c) 最大: log_rows = 50 件 (Insights query の `limit 50` 上限)
- [ ] ケース別 (generic / timeout / dependency) でも system prompt サイズ差を測る

### C-2. 出力トークン実測

- [ ] 上記入力で実際に Bedrock を叩き、`output.message` のトークン数と JSON 内容長を記録
- [ ] `max_tokens=1024` ([deploy/config.yml:21](../../../../deploy/config.yml#L21)) が妥当か (実出力が常に 512 程度なら下げてコスト圧縮可)

### C-3. 1M トークン = 入力何回分 計算

- [ ] 入力単価で計算 ($3 per Mtok = $3/1,000,000 tok):
  - 入力 平均 X tok/回 → 1M / X = 月 Y 回 ≈ ? アラート
- [ ] 出力単価で同様に ($15 per Mtok)
- [ ] 出力: 「Sonnet 4.6 で入力 1M トークン = 約 N 回のアラート」「= 月額 $Z」の表

### C-4. モデル比較

- [ ] Sonnet 4.6 ($3/$15)、Haiku 4.5 ($1/$5 概算 — 要 AWS pricing page 確認)、Opus 4.7 ($15/$75 概算 — 要確認) で同じ入力数を流したときの月額を表で比較
- [ ] 注: Opus 4.7 は test 環境で AccessDenied 履歴あり ([docs/2026/05/15/.../910c183](../../15/bedrock-opus-model-access-denied/)) — 利用可否も含めて要確認

### C-5. その他コスト要素

- [ ] CloudWatch Logs Insights スキャン量: test/prod のログ流量から実値で推定 (PLAN.md §4 は 1GB/月 仮置き)
- [ ] Lambda invocations + duration: ARM/x86, memory size, 平均実行時間 (Bedrock 同期呼びで数秒) を実測
- [ ] CW Alarm $0.10, SSM 廃止済み ($0)、ECR ストレージ (image size 確認要)

### 成果物

- `docs/2026/05/18/mvp-followups-investigation/cost-estimate.md` (実測トークン表 + モデル比較表 + 月額レンジ)
- これが「責任者の最終判断材料」になるので、結論 1 ページ + 詳細別ページの構成にする

---

## 5. 全体スケジュール (調査フェーズのみ)

| Step | 内容 | 想定所要 | ブロッカー |
|---|---|---|---|
| 0 | 質問 (§1) をユーザーに聞く | 〜0.5h | — |
| 1 | A-1 / B-1 / C-1 を並行 (現状棚卸し) | 〜2h | 過去 LLM 出力サンプルが手に入るか |
| 2 | A-2〜A-4, B-2〜B-5, C-2〜C-5 を並行調査 | 〜半日 | Bedrock 実呼びの可否 (Q2-2) |
| 3 | 3 テーマそれぞれの成果物 markdown を書く | 〜半日 | — |
| 4 | 3 テーマの優先順位と次の PLAN 化スコープをユーザーと合意 | 〜0.5h | — |

調査が終わったら、テーマごとに別々の `PLAN.md` を書く (MVP PLAN と同じ形式)。

---

## 6. オープン項目 / 確認したいこと

- [ ] §1 の質問群への回答
- [ ] 過去の Discord 通知 / Bedrock 出力サンプルへのアクセス方法
- [ ] hdw-test アカウントで Bedrock 呼び出しを「調査目的で」叩くことに対する予算上限の合意
- [ ] このドキュメントを `DRAFT.md` のまま反復するか、`PLAN.md` に格上げするタイミングの基準
