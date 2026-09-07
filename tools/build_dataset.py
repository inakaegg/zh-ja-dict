#!/usr/bin/env python3
"""骨組みと生成した訳を合わせて `data/` を書く。

    python3 tools/build_dataset.py \
        --base tmp/entries-base.jsonl --glosses tmp/ja-full.jsonl \
        --moedict <dict-revised.json> --generated 2026-09-06 \
        --out data --report tmp/dataset.md

出るのは次の2つ。

- `data/zh-ja/entries.jsonl.deflate` — 1行1 entry の JSON Lines を raw DEFLATE で固めたもの
- `data/manifest.json` — 行数・大きさ・出どころ

`data/ja-zh/glosses.jsonl` は触らない（日中は ja-learner-dict が引き継ぐ）。

同じ入力と同じ `--generated` からは同じバイト列を出す。

Python 3.9 以上。標準ライブラリだけを使う。
"""

from __future__ import annotations

import argparse
import json
import pathlib
import sys
from collections import Counter, OrderedDict

sys.path.insert(0, str(pathlib.Path(__file__).resolve().parent))
import dataset_sources  # noqa: E402
import entries_file  # noqa: E402
import validate_data  # noqa: E402

# 配るデータのキーの順序。骨組みだけで使う `id`・`seed_gloss` はここに無い＝落とす。
ENTRY_KEYS = ("word", "trad", "pinyin", "tw_pr", "also_pr", "cl",
              "hsk2", "hsk3", "pos", "src", "seed", "moe", "senses")
SENSE_KEYS = ("en", "ja", "qa", "unsure", "misc", "variant_of", "see_also",
              "lsource", "s_inf")

DIRECTION = "zh-ja"


def read_jsonl(path: pathlib.Path):
    with path.open(encoding="utf-8") as source:
        for line in source:
            if line.strip():
                yield json.loads(line)


def load_moedict(path: pathlib.Path):
    """萌典から (繁体の見出し -> 語義の数) だけを取る。**本文は読み捨てる。**

    照合に要るのは「その見出しが在るか」「語義がいくつあるか」だけである。
    本文を持ち回ると、うっかり生成物へ混ぜる道ができる。
    """
    counts = {}
    for entry in json.loads(path.read_text(encoding="utf-8")):
        title = entry.get("title")
        if not title:
            continue
        total = sum(len(reading.get("definitions") or [])
                    for reading in entry.get("heteronyms") or [])
        counts[title] = max(counts.get(title, 0), total)
    return counts


def moe_verdict(entry: dict, counts: dict):
    """萌典との照合結果。見出しは繁体字で引く（萌典は台湾の辞典なので）。"""
    if not counts:
        return None
    headword = entry.get("trad") or entry["word"]
    found = counts.get(headword)
    if found is None:
        return "none"
    return "full" if found >= len(entry["senses"]) else "headword"


# 語義をまとめてよいかを見るときに突き合わせる注記。`en` と `ja` は含めない。
_NOTE_KEYS = ("misc", "variant_of", "see_also", "lsource", "s_inf", "unsure")


def _notes(sense: dict) -> str:
    return json.dumps({key: sense.get(key) for key in _NOTE_KEYS},
                      ensure_ascii=False, sort_keys=True)


def collapse_duplicate_ja(senses: list) -> list:
    """同じ entry の中で日本語訳が同じ語義を1つにまとめる。

    CC-CEDICT は英語の同義語を別々の語義として並べる（`时代` の `age` と `era`、
    `水果刀` の `paring knife` と `fruit knife`）。日本語にすると同じ訳になるので、
    そのままでは画面に同じ訳が並ぶ。

    **英語の語義は捨てず、`en` を順に連ねる。** まとめるのは注記（`misc`・参照・
    借用元・`s_inf`・`unsure`）がすべて同じ語義どうしに限る。注記が違うものまで
    まとめると、口語や方言の印が付いていない語義にまで印が付いてしまう。

    `qa` は最初の語義のものを引き継ぐ。ただし1つでも `llm_fixed` があれば
    `llm_fixed` にする（作り直しがあった事実を隠さない）。
    """
    order: list = []
    merged: dict = {}
    for sense in senses:
        key = (sense.get("ja"), _notes(sense))
        first = merged.get(key)
        if first is None:
            merged[key] = sense
            order.append(key)
            continue
        for gloss in sense.get("en") or []:
            if gloss not in first.setdefault("en", []):
                first["en"].append(gloss)
        if sense.get("qa") == "llm_fixed":
            first["qa"] = "llm_fixed"
    return [merged[key] for key in order]


OVERRIDES = pathlib.Path(__file__).resolve().parent / "gloss-overrides.tsv"


def load_overrides(path: pathlib.Path = OVERRIDES) -> dict:
    """人が書いた訳の上書きを読む。鍵は (見出し語, 読み, 語義の番号)。

    生成と作り直しを繰り返しても決まりに合う訳が出ない語義がわずかに残る。
    そこだけ人が書いて差し替え、`qa` を `hand_fixed` にして出どころを隠さない。
    """
    table = {}
    if not path.exists():
        return table
    for line in path.read_text(encoding="utf-8").splitlines():
        if not line.strip() or line.startswith("#"):
            continue
        columns = line.split("\t")
        if len(columns) < 4:
            raise SystemExit(f"上書きの行に列が足りない: {line!r}")
        word, pinyin, number, japanese = columns[:4]
        table[(word, pinyin, int(number))] = japanese
    return table


def load_repaired(paths):
    """作り直した語義の (id, 番号) を集める。`qa` を `llm_fixed` にするために使う。"""
    repaired = set()
    for path in paths:
        if not path.exists():
            continue
        for line in path.read_text(encoding="utf-8").splitlines():
            if not line.strip():
                continue
            row = json.loads(line)
            repaired.add((str(row["id"]), int(row["sense"])))
    return repaired


def build(args) -> int:
    report = []

    def say(text=""):
        print(text, flush=True)
        report.append(text)

    glosses = {}
    for path in args.glosses:
        for row in read_jsonl(path):
            glosses[(str(row["id"]), int(row["sense"]))] = row["ja"]
    say(f"生成した訳を読んだ: {len(glosses):,} 語義")

    repaired = load_repaired(args.repaired)
    say(f"作り直した語義: {len(repaired):,}")

    counts = load_moedict(args.moedict) if args.moedict else {}
    say(f"萌典の見出しを読んだ: {len(counts):,}（本文は保持しない）")

    overrides = load_overrides(args.overrides)
    used_overrides = set()
    say(f"人が書いた訳の上書き: {len(overrides):,}")

    rows = []
    missing = []
    collapsed = 0
    qa_counts = Counter()
    moe_counts = Counter()
    for entry in read_jsonl(args.base):
        entry_id = entry.pop("id")
        entry.pop("seed_gloss", None)
        senses = []
        for number, sense in enumerate(entry["senses"], start=1):
            if not sense.get("ja"):
                text = glosses.get((entry_id, number))
                if text is None:
                    missing.append(f"{entry_id}#{number} {entry['word']}")
                    continue
                sense["ja"] = text
                sense["qa"] = "llm_fixed" if (entry_id, number) in repaired else "llm_ok"
            key = (entry["word"], entry["pinyin"], number)
            if key in overrides:
                sense["ja"] = overrides[key]
                sense["qa"] = "hand_fixed"
                used_overrides.add(key)
            senses.append(sense)
        before = len(senses)
        senses = collapse_duplicate_ja(senses)
        collapsed += before - len(senses)
        for sense in senses:
            qa_counts[sense["qa"]] += 1
        entry["senses"] = [OrderedDict((k, sense[k]) for k in SENSE_KEYS if k in sense)
                           for sense in senses]
        verdict = moe_verdict(entry, counts)
        if verdict:
            entry["moe"] = verdict
            moe_counts[verdict] += 1
        unknown = [k for k in entry if k not in ENTRY_KEYS]
        if unknown:
            raise SystemExit(f"仕様に無いキー {unknown}: {entry['word']}")
        rows.append(OrderedDict((k, entry[k]) for k in ENTRY_KEYS if k in entry))

    stale = sorted(set(overrides) - used_overrides)
    if stale:
        raise SystemExit(f"中止: 当たらない上書きがある（古い行が残っている）: {stale}")

    if missing:
        say(f"**訳が埋まっていない語義: {len(missing):,}**")
        for item in missing[:20]:
            say(f"  {item}")
        if not args.allow_missing:
            raise SystemExit("中止: 訳の無い語義がある。--allow-missing で下見だけできる")

    empty = [row for row in rows if not row["senses"]]
    if empty:
        say(f"語義が1つも無い entry: {len(empty):,} → 落とす: "
            f"{[row['word'] for row in empty[:10]]}")
        rows = [row for row in rows if row["senses"]]

    skeleton = sum(1 for row in rows if not row.get("src"))
    supplement = len(rows) - skeleton
    say(f"entry {len(rows):,}（骨格 {skeleton:,} ＋ 補遺 {supplement:,}）"
        f" / 語義 {sum(len(row['senses']) for row in rows):,}")
    say(f"訳が同じで1つにまとめた語義: {collapsed:,}")
    say(f"qa の内訳: {dict(qa_counts)}")
    say(f"moe の内訳: {dict(moe_counts)}")

    target = args.out / DIRECTION / entries_file.NAME
    sizes = entries_file.write(
        target, (json.dumps(row, ensure_ascii=False) for row in rows))
    say(f"{target} へ書いた: 圧縮後 {sizes.compressed:,} バイト / "
        f"展開後 {sizes.uncompressed:,} バイト"
        f"（{100 * sizes.compressed / sizes.uncompressed:.1f}%）")

    manifest = OrderedDict()
    manifest["schema_version"] = dataset_sources.SCHEMA_VERSION
    manifest["generated"] = args.generated
    manifest["files"] = OrderedDict()
    manifest["files"][f"{DIRECTION}/{entries_file.NAME}"] = OrderedDict([
        ("lines", len(rows)),
        ("entries_skeleton", skeleton),
        ("entries_supplement", supplement),
        ("senses", sum(len(row["senses"]) for row in rows)),
        ("compression", entries_file.COMPRESSION),
        ("bytes", sizes.compressed),
        ("uncompressed_bytes", sizes.uncompressed),
    ])
    ja_zh = args.out / "ja-zh" / "glosses.jsonl"
    if ja_zh.exists():
        with ja_zh.open(encoding="utf-8") as source:
            manifest["files"]["ja-zh/glosses.jsonl"] = {
                "lines": sum(1 for line in source if line.strip())}
    manifest["sources"] = dataset_sources.SOURCES
    (args.out / "manifest.json").write_text(
        json.dumps(manifest, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
    say(f"{args.out / 'manifest.json'} を書いた")

    if args.report:
        args.report.parent.mkdir(parents=True, exist_ok=True)
        args.report.write_text("\n".join(report) + "\n", encoding="utf-8")
    return 0


def main(argv=None) -> int:
    parser = argparse.ArgumentParser(description="骨組みと訳を合わせて data/ を書く")
    parser.add_argument("--base", type=pathlib.Path, required=True)
    parser.add_argument("--glosses", action="append", type=pathlib.Path, default=[],
                        required=True)
    parser.add_argument("--repaired", action="append", type=pathlib.Path, default=[],
                        help="作り直した語義の記録。`qa` を llm_fixed にする")
    parser.add_argument("--moedict", type=pathlib.Path)
    parser.add_argument("--overrides", type=pathlib.Path, default=OVERRIDES,
                        help="人が書いた訳の上書き（既定は tools/gloss-overrides.tsv）")
    parser.add_argument("--generated", required=True, help="manifest に書く日付 YYYY-MM-DD")
    parser.add_argument("--out", type=pathlib.Path, required=True)
    parser.add_argument("--report", type=pathlib.Path)
    parser.add_argument("--allow-missing", action="store_true",
                        help="訳の無い語義があっても止めない（下見用）")
    return build(parser.parse_args(argv))


if __name__ == "__main__":
    raise SystemExit(main())
