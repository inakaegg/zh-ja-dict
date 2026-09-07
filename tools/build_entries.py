#!/usr/bin/env python3
"""CC-CEDICT・HSK・既存の訳から、schema 3 の骨組みを作る。

    python3 tools/build_entries.py \
        --cedict <cedict_1_0_ts_utf-8_mdbg.txt[.gz]> \
        --hsk-seed <hsk-seed.json> \
        --existing data/zh-ja/glosses.jsonl \
        --jieba <jieba.dict.utf8> \
        --out tmp/entries-base.jsonl --order tmp/order.tsv --report tmp/skeleton.md

出るのは「日本語訳がまだ入っていない entry の一覧」で、`tools/generate_ja.py` が
これを読んで語義ごとの訳を作る。最後に `tools/build_dataset.py` が両者を合わせて
`data/` を書く。

entry は2種類ある。

- **骨格 entry** — CC-CEDICT の1行。(簡体, 繁体, ピンイン) で一意（実測で重複0）
- **補遺 entry** — CC-CEDICT に無い、既存 zh-ja-dict だけの語。訳は既存のものを使う

同じ入力からは同じバイト列を出す（集合を反復せず、日付を実行時に取らない）。

Python 3.9 以上。標準ライブラリだけを使う。
"""

from __future__ import annotations

import argparse
import gzip
import json
import pathlib
import sys
from collections import Counter, OrderedDict, defaultdict

sys.path.insert(0, str(pathlib.Path(__file__).resolve().parent))
import cedict  # noqa: E402
import pinyin as pinyin_tools  # noqa: E402

SCHEMA_VERSION = 3

# 出力するキーの順序。値が無いキーは出さない。
ENTRY_KEYS = ("id", "word", "trad", "pinyin", "tw_pr", "also_pr", "cl",
              "hsk2", "hsk3", "pos", "src", "seed", "seed_gloss", "senses")
SENSE_KEYS = ("en", "ja", "qa", "unsure", "misc", "variant_of", "see_also",
              "lsource", "s_inf")

# 参照だけの語義に機械で当てる訳の型。README の表と test_build_entries.py が正本。
DERIVED_FORMS = {
    "variant": "{ref}の異体字",
    "old": "{ref}の旧字体",
    "erhua": "{ref}の儿化形",
    "see": "{ref}に同じ",
    "see_also": "{ref}も参照",
    "abbr": "{ref}の略",
    "used_in": "{ref}に使われる字",
}


def sandhi_match(cedict_pinyin: str, old_pinyin: str) -> bool:
    """旧版の読みが、`一`・`不` の変調だけを直せば CC-CEDICT の読みと同じか。

    旧版は変調を書き込んだ読みを持ち（`一点一滴 yìdiǎn yìdī`）、CC-CEDICT は変調前を
    書く（`yi1 dian3 yi1 di1`）。**認めるのはこの2音節の声調の違いだけ**で、ほかの
    音節の声調や軽声の違いは別の読みである。`一场空` の `chǎng`／`cháng` や
    `不足齿数` の `shǔ`／`shù` を同じものとして扱うと、旧版の読みと訳が消える。
    """
    return bool(pinyin_tools.sandhi_pattern(cedict_pinyin)
                .match(pinyin_tools.key(old_pinyin)))


def read_cedict_text(path: pathlib.Path):
    """`.gz` でも生でも読めるようにする。取り違えを避けるため中身で判定しない。"""
    opener = gzip.open if path.suffix == ".gz" else open
    with opener(path, "rt", encoding="utf-8") as source:
        for line in source:
            yield line


def read_jsonl(path: pathlib.Path):
    rows = []
    with path.open(encoding="utf-8") as source:
        for line in source:
            if line.strip():
                rows.append(json.loads(line))
    return rows


def dump_line(obj: dict, keys) -> str:
    ordered = OrderedDict((k, obj[k]) for k in keys if k in obj)
    unknown = [k for k in obj if k not in keys]
    if unknown:
        raise SystemExit(f"仕様に無いキーを出そうとした: {unknown} ({obj.get('word')})")
    return json.dumps(ordered, ensure_ascii=False)


def ref_label(ref: dict) -> str:
    """`{"w": "开金", "py": "kai1 jin1"}` を `开金（kāi jīn）` にする。"""
    word = ref["w"]
    reading = ref.get("py")
    if not reading:
        return word
    return f"{word}（{pinyin_tools.to_marks(reading)}）"


def derived_ja(sense: dict) -> str:
    """英語の語義文が無い語義に、参照から機械で訳を当てる。

    CC-CEDICT の異体字・参照の項目は文が無く、`variant of 汝[ru3]` のように
    参照だけが書いてある。形が決まっているので LLM を通さない。
    """
    for field in ("variant_of", "see_also"):
        refs = sense.get(field) or []
        if not refs:
            continue
        kind = refs[0]["kind"]
        label = "・".join(ref_label(ref) for ref in refs)
        return DERIVED_FORMS[kind].format(ref=label)
    return ""


def sense_to_dict(sense: cedict.Sense) -> dict:
    out = {}
    for key in ("en", "misc", "variant_of", "see_also", "lsource", "s_inf"):
        value = getattr(sense, key)
        if value:
            out[key] = value
    return out


# --- HSK と品詞 ---------------------------------------------------------------

def load_hsk(path: pathlib.Path):
    """hsk-seed.json から (語 -> 級・品詞・読み) を読む。

    `hsk_levels` は HSK 2.0 と 3.0 の級を併記していて、片方が `null` のことがある。
    既存データと同じく、両方をそれぞれの欄へ入れる。
    """
    root = json.loads(path.read_text(encoding="utf-8"))
    table = OrderedDict()
    for entry in root["entries"]:
        levels = entry.get("hsk_levels") or {}
        table[entry["word"]] = {
            "hsk2": levels.get("2.0"),
            "hsk3": levels.get("3.0"),
            "pos": [code for code in
                    dict.fromkeys(x.strip() for x in (entry.get("pos") or "").split(","))
                    if code and code != "unknown"],
            "pinyin_key": pinyin_tools.key(entry.get("pinyin") or ""),
        }
    return table


def load_jieba(path: pathlib.Path):
    """`語 頻度 品詞` の行から (語 -> 頻度) を読む。並べる順を決めるためだけに使う。"""
    freq = {}
    with path.open(encoding="utf-8") as source:
        for line in source:
            parts = line.split()
            if len(parts) >= 2 and parts[1].isdigit():
                freq[parts[0]] = int(parts[1])
    return freq


# --- 組み立て -----------------------------------------------------------------

def build(args) -> int:
    report = []

    def say(text=""):
        print(text, flush=True)
        report.append(text)

    # 1. CC-CEDICT
    declared = cedict.declared_entries(args.cedict) if args.cedict.suffix != ".gz" else None
    entries = []
    for index, line in enumerate(read_cedict_text(args.cedict)):
        if declared is None and line.startswith("#!"):
            import re
            found = re.match(r"^#!\s*entries=(\d+)", line)
            if found:
                declared = int(found.group(1))
        parsed = cedict.parse_line(line)
        if parsed is None:
            continue
        entries.append(parsed)
    say(f"CC-CEDICT を読んだ: {len(entries):,} entry（宣言値 {declared:,}）")
    if declared is not None and declared != len(entries):
        raise SystemExit(f"中止: entry 数が宣言値と違う（{len(entries)} / {declared}）")

    # 2. HSK と品詞
    hsk = load_hsk(args.hsk_seed)
    say(f"HSK を読んだ: {len(hsk):,} 語")

    # 3. 既存の訳
    existing = read_jsonl(args.existing)
    say(f"既存の訳を読んだ: {len(existing):,} 行")

    # 骨格 entry を組み立てる。
    rows = []
    by_word = defaultdict(list)          # 簡体 -> 骨格 entry の位置
    by_word_pinyin = defaultdict(list)   # (簡体, 読みの鍵) -> 骨格 entry の位置
    by_word_toneless = defaultdict(list)   # (綴り, 声調なしの鍵) -> 骨格 entry の位置
    derived_count = 0
    for index, entry in enumerate(entries):
        senses = []
        for sense in entry.senses:
            item = sense_to_dict(sense)
            if not item.get("en"):
                text = derived_ja(item)
                if text:
                    item["ja"] = text
                    item["qa"] = "derived"
                    derived_count += 1
            senses.append(item)
        row = {
            "id": f"c{index + 1}",
            "word": entry.simp,
            "pinyin": pinyin_tools.to_marks(entry.pinyin),
            "senses": senses,
        }
        if entry.trad != entry.simp:
            row["trad"] = entry.trad
        if entry.cl:
            row["cl"] = entry.cl
        if entry.tw_pr:
            row["tw_pr"] = pinyin_tools.to_marks(entry.tw_pr)
        if entry.also_pr:
            row["also_pr"] = pinyin_tools.to_marks(entry.also_pr)
        rows.append(row)
        # 既存データには繁体字の見出しも混じる（`雙`・`經過` など）。どちらの綴りからも
        # 引けるようにしておかないと、同じ語を補遺として二重に持つことになる。
        key = pinyin_tools.key(entry.pinyin)
        toneless = pinyin_tools.toneless_key(entry.pinyin)
        for spelling in dict.fromkeys((entry.simp, entry.trad)):
            by_word[spelling].append(index)
            by_word_pinyin[(spelling, key)].append(index)
            by_word_toneless[(spelling, toneless)].append(index)
    say(f"参照から機械で訳を当てた語義: {derived_count:,}")

    # 4. HSK の級と品詞を当てる。
    #
    # **級は語の属性なので、同じ見出し語のすべての entry へ付ける。** 読みが一致する
    # entry だけに付けると、`了 liǎo` に級があって `了 le` に無い、といった歯抜けが
    # できる。旧版も「同じ語のすべての行が同じ値を持つ」形だった。
    hsk_by_reading = 0
    hsk_missing = []
    for word, info in hsk.items():
        targets = by_word.get(word)
        if not targets:
            hsk_missing.append(word)
            continue
        if by_word_pinyin.get((word, info["pinyin_key"])):
            hsk_by_reading += 1
        for index in targets:
            if info["hsk2"] is not None:
                rows[index]["hsk2"] = info["hsk2"]
            if info["hsk3"] is not None:
                rows[index]["hsk3"] = info["hsk3"]
            if info["pos"]:
                rows[index]["pos"] = info["pos"]
    say(f"HSK: 見出しが当たった {len(hsk) - len(hsk_missing):,} 語"
        f"（うち読みも一致 {hsk_by_reading:,} 語） / CC-CEDICT に無い {len(hsk_missing):,} 語")

    # 5. 既存の訳を候補として当てる。当たらなかった行は補遺 entry にする。
    matched_exact = 0
    matched_sandhi = 0
    supplement_rows = []
    for existing_index, existing_row in enumerate(existing, start=1):
        word = existing_row["word"]
        key = pinyin_tools.key(existing_row["pinyin"])
        targets = by_word_pinyin.get((word, key))
        if targets:
            matched_exact += 1
        else:
            # 声調の違いを認めるのは `一`・`不` の変調だけ。音節ごとに突き合わせる。
            # ここを緩めると、`繃 bèng` が `繃 bēng` に当たって旧版の読みと訳が
            # 消えたまま「対応済み」と数えられる。当たらないものは補遺 entry にする。
            candidates = by_word_toneless.get(
                (word, pinyin_tools.toneless_key(existing_row["pinyin"])), [])
            targets = [i for i in candidates
                       if sandhi_match(entries[i].pinyin, existing_row["pinyin"])]
            if targets:
                matched_sandhi += 1
        if not targets:
            supplement_rows.append((existing_index, existing_row))
            continue
        for index in targets:
            rows[index].setdefault("seed_gloss", [])
            for gloss in existing_row.get("gloss") or []:
                if gloss not in rows[index]["seed_gloss"]:
                    rows[index]["seed_gloss"].append(gloss)
            rows[index]["seed"] = existing_row["qa"]
    say(f"既存の訳: 読みまで一致 {matched_exact:,} 行 / 一・不の変調として当てた "
        f"{matched_sandhi:,} 行 / 補遺へ回した {len(supplement_rows):,} 行")

    # 6. 補遺 entry。訳は既存のものをそのまま使うので、生成の対象にしない。
    # 番号は**旧版ファイルの行番号**から作る。補遺の通し番号にすると、当て込みの
    # 規則を直したときに全部ずれて、既に作った訳と結び付かなくなる。
    for number, existing_row in supplement_rows:
        gloss = [g for g in (existing_row.get("gloss") or []) if g]
        if gloss:
            # 既存の訳は語ごとに1〜3件で、語義に対応していない。1つの語義へまとめる。
            sense = {"ja": "、".join(gloss), "qa": existing_row["qa"]}
            if existing_row.get("unsure"):
                sense["unsure"] = True
        else:
            # 訳を持たない行（実測3行）。語義を1つ置いて、生成の対象に含める。
            sense = {}
        # 旧版には繁体字の見出しが混じる（`繃`）。骨格に同じ綴りの entry があれば、
        # そこから簡体・繁体を取って揃える。**配る形式は `word` が簡体字**なので、
        # 繁体字のまま入れると簡体字だけを索引する読み手が引けなくなる。
        word = existing_row["word"]
        traditional = None
        for index in by_word.get(word, []):
            skeleton = entries[index]
            if skeleton.trad == word and skeleton.simp != word:
                word, traditional = skeleton.simp, skeleton.trad
                break
        row = {
            "id": f"x{number}",
            "word": word,
            "pinyin": existing_row["pinyin"],
            "src": "zh-ja-dict",
            "senses": [sense],
        }
        if traditional:
            row["trad"] = traditional
        else:
            trad = existing_row.get("trad") or []
            if trad and trad[0] != word:
                row["trad"] = trad[0]
        for key in ("hsk2", "hsk3", "pos"):
            if existing_row.get(key) is not None:
                row[key] = existing_row[key]
        # 級は語の属性なので、補遺 entry にも同じ値を付ける。骨格だけに付けると、
        # 旧版から拾った別の読み（`绷 bèng`）が級を持たない歯抜けになる。
        info = hsk.get(word)
        if info:
            for key in ("hsk2", "hsk3"):
                if info[key] is not None:
                    row[key] = info[key]
            if info["pos"]:
                row["pos"] = info["pos"]
        rows.append(row)
    no_gloss = [r for r in rows if r.get("src") and not r["senses"][0]]
    say(f"補遺 entry: {len(supplement_rows):,}（うち既存の訳が空で生成へ回すもの "
        f"{len(no_gloss):,}: {[r['word'] for r in no_gloss]}）")

    # 7. 生成の対象と、回す順番。
    freq = load_jieba(args.jieba) if args.jieba else {}
    say(f"jieba の頻度を読んだ: {len(freq):,} 語（並べる順を決めるためだけに使う）")
    pending = []
    for row in rows:
        need = sum(1 for sense in row["senses"] if "ja" not in sense)
        if need:
            pending.append((row, need))
    say(f"訳の生成が要る entry {len(pending):,} / 語義 {sum(n for _, n in pending):,}")

    def order_key(item):
        row, _ = item
        has_hsk = 0 if (row.get("hsk2") or row.get("hsk3")) else 1
        return (has_hsk, -freq.get(row["word"], 0), row["id"])

    ordered = sorted(pending, key=order_key)
    args.order.parent.mkdir(parents=True, exist_ok=True)
    with args.order.open("w", encoding="utf-8") as sink:
        sink.write("id\tword\tsenses\n")
        for row, need in ordered:
            sink.write(f"{row['id']}\t{row['word']}\t{need}\n")
    say(f"{args.order} へ生成の順番を書いた")

    # 8. 書き出す。
    args.out.parent.mkdir(parents=True, exist_ok=True)
    with args.out.open("w", encoding="utf-8") as sink:
        for row in rows:
            row["senses"] = [
                OrderedDict((k, sense[k]) for k in SENSE_KEYS if k in sense)
                for sense in row["senses"]
            ]
            sink.write(dump_line(row, ENTRY_KEYS) + "\n")
    say(f"{args.out} へ {len(rows):,} entry を書いた"
        f"（骨格 {len(entries):,} ＋ 補遺 {len(supplement_rows):,}）")

    counts = Counter()
    for row in rows:
        for sense in row["senses"]:
            counts[sense.get("qa", "（未生成）")] += 1
    say(f"語義の内訳: {dict(counts)}")

    if args.report:
        args.report.parent.mkdir(parents=True, exist_ok=True)
        args.report.write_text("\n".join(report) + "\n", encoding="utf-8")
    return 0


def main(argv=None) -> int:
    parser = argparse.ArgumentParser(description="schema 3 の骨組みを作る")
    parser.add_argument("--cedict", type=pathlib.Path, required=True)
    parser.add_argument("--hsk-seed", type=pathlib.Path, required=True)
    parser.add_argument("--existing", type=pathlib.Path, required=True)
    parser.add_argument("--jieba", type=pathlib.Path)
    parser.add_argument("--out", type=pathlib.Path, required=True)
    parser.add_argument("--order", type=pathlib.Path, required=True)
    parser.add_argument("--report", type=pathlib.Path)
    return build(parser.parse_args(argv))


if __name__ == "__main__":
    raise SystemExit(main())
