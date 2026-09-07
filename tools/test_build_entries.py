#!/usr/bin/env python3
"""tools/build_entries.py の試験。"""

from __future__ import annotations

import contextlib
import io
import json
import pathlib
import sys
import tempfile
import unittest

sys.path.insert(0, str(pathlib.Path(__file__).resolve().parent))
import build_entries  # noqa: E402

CEDICT = """\
# CC-CEDICT
#! entries=7
上級 上级 [shang4 ji2] /higher authorities/superiors/CL:個|个[ge4]/
一個 一个 [yi1 ge5] /a; an; one/
一路 一路 [yi1 lu4] /the whole journey/
女 女 [ru3] /old variant of 汝[ru3]/
經過 经过 [jing1 guo4] /to pass; to go through/
著 着 [zhe5] /aspect particle indicating action in progress/
K金 K金 [K jin1] /see 開金|开金[kai1 jin1]/
"""

HSK = {
    "metadata": {},
    "entries": [
        {"word": "上级", "pinyin": "shàng jí", "pos": "n,unknown",
         "hsk_levels": {"2.0": 5, "3.0": 6}},
        {"word": "一个", "pinyin": "yí gè", "pos": "m", "hsk_levels": {"2.0": None, "3.0": 1}},
    ],
}

EXISTING = [
    # 読みまで一致する（seed になる）
    {"word": "上级", "pinyin": "shàng jí", "gloss": ["上司"], "qa": "machine_backed"},
    # 先頭の `一` の変調。ここだけ声調が違うので当てにいく
    {"word": "一路", "pinyin": "yí lù", "gloss": ["道中"], "qa": "llm_ok"},
    # `一个` は軽声も違う（旧 `gè` / CC-CEDICT `ge5`）。別の読みとして補遺にする
    {"word": "一个", "pinyin": "yí gè", "gloss": ["1つ", "1人"], "qa": "llm_ok"},

    # 繁体字の見出し。CC-CEDICT の簡体 entry へ当たる
    {"word": "經過", "pinyin": "jīng guò", "gloss": ["経過する"], "qa": "llm_ok"},
    # CC-CEDICT に無い語。補遺 entry になる
    {"word": "运输机", "pinyin": "yùnshūjī", "gloss": ["輸送機"], "qa": "machine_backed",
     "hsk3": 7, "trad": ["運輸機"]},
    # 訳を持たない行
    {"word": "幖", "pinyin": "biāo", "gloss": [], "unsure": True, "qa": "machine_backed"},
]

JIEBA = "上级 3 n\n一个 9000 m\n运输机 5 n\n"


class Derived(unittest.TestCase):
    """参照だけの語義に機械で当てる訳の型。README の表と揃っていること。"""

    def test_異体字(self):
        sense = {"variant_of": [{"kind": "variant", "w": "它", "py": "ta1"}]}
        self.assertEqual(build_entries.derived_ja(sense), "它（tā）の異体字")

    def test_旧字体(self):
        sense = {"variant_of": [{"kind": "old", "w": "汝", "py": "ru3"}]}
        self.assertEqual(build_entries.derived_ja(sense), "汝（rǔ）の旧字体")

    def test_儿化形(self):
        sense = {"variant_of": [{"kind": "erhua", "w": "词", "t": "詞", "py": "ci2"}]}
        self.assertEqual(build_entries.derived_ja(sense), "词（cí）の儿化形")

    def test_同義の参照(self):
        sense = {"see_also": [{"kind": "see", "w": "开金", "py": "kai1 jin1"}]}
        self.assertEqual(build_entries.derived_ja(sense), "开金（kāi jīn）に同じ")

    def test_あわせて見る参照(self):
        sense = {"see_also": [{"kind": "see_also", "w": "词", "py": "ci2"}]}
        self.assertEqual(build_entries.derived_ja(sense), "词（cí）も参照")

    def test_略語(self):
        sense = {"see_also": [{"kind": "abbr", "w": "开金", "py": "kai1 jin1"}]}
        self.assertEqual(build_entries.derived_ja(sense), "开金（kāi jīn）の略")

    def test_この字が使われる語(self):
        sense = {"see_also": [{"kind": "used_in", "w": "㐖毒", "py": "Xie2 du2"}]}
        self.assertEqual(build_entries.derived_ja(sense), "㐖毒（Xié dú）に使われる字")

    def test_参照が複数なら中黒で並べる(self):
        sense = {"see_also": [{"kind": "see", "w": "甲", "py": "jia3"},
                              {"kind": "see", "w": "乙", "py": "yi3"}]}
        self.assertEqual(build_entries.derived_ja(sense), "甲（jiǎ）・乙（yǐ）に同じ")

    def test_読みが無ければ語だけ(self):
        sense = {"see_also": [{"kind": "see", "w": "甲"}]}
        self.assertEqual(build_entries.derived_ja(sense), "甲に同じ")

    def test_参照が無ければ空(self):
        self.assertEqual(build_entries.derived_ja({"en": ["thing"]}), "")


class Build(unittest.TestCase):
    def setUp(self):
        self.dir = pathlib.Path(tempfile.mkdtemp())
        (self.dir / "cedict.txt").write_text(CEDICT, encoding="utf-8")
        (self.dir / "hsk.json").write_text(json.dumps(HSK, ensure_ascii=False),
                                           encoding="utf-8")
        (self.dir / "existing.jsonl").write_text(
            "".join(json.dumps(row, ensure_ascii=False) + "\n" for row in EXISTING),
            encoding="utf-8")
        (self.dir / "jieba.utf8").write_text(JIEBA, encoding="utf-8")
        self.out = self.dir / "entries-base.jsonl"
        self.order = self.dir / "order.tsv"
        self.build()
        self.rows = [json.loads(line) for line in
                     self.out.read_text(encoding="utf-8").splitlines()]
        self.by_id = {row["id"]: row for row in self.rows}

    def test_骨格と補遺の数(self):
        skeleton = [row for row in self.rows if row["id"].startswith("c")]
        supplement = [row for row in self.rows if row["id"].startswith("x")]
        self.assertEqual(len(skeleton), 7)
        # `一个`（軽声が違う）・`运输机`・`幖` の3件
        self.assertEqual(len(supplement), 3)

    def test_読みを声調記号へ直す(self):
        self.assertEqual(self.by_id["c1"]["pinyin"], "shàng jí")
        self.assertEqual(self.by_id["c2"]["pinyin"], "yī ge")

    def test_繁体字は違うときだけ置く(self):
        self.assertEqual(self.by_id["c1"]["trad"], "上級")
        self.assertNotIn("trad", self.by_id["c4"])  # 女／女

    def test_HSKの級と品詞(self):
        self.assertEqual(self.by_id["c1"]["hsk2"], 5)
        self.assertEqual(self.by_id["c1"]["hsk3"], 6)
        self.assertEqual(self.by_id["c1"]["pos"], ["n"])   # `unknown` は落とす
        self.assertNotIn("hsk2", self.by_id["c2"])         # 2.0 が null なら置かない
        self.assertEqual(self.by_id["c2"]["hsk3"], 1)

    def test_既存の訳を候補として付ける(self):
        self.assertEqual(self.by_id["c1"]["seed_gloss"], ["上司"])
        self.assertEqual(self.by_id["c1"]["seed"], "machine_backed")

    def test_先頭の一の変調は当てる(self):
        # 既存 `yí lù` と CC-CEDICT `yi1 lu4` は先頭の声調だけが違う
        self.assertEqual(self.by_id["c3"]["seed_gloss"], ["道中"])

    def test_軽声まで違えば補遺にする(self):
        # `一个` は旧版が `gè`、CC-CEDICT が `ge5`。同じ読みとして扱うと
        # 旧版の読みが消えるので、補遺 entry として残す。
        supplement = [r for r in self.rows if r.get("src") and r["word"] == "一个"]
        self.assertEqual(len(supplement), 1)
        self.assertEqual(supplement[0]["pinyin"], "yí gè")

    def test_繁体字の見出しも当てる(self):
        self.assertEqual(self.by_id["c5"]["seed_gloss"], ["経過する"])

    def test_補遺は既存の訳をそのまま持つ(self):
        # 番号は旧版ファイルの行番号。EXISTING の5行目が `运输机`。
        supplement = self.by_id["x5"]
        self.assertEqual(supplement["word"], "运输机")
        self.assertEqual(supplement["src"], "zh-ja-dict")
        self.assertEqual(supplement["trad"], "運輸機")
        self.assertEqual(supplement["hsk3"], 7)
        self.assertEqual(supplement["senses"],
                         [{"ja": "輸送機", "qa": "machine_backed"}])

    def test_訳の無い補遺は生成へ回す(self):
        self.assertEqual(self.by_id["x6"]["word"], "幖")
        self.assertEqual(self.by_id["x6"]["senses"], [{}])

    def test_補遺の番号は旧版の行番号から作る(self):
        # 通し番号にすると、当て込みの規則を直したときに全部ずれて、
        # 既に作った訳と結び付かなくなる。
        self.assertEqual({row["id"] for row in self.rows if row["id"].startswith("x")},
                         {"x3", "x5", "x6"})

    def test_参照だけの語義には機械で訳を当てる(self):
        self.assertEqual(self.by_id["c4"]["senses"][0]["ja"], "汝（rǔ）の旧字体")
        self.assertEqual(self.by_id["c4"]["senses"][0]["qa"], "derived")
        self.assertEqual(self.by_id["c7"]["senses"][0]["ja"], "开金（kāi jīn）に同じ")

    def test_量詞はentryの欄へ(self):
        self.assertEqual(self.by_id["c1"]["cl"], [{"w": "个", "t": "個", "py": "ge4"}])
        self.assertNotIn("cl", self.by_id["c1"]["senses"][1])

    def test_順番はHSKが先で次に頻度の降順(self):
        ids = [line.split("\t")[0] for line in
               self.order.read_text(encoding="utf-8").splitlines()[1:]]
        # HSK を持つ c2（一个・頻度9000）と c1（上级・頻度3）が先、次に頻度順
        self.assertEqual(ids[:2], ["c2", "c1"])
        # 参照だけの c3・c6 は訳が要らないので一覧に出ない
        self.assertNotIn("c4", ids)
        self.assertNotIn("c7", ids)

    def build(self):
        # 組み立ての進み具合の出力は試験の結果を読みにくくするだけなので伏せる。
        with contextlib.redirect_stdout(io.StringIO()):
            build_entries.main([
                "--cedict", str(self.dir / "cedict.txt"),
                "--hsk-seed", str(self.dir / "hsk.json"),
                "--existing", str(self.dir / "existing.jsonl"),
                "--jieba", str(self.dir / "jieba.utf8"),
                "--out", str(self.out), "--order", str(self.order),
            ])

    def test_同じ入力からは同じバイト列(self):
        first = self.out.read_bytes()
        self.build()
        self.assertEqual(self.out.read_bytes(), first)

    def test_entry数が宣言値と違えば止まる(self):
        broken = self.dir / "broken.txt"
        broken.write_text(CEDICT.replace("entries=7", "entries=8"), encoding="utf-8")
        with self.assertRaises(SystemExit), contextlib.redirect_stdout(io.StringIO()):
            build_entries.main([
                "--cedict", str(broken),
                "--hsk-seed", str(self.dir / "hsk.json"),
                "--existing", str(self.dir / "existing.jsonl"),
                "--out", str(self.dir / "x.jsonl"), "--order", str(self.dir / "x.tsv"),
            ])


class DumpLine(unittest.TestCase):
    def test_仕様に無いキーで止まる(self):
        with self.assertRaises(SystemExit):
            build_entries.dump_line({"word": "x", "nope": 1}, build_entries.ENTRY_KEYS)

    def test_キーの順序を固定する(self):
        line = build_entries.dump_line(
            {"senses": [], "word": "上级", "id": "c1"}, build_entries.ENTRY_KEYS)
        self.assertEqual(line, '{"id": "c1", "word": "上级", "senses": []}')


if __name__ == "__main__":
    unittest.main()
