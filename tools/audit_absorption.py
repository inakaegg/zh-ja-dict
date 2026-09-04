#!/usr/bin/env python3
"""hsk-seed.json の全キー経路が、新形式へ吸収されたか廃棄されたかを照合する。

TASK.md の D14 の対応表を、そのままこのファイルの表として持つ。
使い方:
    python3 tools/audit_absorption.py --hsk-seed <path> --data <新data> --old-data <旧data> [--readme README.md]

Python 3.9 以上。標準ライブラリだけを使う。read-only。
"""

from __future__ import annotations

import argparse
import json
import pathlib
import sys
from collections import Counter, OrderedDict

CASE_KEEP = {"包头", "酂"}


def norm(word, pinyin):
    """build_glosses.py と同じ鍵。軽声の印（末尾の `5`、`˙`）も落とす。"""
    t = pinyin.replace(" ", "").replace("'", "").replace("-", "").replace("\u02d9", "")
    if t.endswith("5"):
        t = t[:-1]
    return t if word in CASE_KEEP else t.lower()


def dedup(values):
    return list(dict.fromkeys(values))


def pos_codes(text):
    return [c for c in dedup(x.strip() for x in (text or "").split(",")) if c and c != "unknown"]


def read_jsonl(path):
    return [json.loads(l) for l in path.read_text(encoding="utf-8").splitlines() if l.strip()]


def key_paths(node, prefix=""):
    """hsk-seed を歩いて、値を持つキー経路を数える。"""
    counts = Counter()
    if isinstance(node, dict):
        for k, v in node.items():
            path = f"{prefix}.{k}" if prefix else k
            if isinstance(v, (dict, list)):
                counts += key_paths(v, path)
            else:
                counts[path] += 1
    elif isinstance(node, list):
        for item in node:
            if isinstance(item, (dict, list)):
                counts += key_paths(item, prefix + "[]")
            else:
                counts[prefix + "[]"] += 1
    return counts


def main(argv=None) -> int:
    ap = argparse.ArgumentParser(description="hsk-seed の吸収・廃棄を照合する")
    ap.add_argument("--hsk-seed", type=pathlib.Path, required=True)
    ap.add_argument("--data", type=pathlib.Path, required=True, help="新しい data/")
    ap.add_argument("--old-data", type=pathlib.Path, required=True, help="現行の data/")
    ap.add_argument("--readme", type=pathlib.Path)
    args = ap.parse_args(argv)

    root = json.loads(args.hsk_seed.read_text(encoding="utf-8"))
    seed = OrderedDict((e["word"], e) for e in root["entries"])
    new_rows = read_jsonl(args.data / "zh-ja" / "glosses.jsonl")
    old_rows = read_jsonl(args.old_data / "zh-ja" / "glosses.jsonl")
    old_poly = read_jsonl(args.old_data / "zh-ja" / "polyphonic.jsonl")
    readme = args.readme.read_text(encoding="utf-8") if args.readme else ""

    by_word = OrderedDict()
    for r in new_rows:
        by_word.setdefault(r["word"], []).append(r)
    old_gloss = {r["word"]: r for r in old_rows}

    problems = []
    lines = []

    def check(label, ok, detail=""):
        lines.append(f"  {'OK ' if ok else 'NG '} {label}{('  ' + detail) if detail else ''}")
        if not ok:
            problems.append(label)

    # ---------- 1. キー経路の網羅 ----------
    lines.append("## 1. キー経路の網羅")
    found = key_paths(root)
    declared = {
        "metadata.format", "metadata.source_type", "metadata.review_status", "metadata.hsk_versions[]",
        "metadata.provenance[].name", "metadata.provenance[].url", "metadata.provenance[].commit",
        "metadata.provenance[].sha256", "metadata.provenance[].license", "metadata.provenance[].usage[]",
        "metadata.provenance[].definition_policy", "metadata.provenance[].path",
        "metadata.provenance[].status",
        "entries[].word", "entries[].simplified", "entries[].traditional", "entries[].pinyin",
        "entries[].meaning_ja[]", "entries[].pos",
        "entries[].hsk_levels.2.0", "entries[].hsk_levels.3.0",
        "entries[].senses[].pinyin", "entries[].senses[].meaning_ja", "entries[].senses[].pos",
        "entries[].senses[].priority", "entries[].senses[].source", "entries[].senses[].tags[]",
        "entries[].source_forms[].traditional", "entries[].source_forms[].pinyin",
        "entries[].flags.polyphonic", "entries[].flags.needs_context", "entries[].flags.reviewed",
    }
    unclassified = sorted(set(found) - declared)
    unused = sorted(declared - set(found))
    check("hsk-seed の全キー経路が対応表にある", not unclassified, f"未分類: {unclassified}")
    check("対応表に余分な経路がない", not unused, f"データに無い: {unused}")

    # ---------- 2. selector による排他的な分類 ----------
    lines.append("## 2. selector による分類（和が元の全出現と一致すること）")

    # meaning_ja[]: 現行 gloss に在るか
    mj = Counter()
    for w, e in seed.items():
        cur = set(old_gloss[w]["gloss"])
        for m in e["meaning_ja"]:
            mj["absorb" if m in cur else "discard"] += 1
    check("meaning_ja[] の分類", mj["absorb"] == 11583 and mj["discard"] == 23 and sum(mj.values()) == found["entries[].meaning_ja[]"],
          f"吸収{mj['absorb']} + 廃棄{mj['discard']} = {sum(mj.values())} / 全出現{found['entries[].meaning_ja[]']}")

    # senses[].source
    src = Counter()
    for w, e in seed.items():
        known = {norm(w, old_gloss[w]["pinyin"])}
        for s in e["senses"]:
            if s.get("source") != "reviewed":
                src["project_generated"] += 1
            elif norm(w, s["pinyin"]) in known:
                src["reviewed_existing"] += 1
            else:
                src["reviewed_new"] += 1
    check("senses[].source の分類",
          src["reviewed_new"] == 62 and src["reviewed_existing"] == 395 and src["project_generated"] == 11152
          and sum(src.values()) == found["entries[].senses[].source"],
          f"新規{src['reviewed_new']} + 既存{src['reviewed_existing']} + 生成{src['project_generated']} = {sum(src.values())}")

    # source_forms[].pinyin
    sf = Counter()
    for w, e in seed.items():
        known = {norm(w, e["pinyin"])} | {norm(w, s["pinyin"]) for s in e["senses"]}
        for f in e["source_forms"]:
            sf["known" if norm(w, f["pinyin"]) in known else "unknown"] += 1
    check("source_forms[].pinyin の分類",
          sf["known"] == 11950 and sf["unknown"] == 385 and sum(sf.values()) == found["entries[].source_forms[].pinyin"],
          f"既知{sf['known']} + 未知{sf['unknown']} = {sum(sf.values())}")

    # senses[].tags[]
    tg = Counter()
    for e in seed.values():
        for s in e["senses"]:
            for t in (s.get("tags") or []):
                tg["polyphone_review" if t == "polyphone_review" else "pos_tag"] += 1
    check("senses[].tags[] の分類",
          tg["polyphone_review"] == 403 and tg["pos_tag"] == 54 and sum(tg.values()) == found["entries[].senses[].tags[]"],
          f"review{tg['polyphone_review']} + 品詞{tg['pos_tag']} = {sum(tg.values())}")

    # ---------- 3. absorb の照合（照合鍵つき） ----------
    lines.append("## 3. 吸収の照合（照合鍵で確かめる。値の包含検査にしない）")

    def rows_of(w):
        return by_word.get(w, [])

    # entries[].word
    check("entries[].word", all(w in by_word for w in seed), "")

    # entries[].traditional と source_forms[].traditional（出現単位）
    miss = 0
    for w, e in seed.items():
        trad = set(rows_of(w)[0].get("trad", []))
        for f in e["source_forms"]:
            if not (f["traditional"] == w or f["traditional"] in trad):
                miss += 1
        if not (e["traditional"] == w or e["traditional"] in trad):
            miss += 1
    check("traditional 系（entries[].traditional + source_forms[].traditional）",
          miss == 0, f"照合できない出現 {miss} / {found['entries[].source_forms[].traditional'] + found['entries[].traditional']}")

    # entries[].pinyin / senses[].pinyin
    miss_py = 0
    for w, e in seed.items():
        keys = {norm(w, r["pinyin"]) for r in rows_of(w)}
        if norm(w, e["pinyin"]) not in keys:
            miss_py += 1
        for s in e["senses"]:
            if norm(w, s["pinyin"]) not in keys:
                miss_py += 1
    check("pinyin 系（entries[].pinyin + senses[].pinyin）", miss_py == 0, f"未照合 {miss_py}")

    # meaning_ja / senses[].meaning_ja を (word, norm(pinyin), meaning) で照合
    pairs = set()
    for w, rs in by_word.items():
        for r in rs:
            for g in r["gloss"]:
                pairs.add((w, norm(w, r["pinyin"]), g))
    miss_sense = []
    for w, e in seed.items():
        cur = set(old_gloss[w]["gloss"])
        for s in e["senses"]:
            if s["meaning_ja"] not in cur and s["meaning_ja"] != "間に合う":
                continue           # 廃棄と分類した23値
            if (w, norm(w, s["pinyin"]), s["meaning_ja"]) not in pairs:
                miss_sense.append((w, s["pinyin"], s["meaning_ja"]))
    check("senses[].meaning_ja（吸収分）を (word, norm(pinyin), meaning) で照合",
          not miss_sense, f"未照合 {len(miss_sense)}: {miss_sense[:5]}")

    # alt_pinyin
    miss_alt = 0
    for w, e in seed.items():
        known = {norm(w, e["pinyin"])} | {norm(w, s["pinyin"]) for s in e["senses"]}
        alt = {norm(w, a) for a in rows_of(w)[0].get("alt_pinyin", [])}
        for f in e["source_forms"]:
            k = norm(w, f["pinyin"])
            if k not in known and k not in alt:
                miss_alt += 1
    check("source_forms[].pinyin（未知）が alt_pinyin に在る", miss_alt == 0, f"未照合 {miss_alt}")

    # hsk_levels
    miss_lv = 0
    for w, e in seed.items():
        r = rows_of(w)[0]
        lv = e["hsk_levels"]
        if isinstance(lv.get("2.0"), int) and r.get("hsk2") != lv["2.0"]:
            miss_lv += 1
        if isinstance(lv.get("3.0"), int) and r.get("hsk3") != lv["3.0"]:
            miss_lv += 1
    check("hsk_levels → hsk2 / hsk3", miss_lv == 0, f"不一致 {miss_lv}")

    # pos と senses[].pos（reading_pos の疎な復元規則を含む）
    miss_pos = 0
    for w, e in seed.items():
        wp = pos_codes(e["pos"])
        r0 = rows_of(w)[0]
        if wp and r0.get("pos") != wp:
            miss_pos += 1
        table = {}
        for s in e["senses"]:
            table.setdefault(norm(w, s["pinyin"]), []).append(s)
        for r in rows_of(w):
            ss = table.get(norm(w, r["pinyin"]))
            if not ss:
                continue
            want = dedup(c for s in ss for c in pos_codes(s.get("pos")))
            got = r.get("reading_pos", r.get("pos", []))   # 復元規則: 無ければ語の pos
            if want and want != got:
                miss_pos += 1
    check("pos / senses[].pos（reading_pos の復元規則つき）", miss_pos == 0, f"不一致 {miss_pos}")

    # ---------- 4. README / manifest を吸収先とする経路 ----------
    lines.append("## 4. README・manifest を吸収先とする経路")
    if readme:
        pr = root["metadata"]["provenance"][0]
        for label, value in (("provenance[].url", pr["url"]), ("provenance[].commit", pr["commit"]),
                             ("provenance[].name", pr["name"]), ("provenance[].license", "MIT")):
            check(f"README に {label} がある", value in readme, value[:60])
        check("README に hsk_versions（2.0 と 3.0）がある", "2.0" in readme and "3.0" in readme)
    else:
        lines.append("  -- README 未指定のため飛ばした（最終監査では --readme を渡すこと）")
    mf = json.loads((args.data / "manifest.json").read_text(encoding="utf-8"))
    check("manifest の schema_version が 2", mf["schema_version"] == 2)
    check("manifest の行数が実ファイルと一致",
          mf["files"]["zh-ja/glosses.jsonl"]["lines"] == len(new_rows))

    # ---------- 5. 既存行の不変（合格条件5） ----------
    lines.append("## 5. 既存行の不変（D11 の52語と 赶 を除く）")
    # 契約が認めた例外だけを除く（TASK.md 合格条件5）。
    #   1. D11 の多読み52語（読み別に訳を振り分ける）
    #   2. `赶`（senses にしか無い訳「間に合う」を足す）
    #   3. `酪酸`（gloss 内の完全一致の重複を落とす。影響1行）
    seed_multi = {w for w, e in seed.items()
                  if len({norm(w, s["pinyin"]) for s in e["senses"]}) >= 2}
    exempt = seed_multi | {"赶", "酪酸"}
    check("例外の語数が契約どおり", len(exempt) == 54, f"{len(exempt)} 語（52 + 赶 + 酪酸）")
    diff = []
    for old in old_rows:
        w = old["word"]
        new = by_word[w][0]
        if w in exempt:
            continue
        if (new["word"], new["pinyin"], new["gloss"], new["qa"], new.get("unsure")) != \
           (old["word"], old["pinyin"], old["gloss"], old["qa"], old.get("unsure")):
            diff.append(w)
    check("word/pinyin/gloss/qa/unsure が同一（例外を除く）", not diff, f"差分 {len(diff)}: {diff[:5]}")

    # 例外の語も、gloss 以外は変わっていないこと。
    other = []
    for old in old_rows:
        w = old["word"]
        if w not in exempt:
            continue
        new = by_word[w][0]
        if (new["pinyin"], new["qa"], new.get("unsure")) != (old["pinyin"], old["qa"], old.get("unsure")):
            other.append(w)
    check("例外の語も pinyin/qa/unsure は変わっていない", not other, f"差分 {len(other)}: {other[:5]}")

    # `酪酸` の変更は重複の除去だけであること。
    lao = by_word["酪酸"][0]["gloss"]
    old_lao = next(r["gloss"] for r in old_rows if r["word"] == "酪酸")
    check("酪酸 の変更は重複の除去だけ",
          lao == list(dict.fromkeys(old_lao)) and set(lao) == set(old_lao),
          f"{old_lao} → {lao}")

    old_keys = [(r["word"], norm(r["word"], r["pinyin"])) for r in old_rows]
    new_keys = [(r["word"], norm(r["word"], r["pinyin"])) for r in new_rows]
    it = iter(new_keys)
    is_sub = all(k in it for k in old_keys)
    check("旧95,463行の (word, pinyin) が新ファイルの部分列（同じ順序）", is_sub)

    # ---------- 6. polyphonic の全 senses の3分類（合格条件6b） ----------
    #
    # ★分類は**入力だけ**から決める。出力に在るものを見て後から名前を付けると、
    # 「和が全件と一致する」が恒真になって何も確かめられない。
    # 入力から期待する区分を出し、そのうえで新ファイルに在る／無いを確かめる。
    lines.append("## 6. polyphonic.jsonl の全 senses の3分類（入力から決めた区分を出力で確かめる）")
    new_keys = {(r["word"], norm(r["word"], r["pinyin"])) for r in new_rows}
    cls = Counter()
    expect_present, expect_absent = [], []
    dropped_words = 0
    for entry in old_poly:
        w = entry["word"]
        in_gloss = w in old_gloss
        old_key = norm(w, old_gloss[w]["pinyin"]) if in_gloss else None
        # 語の中で正規化後に何種類の読みがあるか（入力だけで決まる）
        distinct = len({norm(w, s["pinyin"]) for s in entry["senses"]})
        if not in_gloss and not entry["senses"]:
            dropped_words += 1          # 訳なし34語。sense が無いので下の数には入らない
        seen = set()
        for sense in entry["senses"]:
            key = norm(w, sense["pinyin"])
            pair = (w, key)
            if not in_gloss:
                # D8: glosses に無い語。訳があるものだけ取り込む
                if key in seen:
                    cls["dropped_duplicate_reading"] += 1
                else:
                    cls["added_d8"] += 1
                    expect_present.append(pair)
            elif key == old_key:
                cls["same_as_existing"] += 1
                expect_present.append(pair)     # 既存行として在る
            elif distinct >= 2:
                if key in seen:
                    cls["dropped_duplicate_reading"] += 1
                else:
                    cls["added"] += 1
                    expect_present.append(pair)
            else:
                # 単読みの語で、読みが既存行と違う。上位決定により捨てる
                cls["dropped_single_reading"] += 1
                expect_absent.append(pair)
            seen.add(key)

    total_senses = sum(len(e["senses"]) for e in old_poly)
    check("区分の和が全 senses と一致", sum(cls.values()) == total_senses,
          f"{dict(cls)} 和={sum(cls.values())} / 全{total_senses}")
    check("訳なしで落とした語が34", dropped_words == 34, f"{dropped_words} 語")
    check("取り込むと決めた読みが新ファイルに在る",
          all(pair in new_keys for pair in expect_present),
          f"未収録 {sum(1 for x in expect_present if x not in new_keys)} / {len(expect_present)}")
    missing_absent = [x for x in expect_absent if x in new_keys]
    check("捨てると決めた読みが新ファイルに無い", not missing_absent,
          f"混入 {len(missing_absent)}: {missing_absent[:5]}")
    check("追加した行の数が契約どおり",
          cls["added"] == 784 and cls["added_d8"] == 17,
          f"多読み語へ追加 {cls['added']} / D8 {cls['added_d8']}")

    print("\n".join(lines))
    print()
    if problems:
        print(f"NG {len(problems)} 件: {problems}")
        return 1
    print("すべて OK")
    return 0


if __name__ == "__main__":
    sys.exit(main())
