#!/usr/bin/env python3
"""共通辞書形式v2への変換と情報保存の試験。"""

from __future__ import annotations

import copy
import json
import pathlib
import sqlite3
import sys
import tempfile
import unittest
import zlib

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
                {
                    "en": ["calculator"], "ja": "電卓", "qa": "llm_fixed",
                    "misc": ["tw"],
                    "see_also": [{"kind": "abbr", "w": "电子计算机",
                                  "t": "電子計算機", "py": "dian4 zi3 ji4 suan4 ji1"}],
                    "lsource": ['"calculator"'], "s_inf": ["fixture note"],
                },
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
        self.assertEqual(common[0], {
            "id": {"source": "zh-ja-dict",
                   "value": '["计算机","計算機","jì suàn jī"]'},
            "headwords": [
                {"text": "计算机", "kind": "primary"},
                {"text": "計算機", "kind": "traditional"},
            ],
            "readings": [
                {"text": "jì suàn jī", "system": "pinyin", "kind": "primary"},
                {"text": "jì suàn jī", "system": "pinyin", "kind": "taiwan"},
                {"text": "jì suàn jī", "system": "pinyin", "kind": "alternate"},
            ],
            "levels": [
                {"system": "HSK", "version": "2.0", "value": "5"},
                {"system": "HSK", "version": "3.0", "value": "2"},
            ],
            "verification": [{
                "subject": "entry_headword_and_sense_count",
                "method": "moedict_crosscheck", "result": "full",
            }],
            "extensions": {"zh-ja-dict": {
                "cl": [{"w": "台", "t": "臺", "py": "tai2"}],
                "pos": ["n"], "seed": "machine_backed",
            }},
            "senses": [
                {
                    "glosses": [{"language": "en", "text": "computer"}],
                    "translations": [{
                        "language": "ja", "text": "コンピュータ",
                        "provenance": {"method": "llm", "source": "zh-ja-dict",
                                       "source_value": "llm_ok"},
                        "verification": [{"subject": "translation",
                                          "method": "script_and_length",
                                          "result": "passed"}],
                        "uncertain": False,
                    }],
                    "extensions": {},
                },
                {
                    "glosses": [{"language": "en", "text": "calculator"}],
                    "translations": [{
                        "language": "ja", "text": "電卓",
                        "provenance": {"method": "llm", "source": "zh-ja-dict",
                                       "source_value": "llm_fixed"},
                        "verification": [{"subject": "translation",
                                          "method": "script_and_length",
                                          "result": "passed"}],
                        "uncertain": False,
                    }],
                    "extensions": {"zh-ja-dict": {
                        "misc": ["tw"],
                        "see_also": [{"kind": "abbr", "w": "电子计算机",
                                      "t": "電子計算機",
                                      "py": "dian4 zi3 ji4 suan4 ji1"}],
                        "lsource": ['"calculator"'], "s_inf": ["fixture note"],
                    }},
                },
            ],
        })
        self.assertEqual(
            common[1]["senses"][0]["extensions"],
            {"zh-ja-dict": {"variant_of": [
                {"kind": "old", "w": "汝", "py": "ru3"}]}})
        encoded = json.dumps(common, ensure_ascii=False)
        self.assertNotIn('"qa"', encoded)
        self.assertNotIn('"moe"', encoded)
        self.assertNotIn("verified", encoded)

    def test_fixtureは全native属性とqa組合せを独立期待値で網羅する(self):
        native, common, *_ = self.export(20)
        self.assertEqual(
            set().union(*(entry.keys() for entry in native)),
            set(common_format.NATIVE_ENTRY_KEYS))
        self.assertEqual(
            set().union(*(sense.keys() for entry in native for sense in entry["senses"])),
            set(common_format.NATIVE_SENSE_KEYS))

        cases = [
            (0, 0, "llm_ok", "llm", "translation", "script_and_length", "passed"),
            (0, 1, "llm_fixed", "llm", "translation", "script_and_length", "passed"),
            (1, 0, "derived", "derived", None, None, None),
            (2, 0, "hand_fixed", "manual_override",
             "translation", "script_and_length", "passed"),
            (3, 0, "llm_ok", "legacy", "legacy_entry_translation_set",
             "legacy_llm_review", "passed"),
            (4, 0, "llm_fixed", "legacy", "legacy_entry_translation_set",
             "legacy_llm_review", "corrected"),
            (5, 0, "machine_backed", "legacy", "legacy_entry_translation_set",
             "legacy_dictionary_overlap", "reported_overlap"),
            (6, 0, "unchecked", "legacy", "legacy_entry_translation_set",
             "legacy_review", "unchecked"),
            (7, 0, "human_reviewed", "legacy", "reading_sense_alignment",
             "legacy_human_review", "passed"),
        ]
        for entry_index, sense_index, qa, method, subject, check_method, result in cases:
            with self.subTest(qa=qa):
                translation = common[entry_index]["senses"][sense_index]["translations"][0]
                self.assertEqual(translation["provenance"], {
                    "method": method, "source": "zh-ja-dict", "source_value": qa,
                })
                expected = [] if subject is None else [{
                    "subject": subject, "method": check_method, "result": result,
                }]
                self.assertEqual(translation["verification"], expected)

        self.assertEqual(common[1]["verification"], [{
            "subject": "entry_headword_and_sense_count",
            "method": "moedict_crosscheck", "result": "headword",
        }])
        self.assertEqual(common[2]["verification"], [{
            "subject": "entry_headword_and_sense_count",
            "method": "moedict_crosscheck", "result": "none",
        }])
        self.assertEqual(common[4]["verification"], [])
        self.assertTrue(common[3]["senses"][0]["translations"][0]["uncertain"])

    def test_100件を再集約せず全属性の保存先と候補順を検査する(self):
        native, common, stats, *_ = self.export(100)
        self.assertEqual(stats.entries, 100)
        for number, (native_entry, common_entry) in enumerate(
                zip(native, common), start=1):
            common_format.check_information_preserved(
                native_entry, common_entry, number=number)
        self.assertEqual(
            common[0]["headwords"],
            [{"text": "计算机", "kind": "primary"},
             {"text": "計算機", "kind": "traditional"}])
        self.assertEqual(
            [reading["kind"] for reading in common[0]["readings"]],
            ["primary", "taiwan", "alternate"])
        self.assertEqual(
            [sense["translations"][0]["text"] for sense in common[0]["senses"]],
            ["コンピュータ", "電卓"])

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

    def test_SQLiteと共通生成元の不一致を拒否する(self):
        _, common_rows, _, entries, native_manifest, out = self.export(20)
        common_entries = out / entries_file.NAME
        common_manifest = out / "manifest.json"
        database = out / "dictionary.sqlite3"
        sidecar = out / "dictionary-db-manifest.json"
        database.write_bytes(b"SQLite fixture")
        with self.assertRaisesRegex(common_format.CommonFormatError, "両方必要"):
            common_format.validate_common(common_entries, common_manifest, entries, native_manifest)
        sidecar.write_text(json.dumps({
            "source_entries_sha256": common_format.sha256_file(common_entries),
            "source_manifest_sha256": common_format.sha256_file(common_manifest),
            "file_sha256": common_format.sha256_file(database),
            "file_bytes": database.stat().st_size,
            "dictionary": common_format.DICTIONARY,
            "entry_count": 20,
            "sense_count": sum(len(row["senses"]) for row in common_rows),
            "payload_encoding": "deflate-raw",
        }), encoding="utf-8")
        with self.assertRaisesRegex(common_format.CommonFormatError, "SQLiteの内容"):
            common_format.validate_common(common_entries, common_manifest, entries, native_manifest)
        database.write_bytes(b"stale database")
        with self.assertRaisesRegex(common_format.CommonFormatError, "一致しない"):
            common_format.validate_common(common_entries, common_manifest, entries, native_manifest)

    def test_SQLiteの中間entryがJSONLと違えばhash更新後も拒否する(self):
        _, rows, _, entries, native_manifest, out = self.export(20)
        common_entries = out / entries_file.NAME
        common_manifest = out / "manifest.json"
        database = out / "dictionary.sqlite3"
        sidecar = out / "dictionary-db-manifest.json"

        def encode(row):
            compressor = zlib.compressobj(wbits=-15)
            data = json.dumps(row, ensure_ascii=False).encode()
            return compressor.compress(data) + compressor.flush()

        with sqlite3.connect(database) as connection:
            connection.executescript("""
                PRAGMA user_version=2;
                CREATE TABLE dictionary_meta (
                    singleton INTEGER, dictionary TEXT, entry_count INTEGER,
                    sense_count INTEGER, source_manifest_sha256 TEXT,
                    source_entries_sha256 TEXT, payload_encoding TEXT);
                CREATE TABLE entries (
                    ordinal INTEGER, id_source TEXT, id_value TEXT,
                    sense_count INTEGER, payload BLOB);
                CREATE TABLE lookup_keys (key TEXT, ordinal INTEGER);
                CREATE TABLE shared_values (id INTEGER, kind TEXT, json BLOB);
            """)
            connection.execute("INSERT INTO dictionary_meta VALUES (1,?,?,?,?,?,?)", (
                common_format.DICTIONARY, len(rows), sum(len(row["senses"]) for row in rows),
                common_format.sha256_file(common_manifest),
                common_format.sha256_file(common_entries), "deflate-raw",
            ))
            for ordinal, row in enumerate(rows):
                connection.execute("INSERT INTO entries VALUES (?,?,?,?,?)", (
                    ordinal, row["id"]["source"], row["id"]["value"],
                    len(row["senses"]), encode(row),
                ))

        def write_sidecar():
            sidecar.write_text(json.dumps({
                "dictionary": common_format.DICTIONARY,
                "entry_count": len(rows),
                "sense_count": sum(len(row["senses"]) for row in rows),
                "payload_encoding": "deflate-raw",
                "source_entries_sha256": common_format.sha256_file(common_entries),
                "source_manifest_sha256": common_format.sha256_file(common_manifest),
                "file_sha256": common_format.sha256_file(database),
                "file_bytes": database.stat().st_size,
            }), encoding="utf-8")

        write_sidecar()
        common_format.validate_common(common_entries, common_manifest, entries, native_manifest)
        changed = copy.deepcopy(rows[10])
        changed["senses"][0]["translations"][0]["text"] = "別の訳"
        with sqlite3.connect(database) as connection:
            connection.execute("UPDATE entries SET payload=? WHERE ordinal=10", (encode(changed),))
        write_sidecar()
        with self.assertRaisesRegex(common_format.CommonFormatError, "ordinal=10"):
            common_format.validate_common(common_entries, common_manifest, entries, native_manifest)

    def test_qaとsrcの未定義な組合せを拒否する(self):
        row = {"word": "未定義", "pinyin": "wèi dìng yì",
               "senses": [{"ja": "未定義", "qa": "machine_backed"}]}
        with self.assertRaises(common_format.CommonFormatError):
            common_format.to_common_entry(row)

    def test_保存先のないentryとsense属性を拒否する(self):
        entry = copy.deepcopy(sample_rows(20)[0])
        entry["unknown_entry"] = 1
        with self.assertRaises(common_format.CommonFormatError):
            common_format.to_common_entry(entry)
        sense = copy.deepcopy(sample_rows(20)[0])
        sense["senses"][0]["unknown_sense"] = 1
        with self.assertRaises(common_format.CommonFormatError):
            common_format.to_common_entry(sense)

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
