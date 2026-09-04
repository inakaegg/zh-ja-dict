#!/usr/bin/env python3
"""build_glosses.py の自己テスト。

    python3 tools/test_build_glosses.py

小さな作り物の入力を渡し、行の並び順と鍵の正規化を確かめる。実データは使わない
（実データに対する検査は build_glosses.py 自身の期待値の照合と
tools/audit_absorption.py が行う）。
"""

from __future__ import annotations

import json
import pathlib
import sys
import tempfile
import unittest

sys.path.insert(0, str(pathlib.Path(__file__).resolve().parent))
import build_glosses as b  # noqa: E402


def make_seed(entries):
    return {"metadata": {"format": "hsk-seed-v2"}, "entries": entries}


def entry(word, pinyin, meanings, senses=None, pos="n"):
    return {
        "word": word, "simplified": word, "traditional": word, "pinyin": pinyin,
        "meaning_ja": meanings, "pos": pos, "hsk_levels": {"2.0": None, "3.0": 1},
        "senses": senses if senses is not None
        else [{"pinyin": pinyin, "meaning_ja": m, "priority": i + 1,
               "source": "project_generated", "pos": pos} for i, m in enumerate(meanings)],
        "source_forms": [{"traditional": word, "pinyin": pinyin}],
    }


def build(gloss_rows, poly_rows, seed_entries):
    """作り物の入力から変換を走らせ、出力の行を返す。"""
    with tempfile.TemporaryDirectory() as tmp:
        root = pathlib.Path(tmp)
        data, out = root / "data", root / "out"
        (data / "zh-ja").mkdir(parents=True)
        (data / "ja-zh").mkdir(parents=True)
        (data / "zh-ja" / "glosses.jsonl").write_text(
            "".join(json.dumps(r, ensure_ascii=False) + "\n" for r in gloss_rows), encoding="utf-8")
        (data / "zh-ja" / "polyphonic.jsonl").write_text(
            "".join(json.dumps(r, ensure_ascii=False) + "\n" for r in poly_rows), encoding="utf-8")
        (data / "ja-zh" / "glosses.jsonl").write_text("", encoding="utf-8")
        seed = root / "seed.json"
        seed.write_text(json.dumps(make_seed(seed_entries), ensure_ascii=False), encoding="utf-8")
        b.main(["--current-data", str(data), "--hsk-seed", str(seed),
                "--generated", "2026-09-03", "--out", str(out),
                "--report", str(root / "report.json"), "--no-expect"])
        return [json.loads(l) for l in
                (out / "zh-ja" / "glosses.jsonl").read_text(encoding="utf-8").splitlines() if l]


class NormalizeTest(unittest.TestCase):
    def test_空白とハイフンとアポストロフィを落とす(self):
        self.assertEqual(b.norm("丧家", "sāng jiā"), b.norm("丧家", "sāngjiā"))
        self.assertEqual(b.norm("难兄难弟", "nànxiōng-nàndì"), b.norm("难兄难弟", "nànxiōngnàndì"))

    def test_軽声の印を落とす(self):
        self.assertEqual(b.norm("有空儿", "yǒukòngr5"), b.norm("有空儿", "yǒukòngr"))
        self.assertEqual(b.norm("闺女", "guī ˙nü"), b.norm("闺女", "guī nü"))

    def test_既定では大小文字を区別しない(self):
        self.assertEqual(b.norm("俞", "Yú"), b.norm("俞", "yú"))

    def test_一覧に載せた語だけ大小文字を保つ(self):
        self.assertNotEqual(b.norm("包头", "Bāotóu"), b.norm("包头", "bāotóu"))
        self.assertNotEqual(b.norm("酂", "Zàn"), b.norm("酂", "zàn"))


class OrderTest(unittest.TestCase):
    """D6 の並び順。現データに無い組み合わせも小さなfixtureで確かめる。"""

    def test_追加行は同じ語の既存行の直後に入る(self):
        rows = build(
            [{"word": "甲", "pinyin": "jiǎ", "gloss": ["こう"], "qa": "llm_ok"},
             {"word": "乙", "pinyin": "yǐ", "gloss": ["おつ"], "qa": "llm_ok"}],
            [{"word": "甲", "senses": [{"pinyin": "jiǎ", "gloss": ["こう"]},
                                       {"pinyin": "jià", "gloss": ["よろい"]}]}],
            [])
        self.assertEqual([(r["word"], r["pinyin"]) for r in rows],
                         [("甲", "jiǎ"), ("甲", "jià"), ("乙", "yǐ")])

    def test_polyphonic由来がhsk_seed由来より先に来る(self):
        # 両方の追加行を持つ語は現データに存在しないので、ここで規則だけ確かめる。
        rows = build(
            [{"word": "甲", "pinyin": "jiǎ", "gloss": ["こう"], "qa": "llm_ok"}],
            [{"word": "甲", "senses": [{"pinyin": "jiǎ", "gloss": ["こう"]},
                                       {"pinyin": "jià", "gloss": ["よろい"]}]}],
            [entry("甲", "jiǎ", ["こう"],
                   senses=[{"pinyin": "jiǎ", "meaning_ja": "こう", "priority": 1,
                            "source": "project_generated", "pos": "n"},
                           {"pinyin": "gǔ", "meaning_ja": "かぶと", "priority": 2,
                            "source": "reviewed", "pos": "n"}])])
        self.assertEqual([(r["word"], r["pinyin"]) for r in rows],
                         [("甲", "jiǎ"), ("甲", "jià"), ("甲", "gǔ")])
        self.assertEqual([r["qa"] for r in rows], ["llm_ok", "unchecked", "human_reviewed"])

    def test_既存行が無い語は全既存行の後ろへ置く(self):
        rows = build(
            [{"word": "甲", "pinyin": "jiǎ", "gloss": ["こう"], "qa": "llm_ok"},
             {"word": "乙", "pinyin": "yǐ", "gloss": ["おつ"], "qa": "llm_ok"}],
            [{"word": "丙", "senses": [{"pinyin": "bǐng", "gloss": ["へい"]}]}],
            [])
        self.assertEqual([(r["word"], r["pinyin"]) for r in rows],
                         [("甲", "jiǎ"), ("乙", "yǐ"), ("丙", "bǐng")])
        self.assertEqual(rows[-1]["qa"], "unchecked")

    def test_訳を持たない語は取り込まない(self):
        rows = build(
            [{"word": "甲", "pinyin": "jiǎ", "gloss": ["こう"], "qa": "llm_ok"}],
            [{"word": "丁", "senses": [], "unsure": True}],
            [])
        self.assertEqual([r["word"] for r in rows], ["甲"])


class KeyOrderTest(unittest.TestCase):
    def test_出力のキー順が仕様どおり(self):
        rows = build(
            [{"word": "甲", "pinyin": "jiǎ", "gloss": ["こう"], "qa": "llm_ok"}],
            [], [entry("甲", "jiǎ", ["こう"])])
        line = json.dumps(rows[0], ensure_ascii=False)
        self.assertEqual(list(rows[0]), [k for k in b.KEY_ORDER if k in rows[0]])
        self.assertIn('"word"', line)

    def test_gloss内の重複を落とす(self):
        rows = build(
            [{"word": "甲", "pinyin": "jiǎ", "gloss": ["こう", "こう"], "qa": "llm_ok"}], [], [])
        self.assertEqual(rows[0]["gloss"], ["こう"])


if __name__ == "__main__":
    unittest.main(verbosity=1)
