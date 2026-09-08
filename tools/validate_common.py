#!/usr/bin/env python3
"""中日共通辞書形式v1とnativeへの逆投影を検査する。"""

from __future__ import annotations

import argparse
import pathlib
import sys

import common_format
import entries_file


REPO_ROOT = pathlib.Path(__file__).resolve().parent.parent


def main(argv=None) -> int:
    parser = argparse.ArgumentParser(description="中日共通辞書形式v1を全件検査する")
    parser.add_argument(
        "--entries", type=pathlib.Path,
        default=REPO_ROOT / "data" / "common" / entries_file.NAME)
    parser.add_argument(
        "--manifest", type=pathlib.Path,
        default=REPO_ROOT / "data" / "common" / "manifest.json")
    parser.add_argument(
        "--native-entries", type=pathlib.Path,
        default=REPO_ROOT / "data" / "zh-ja" / entries_file.NAME)
    parser.add_argument(
        "--native-manifest", type=pathlib.Path,
        default=REPO_ROOT / "data" / "manifest.json")
    parser.add_argument("--limit", type=int, help="段階検証用に先頭N entryだけ比較する")
    args = parser.parse_args(argv)
    try:
        stats = common_format.validate_common(
            args.entries, args.manifest, args.native_entries, args.native_manifest,
            limit=args.limit)
    except (OSError, common_format.CommonFormatError) as error:
        print(f"validate_common: {error}", file=sys.stderr)
        return 1
    print(
        f"共通形式: {stats.entries:,} entries / {stats.senses:,} senses / "
        f"{stats.translations:,} translations / 違反0件")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
