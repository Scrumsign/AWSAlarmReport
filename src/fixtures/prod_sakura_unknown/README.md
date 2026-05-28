# prod_sakura_unknown

本番の実ログから取得し、識別子（アカウントID・request_id・xray_trace_id）を匿名化した fixture。

- 対象: ship_name=sakura
- 取得時間窓: 2026-05-27 17:32〜23:02 UTC（直近5h30m）
- ログ件数: 132 行
- パターン: status=error のログが存在しない（unknown / 状態不明 パターン相当）

通知メッセージ改善（issue #4）の新スキーマ
（business_summary / root_cause_hypothesis / technical_observation /
technical_hypothesis）の Bedrock 疎通確認用。

`insights_result.json` は CloudWatch Logs Insights の生レスポンス（参考用）。
`logs.jsonl` は各行の @message（powertools 生 JSON）を抽出したもの。
