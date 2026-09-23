#!/usr/bin/env python3
"""確定済み中日nativeデータを監査用の共通辞書形式v2へ変換する。"""

from __future__ import annotations

import argparse
import pathlib
import sys

import common_format
import entries_file


REPO_ROOT = pathlib.Path(__file__).resolve().parent.parent


def main(argv=None) -> int:
    parser = argparse.ArgumentParser(description="中日nativeデータから共通辞書形式v2を作る")
    parser.add_argument(
        "--native-entries", type=pathlib.Path,
        default=REPO_ROOT / "data" / "zh-ja" / entries_file.NAME)
    parser.add_argument(
        "--native-manifest", type=pathlib.Path,
        default=REPO_ROOT / "data" / "manifest.json")
    parser.add_argument("--out", type=pathlib.Path, default=REPO_ROOT / "data" / "common")
    parser.add_argument("--limit", type=int, help="段階検証用に先頭N entryだけ変換する")
    args = parser.parse_args(argv)
    try:
        stats = common_format.export_common(
            args.native_entries, args.native_manifest, args.out, limit=args.limit)
    except common_format.CommonFormatError as error:
        print(f"export_common: {error}", file=sys.stderr)
        return 1
    print(f"共通形式を書いた: {stats.entries:,} entries / {stats.senses:,} senses / {args.out}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
