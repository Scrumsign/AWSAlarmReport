#!/usr/bin/env python3
"""テスト用 ZIP 検証スクリプト。

make_test_zip.py で生成した ZIP がベース ZIP の規約および各 TC の
AC を満たしているかを機械的に検証する。

spec: test-zip-management@2.0.0 TEST TC-001-2 / TC-002-* / TC-003-* / TC-004-* / TC-VERIFY-CLI

CLI:
    python scripts/verify_test_zip.py <MODE> <zip-path> [--base <base-zip>]

MODE:
    base     ベース ZIP がフォルダ規約を満たすか（AC-001-2）
    TC-B-3   tampered/ プレフィックス確認（AC-002-1, --base で AC-002-2）
    TC-B-5   BROKEN 注入確認（AC-003-1, --base で AC-003-2）
    TC-S-1   ファイル名形式確認（AC-004-1, --base で AC-004-2）
"""
from __future__ import annotations

import argparse
import re
import sys
import zipfile
from pathlib import Path


PAT_ENTRY = re.compile(
    r"^(db01|db02|db05em|db06em)/\d{4}/[^/]+/(定時|任意)/.+$"
)
PAT_DB02_GEN = re.compile(
    r"^db02/\d{4}/[^/]+/(定時|任意)/\d{14}/General\.csv$"
)
PAT_DB02_SENSOR = re.compile(
    r"^db02/\d{4}/[^/]+/(定時|任意)/\d{14}/(?!General)[^/]+\.csv$"
)
PAT_TCB5_TARGET = re.compile(
    r"(^|.*?/)db02/\d{4}/[^/]+/(定時|任意)/\d{14}/(?!General)[^/]+\.csv$"
)
PAT_TCS1_FILENAME = re.compile(r"^shimakaji-\d{14}\.zip$")


def _real_filename(info: zipfile.ZipInfo) -> str:
    """zipfile が返した filename を実際の日本語に復元する。

    - base ZIP（UTF-8 フラグなし）: filename は cp437 として decode された
      mojibake str。cp437→cp932 ラウンドトリップで真の日本語に戻る。
    - 生成 ZIP（make_test_zip.py 出力、UTF-8 フラグあり）: zipfile が
      mojibake str を UTF-8 で書き込んだため、読み戻すと再び mojibake str
      になる。同じく cp437→cp932 ラウンドトリップが効く。
    - 真の UTF-8 で書かれた ZIP（例: 7-Zip）: filename は既に正しい
      日本語 str。cp437 encode で UnicodeEncodeError → 原文 fallback。

    UTF-8 フラグの有無に依存しない判定にすることで、上記 3 ケースを
    一律に扱う。
    """
    try:
        return info.filename.encode("cp437").decode("cp932")
    except (UnicodeEncodeError, UnicodeDecodeError):
        return info.filename


def verify_base(zip_path: Path) -> None:
    """ベース ZIP がフォルダ規約を満たすか確認（AC-001-2）。"""
    with zipfile.ZipFile(zip_path) as z:
        real_names = [_real_filename(i) for i in z.infolist()]
        bad = [n for n in real_names
               if not n.endswith("/") and not PAT_ENTRY.match(n)]
        assert not bad, f"規約違反エントリ: {bad[:3]}"
        assert any(PAT_DB02_GEN.match(n) for n in real_names), \
            "db02 配下に General.csv が見つかりません"
        assert any(PAT_DB02_SENSOR.match(n) for n in real_names), \
            "db02 配下に sensor CSV が見つかりません"
    print(f"OK: base ({len(real_names)} エントリすべて規約準拠)")


def verify_tcb3(zip_path: Path, base_path: Path | None = None) -> None:
    """TC-B-3 ZIP の検証（AC-002-1, --base 指定時 AC-002-2）。

    "tampered/" は ASCII なので zipfile の cp437 decode で化けない。
    namelist() の raw 結果で判定でき _real_filename は不要。
    --base が指定された場合はベース ZIP とのエントリ数比較を行う
    （AC-002-2: エントリの欠落・追加が無い）。
    """
    with zipfile.ZipFile(zip_path) as z:
        names = z.namelist()
        assert names, "ZIP が空"
        bad = [n for n in names if not n.startswith("tampered/")]
        assert not bad, f"tampered/ で始まらないエントリ: {bad[:3]}"
    print(f"OK: TC-B-3 {len(names)} エントリすべて tampered/ 配下")

    if base_path:
        with zipfile.ZipFile(base_path) as zb:
            base_count = len(zb.namelist())
        assert len(names) == base_count, \
            f"エントリ数不一致: 生成={len(names)} base={base_count}"
        print(f"OK: エントリ数一致 {len(names)}={base_count}")


def verify_tcb5(zip_path: Path, base_path: Path | None = None) -> None:
    """TC-B-5 ZIP の検証（AC-003-1, --base 指定時 AC-003-2）。

    対象 CSV を db02/<year>/<ship>/(定時|任意)/<ts>/(General 以外).csv の
    パターンで探し、その 2 行目 1 列目が "BROKEN" であることを確認する
    （AC-003-1）。--base が指定された場合は対象 CSV 以外の全エントリの
    バイト列がベース ZIP と一致することを確認する（AC-003-2）。
    """
    with zipfile.ZipFile(zip_path) as z:
        target_info = None
        for info in z.infolist():
            if PAT_TCB5_TARGET.match(_real_filename(info)):
                target_info = info
                break
        assert target_info is not None, "対象 CSV が見つかりません"
        target_real = _real_filename(target_info)

        text = z.read(target_info.filename).decode("cp932", errors="replace")
        lines = text.splitlines()
        assert len(lines) >= 2, f"行数不足: {target_real}"
        cells = lines[1].split(",")
        assert cells[0] == "BROKEN", \
            f"2行目1列目: {cells[0]!r} (BROKEN を期待)"
    print(f"OK: TC-B-5 {target_real} の 2行目1列目 = BROKEN")

    if base_path:
        with zipfile.ZipFile(zip_path) as z, zipfile.ZipFile(base_path) as zb:
            # 対象 CSV と同名 (real) のベースエントリを探して除外比較
            base_target = None
            for info in zb.infolist():
                if _real_filename(info) == target_real:
                    base_target = info.filename
                    break
            assert base_target is not None, \
                f"ベース ZIP に対応エントリが見つかりません: {target_real}"

            diffs = []
            for info in zb.infolist():
                raw = info.filename
                if raw == base_target:
                    continue
                if z.read(raw) != zb.read(raw):
                    diffs.append(_real_filename(info))
            assert not diffs, f"バイト列差分: {diffs[:3]}"
            count = len(zb.namelist()) - 1
        print(f"OK: 対象 CSV 以外 {count} エントリのバイト列一致")


def verify_tcs1(zip_path: Path, base_path: Path | None = None) -> None:
    """TC-S-1 ZIP の検証（AC-004-1, --base 指定時 AC-004-2）。

    ファイル名が shimakaji-<14digits>.zip 形式であることを確認する
    （AC-004-1）。--base が指定された場合はエントリ一覧および
    各エントリのバイト列がベース ZIP と完全一致することを確認する
    （AC-004-2）。
    """
    name = zip_path.name
    assert PAT_TCS1_FILENAME.match(name), \
        f"ファイル名: {name} (shimakaji-<14digits>.zip を期待)"
    print(f"OK: TC-S-1 ファイル名 {name}")

    if base_path:
        with zipfile.ZipFile(zip_path) as z, zipfile.ZipFile(base_path) as zb:
            # raw filename ベースの一覧比較。生成 ZIP は UTF-8 フラグ付き、
            # base ZIP は cp437 mojibake で raw str は両者一致する設計
            # （make_test_zip.py の copy_entry が info.filename をそのまま渡す）。
            names_z = sorted(z.namelist())
            names_b = sorted(zb.namelist())
            assert names_z == names_b, \
                f"エントリ一覧差分: {sorted(set(names_z) ^ set(names_b))[:3]}"

            diffs = [n for n in names_z if z.read(n) != zb.read(n)]
            assert not diffs, f"バイト列差分: {diffs[:3]}"
        print(f"OK: TC-S-1 {len(names_z)} エントリすべて base と一致")


def main() -> int:
    # Windows コンソール (cp932) で mojibake 文字を含む print が
    # UnicodeEncodeError で落ちるのを防ぐ。errors='replace' で
    # encode 不能文字は '?' に置換される。
    for stream in (sys.stdout, sys.stderr):
        if hasattr(stream, "reconfigure"):
            stream.reconfigure(encoding="utf-8", errors="replace")

    parser = argparse.ArgumentParser(description="テスト用 ZIP 検証スクリプト")
    parser.add_argument(
        "mode", choices=["base", "TC-B-3", "TC-B-5", "TC-S-1"]
    )
    parser.add_argument("zip_path", type=Path)
    parser.add_argument(
        "--base", dest="base_path", type=Path, default=None,
        help="ベース ZIP のパス（一部 mode で --base 比較が必要）",
    )
    parser.add_argument(
        "--expect-fail", action="store_true",
        help=(
            "negative テスト用。検証の合否を反転する。"
            "検証が fail（AssertionError や他の例外含む）した場合 exit 0、"
            "検証が pass した場合は UNEXPECTED PASS として exit 1。"
        ),
    )
    args = parser.parse_args()

    def _run() -> None:
        if args.mode == "base":
            verify_base(args.zip_path)
        elif args.mode == "TC-B-3":
            verify_tcb3(args.zip_path, args.base_path)
        elif args.mode == "TC-B-5":
            verify_tcb5(args.zip_path, args.base_path)
        elif args.mode == "TC-S-1":
            verify_tcs1(args.zip_path, args.base_path)

    if args.expect_fail:
        # negative テスト: 検証が fail することが期待される。
        # AssertionError 以外の例外（regex 不一致による IndexError, KeyError 等）も
        # 「検証が wrong case を弾いた」証拠として妥当扱いする。
        try:
            _run()
        except BaseException as e:
            print(
                f"[EXPECTED FAIL] {args.mode} on {args.zip_path.name}: "
                f"{type(e).__name__}: {e}"
            )
            return 0
        print(
            f"[UNEXPECTED PASS] {args.mode} on {args.zip_path.name} で fail を"
            "期待したが pass した。verify ロジックが緩い可能性。",
            file=sys.stderr,
        )
        return 1

    try:
        _run()
    except AssertionError as e:
        # 検証失敗は AC 不合格として exit 1。stderr で詳細を出す。
        print(f"FAIL: {args.mode}: {e}", file=sys.stderr)
        return 1
    return 0


if __name__ == "__main__":
    sys.exit(main())
