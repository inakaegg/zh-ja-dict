#!/usr/bin/env python3
"""現行の data/ と hsk-seed.json から、(語, 読み) を単位とする新しい glosses.jsonl を作る。

使い方:
    python3 tools/build_glosses.py \
        --current-data data --hsk-seed <path>/hsk-seed.json \
        --generated 2026-09-03 --out <出力先> --report <path>

Python 3.9 以上。標準ライブラリだけを使う。同じ入力と同じ --generated からは
同じバイト列を出す（集合を反復せず、日付を実行時に取らない）。
"""

from __future__ import annotations

import argparse
import json
import pathlib
import sys
from collections import Counter, OrderedDict

# 大小文字だけが違う組のうち、人が「本当に別の語」と判定した語（TASK.md D5）。
# ここに無い語は突き合わせのときに小文字化する。
CASE_KEEP = {"包头", "酂"}

# 出力するキーの順序（TASK.md D17）。値が無いキーは出さない。
KEY_ORDER = ("word", "pinyin", "gloss", "qa", "unsure",
             "hsk2", "hsk3", "trad", "pos", "reading_pos", "alt_pinyin")

SCHEMA_VERSION = 2


def norm(word: str, pinyin: str) -> str:
    """突き合わせの鍵。

    空白・アポストロフィ・ハイフンを除き、原則として小文字化する（TASK.md D5）。
    2つの資料で表記が違うだけの軽声の印は、鍵の上では無視する。

    - 末尾の `5`: hsk-seed は儿化を `yǒukòngr5`、zh-ja-dict は `yǒukòngr` と書く
      （ユーザー指示7）。zh-ja-dict 側に数字で終わるピンインは1つも無い（実測）
    - `˙`（U+02D9 DOT ABOVE）: hsk-seed が軽声の印に使う。`闺女` の `guī ˙nü` に対し
      zh-ja-dict は `guī nü` と書く。hsk-seed に1語、zh-ja-dict に0語（実測）
    """
    text = pinyin.replace(" ", "").replace("'", "").replace("-", "").replace("\u02d9", "")
    if text.endswith("5"):
        text = text[:-1]
    return text if word in CASE_KEEP else text.lower()


def strip_r5(pinyin: str) -> str:
    """hsk-seed の儿化は末尾に 5 を付ける（`yǒukòngr5`）。zh-ja-dict は付けない。"""
    return pinyin[:-1] if pinyin.endswith("5") else pinyin


def dedup(values):
    """入力順を保った重複除去。集合を反復しないので実行ごとに順序が変わらない。"""
    return list(dict.fromkeys(values))


def pos_codes(text):
    """`"m,d,t"` を `["m","d","t"]` にする。情報を持たない `unknown` は落とす。"""
    return [c for c in dedup(x.strip() for x in (text or "").split(",")) if c and c != "unknown"]


def read_jsonl(path: pathlib.Path):
    rows = []
    for line in path.read_text(encoding="utf-8").splitlines():
        if line.strip():
            rows.append(json.loads(line))
    return rows


def dump_line(obj: dict) -> str:
    ordered = OrderedDict((k, obj[k]) for k in KEY_ORDER if k in obj)
    unknown = [k for k in obj if k not in KEY_ORDER]
    if unknown:
        raise SystemExit(f"出力しようとしたキーが仕様にない: {unknown} ({obj.get('word')})")
    return json.dumps(ordered, ensure_ascii=False, separators=(", ", ": "))


def fail(message: str):
    raise SystemExit(f"中止: {message}")


def expect(actual, wanted, label: str):
    """契約に書いた期待値と違ったら止める。黙って進めない。"""
    if actual != wanted:
        fail(f"{label} が期待値と違う: 実際 {actual} / 期待 {wanted}")


def main(argv=None) -> int:
    parser = argparse.ArgumentParser(description="(語, 読み) 単位の glosses.jsonl を作る")
    parser.add_argument("--current-data", type=pathlib.Path, required=True)
    parser.add_argument("--hsk-seed", type=pathlib.Path, required=True)
    parser.add_argument("--generated", required=True, help="manifest に書く日付 YYYY-MM-DD（必須）")
    parser.add_argument("--out", type=pathlib.Path, required=True)
    parser.add_argument("--report", type=pathlib.Path)
    parser.add_argument("--no-expect", action="store_true", help="期待値の照合を飛ばす（調査用）")
    args = parser.parse_args(argv)

    check = not args.no_expect

    # ---- 1. 読み込み（入力順を保つ）
    gl_rows = read_jsonl(args.current_data / "zh-ja" / "glosses.jsonl")
    poly_rows = read_jsonl(args.current_data / "zh-ja" / "polyphonic.jsonl")
    seed_root = json.loads(args.hsk_seed.read_text(encoding="utf-8"))
    seed_entries = seed_root["entries"]
    seed = OrderedDict((e["word"], e) for e in seed_entries)

    if check:
        expect(len(gl_rows), 95463, "現行 glosses.jsonl の行数")
        expect(len(poly_rows), 4552, "現行 polyphonic.jsonl の行数")
        expect(len(seed_entries), 11470, "hsk-seed の語数")

    # 語 -> 既存行（現行は語ごとに1行）
    existing = OrderedDict()
    for row in gl_rows:
        existing.setdefault(row["word"], []).append(row)

    # D7: hsk-seed にあって zh-ja-dict に無い語は、黙って落とさず止める。
    missing = [w for w in seed if w not in existing]
    if missing:
        fail(f"hsk-seed にあって glosses.jsonl に無い語が {len(missing)} 語ある: {missing[:5]}")

    # ---- 2. 語の属性（D12）
    attributes = {}
    for word, entry in seed.items():
        attr = {}
        levels = entry.get("hsk_levels") or {}
        if isinstance(levels.get("2.0"), int):
            attr["hsk2"] = levels["2.0"]
        if isinstance(levels.get("3.0"), int):
            attr["hsk3"] = levels["3.0"]
        # D1: word と異なる繁体字の綴りを全部入れる（ICU に依存しない）
        spellings = {entry["traditional"]} | {f["traditional"] for f in entry["source_forms"]}
        trad = sorted(s for s in spellings if s != word)
        if trad:
            attr["trad"] = trad
        pos = pos_codes(entry["pos"])
        if pos:
            attr["pos"] = pos
        # D16: 上流にしか無い読み
        known = {norm(word, entry["pinyin"])} | {norm(word, s["pinyin"]) for s in entry["senses"]}
        alt = []
        for form in entry["source_forms"]:
            key = norm(word, form["pinyin"])
            if key not in known and key not in {norm(word, a) for a in alt}:
                alt.append(strip_r5(form["pinyin"]))
        if alt:
            attr["alt_pinyin"] = alt
        attributes[word] = attr

    if check:
        expect(sum(1 for a in attributes.values() if "trad" in a), 6830, "trad を持つ語")
        expect(sum(1 for a in attributes.values() if "alt_pinyin" in a), 334, "alt_pinyin を持つ語")
        expect(sum(len(a["alt_pinyin"]) for a in attributes.values() if "alt_pinyin" in a), 370,
               "alt_pinyin の値の総数")

    # ---- 3. 既存行を作り直す
    rows_by_word = OrderedDict()
    order = []
    dedup_detail = []
    for row in gl_rows:
        word = row["word"]
        # 既存の訳はそのまま運ぶ。ただし完全な重複だけは落とす（実データに1行ある: 酪酸）。
        # 情報を持たない重複で、validator の「配列に重複なし」と両立させるために要る。
        new = {"word": word, "pinyin": row["pinyin"], "gloss": dedup(row["gloss"]), "qa": row["qa"]}
        if row.get("unsure") is True:
            new["unsure"] = True
        new.update(attributes.get(word, {}))
        if len(new["gloss"]) != len(row["gloss"]):
            dedup_detail.append({"word": word, "before": row["gloss"], "after": new["gloss"]})
        rows_by_word.setdefault(word, []).append(new)
        order.append(word)

    # hsk-seed の語ごとに「読み -> その読みの sense」を作る（4・6b で共有する）
    senses_by_reading = {}
    for word, entry in seed.items():
        table = OrderedDict()
        for sense in entry["senses"]:
            table.setdefault(norm(word, sense["pinyin"]), []).append(sense)
        senses_by_reading[word] = table

    # ---- 4. D11 の振り分け（多読み52語）
    multi_words = [w for w, t in senses_by_reading.items() if len(t) >= 2]
    if check:
        expect(len(multi_words), 52, "hsk-seed の多読み語")

    moved = kept = 0
    moved_detail = []
    for word in multi_words:
        row = rows_by_word[word][0]
        row_key = norm(word, row["pinyin"])
        table = senses_by_reading[word]
        own = {s["meaning_ja"] for s in table.get(row_key, [])}
        other = {s["meaning_ja"] for key, ss in table.items() if key != row_key for s in ss}
        removable = other - own          # ★差集合。own に入る訳は動かさない（嗯 の「うん」）
        before = list(row["gloss"])
        row["gloss"] = [g for g in before if g not in removable]
        gone = [g for g in before if g in removable]
        moved += len(gone)
        kept += len(row["gloss"])
        if gone:
            moved_detail.append({"word": word, "pinyin": row["pinyin"],
                                 "before": before, "after": list(row["gloss"]), "moved": gone})
        if not row["gloss"]:
            fail(f"D11 の振り分けで gloss が空になった: {word}")

    if check:
        expect(moved, 60, "D11 で動かした訳")
        expect(kept, 93, "D11 で残した訳")
        expect(len(moved_detail), 51, "D11 で訳が動いた語")
        expect(next(len(d["moved"]) for d in moved_detail if d["word"] == "嗯") if
               any(d["word"] == "嗯" for d in moved_detail) else 0, 0, "嗯 の移動件数")

    # ---- 5. `赶` の吸収（ユーザー決定 2026-09-03）
    # 実データでは `赶` は必ず在る。期待値の照合（下）が在ることまで確かめる。
    # 小さなfixtureでも動くよう、無ければ何もしない。
    added_gan = []
    if "赶" in rows_by_word and "赶" in senses_by_reading:
        gan = rows_by_word["赶"][0]
        key_gan = norm("赶", gan["pinyin"])
        for sense in senses_by_reading["赶"].get(key_gan, []):
            if sense["meaning_ja"] not in gan["gloss"]:
                gan["gloss"].append(sense["meaning_ja"])
                added_gan.append(sense["meaning_ja"])
    if check:
        expect(added_gan, ["間に合う"], "赶 へ足した訳")
        expect(len(rows_by_word["赶"][0]["gloss"]), 4, "赶 の gloss の件数")

    # ---- 6. 追加行
    added_poly = added_seed = 0
    tail_rows = []           # D6: 既存行が無い語（D8）は全既存行の後ろへ
    d8_words = 0

    # (a) polyphonic の多読み語（既存行がある語）
    for entry in poly_rows:
        word = entry["word"]
        senses = entry["senses"]
        if word not in rows_by_word:
            continue
        if len(senses) < 2:
            continue
        known = {norm(word, r["pinyin"]) for r in rows_by_word[word]}
        # D9: 同じ読みの sense が複数あるときは、入力順を保って1行へ併合する。
        # 2件目を捨てると訳が失われる（現データにこの経路は無いが、規則として実装する）。
        made = {}
        for sense in senses:
            key = norm(word, sense["pinyin"])
            if key in known:
                continue
            if key in made:
                row = made[key]
                row["gloss"] = dedup(row["gloss"] + list(sense["gloss"]))
                continue
            new = {"word": word, "pinyin": sense["pinyin"],
                   "gloss": dedup(sense["gloss"]), "qa": "unchecked"}
            new.update(attributes.get(word, {}))
            rows_by_word[word].append(new)
            made[key] = new
            added_poly += 1

    # (c) polyphonic にしか無い語のうち訳を持つもの（D8）
    for entry in poly_rows:
        word = entry["word"]
        if word in rows_by_word or not entry["senses"]:
            continue
        d8_words += 1
        merged = OrderedDict()
        for sense in entry["senses"]:
            merged.setdefault(norm(word, sense["pinyin"]), []).append(sense)
        for key, ss in merged.items():
            new = {"word": word, "pinyin": ss[0]["pinyin"],
                   "gloss": dedup(g for s in ss for g in s["gloss"]), "qa": "unchecked"}
            tail_rows.append(new)

    # (b) hsk-seed の多読み52語
    for word in multi_words:
        known = {norm(word, r["pinyin"]) for r in rows_by_word[word]}
        for key, ss in senses_by_reading[word].items():
            if key in known:
                continue
            new = {"word": word, "pinyin": strip_r5(ss[0]["pinyin"]),
                   "gloss": dedup(s["meaning_ja"] for s in ss), "qa": "human_reviewed"}
            new.update(attributes.get(word, {}))
            rows_by_word[word].append(new)
            added_seed += 1

    if check:
        expect(added_poly, 784, "polyphonic 由来の追加行")
        expect(added_seed, 62, "hsk-seed 由来の追加行")
        expect(d8_words, 15, "D8 の語数")
        expect(len(tail_rows), 17, "D8 の行数")

    # ---- 7. reading_pos（D15）
    reading_pos_rows = 0
    reading_pos_words = set()
    for word, entry in seed.items():
        word_pos = set(pos_codes(entry["pos"]))
        for row in rows_by_word[word]:
            table = senses_by_reading[word].get(norm(word, row["pinyin"]))
            if not table:
                continue
            row_pos = dedup(c for s in table for c in pos_codes(s.get("pos")))
            if row_pos and set(row_pos) != word_pos:
                row["reading_pos"] = row_pos
                reading_pos_rows += 1
                reading_pos_words.add(word)
    if check:
        expect(reading_pos_rows, 98, "reading_pos を持つ行")
        expect(len(reading_pos_words), 48, "reading_pos を持つ語")

    # ---- 8. 並べ替え（D6）
    out_rows = []
    emitted = set()
    for word in order:
        if word in emitted:
            continue
        emitted.add(word)
        out_rows.extend(rows_by_word[word])
    out_rows.extend(tail_rows)

    if check:
        expect(len(out_rows), 96326, "新 glosses.jsonl の行数")
        expect(sum(1 for r in out_rows if r["qa"] == "unchecked"), 801, "qa: unchecked の行")
        expect(sum(1 for r in out_rows if r["qa"] == "human_reviewed"), 62, "qa: human_reviewed の行")

    seen_keys = {}
    for index, row in enumerate(out_rows):
        key = (row["word"], norm(row["word"], row["pinyin"]))
        if key in seen_keys:
            fail(f"(語, 読み) が重複している: {key} 行{index + 1} と 行{seen_keys[key] + 1}")
        seen_keys[key] = index

    # ---- 9. 出力
    out_dir = args.out
    (out_dir / "zh-ja").mkdir(parents=True, exist_ok=True)
    (out_dir / "ja-zh").mkdir(parents=True, exist_ok=True)
    target = out_dir / "zh-ja" / "glosses.jsonl"
    target.write_text("".join(dump_line(r) + "\n" for r in out_rows), encoding="utf-8")

    ja_zh = (args.current_data / "ja-zh" / "glosses.jsonl").read_bytes()
    (out_dir / "ja-zh" / "glosses.jsonl").write_bytes(ja_zh)
    ja_zh_lines = ja_zh.decode("utf-8").count("\n")

    # ---- 10. manifest（D13）
    manifest = OrderedDict([
        ("schema_version", SCHEMA_VERSION),
        ("generated", args.generated),
        ("files", OrderedDict([
            ("zh-ja/glosses.jsonl", {"lines": len(out_rows)}),
            ("ja-zh/glosses.jsonl", {"lines": ja_zh_lines}),
        ])),
    ])
    (out_dir / "manifest.json").write_text(
        json.dumps(manifest, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")

    # ---- 11. レポート（実行時刻も絶対pathも入れない）
    qa_counts = Counter(r["qa"] for r in out_rows)
    report = OrderedDict([
        ("schema_version", SCHEMA_VERSION),
        ("rows", OrderedDict([
            ("existing", len(gl_rows)),
            ("added_from_polyphonic", added_poly),
            ("added_from_hsk_seed", added_seed),
            ("added_polyphonic_only", len(tail_rows)),
            ("total", len(out_rows)),
        ])),
        ("words", len(rows_by_word) + d8_words),
        ("qa", OrderedDict(sorted(qa_counts.items()))),
        ("attributes", OrderedDict([
            ("hsk2", sum(1 for r in out_rows if "hsk2" in r)),
            ("hsk3", sum(1 for r in out_rows if "hsk3" in r)),
            ("trad", sum(1 for r in out_rows if "trad" in r)),
            ("pos", sum(1 for r in out_rows if "pos" in r)),
            ("reading_pos", reading_pos_rows),
            ("alt_pinyin", sum(1 for r in out_rows if "alt_pinyin" in r)),
        ])),
        ("d11", OrderedDict([("moved", moved), ("kept", kept), ("words", len(moved_detail))])),
        ("d11_detail", moved_detail),
        ("gan_added", added_gan),
        ("gloss_dedup", dedup_detail),
    ])
    text = json.dumps(report, ensure_ascii=False, indent=2) + "\n"
    if args.report:
        args.report.write_text(text, encoding="utf-8")
    else:
        sys.stdout.write(text)
    return 0


if __name__ == "__main__":
    sys.exit(main())
