# コスト ラフ試算 (2026-05-19, Phase A + SPEC v1.5 fixture ベース)

> **位置づけ**: Phase A baseline + SPEC v1.5 で拡張した 85-log fixture の実測トークン数を使った **暫定試算**。
> Phase E (TODO §9 Step 3) で正式な実測スクリプト + 単価検証 + AWS 他コストを乗せた `cost-measurements-2026-05-19.md` に発展させる。
>
> **目的**: SPEC FR-E-3 の worst case (悲観 180 calls = 30 日 × 4 時間おき) で、Opus 4.7 を含めて月額がどの程度になるかを概算で押さえ、本実装に進む心理的ハードルを下げる。

---

## 0. 改定履歴

| Version | 日付 | 変更内容 |
|---|---|---|
| v1.0 | 2026-05-19 朝 | 初版。fixture 1-log 前提 (handler_value_error: ValueError 単発) |
| v1.5 | 2026-05-19 午後 | SPEC v1.5 fixture 拡張 (alarm 前 30min 全ログ 85 件) に追従し再計算。input トークンが 1395 → 7441 (5.3 倍) に増加 |

---

## 1. 入力データ

### 1.1 実測トークン (Phase A + SPEC v1.5 fixture, 3 モデル × 2 fixture)

source: [../samples/](../samples/) (2026-05-19 取得)

| Model | Fixture | input tokens | output tokens |
|---|---|---|---|
| Haiku 4.5 | handler_value_error (85 logs) | **7,441** | **1,001** (max=1024 寸前) |
| Haiku 4.5 | no_logs | 1,878 | 394 |
| Sonnet 4.6 | handler_value_error (85 logs) | **7,441** | 477 |
| Sonnet 4.6 | no_logs | 1,878 | 427 |
| Opus 4.7 | handler_value_error (85 logs) | **8,210** | 373 |
| Opus 4.7 | no_logs | 2,085 | 342 |

worst case 試算は **handler_value_error の数値** (全件 error 想定) を使う。
**Opus 4.7 は他モデルより +10% input** (tokenizer 差)。

### 1.2 公開モデル単価 (参考値, 要 Phase E C-6 検証)

| Model | $/Mtok input | $/Mtok output |
|---|---|---|
| Haiku 4.5 | $1 | $5 |
| Sonnet 4.6 | $3 | $15 |
| Opus 4.7 | $15 | $75 |

**caveat**:
- `jp.*` inference profile (cross-region) の実単価は公開値より高い可能性あり
- prompt caching 適用時: cache read は input 単価の **約 10%** (Anthropic 公称 90% off)、cache write は input 単価の **1.25 倍** (Anthropic 公称)

### 1.3 N_calls シナリオ (SPEC FR-E-3)

| シナリオ | calls/月 | 根拠 |
|---|---|---|
| 楽観 | 10 | エラー稀 |
| 想定 | 30 | 中央値推定 |
| **悲観** | **180** | **30 日 × 4 時間おき = 6/日 × 30 = 全件失敗の理論上限** |

### 1.4 HDW_ML snapshot 想定サイズ (Phase C 完了前の仮定)

`T_source = 7,000 tok` (SPEC FR-C-1 の想定上限 8k tok を参考)。
**実測は Phase C Task C-2 で確定**。超過時は SPEC R-2 縮退策 (P2 シグネチャ抽出版)。

---

## 2. 計算式

```
1 call = T_in × P_in + T_out × P_out                                       (cache なし)
1 call (cache read) = T_cached × P_in × 0.10  + T_fresh × P_in + T_out × P_out

月額 = N_calls × (1 call コスト)
     + 初回 cache write 補正 (cache write × 1.25 - 通常 read × 1)
```

cache 計算 (HDW_ML embed あり想定):
- T_cached = 7,000 (HDW_ML snapshot) + 2,000 (system prompt 共通部) = 9,000
- T_fresh = 6,210 (alarm + 85 logs)
- T_out = ~400
- 1 回目: 9,000 × P_in × 1.25 (write) + 6,210 × P_in + 400 × P_out
- 2 回目以降 (N-1 回): 9,000 × P_in × 0.10 + 6,210 × P_in + 400 × P_out

---

## 3. 試算結果

### 3.1 HDW_ML embed なし (Phase B のみ、Phase C 未着手) — **現在の状態**

| Model | 1 call | 楽観 ($/月) | 想定 ($/月) | **悲観 ($/月, ¥/月)** |
|---|---|---|---|---|
| Haiku 4.5 | $0.0124 | $0.12 | $0.37 | **$2.24 (≒¥335)** |
| Sonnet 4.6 | $0.0295 | $0.29 | $0.88 | **$5.31 (≒¥795)** |
| Opus 4.7 | $0.1511 | $1.51 | $4.53 | **$27.20 (≒¥4,080)** |

### 3.2 HDW_ML embed あり、caching **なし** (Phase C 採用、cache 不動作 = R-1 発動時)

T_in = 14,441 (7441 + 7000 snapshot), T_out 各モデル baseline

| Model | 1 call | 楽観 | 想定 | **悲観 ($/月)** |
|---|---|---|---|---|
| Haiku 4.5 | $0.0194 | $0.19 | $0.58 | **$3.50** |
| Sonnet 4.6 | $0.0505 | $0.50 | $1.51 | **$9.08** |
| Opus 4.7 (in 15210) | $0.2563 | $2.56 | $7.69 | **$46.14** |

### 3.3 HDW_ML embed あり、caching **あり** (Phase C 採用、cache 動作)

| Model | 1 回目 (write) | 2 回目以降 (read) | **悲観 月額** |
|---|---|---|---|
| Haiku 4.5 | $0.0214 | $0.0135 | **$2.43** |
| Sonnet 4.6 | $0.0590 | $0.0260 | **$4.71** |
| Opus 4.7 | $0.3061 | $0.1392 | **$25.23** |

(月初 1 回 cache write + 179 回 cache read として計算)

---

## 4. Opus 4.7 の妥当性 — スケール感比較

worst case 各シナリオの参考:

| シナリオ | Opus 4.7 月額 |
|---|---|
| 現在 (embed なし、cache なし) | $27.20 |
| Phase C 後 (embed あり、cache あり) | $25.23 |
| 最悪 (embed あり、cache なし = R-1 発動) | $46.14 |

参考スケール感:

| サービス | 月額 |
|---|---|
| Netflix ベーシック | $7.99 |
| GitHub Copilot | $10 |
| ChatGPT Plus | $20 |
| Claude Pro | $20 |
| **HDW_Notify (Opus 4.7 + embed + cache, 悲観)** | **$25.23** |
| **HDW_Notify (Opus 4.7, cache 失敗時最悪)** | **$46.14** |

→ **v1.0 試算 ($10.90) から ~2.4 倍に増加**。原因は fixture が 1-log から 85-log になり input が 5.3 倍に増えたため。
→ それでも Claude Pro ($20) と同程度から ChatGPT Plus 2 ヶ月分 ($40) のレンジ。導入判断としては許容範囲だが「想定運用ならコーヒー 1 杯」の触れ込みは v1.0 と比較して薄れた。
→ 想定運用 (30 calls/月) なら Opus 4.7 でも **$4.53/月** = 想定運用なら依然コーヒー 1 杯。

---

## 5. リスクと不確実性

| 不確実性 | 影響度 | 縮退想定 |
|---|---|---|
| `jp.*` inference profile 単価が公開値より高い | 中 | 1.2〜1.5 倍想定。**最悪 Opus 悲観 $40〜70/月** |
| HDW_ML snapshot が 7000 tok 超過 | 中 | 12000 tok まで想定すると Opus 悲観 ~$55/月 |
| prompt caching が動かない (R-1) | **大** | §3.2 表に張り付く (Opus 悲観 **$46.14/月**) |
| max_tokens=1024 で出力張り付き (Haiku 4.5 で実測 1001 tok = 寸前) | **大** | **Haiku では既に頭打ち発生中**。max_tokens を 2048 に上げると Haiku 悲観 +$1〜2/月 |
| 30min 窓で error 件数が想定 (85) を大幅超過 | 中 | 200 件まで想定すると input ~15000 → Opus 悲観 $60/月 |
| 全件複合の最悪 | — | **Opus 4.7 でも月額 $70〜100 程度が天井** |

天井 $100 (≒¥15,000)/月 ですら、エンタープライズ SaaS 1 つ程度。**「Opus は高すぎる」という直感的判断は外している**が、v1.0 時点よりは慎重に判断要。

---

## 6. AWS その他コスト (試算外、Phase E C-9 で実測)

- Lambda invoke + duration: 想定 $0.10〜0.50/月
- CW Logs Insights scan: $0.10〜1.00/月 (1GB scan × 2 query/call ÷ N_calls 依存)
- ECR storage (image): $0.05〜0.20/月
- CW Alarm: $0.10/月 固定
- Discord webhook egress: $0 (実質ゼロ)

**合計 $1〜2/月** 程度で、Bedrock コストに上乗せ。

---

## 7. 結論 (preliminary, v1.5)

- worst case (悲観 180 calls 全件 error) で:
  - **Haiku 4.5**: 月 $2.2〜3.5 — 誤差レンジ + cache 効果 limited (output 偏重のため)
  - **Sonnet 4.6**: 月 $5.3〜9.1 — コーヒー 2 杯
  - **Opus 4.7**: 月 $25〜46 (cache 動作可否で変動)
- 想定運用 (30 calls/月) なら:
  - Haiku 4.5: 月 $0.37
  - Sonnet 4.6: 月 $0.88
  - Opus 4.7: 月 $4.53
- **推奨方針**:
  - **Haiku 4.5 で max_tokens を 2048 に上げて使うのが「コスト × 品質」のスイートスポット候補**
  - Sonnet 4.6 は中庸選択、コスト感もちょうどよい
  - Opus 4.7 は本気で品質欲しい時の選択肢。本番採用前に Phase B+C 改善ループで他モデルとの品質差分を再評価
  - **Phase E で `jp.*` profile の実単価確認** + **prompt caching 実機検証** が次に潰すべき不確実性

---

## 8. 次に確定させること (Phase E 正式版で)

- [ ] `T_system` (3 case 削除済み = 1 case のみ実測) — C-1
- [ ] `T_source` (HDW_ML snapshot) 実測 — C-2 (Phase C 完了後)
- [ ] `T_per_log` 線形係数の再測定 (85-log fixture を分割してプロット) — C-3
- [ ] `T_out` モデル別頭打ち閾値 (Haiku で 1024 寸前) — C-5
- [ ] **モデル単価 web 確認** (`jp.*` profile の実単価) — C-6
- [ ] **prompt caching 実機検証** (cacheReadInputTokens > 0) — C-7
- [ ] `N_calls` 想定値 (Alarm history or Lambda Errors metric) — C-8
- [ ] AWS 他コスト実測 — C-9

確定後、`cost-measurements-2026-05-19.md` (正式版) に置き換える。

---

## 9. v1.0 → v1.5 変動まとめ

| 項目 | v1.0 (1-log) | v1.5 (85-log) | 変動 |
|---|---|---|---|
| handler_value_error input | 1,395 tok | 7,441-8,210 tok | **+5.3〜5.9 倍** |
| Opus 4.7 悲観 (embed なし) | $8.91 | $27.20 | +3.1 倍 |
| Opus 4.7 悲観 (embed + cache) | $10.90 | $25.23 | +2.3 倍 |
| Sonnet 4.6 悲観 (embed なし) | $1.78 | $5.31 | +3.0 倍 |
| Haiku 4.5 悲観 (embed なし) | $0.60 | $2.24 | +3.7 倍 |
| **メッセージ** | 「コーヒー 1 杯」 | 「ChatGPT Plus 並み」 | **判断材料の解像度向上** |

**v1.5 の意味**: 想定が「ちょうどいい数字」から「現実的な数字」になった。本番採用判断としては v1.5 のほうが誠実。
