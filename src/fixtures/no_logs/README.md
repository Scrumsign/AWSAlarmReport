# no_logs

## シナリオ
4 時間おきの起動枠で HDW_Backend_Processor_0001 が走った形跡がない。
直近時間窓に error / success どちらのログもない状態を再現する。
(S3 への入力ファイル未アップで Lambda がそもそも起動しなかった想定)

## LLM に期待する回答
- summary に「Lambda 未起動」または「ログなし」相当
- root_cause_hypothesis に「S3 入力ファイル未アップ」「アップロード処理の失敗」を仮説として
- suggested_actions に S3 確認系のアクションが入る
