#!/usr/bin/env python3
"""テスト用 ZIP 生成スクリプト。

本番運用試験用に、ベース ZIP（クライアントから受領した本物の HDW_ML 入力 ZIP）から
TC 固有の改造を施したテスト ZIP を生成する。生成された ZIP を S3 inputFiles/ に
投入することで、HDW_ML の特定エラーパスを誘発する。

spec: test-zip-management@2.0.0 PLAN TASK-002

CLI:
    python scripts/make_test_zip.py <TC-ID> <input-zip> -o <output-zip>

TC-ID:
    TC-B-3  フォルダ構成違反: 全エントリを tampered/ 配下に移動
    TC-B-5  CSV データ破損: db02 配下の sensor CSV の 2 行目 1 列目を BROKEN
    TC-S-1  スキップ船名: 中身無改造（出力ファイル名のみ呼び出し側で変更）
"""
from __future__ import annotations

import argparse
import re
import sys
import zipfile
from pathlib import Path


def copy_entry(
    zin: zipfile.ZipFile,
    zout: zipfile.ZipFile,
    info: zipfile.ZipInfo,
    new_filename: str | None = None,
    new_data: bytes | None = None,
) -> None:
    """エントリを zin から zout へコピー。filename / data を上書き可能。

    TC-S-1 のバイト列完全一致要件（SPEC AC-004-2）のため、ZipInfo の
    タイムスタンプ・圧縮方式・external_attr を明示的に保持する。
    zipfile.writestr(filename, data) を直接呼ぶと現在時刻 / デフォルト圧縮で
    新規 ZipInfo が作られるためメタデータが失われる。

    new_filename は TC-B-3 のプレフィックス付加、
    new_data は TC-B-5 の CSV 加工で利用する。
    """
    data = new_data if new_data is not None else zin.read(info.filename)
    new_info = zipfile.ZipInfo(
        filename=new_filename or info.filename,
        date_time=info.date_time,
    )
    new_info.compress_type = info.compress_type
    new_info.external_attr = info.external_attr
    zout.writestr(new_info, data)


def tcb3_transform(zin: zipfile.ZipFile, zout: zipfile.ZipFile) -> None:
    """TC-B-3: 全エントリを tampered/ 配下に移動（フォルダ構成違反）。

    HDW_ML の validation は db01|db02|db05em|db06em/<year>/<ship>/定時|任意/...
    の規約と一致しないエントリをすべて NG にする。本関数はベース ZIP の
    全エントリのパスに "tampered/" を前置することで、validation が全件 NG を
    返す状態を作る（SPEC AC-002-1）。データ・タイムスタンプ・圧縮方式は
    保持して、改造の有無が「パスのみ」であることを明確にする。
    """
    for info in zin.infolist():
        # 既に tampered/ で始まるエントリはベース ZIP の規約として想定外。
        # 二重プレフィックスを許容しつつも気付けるよう警告だけ出して継続。
        if info.filename.startswith("tampered/"):
            print(
                f"warning: entry already prefixed with tampered/: {info.filename}",
                file=sys.stderr,
            )
        copy_entry(zin, zout, info, new_filename=f"tampered/{info.filename}")


_TCB5_PAT = re.compile(
    r"(^|.*?/)db02/\d{4}/[^/]+/(定時|任意)/\d{14}/(?!General)[^/]+\.csv$"
)


def _real_filename(info: zipfile.ZipInfo) -> str:
    """zipfile が返した filename を実際の日本語に復元する。

    - base ZIP（UTF-8 フラグなし）: filename は cp437 として decode された
      mojibake str。cp437→cp932 ラウンドトリップで真の日本語に戻る。
    - 生成 ZIP（make_test_zip.py 自身が書き出した、UTF-8 フラグあり）:
      mojibake str を UTF-8 で書き込んだため、読み戻しても mojibake str。
      同じく cp437→cp932 ラウンドトリップが効く。
    - 真の UTF-8 で書かれた ZIP（例: 7-Zip）: filename は既に正しい
      日本語 str。cp437 encode で UnicodeEncodeError → 原文 fallback。

    UTF-8 フラグの有無に依存しない判定にすることで、上記 3 ケースを
    一律に扱う。verify_test_zip.py 側と同一実装。
    """
    try:
        return info.filename.encode("cp437").decode("cp932")
    except (UnicodeEncodeError, UnicodeDecodeError):
        return info.filename


def tcb5_transform(zin: zipfile.ZipFile, zout: zipfile.ZipFile) -> None:
    """TC-B-5: db02 配下の最初の sensor CSV の 2 行目 1 列目を BROKEN に置換。

    HDW_ML の csv parse 処理は数値カラムを float() で変換する。文字列
    "BROKEN" を 1 列目に注入することで ValueError を誘発し、データ起因の
    異常通知パス（SPEC AC-003-1）を検証できる状態を作る。対象 CSV 以外の
    エントリはバイト列ごとそのままコピーし、改造の有無が 1 ファイル
    （かつ 1 セル）に限定されることを保証する（SPEC AC-003-2）。
    """
    # ベース ZIP のエントリ順で最初に PAT に一致する sensor CSV を探す。
    # 「最初に見つかった 1 件」を改造対象とする規約（検証スクリプトも同順）。
    target_info: zipfile.ZipInfo | None = None
    for info in zin.infolist():
        if _TCB5_PAT.match(_real_filename(info)):
            target_info = info
            break
    if target_info is None:
        raise SystemExit("対象 CSV（db02 配下の sensor CSV）が見つかりません")

    for info in zin.infolist():
        if info is not target_info:
            copy_entry(zin, zout, info)
            continue

        # 対象 CSV のみ加工。cp932 は船側センサ装置の CSV 出力固定。
        # errors="replace" で decode 不能バイトがあっても処理を継続する。
        raw = zin.read(info.filename)
        text = raw.decode("cp932", errors="replace")
        lines = text.splitlines(keepends=True)
        if len(lines) < 2:
            raise SystemExit(f"対象 CSV の行数が不足: {_real_filename(info)}")

        # 2 行目（index 1）の 1 列目を BROKEN に置換。元の改行コードを保持
        # することで、HDW_ML 側の改行依存ロジックへの予期しない影響を避ける。
        row2 = lines[1]
        eol = "\r\n" if row2.endswith("\r\n") else ("\n" if row2.endswith("\n") else "")
        cells = row2.rstrip("\r\n").split(",")
        cells[0] = "BROKEN"
        lines[1] = ",".join(cells) + eol

        new_data = "".join(lines).encode("cp932", errors="replace")
        copy_entry(zin, zout, info, new_data=new_data)


def tcs1_transform(zin: zipfile.ZipFile, zout: zipfile.ZipFile) -> None:
    """TC-S-1: 全エントリをそのままコピー（スキップ船名リネーム）。

    HDW_ML は ZIP ファイル名から船名を抽出し、停止リスト（shimakaji 等）に
    一致する場合は処理を skip して status=success で終了する。
    そのため Alarm が発火せず Discord 通知も発火しない（SPEC AC-007-1 で
    検証する「通知ゼロ」状態）。本関数は中身を一切加工せず、改造は呼び出し側が
    -o 引数で shimakaji-<timestamp>.zip を指定することで実現する。
    ZipInfo を保持してコピーすることで、エントリ一覧・バイト列・タイムスタンプ・
    圧縮方式の完全一致を保証する（SPEC AC-004-2）。
    """
    for info in zin.infolist():
        copy_entry(zin, zout, info)


DISPATCH = {
    "TC-B-3": tcb3_transform,
    "TC-B-5": tcb5_transform,
    "TC-S-1": tcs1_transform,
}


def main() -> int:
    parser = argparse.ArgumentParser(
        description="テスト用 ZIP 生成スクリプト",
        formatter_class=argparse.RawDescriptionHelpFormatter,
    )
    parser.add_argument("tc_id", choices=list(DISPATCH.keys()), help="TC-ID")
    parser.add_argument("input_zip", type=Path, help="ベース ZIP のパス")
    parser.add_argument(
        "-o", "--output", dest="output_zip", type=Path, required=True,
        help="出力 ZIP のパス",
    )
    args = parser.parse_args()

    # 入力 ZIP の事前存在チェック。zipfile.ZipFile の例外より分かりやすい
    # メッセージを出す。exit code 2 は argparse 流の "misuse" 慣習に合わせる。
    if not args.input_zip.exists():
        print(f"error: input ZIP not found: {args.input_zip}", file=sys.stderr)
        return 2

    # tmp/test-zips/<TC-ID>/ のように呼び出し側が深いパスを指定する想定。
    # 毎回 mkdir を強要しないよう、ここで自動作成する。
    args.output_zip.parent.mkdir(parents=True, exist_ok=True)

    transform = DISPATCH[args.tc_id]
    with zipfile.ZipFile(args.input_zip, "r") as zin, \
            zipfile.ZipFile(args.output_zip, "w", zipfile.ZIP_DEFLATED) as zout:
        transform(zin, zout)

    print(f"OK: {args.tc_id} -> {args.output_zip}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
