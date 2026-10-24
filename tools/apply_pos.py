#!/usr/bin/env python3
"""確定済みの品詞の上書きを同梱データへ適用する。

品詞は上流（complete-hsk-vocabulary）の略号をそのまま使うが、上流に感嘆詞の印が無い語がある
（哇 wā は語気詞・擬声語だけ）。記録には元の品詞（from）も持たせ、上流が変わって
元の品詞と合わなくなったら、黙って上書きせずに止める。
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
from validate_data import POS_VALUES

REPO_ROOT = pathlib.Path(__file__).resolve().parent.parent
FILE_KEY = f"zh-ja/{entries_file.NAME}"


class PosError(ValueError):
    """記録と同梱データの対応が成立しない。"""


def valid_pos(value, allow_empty=False):
    return (isinstance(value, list) and (allow_empty or value)
            and all(isinstance(code, str) and code in POS_VALUES for code in value)
            and len(set(value)) == len(value))


def load_records(path):
    records = {}
    for number, line in enumerate(path.read_text(encoding="utf-8").splitlines(), 1):
        row = json.loads(line)
        if not isinstance(row, dict):
            raise PosError(f"{path}:{number}: 記録がobjectでない")
        if set(row) - {"word", "trad", "pinyin", "from", "pos", "reason"}:
            raise PosError(f"{path}:{number}: 未知の鍵がある")
        try:
            key = row_key(row)
        except ValueError as error:
            raise PosError(f"{path}:{number}: {error}") from None
        if key in records:
            raise PosError(f"記録の重複: {key!r}")
        if not valid_pos(row.get("from"), allow_empty=True) or not valid_pos(row.get("pos")):
            raise PosError(f"{path}:{number}: 品詞が不正")
        if row["from"] == row["pos"]:
            raise PosError(f"{path}:{number}: 変更が無い")
        if not isinstance(row.get("reason"), str) or not row["reason"].strip():
            raise PosError(f"{path}:{number}: 理由が無い")
        records[key] = row
    return records


def apply_pos(entries, records_path, manifest_path):
    records = load_records(records_path)
    rows = [json.loads(line) for line in entries_file.read_lines(entries)]
    applied = set()
    for row in rows:
        key = row_key(row)
        record = records.get(key)
        if record is None:
            continue
        current = row.get("pos", [])
        # 適用済み（pos と同じ）なら何もしない。再実行で同じバイト列にするため。
        if current != record["pos"]:
            if current != record["from"]:
                raise PosError(f"品詞が記録と違う: {key!r} はデータ {current!r}、記録 {record['from']!r}")
            row["pos"] = record["pos"]
        applied.add(key)
    missing = [key for key in records if key not in applied]
    if missing:
        raise PosError(f"行がデータに無い: {len(missing):,}件 / 例 {missing[:3]!r}")
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
    return len(rows), len(records)


def main(argv=None):
    parser = argparse.ArgumentParser(description="品詞の上書きの記録を適用する")
    for option, default in (
        ("entries", "data/zh-ja/" + entries_file.NAME),
        ("pos-overrides", "data/inputs/pos-overrides.jsonl"),
        ("manifest", "data/manifest.json"),
    ):
        parser.add_argument("--" + option, type=pathlib.Path, default=REPO_ROOT / default)
    args = parser.parse_args(argv)
    try:
        rows, records = apply_pos(args.entries, args.pos_overrides, args.manifest)
    except (OSError, ValueError, KeyError, zlib.error) as error:
        print(f"apply_pos: {error}", file=sys.stderr)
        return 1
    print(f"適用: {rows:,}行 / 品詞の上書き {records:,}件 / 違反0件")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
