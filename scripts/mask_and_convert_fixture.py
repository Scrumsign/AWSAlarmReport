"""
Insights `get-query-results` 生 JSON → masked fixture jsonl 変換スクリプト。

入力: tmp/raw/query-result-raw.json (aws logs get-query-results 出力)
出力: src/fixtures/<case>/logs.jsonl (powertools dict 1 行 1 ログ、マスキング済み)

SPEC NFR-1 v1.2 規約に準拠:
- account ID 920373030024 → 000000000000
- function_request_id (UUID) → 連番 00000000-0000-0000-0000-{N:012d}
- xray_trace_id 1-{8hex}-{24hex} → 連番 1-00000000-{N:024d}

非 JSON ログ (INIT_REPORT 等の Lambda runtime ログ) は
{"@timestamp": ..., "@message": ...} の形にラップして残す。

usage:
    python scripts/mask_and_convert_fixture.py \\
        --input tmp/raw/query-result-raw.json \\
        --output src/fixtures/handler_value_error/logs.jsonl
"""

from __future__ import annotations

import argparse
import json
import re
from pathlib import Path

ACCOUNT_ID_PROD = "920373030024"
ACCOUNT_ID_DUMMY = "000000000000"
UUID_RE = re.compile(r"^[0-9a-f]{8}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{12}$")
XRAY_RE = re.compile(r"^1-[0-9a-f]{8}-[0-9a-f]{24}$")


def make_dummy_request_id(n: int) -> str:
    return f"00000000-0000-0000-0000-{n:012d}"


def make_dummy_xray_id(n: int) -> str:
    return f"1-00000000-{n:024d}"


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--input", required=True, type=Path)
    ap.add_argument("--output", required=True, type=Path)
    args = ap.parse_args()

    data = json.loads(args.input.read_text(encoding="utf-8"))
    rows = data["results"]
    print(f"input records: {len(rows)}")

    # Step 1: 各 row から @timestamp + @message 抽出 → dict 化
    raw_entries: list[dict] = []
    for row in rows:
        fields = {item["field"]: item["value"] for item in row if item.get("field") != "@ptr"}
        ts = fields.get("@timestamp", "")
        msg = fields.get("@message", "")
        # @message が JSON ならパース、そうでなければ wrap
        try:
            parsed = json.loads(msg)
            if isinstance(parsed, dict):
                # powertools 由来。timestamp が無ければ @timestamp で補完
                if "timestamp" not in parsed:
                    parsed["timestamp"] = ts
                raw_entries.append(parsed)
                continue
        except json.JSONDecodeError:
            pass
        # 非 JSON (Lambda runtime ログ) → wrap
        raw_entries.append({"@timestamp": ts, "@message": msg.rstrip()})

    # Step 2: 全エントリから sensitive value を収集
    request_ids = set()
    xray_ids = set()
    for e in raw_entries:
        for v in e.values():
            if not isinstance(v, str):
                continue
            if UUID_RE.match(v):
                request_ids.add(v)
            elif XRAY_RE.match(v):
                xray_ids.add(v)
        # @message 内に埋め込まれた UUID / xray_id も探索
        msg = e.get("@message", "")
        if isinstance(msg, str):
            for m in re.findall(r"[0-9a-f]{8}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{12}", msg):
                request_ids.add(m)
            for m in re.findall(r"1-[0-9a-f]{8}-[0-9a-f]{24}", msg):
                xray_ids.add(m)

    # Step 3: マスキングマップ生成
    req_map = {rid: make_dummy_request_id(i + 1) for i, rid in enumerate(sorted(request_ids))}
    xray_map = {xid: make_dummy_xray_id(i + 1) for i, xid in enumerate(sorted(xray_ids))}
    print(f"unique request_ids: {len(req_map)}")
    print(f"unique xray_ids: {len(xray_map)}")

    # Step 4: 各エントリに対してマスキング適用 (JSON 文字列レベルで置換、複雑な階層は扱わない)
    def mask_str(s: str) -> str:
        s = s.replace(ACCOUNT_ID_PROD, ACCOUNT_ID_DUMMY)
        for orig, dummy in req_map.items():
            s = s.replace(orig, dummy)
        for orig, dummy in xray_map.items():
            s = s.replace(orig, dummy)
        return s

    def mask_value(v):
        if isinstance(v, str):
            return mask_str(v)
        if isinstance(v, dict):
            return {k: mask_value(vv) for k, vv in v.items()}
        if isinstance(v, list):
            return [mask_value(x) for x in v]
        return v

    masked = [mask_value(e) for e in raw_entries]

    # Step 5: jsonl 書き出し
    args.output.parent.mkdir(parents=True, exist_ok=True)
    with args.output.open("w", encoding="utf-8") as f:
        for e in masked:
            f.write(json.dumps(e, ensure_ascii=False) + "\n")
    print(f"wrote: {args.output} ({len(masked)} lines)")


if __name__ == "__main__":
    main()
