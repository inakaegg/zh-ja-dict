#!/usr/bin/env python3
"""共通辞書形式への変換と逆投影の試験。"""

from __future__ import annotations

import copy
import json
import pathlib
import sys
import tempfile
import unittest

sys.path.insert(0, str(pathlib.Path(__file__).resolve().parent))
import common_format  # noqa: E402
import entries_file  # noqa: E402


def sample_rows(count: int) -> list[dict]:
    rows = [
        {
            "word": "计算机", "trad": "計算機", "pinyin": "jì suàn jī",
            "tw_pr": "jì suàn jī", "also_pr": "jì suàn jī",
            "cl": [{"w": "台", "t": "臺", "py": "tai2"}],
            "hsk2": 5, "hsk3": 2, "pos": ["n"], "seed": "machine_backed",
            "moe": "full",
            "senses": [
                {"en": ["computer"], "ja": "コンピュータ", "qa": "llm_ok"},
                {"en": ["calculator"], "ja": "電卓", "qa": "llm_fixed", "misc": ["tw"]},
            ],
        },
        {
            "word": "女", "pinyin": "rǔ", "moe": "headword",
            "senses": [{
                "ja": "汝（rǔ）の旧字体", "qa": "derived",
                "variant_of": [{"kind": "old", "w": "汝", "py": "ru3"}],
            }],
        },
        {
            "word": "測試", "pinyin": "cè shì", "moe": "none",
            "senses": [{"en": ["test"], "ja": "試験", "qa": "hand_fixed"}],
        },
        {
            "word": "一个", "pinyin": "yí gè", "src": "zh-ja-dict", "moe": "none",
            "senses": [{"ja": "1つ、1人", "qa": "llm_ok", "unsure": True}],
        },
        {
            "word": "补遗修正", "pinyin": "bǔ yí xiū zhèng", "src": "zh-ja-dict",
            "senses": [{"ja": "補遺修正", "qa": "llm_fixed"}],
        },
        {
            "word": "运输机", "trad": "運輸機", "pinyin": "yùnshūjī",
            "src": "zh-ja-dict", "hsk3": 7,
            "senses": [{"ja": "輸送機", "qa": "machine_backed"}],
        },
        {
            "word": "未检", "pinyin": "wèi jiǎn", "src": "zh-ja-dict",
            "senses": [{"ja": "未検査", "qa": "unchecked"}],
        },
        {
            "word": "多音", "pinyin": "duō yīn", "src": "zh-ja-dict",
            "senses": [{"ja": "多音字", "qa": "human_reviewed"}],
        },
        # (word, pinyin) は同じでも trad が違うため別entry。
        {"word": "俊", "pinyin": "jùn", "senses": [{"ja": "俊才", "qa": "llm_ok"}]},
        {"word": "俊", "trad": "儁", "pinyin": "jùn",
         "senses": [{"ja": "すぐれる", "qa": "llm_ok"}]},
    ]
    while len(rows) < count:
        number = len(rows) + 1
        rows.append({
            "word": f"例{number}", "pinyin": f"lì {number}",
            "senses": [{"en": [f"example {number}"], "ja": f"例{number}", "qa": "llm_ok"}],
        })
    return rows


class CommonFixture(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory()
        self.root = pathlib.Path(self.temp.name)

    def tearDown(self):
        self.temp.cleanup()

    def native_fixture(self, count: int):
        rows = sample_rows(count)
        entries = self.root / f"native-{count}.deflate"
        sizes = entries_file.write(entries, (json.dumps(row, ensure_ascii=False) for row in rows))
        manifest = self.root / f"native-{count}.json"
        manifest.write_text(json.dumps({
            "schema_version": 3,
            "generated": "2026-09-08",
            "files": {"zh-ja/entries.jsonl.deflate": {
                "lines": count,
                "senses": sum(len(row["senses"]) for row in rows),
                "compression": "deflate",
                "bytes": sizes.compressed,
                "uncompressed_bytes": sizes.uncompressed,
            }},
            "sources": {"CC-CEDICT": {"license": "CC BY-SA 4.0"}},
        }, ensure_ascii=False), encoding="utf-8")
        return rows, entries, manifest

    def export(self, count: int):
        rows, entries, manifest = self.native_fixture(count)
        out = self.root / f"common-{count}"
        common_format.export_common(entries, manifest, out)
        stats = common_format.validate_common(
            out / entries_file.NAME, out / "manifest.json", entries, manifest)
        common_rows = [json.loads(line) for line in entries_file.read_lines(out / entries_file.NAME)]
        return rows, common_rows, stats, entries, manifest, out

    def test_20件で全metadataと検証結果の意味を保つ(self):
        native, common, stats, *_ = self.export(20)
        self.assertEqual(stats.entries, 20)
        self.assertEqual(stats.senses, 21)
        self.assertEqual(
            common[0]["extensions"]["zh-ja-dict"],
            {key: value for key, value in native[0].items() if key != "senses"})
        self.assertEqual(
            common[0]["senses"][0]["translations"][0]["verification"],
            [{"subject": "translation", "method": "script_and_length",
              "result": "passed", "source_value": "llm_ok"}])
        self.assertEqual(common[1]["senses"][0]["translations"][0]["verification"], [])
        supplement = common[3]["senses"][0]["translations"][0]
        self.assertEqual(supplement["provenance"]["method"], "legacy")
        self.assertEqual(supplement["verification"], [{
            "subject": "legacy_entry_translation_set", "method": "legacy_llm_review",
            "result": "passed", "source_value": "llm_ok"}])
        self.assertTrue(supplement["uncertain"])
        self.assertNotIn("verified", json.dumps(common, ensure_ascii=False))

    def test_100件を再集約せず逆投影できる(self):
        native, common, stats, *_ = self.export(100)
        self.assertEqual(stats.entries, 100)
        self.assertEqual([common_format.project_native_entry(row) for row in common], native)

    def test_wordとpinyinが同じでもtradを含むIDで区別する(self):
        _, common, *_ = self.export(20)
        self.assertNotEqual(common[8]["id"], common[9]["id"])
        self.assertEqual(common[8]["id"]["value"], '["俊",null,"jùn"]')
        self.assertEqual(common[9]["id"]["value"], '["俊","儁","jùn"]')

    def test_manifestの形式名とhashと件数を検査する(self):
        _, _, _, entries, native_manifest, out = self.export(20)
        common_manifest = out / "manifest.json"
        original = json.loads(common_manifest.read_text(encoding="utf-8"))
        for mutate in (
            lambda value: value["schema"].__setitem__("name", "unknown"),
            lambda value: value["schema"].__setitem__("version", True),
            lambda value: value["files"][entries_file.NAME].__setitem__("sha256", "0" * 64),
            lambda value: value["files"][entries_file.NAME].__setitem__("lines", 999),
        ):
            changed = copy.deepcopy(original)
            mutate(changed)
            common_manifest.write_text(json.dumps(changed), encoding="utf-8")
            with self.assertRaises(common_format.CommonFormatError):
                common_format.validate_common(
                    out / entries_file.NAME, common_manifest, entries, native_manifest)
        common_manifest.write_text(json.dumps(original), encoding="utf-8")

    def test_qaとsrcの未定義な組合せを拒否する(self):
        row = {"word": "未定義", "pinyin": "wèi dìng yì",
               "senses": [{"ja": "未定義", "qa": "machine_backed"}]}
        with self.assertRaises(common_format.CommonFormatError):
            common_format.to_common_entry(row)

    def test_native件数不一致なら既存commonを置き換えない(self):
        _, entries, manifest = self.native_fixture(20)
        out = self.root / "common-atomic"
        common_format.export_common(entries, manifest, out)
        targets = [out / entries_file.NAME, out / "manifest.json"]
        before = [path.read_bytes() for path in targets]
        changed = json.loads(manifest.read_text(encoding="utf-8"))
        changed["files"]["zh-ja/entries.jsonl.deflate"]["lines"] = 999
        manifest.write_text(json.dumps(changed), encoding="utf-8")
        with self.assertRaises(common_format.CommonFormatError):
            common_format.export_common(entries, manifest, out)
        self.assertEqual([path.read_bytes() for path in targets], before)

    def test_入力と出力が交差する場合はsymlink解決後に拒否し既存byteを保つ(self):
        _, source_entries, source_manifest = self.native_fixture(20)
        data = self.root / "data"
        native_dir = data / "zh-ja"
        native_dir.mkdir(parents=True)
        entries = native_dir / entries_file.NAME
        manifest = data / "manifest.json"
        source_entries.replace(entries)
        source_manifest.replace(manifest)
        before = (entries.read_bytes(), manifest.read_bytes())

        entries_alias = self.root / "entries-alias"
        entries_alias.symlink_to(native_dir, target_is_directory=True)
        data_alias = self.root / "data-alias"
        data_alias.symlink_to(data, target_is_directory=True)
        for out in (native_dir, data, entries_alias, data_alias):
            with self.subTest(out=out):
                with self.assertRaises(common_format.CommonFormatError):
                    common_format.export_common(entries, manifest, out)
                self.assertEqual((entries.read_bytes(), manifest.read_bytes()), before)

    def test_大文字小文字を区別しないFSの同一実体を入力と出力にできない(self):
        probe = self.root / "case-probe"
        probe.mkdir()
        probe_alias = self.root / "CASE-PROBE"
        if not probe_alias.exists() or not probe.samefile(probe_alias):
            self.skipTest("大文字小文字を区別しないfilesystemでだけ実行する")

        for label, output_kind in (("entries", "ZH-JA"), ("manifest", "DATA")):
            with self.subTest(label=label):
                _, source_entries, source_manifest = self.native_fixture(20)
                base = self.root / label
                data = base / "data"
                native_dir = data / "zh-ja"
                native_dir.mkdir(parents=True)
                entries = native_dir / entries_file.NAME
                manifest = data / "manifest.json"
                source_entries.replace(entries)
                source_manifest.replace(manifest)
                out = data / output_kind if label == "entries" else base / output_kind
                self.assertTrue(
                    out.samefile(native_dir if label == "entries" else data))
                before = (entries.read_bytes(), manifest.read_bytes())

                with self.assertRaises(common_format.CommonFormatError):
                    common_format.export_common(entries, manifest, out)
                self.assertEqual((entries.read_bytes(), manifest.read_bytes()), before)

    def test_limitは全量artifactの先頭だけを比較し全件数検査を維持する(self):
        _, entries, native_manifest = self.native_fixture(100)
        out = self.root / "common-full"
        common_format.export_common(entries, native_manifest, out)

        stats = common_format.validate_common(
            out / entries_file.NAME, out / "manifest.json",
            entries, native_manifest, limit=20)
        self.assertEqual(stats, common_format.ValidationStats(20, 21, 21))

        common_manifest = out / "manifest.json"
        original_common = common_manifest.read_bytes()
        original_native = native_manifest.read_bytes()
        for changed_path, changed_meta in (
            (common_manifest, json.loads(original_common)),
            (native_manifest, json.loads(original_native)),
        ):
            with self.subTest(changed_path=changed_path):
                if changed_path == common_manifest:
                    changed_meta["files"][entries_file.NAME]["lines"] = 20
                else:
                    changed_meta["files"]["zh-ja/entries.jsonl.deflate"]["lines"] = 20
                changed_path.write_text(json.dumps(changed_meta), encoding="utf-8")
                with self.assertRaises(common_format.CommonFormatError):
                    common_format.validate_common(
                        out / entries_file.NAME, common_manifest,
                        entries, native_manifest, limit=20)
                common_manifest.write_bytes(original_common)
                native_manifest.write_bytes(original_native)

    def test_limitは同じ件数のpilot_artifactも検証できる(self):
        _, entries, native_manifest = self.native_fixture(100)
        out = self.root / "common-pilot"
        common_format.export_common(entries, native_manifest, out, limit=20)

        stats = common_format.validate_common(
            out / entries_file.NAME, out / "manifest.json",
            entries, native_manifest, limit=20)
        self.assertEqual(stats, common_format.ValidationStats(20, 21, 21))


if __name__ == "__main__":
    unittest.main(verbosity=2)
