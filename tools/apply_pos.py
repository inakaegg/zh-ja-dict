#!/usr/bin/env python3
"""確定済みの「品詞を足す」記録を同梱データへ適用する。

品詞は上流（complete-hsk-vocabulary）の略号をそのまま使うが、上流に感嘆詞の印が無い語がある
（哇 wā は語気詞・擬声語だけ）。記録は足す品詞だけを持ち、上流のほかの品詞は変えない。
上流が変わっても止めないためで、記録の語が無くなったときも警告だけにする。
"""

from __future__ import annotations

import argparse
import hashlib
import json
import os
import pathlib
import sys
import zlib

import entries_file
from apply_primary import row_key
from build_dataset import ENTRY_KEYS
from validate_data import POS_VALUES

REPO_ROOT = pathlib.Path(__file__).resolve().parent.parent
FILE_KEY = f"zh-ja/{entries_file.NAME}"
# 配るデータで pos より前に来る鍵。pos の無い行へ足すとき、この直後へ入れる。
KEYS_BEFORE_POS = frozenset(ENTRY_KEYS[:ENTRY_KEYS.index("pos")])


class PosError(ValueError):
    """記録または同梱データが不正で、適用できない。"""


def load_records(path):
    records = {}
    for number, line in enumerate(path.read_text(encoding="utf-8").splitlines(), 1):
        try:
            row = json.loads(line)
        except json.JSONDecodeError:
            raise PosError(f"{path}:{number}: JSONとして読めない") from None
        if not isinstance(row, dict):
            raise PosError(f"{path}:{number}: 記録がobjectでない")
        if set(row) - {"word", "trad", "pinyin", "add", "reason"}:
            raise PosError(f"{path}:{number}: 未知の鍵がある")
        try:
            key = row_key(row)
        except ValueError as error:
            raise PosError(f"{path}:{number}: {error}") from None
        if key in records:
            raise PosError(f"記録の重複: {key!r}")
        codes = row.get("add")
        if (not isinstance(codes, list) or not codes or len(set(codes)) != len(codes)
                or any(not isinstance(code, str) or code not in POS_VALUES for code in codes)):
            raise PosError(f"{path}:{number}: 品詞が不正")
        if not isinstance(row.get("reason"), str) or not row["reason"].strip():
            raise PosError(f"{path}:{number}: 理由が無い")
        records[key] = row
    return records


def with_pos(row, pos):
    """pos を配るデータの鍵の順の位置に置いた行を返す。"""
    if "pos" in row:
        return {**row, "pos": pos}
    result = {}
    for key, value in row.items():
        if "pos" not in result and key not in KEYS_BEFORE_POS:
            result["pos"] = pos
        result[key] = value
    result.setdefault("pos", pos)
    return result


def apply_pos(entries, records_path, manifest_path):
    """(行数, 足した記録の数, 既に品詞があった記録の数) を返す。"""
    records = load_records(records_path)
    rows = [json.loads(line) for line in entries_file.read_lines(entries)]
    seen = set()
    added = present = 0
    for index, row in enumerate(rows):
        key = row_key(row)
        if key in seen:
            raise PosError(f"データの行の重複: {key!r}")
        seen.add(key)
        record = records.get(key)
        if record is None:
            continue
        current = row.get("pos", [])
        missing = [code for code in record["add"] if code not in current]
        if missing:
            rows[index] = with_pos(row, current + missing)
            added += 1
        else:
            # 再実行か、上流が同じ品詞を持つようになったか。後者なら記録は要らなくなる。
            present += 1
    absent = [key for key in records if key not in seen]
    if absent:
        print(f"apply_pos: 警告: 行がデータに無い: {len(absent):,}件 / 例 {absent[:3]!r}", file=sys.stderr)
    manifest = json.loads(manifest_path.read_text(encoding="utf-8"))
    info = manifest["files"][FILE_KEY]
    temporary = entries.with_name(f".{entries.name}.pos.tmp")
    manifest_temporary = manifest_path.with_name(f".{manifest_path.name}.pos.tmp")
    try:
        sizes = entries_file.write(temporary, (
            json.dumps(row, ensure_ascii=False, separators=(",", ":")) for row in rows))
        info.update(lines=len(rows), senses=sum(len(row["senses"]) for row in rows),
                    compression=entries_file.COMPRESSION, bytes=sizes.compressed,
                    uncompressed_bytes=sizes.uncompressed)
        if "sha256" in info:
            info["sha256"] = hashlib.sha256(temporary.read_bytes()).hexdigest()
        manifest_temporary.write_text(
            json.dumps(manifest, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
        # すべての照合と出力を終えるまで元ファイルを置き換えない。
        os.replace(temporary, entries)
        os.replace(manifest_temporary, manifest_path)
    finally:
        for path in (temporary, manifest_temporary):
            if path.exists():
                path.unlink()
    return len(rows), added, present


def main(argv=None):
    parser = argparse.ArgumentParser(description="品詞を足す記録を適用する")
    for option, default in (
        ("entries", "data/zh-ja/" + entries_file.NAME),
        ("pos-additions", "data/inputs/pos-additions.jsonl"),
        ("manifest", "data/manifest.json"),
    ):
        parser.add_argument("--" + option, type=pathlib.Path, default=REPO_ROOT / default)
    args = parser.parse_args(argv)
    try:
        rows, added, present = apply_pos(args.entries, args.pos_additions, args.manifest)
    except (OSError, ValueError, KeyError, zlib.error) as error:
        print(f"apply_pos: {error}", file=sys.stderr)
        return 1
    print(f"適用: {rows:,}行 / 品詞を足した {added:,}件 / 既にあった {present:,}件 / 違反0件")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
