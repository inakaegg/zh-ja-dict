#!/usr/bin/env python3
"""tools/build_dataset.py の試験。"""

from __future__ import annotations

import contextlib
import io
import json
import pathlib
import sys
import tempfile
import unittest

sys.path.insert(0, str(pathlib.Path(__file__).resolve().parent))
import build_dataset  # noqa: E402
import dataset_sources  # noqa: E402
import entries_file  # noqa: E402

BASE = [
    {"id": "c1", "word": "上级", "trad": "上級", "pinyin": "shàng jí",
     "cl": [{"w": "个", "t": "個", "py": "ge4"}], "hsk3": 6, "pos": ["n"],
     "seed": "machine_backed", "seed_gloss": ["上司"],
     "senses": [{"en": ["higher authorities"]}, {"en": ["superiors"]}]},
    {"id": "c2", "word": "女", "pinyin": "rǔ",
     "senses": [{"ja": "汝（rǔ）の旧字体", "qa": "derived",
                 "variant_of": [{"kind": "old", "w": "汝", "py": "ru3"}]}]},
    {"id": "x1", "word": "运输机", "trad": "運輸機", "pinyin": "yùnshūjī",
     "src": "zh-ja-dict", "senses": [{"ja": "輸送機", "qa": "machine_backed"}]},
]

GLOSSES = [
    {"id": "c1", "sense": 1, "ja": "上層部"},
    {"id": "c1", "sense": 2, "ja": "上司"},
]

# 萌典の形。`title` は繁体字の見出し、`heteronyms[].definitions` が語義。
MOEDICT = [
    {"title": "上級", "heteronyms": [{"definitions": [{"def": "本文"}, {"def": "本文"}]}]},
    {"title": "女", "heteronyms": [{"definitions": []}]},
]


class Build(unittest.TestCase):
    def setUp(self):
        self.dir = pathlib.Path(tempfile.mkdtemp())
        self.base = self.dir / "base.jsonl"
        self.base.write_text(
            "".join(json.dumps(row, ensure_ascii=False) + "\n" for row in BASE),
            encoding="utf-8")
        self.glosses = self.dir / "ja.jsonl"
        self.glosses.write_text(
            "".join(json.dumps(row, ensure_ascii=False) + "\n" for row in GLOSSES),
            encoding="utf-8")
        self.overrides = self.dir / "overrides.tsv"
        self.overrides.write_text("# 空\n", encoding="utf-8")
        self.moedict = self.dir / "moe.json"
        self.moedict.write_text(json.dumps(MOEDICT, ensure_ascii=False), encoding="utf-8")
        self.out = self.dir / "data"

    def run_build(self, *extra):
        # 組み立ての進み具合の出力は試験の結果を読みにくくするだけなので伏せる。
        with contextlib.redirect_stdout(io.StringIO()):
            build_dataset.main([
                "--base", str(self.base), "--glosses", str(self.glosses),
                "--moedict", str(self.moedict), "--generated", "2026-09-07",
                "--overrides", str(self.overrides), "--out", str(self.out), *extra])
        rows = [json.loads(line) for line in
                entries_file.read_lines(self.out / "zh-ja" / entries_file.NAME)]
        manifest = json.loads((self.out / "manifest.json").read_text(encoding="utf-8"))
        return rows, manifest

    def test_訳を語義へ入れる(self):
        rows, _ = self.run_build()
        self.assertEqual([s["ja"] for s in rows[0]["senses"]], ["上層部", "上司"])
        self.assertEqual([s["qa"] for s in rows[0]["senses"]], ["llm_ok", "llm_ok"])

    def test_骨組みだけのキーを落とす(self):
        rows, _ = self.run_build()
        for row in rows:
            self.assertNotIn("id", row)
            self.assertNotIn("seed_gloss", row)

    def test_出どころの印は残す(self):
        rows, _ = self.run_build()
        self.assertEqual(rows[0]["seed"], "machine_backed")
        self.assertEqual(rows[2]["src"], "zh-ja-dict")

    def test_量詞はentryの欄のまま(self):
        rows, _ = self.run_build()
        self.assertEqual(rows[0]["cl"], [{"w": "个", "t": "個", "py": "ge4"}])

    def test_訳が同じ語義は組み立てのときにまとまる(self):
        self.glosses.write_text(
            '{"id": "c1", "sense": 1, "ja": "上司"}\n'
            '{"id": "c1", "sense": 2, "ja": "上司"}\n', encoding="utf-8")
        rows, manifest = self.run_build()
        self.assertEqual(len(rows[0]["senses"]), 1)
        self.assertEqual(rows[0]["senses"][0]["en"], ["higher authorities", "superiors"])
        self.assertEqual(manifest["files"][f"zh-ja/{entries_file.NAME}"]["senses"], 3)

    def test_上書きを当てて_hand_fixed_にする(self):
        self.overrides.write_text("上级\tshàng jí\t1\t上層部だ\t試験\n", encoding="utf-8")
        rows, _ = self.run_build()
        self.assertEqual(rows[0]["senses"][0]["ja"], "上層部だ")
        self.assertEqual(rows[0]["senses"][0]["qa"], "hand_fixed")

    def test_当たらない上書きがあれば止まる(self):
        self.overrides.write_text("無い語\tnài\t1\t訳\t試験\n", encoding="utf-8")
        with self.assertRaises(SystemExit):
            self.run_build()

    def test_萌典との照合(self):
        rows, _ = self.run_build()
        # 上級は萌典に語義2つ、この辞書も2つ → full
        self.assertEqual(rows[0]["moe"], "full")
        # 女は見出しがあるが語義0 → headword
        self.assertEqual(rows[1]["moe"], "headword")
        # 運輸機は萌典に無い → none
        self.assertEqual(rows[2]["moe"], "none")

    def test_萌典を渡さなければ_moe_を書かない(self):
        with contextlib.redirect_stdout(io.StringIO()):
            build_dataset.main([
                "--base", str(self.base), "--glosses", str(self.glosses),
                "--generated", "2026-09-07", "--overrides", str(self.overrides),
                "--out", str(self.out)])
        rows = [json.loads(line) for line in
                entries_file.read_lines(self.out / "zh-ja" / entries_file.NAME)]
        for row in rows:
            self.assertNotIn("moe", row)

    def test_作り直した語義は_llm_fixed(self):
        repaired = self.dir / "ja.jsonl.repaired"
        repaired.write_text('{"id": "c1", "sense": 2}\n', encoding="utf-8")
        rows, _ = self.run_build("--repaired", str(repaired))
        self.assertEqual([s["qa"] for s in rows[0]["senses"]], ["llm_ok", "llm_fixed"])

    def test_訳の無い語義があれば止まる(self):
        self.glosses.write_text('{"id": "c1", "sense": 1, "ja": "上層部"}\n',
                                encoding="utf-8")
        with self.assertRaises(SystemExit):
            self.run_build()

    def test_下見なら止まらず落とす(self):
        self.glosses.write_text("", encoding="utf-8")
        rows, manifest = self.run_build("--allow-missing")
        # c1 は語義が1つも埋まらないので落ちる。残るのは c2 と x1
        self.assertEqual([row["word"] for row in rows], ["女", "运输机"])
        self.assertEqual(manifest["files"][f"zh-ja/{entries_file.NAME}"]["lines"], 2)

    def test_manifest_の数え上げ(self):
        rows, manifest = self.run_build()
        entry = manifest["files"][f"zh-ja/{entries_file.NAME}"]
        self.assertEqual(entry["lines"], 3)
        self.assertEqual(entry["entries_skeleton"], 2)
        self.assertEqual(entry["entries_supplement"], 1)
        self.assertEqual(entry["senses"], 4)
        self.assertEqual(entry["compression"], entries_file.COMPRESSION)
        sizes = entries_file.sizes(self.out / "zh-ja" / entries_file.NAME)
        self.assertEqual(entry["bytes"], sizes.compressed)
        self.assertEqual(entry["uncompressed_bytes"], sizes.uncompressed)

    def test_manifest_の出どころは表と同じ(self):
        _, manifest = self.run_build()
        self.assertEqual(manifest["sources"], dataset_sources.SOURCES)
        self.assertEqual(manifest["schema_version"], dataset_sources.SCHEMA_VERSION)
        self.assertEqual(manifest["generated"], "2026-09-07")

    def test_同じ入力からは同じバイト列(self):
        self.run_build()
        first = (self.out / "zh-ja" / entries_file.NAME).read_bytes()
        self.run_build()
        self.assertEqual((self.out / "zh-ja" / entries_file.NAME).read_bytes(), first)

    def test_仕様に無いキーがあれば止まる(self):
        rows = [dict(BASE[1], nope=1)]
        self.base.write_text(json.dumps(rows[0], ensure_ascii=False) + "\n",
                             encoding="utf-8")
        with self.assertRaises(SystemExit):
            self.run_build()


class Overrides(unittest.TestCase):
    """人が書いた訳の上書き。生成では直らない語義を差し替え、出どころを隠さない。"""

    def test_読んで表にする(self):
        with tempfile.NamedTemporaryFile("w", suffix=".tsv", delete=False,
                                         encoding="utf-8") as handle:
            handle.write("# 見出し語\t読み\t語義\t訳\t理由\n")
            handle.write("谱氏\tpǔ shì\t2\t家系の記録\t英語が残ったため\n")
            path = pathlib.Path(handle.name)
        self.assertEqual(build_dataset.load_overrides(path),
                         {("谱氏", "pǔ shì", 2): "家系の記録"})

    def test_列が足りなければ止まる(self):
        with tempfile.NamedTemporaryFile("w", suffix=".tsv", delete=False,
                                         encoding="utf-8") as handle:
            handle.write("谱氏\tpǔ shì\n")
            path = pathlib.Path(handle.name)
        with self.assertRaises(SystemExit):
            build_dataset.load_overrides(path)

    def test_ファイルが無ければ空(self):
        self.assertEqual(build_dataset.load_overrides(pathlib.Path("/nonexistent")), {})


class CollapseDuplicateJa(unittest.TestCase):
    """CC-CEDICT は英語の同義語を別の語義に分ける（`时代` の age と era）。

    日本語にすると同じ訳になるので、そのままでは画面に同じ訳が並ぶ。
    """

    def test_訳が同じ語義をまとめて英語を連ねる(self):
        got = build_dataset.collapse_duplicate_ja([
            {"en": ["age"], "ja": "時代", "qa": "llm_ok"},
            {"en": ["era"], "ja": "時代", "qa": "llm_ok"},
        ])
        self.assertEqual(got, [{"en": ["age", "era"], "ja": "時代", "qa": "llm_ok"}])

    def test_離れた語義もまとめる(self):
        got = build_dataset.collapse_duplicate_ja([
            {"en": ["certificate"], "ja": "証明書", "qa": "llm_ok"},
            {"en": ["proof"], "ja": "証拠", "qa": "llm_ok"},
            {"en": ["testimonial"], "ja": "証明書", "qa": "llm_ok"},
        ])
        self.assertEqual([s["ja"] for s in got], ["証明書", "証拠"])
        self.assertEqual(got[0]["en"], ["certificate", "testimonial"])

    def test_訳が違えばまとめない(self):
        senses = [{"en": ["a"], "ja": "甲", "qa": "llm_ok"},
                  {"en": ["b"], "ja": "乙", "qa": "llm_ok"}]
        self.assertEqual(build_dataset.collapse_duplicate_ja(senses), senses)

    def test_注記が違えばまとめない(self):
        # 口語の印が付いていない語義にまで印を広げないため。
        senses = [{"en": ["a"], "ja": "同", "qa": "llm_ok"},
                  {"en": ["b"], "ja": "同", "qa": "llm_ok", "misc": ["coll"]}]
        self.assertEqual(build_dataset.collapse_duplicate_ja(senses), senses)

    def test_参照が違えばまとめない(self):
        senses = [{"ja": "甲に同じ", "qa": "derived",
                   "see_also": [{"kind": "see", "w": "甲"}]},
                  {"ja": "甲に同じ", "qa": "derived",
                   "see_also": [{"kind": "abbr", "w": "甲"}]}]
        self.assertEqual(build_dataset.collapse_duplicate_ja(senses), senses)

    def test_英語の重複は増やさない(self):
        got = build_dataset.collapse_duplicate_ja([
            {"en": ["match"], "ja": "試合", "qa": "llm_ok"},
            {"en": ["match", "game"], "ja": "試合", "qa": "llm_ok"},
        ])
        self.assertEqual(got[0]["en"], ["match", "game"])

    def test_作り直しがあれば_llm_fixed_を残す(self):
        got = build_dataset.collapse_duplicate_ja([
            {"en": ["a"], "ja": "同", "qa": "llm_ok"},
            {"en": ["b"], "ja": "同", "qa": "llm_fixed"},
        ])
        self.assertEqual(got[0]["qa"], "llm_fixed")

    def test_英語を持たない語義もまとめられる(self):
        got = build_dataset.collapse_duplicate_ja([
            {"ja": "輸送機", "qa": "machine_backed"},
            {"ja": "輸送機", "qa": "machine_backed"},
        ])
        self.assertEqual(len(got), 1)


class MoeVerdict(unittest.TestCase):
    def test_繁体字で引く(self):
        counts = {"上級": 3}
        entry = {"word": "上级", "trad": "上級", "senses": [{}, {}]}
        self.assertEqual(build_dataset.moe_verdict(entry, counts), "full")

    def test_繁体字が無ければ簡体字で引く(self):
        counts = {"女": 1}
        entry = {"word": "女", "senses": [{}]}
        self.assertEqual(build_dataset.moe_verdict(entry, counts), "full")

    def test_萌典を読んでいなければ_None(self):
        self.assertIsNone(build_dataset.moe_verdict({"word": "x", "senses": []}, {}))


class LoadMoedict(unittest.TestCase):
    def test_本文は持たず語義の数だけ取る(self):
        with tempfile.NamedTemporaryFile("w", suffix=".json", delete=False,
                                         encoding="utf-8") as handle:
            json.dump(MOEDICT, handle, ensure_ascii=False)
            path = pathlib.Path(handle.name)
        counts = build_dataset.load_moedict(path)
        self.assertEqual(counts, {"上級": 2, "女": 0})


if __name__ == "__main__":
    unittest.main()
