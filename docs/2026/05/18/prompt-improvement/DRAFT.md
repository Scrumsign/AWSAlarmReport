# prompt 改善 DRAFT

## 0. このドキュメントの位置づけ

`docs/2026/05/18/mvp-followups-investigation/DRAFT.md` の 3 テーマのうち **テーマ A (prompt 改善)** の独立 DRAFT。

前提として **テーマ B (テストハーネス) の PLAN が先に走る** ([test-harness-and-analyzer-split/PLAN.md](../test-harness-and-analyzer-split/PLAN.md))。`src/test.py` + `src/fixtures/*/` が prompt 改善ループの実走道具になるため、それが揃わないうちは「目で見て直す」ループが回らない。

---

## 1. ゴール / 非ゴール

### ゴール

- 現状の prompt ([src/utils/prompt.py](../../../../src/utils/prompt.py)) の **何が「微妙」か** を具体パターンとして言語化する
- 改善の打ち手を選定し、test.py + fixture で「直す → 流す → 目で確認」のループを回す
- ループを 1〜2 巡回し、「現状より明確に良い」と人手判定できる prompt にする

### 非ゴール

- 自動評価メトリクス (BLEU / Rouge / LLM-as-judge 等) の導入。判定は人手
- ケース分類器 (alarm 種別から timeout / dependency / generic を自動判別) の自動化。**ただし手動で分類して system prompt を切替える程度の改修はスコープ内**
- 多言語対応 / 出力フォーマット変更 (Discord Embed 仕様変更を伴う改修)
- prompt 以外 (Insights クエリ・時間窓・retry) のチューニング

---

## 2. 現状の構造把握

prompt は 2 つに分かれる:

| 要素 | 場所 | 役割 |
|---|---|---|
| system prompt | [prompt.py:17-73](../../../../src/utils/prompt.py#L17-L73) | 役割 / 制約 / suggested_actions の縛り / ヒント / 出力 JSON Schema |
| ケース別追加指示 | [prompt.py:96-137](../../../../src/utils/prompt.py#L96-L137) | generic / timeout / dependency 用の追加指示 (system に embedded) |
| user prompt | [prompt.py:140-222](../../../../src/utils/prompt.py#L140-L222) | Alarm メタ + 圧縮ラベル形式のログ系列 |

呼び出し側 ([main.py:282](../../../../src/main.py#L282)) は **`render_prompt_case_generic()` 固定**。timeout / dependency 用テンプレートは死蔵中。

---

## 3. 「微妙」の言語化 — 候補リスト

何が壊れているかをユーザーと擦り合わせるための仮説リスト。実 fixture を流す前にこれを潰す。

| ID | 失敗モード仮説 | 検証方法 |
|---|---|---|
| F1 | summary が長すぎ / 60 字制約守られない | fixture 1 件流して文字数測定 |
| F2 | root_cause_hypothesis が「ValueError が起きました」レベルで浅い | 出力本文を目視 |
| F3 | suggested_actions に **コードベース固有の言及** が混入 (関数名・変数名) | NG ワード grep |
| F4 | suggested_actions が AWS 操作レベルになってない (「リトライ実装」等の実装提案) | 目視 |
| F5 | severity / confidence の付け方に一貫性がない | 同シナリオを 3 回流して severity 揺らぎを観察 |
| F6 | 空ログ (Case 1) に対して LLM が「ログがありません」とだけ返す | no_logs fixture を流して S3 確認の言及があるか |
| F7 | generic 固定なので timeout / dependency 系で精度が落ちる | サブシナリオ別 fixture で出力比較 |
| F8 | 出力 JSON のスキーマ逸脱 (引用符・ネスト崩れ) | parse_report で例外になる頻度 |
| F9 | 日本語の口調・冗長 (「〜してください」連発) | 目視 |
| F10 | ヒント節 ([prompt.py:57-59](../../../../src/utils/prompt.py#L57-L59)) が固定 2 行で、対象 Lambda 以外で誤誘導 | 別 Lambda を対象にすることを想定したとき矛盾するか確認 |

→ **要ユーザー判断**: F1〜F10 のうち、実体験として「これ」と思うのはどれ? 上位 2〜3 個に絞ると打ち手が決まる。

---

## 4. 改善の打ち手 (調査対象)

### A. system prompt 構造

- A-1. 役割定義 ([prompt.py:19-21](../../../../src/utils/prompt.py#L19-L21)) を「何を出すか」中心に書き直すか
- A-2. 制約節 ([prompt.py:29-35](../../../../src/utils/prompt.py#L29-L35)) と suggested_actions 縛り ([prompt.py:42-56](../../../../src/utils/prompt.py#L42-L56)) の重複整理
- A-3. ヒント節 ([prompt.py:57-59](../../../../src/utils/prompt.py#L57-L59)) を Case 1 (空ログ) 向けに明示化:
  - 例: 「**logs が空の場合は、まず対象 Lambda の S3 入力ファイルがアップされているか確認するよう促すこと**」を明文化
- A-4. 出力 JSON Schema ([prompt.py:61-72](../../../../src/utils/prompt.py#L61-L72)) のフィールド構造を維持するか変えるか (例: severity を出力させる価値はあるか)

### B. ケース別追加指示の活性化

- B-1. main.py を Case 1 (空ログ) / Case 2 (ログあり) で system prompt を切替える形にするか
  - Case 1 用に新規追加指示テンプレートを書く: `render_prompt_case_no_logs()`
  - Case 2 はまず `render_prompt_case_generic()` 維持
- B-2. timeout / dependency 用は **当面塩漬け** (テーマ A スコープ外)。fixture が育って必要性が見えたら活性化

### C. user prompt の圧縮形式

- C-1. 現状の圧縮ラベル形式 ([prompt.py:140-222](../../../../src/utils/prompt.py#L140-L222)) は読みやすいか / トークン効率は? (コスト見積もり PLAN との接続点)
- C-2. trace の全文を入れている部分 ([prompt.py:211-214](../../../../src/utils/prompt.py#L211-L214)) を上位 N 行に切り詰めるかどうか
- C-3. 同一 request_id でログ複数件あるときの並び (現状 `@timestamp desc`) を「フェーズ順 = 時系列 asc」に変える価値があるか

### D. severity / confidence の整流化

- D-1. severity 判定基準 (LOW / MEDIUM / HIGH) の境界を prompt 内で明文化するか
- D-2. confidence の判定基準を明文化するか (現状 prompt は「捏造せず confidence: low」のみ規定)

---

## 5. 改善ループの回し方

test-harness PLAN が動いている前提で:

1. **ベースライン取得**: 現状 prompt のまま `python src/test.py` を全 fixture で流し、出力をコピーして `prompt-improvement/baseline-output.md` に保存
2. **打ち手 1 つ選んで適用**: §4 から 1 つ (例: A-3 のヒント節明示化) を [src/utils/prompt.py](../../../../src/utils/prompt.py) に反映
3. **再走 + 目視比較**: 同じ fixture で test.py を流し、baseline と差分を目視
4. **採否判定**: 明らかに良い → そのまま、微妙 → revert または別案
5. 1〜4 を打ち手ごとに繰り返す

baseline と各 iteration の出力は手動で `.md` に貼り付けて履歴を残す (snapshot ツールは入れない方針なので)。

---

## 6. オープン項目

- [ ] §3 の F1〜F10 のうち、ユーザーが実体験で「これ」と感じている上位 2〜3 個
- [ ] §4-B Case 1 用に `render_prompt_case_no_logs()` を新設するか / system prompt 1 本でヒント節強化のみで済ますか
- [ ] §4-C trace の切り詰めはコスト見積もり PLAN と統合して検討するか (token 削減直結のため)
- [ ] ベースライン取得用に Case 2 fixture (`handler_value_error`) を架空でなく実ログで作りたい — sanitize 済み実ログがもらえるか
- [ ] このループを「1 巡何時間」想定で回すか (1 打ち手あたり Bedrock × fixture 件数 ぶんの課金が発生)
