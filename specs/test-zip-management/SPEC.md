---
id: test-zip-management
version: 2.0.0
title: テスト用 ZIP 生成・管理
created_at: 2026-05-20
type: spec
---

# テスト用 ZIP 生成・管理

- **ID**: test-zip-management
- **Version**: 2.0.0
- **Created at**: 2026-05-20
- **Authors**: Reck Developer
- **Constitution**: main@1.0.0
- **Dependencies**: なし

## 用語集

### ベース ZIP

クライアントから提供を受けた本番の典型的な ZIP ファイル。
テスト用 ZIP の改造元として使用する。
ローカルの tmp/test-zips/base/ に保管し、git にはコミットしない。

### テスト ZIP

ベース ZIP に TC 固有の改造を施した ZIP ファイル。
tmp/test-zips/<TC-ID>/ に保管し、git にはコミットしない。

## REQ-001: ベース ZIP の取得・保管

クライアントから本番の典型的な ZIP(直近 1 週間の任意 1 ファイル)を受領し、
ローカルの tmp/test-zips/base/ に保管する。
このファイルは git にコミットせず、.gitignore で除外する。
ベース ZIP には本番の実際のデータが含まれるため、
テスト専用の環境でのみ使用する。

### AC-001-1

tmp/test-zips/base/ ディレクトリが存在し、
.gitignore に tmp/ が記載されていて git status で追跡されていないこと。

### AC-001-2

ベース ZIP を展開すると db01|db02|db05em|db06em/<year>/<ship>/定時|任意/...
の規約に沿ったフォルダ構成を持つこと(有効な HDW_ML 入力 ZIP であること)。

## REQ-002: TC-B-3 用 ZIP の生成(フォルダ構成違反)

ベース ZIP のすべてのエントリを tampered/ 配下に移動した ZIP を生成する。
これにより HDW_ML の validation がすべてのファイルを NG と判定し、
フォルダ構成違反エラーを誘発する。

### AC-002-1

生成した ZIP を展開すると、すべてのエントリのパスが tampered/ で始まること。

### AC-002-2

生成した ZIP のエントリ数がベース ZIP のエントリ数と一致すること
(エントリの欠落・追加が無いこと)。

## REQ-003: TC-B-5 用 ZIP の生成(CSV データ破損)

ベース ZIP の db02 配下で最初に見つかった sensor CSV(General.csv を除く)の
2 行目 1 列目の値を "BROKEN" に置換した ZIP を生成する。
これにより HDW_ML の csv parse 処理で float 変換エラーを誘発する。

### AC-003-1

生成した ZIP を展開し、対象 CSV の 2 行目 1 列目の値が "BROKEN" であること。

### AC-003-2

生成した ZIP の対象 CSV 以外のエントリのバイト列がベース ZIP と同一であること。

## REQ-004: TC-S-1 用 ZIP の生成(スキップ船名リネーム)

ベース ZIP の中身は変更せず、出力ファイル名のみ
shimakaji-<timestamp>.zip に変更する。
これにより HDW_ML がスキップリストに該当する船名を検出し、
処理を skip して status=success で完了する(Alarm 非発火)。

### AC-004-1

生成した ZIP のファイル名が shimakaji-<timestamp>.zip の形式であること。
(timestamp は 14 桁数字)

### AC-004-2

生成した ZIP のエントリ一覧および各エントリのバイト列が
ベース ZIP と完全に一致すること。
