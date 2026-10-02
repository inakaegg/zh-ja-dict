#!/usr/bin/env python3
"""確定済みの主な語義と既定の行を同梱データへ適用する。"""

from __future__ import annotations

import argparse
import hashlib
import json
import os
import pathlib
import sys
import zlib
from collections import Counter, defaultdict

import entries_file

REPO_ROOT = pathlib.Path(__file__).resolve().parent.parent
FILE_KEY = f"zh-ja/{entries_file.NAME}"


class PrimaryError(ValueError):
    """記録と同梱データの対応が成立しない。"""


def row_key(row):
    values = (row.get("word"), row.get("trad", ""), row.get("pinyin"))
    if any(not isinstance(value, str) for value in values) or not values[0] or not values[2]:
        raise PrimaryError(f"行の鍵が不正: {values!r}")
    return values


def load_records(path, primary=False):
    records = {}
    for number, line in enumerate(path.read_text(encoding="utf-8").splitlines(), 1):
        row = json.loads(line)
        if not isinstance(row, dict):
            raise PrimaryError(f"{path}:{number}: 記録がobjectでない")
        key = row_key(row)
        allowed = {"word", "trad", "pinyin"} | ({"sense", "ja"} if primary else set())
        if set(row) - allowed:
            raise PrimaryError(f"{path}:{number}: 未知の鍵がある")
        if key in records:
            raise PrimaryError(f"記録の重複: 1件 / 例 {key!r}")
        if primary and (type(row.get("sense")) is not int or row["sense"] < 1
                        or not isinstance(row.get("ja"), str) or not row["ja"]):
            raise PrimaryError(f"{path}:{number}: 語義の番号または訳が不正")
        records[key] = row
    return records


def apply_primary(entries, primary_path, default_path, manifest_path):
    primary = load_records(primary_path, primary=True)
    defaults = load_records(default_path)
    rows = [json.loads(line) for line in entries_file.read_lines(entries)]
    keys = set()
    words = Counter()
    default_words = Counter(key[0] for key in defaults)
    errors = defaultdict(list)
    for row in rows:
        key = row_key(row)
        if key in keys:
            errors["データの行の重複"].append(key)
        keys.add(key)
        words[key[0]] += 1
        senses = row.get("senses")
        if not isinstance(senses, list) or not senses or any(not isinstance(s, dict) for s in senses):
            raise PrimaryError(f"語義が空でないobject配列でない: {key!r}")
        row.pop("primary", None)
        row.pop("default", None)
        record = primary.get(key)
        if record is not None:
            index = record["sense"]
            if index > len(senses) or senses[index - 1].get("ja") != record["ja"]:
                errors["語義の番号と訳の不一致"].append(key)
            elif len(senses) >= 2:
                row["primary"] = index
        elif len(senses) >= 2:
            errors["主な語義の記録なし"].append(key)
        if key in defaults:
            row["default"] = True
    for label, records in (("主な語義の行がデータに無い", primary),
                           ("既定の行がデータに無い", defaults)):
        errors[label].extend(key for key in records if key not in keys)
    errors["同じ字の既定が複数"].extend(word for word, count in default_words.items() if count > 1)
    errors["複数行の字に既定なし"].extend(
        word for word, count in words.items() if count > 1 and not default_words[word])
    failures = [f"{label}: {len(values):,}件 / 例 {values[:3]!r}"
                for label, values in errors.items() if values]
    if failures:
        raise PrimaryError("\n".join(failures))
    manifest = json.loads(manifest_path.read_text(encoding="utf-8"))
    info = manifest["files"][FILE_KEY]
    temporary = entries.with_name(f".{entries.name}.primary.tmp")
    manifest_temporary = manifest_path.with_name(f".{manifest_path.name}.primary.tmp")
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
    return len(rows), sum("primary" in row for row in rows), len(defaults)


def main(argv=None):
    parser = argparse.ArgumentParser(description="主な語義と既定の行の記録を適用する")
    for option, default in (
        ("entries", "data/zh-ja/" + entries_file.NAME),
        ("primary-senses", "data/inputs/primary-senses.jsonl"),
        ("default-rows", "data/inputs/default-rows.jsonl"),
        ("manifest", "data/manifest.json"),
    ):
        parser.add_argument("--" + option, type=pathlib.Path, default=REPO_ROOT / default)
    args = parser.parse_args(argv)
    try:
        rows, primary, defaults = apply_primary(
            args.entries, args.primary_senses, args.default_rows, args.manifest)
    except (OSError, ValueError, KeyError, zlib.error) as error:
        print(f"apply_primary: {error}", file=sys.stderr)
        return 1
    print(f"適用: {rows:,}行 / primary {primary:,}件 / default {defaults:,}件 / 違反0件")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
