#!/usr/bin/env python3
"""validate_data.py の自己テスト。

    python3 tools/test_validate_data.py

小さな作り物のデータを渡し、検出すべき違反を検出し、正しいデータを違反にしないことを
確かめる。実データは使わない（実データの検証は tools/validate_data.py 自体が行う）。
"""

from __future__ import annotations

import contextlib
import copy
import io
import json
import pathlib
import sys
import tempfile
import unittest

sys.path.insert(0, str(pathlib.Path(__file__).resolve().parent))
import dataset_sources  # noqa: E402
import entries_file  # noqa: E402
import validate_data as v  # noqa: E402

ZH_JA = f"zh-ja/{entries_file.NAME}"
JA_ZH = "ja-zh/glosses.jsonl"

ENTRIES = [
    {"word": "上级", "trad": "上級", "pinyin": "shàng jí", "hsk2": 5, "hsk3": 6,
     "pos": ["n"], "cl": [{"w": "个", "t": "個", "py": "ge4"}],
     "seed": "machine_backed", "moe": "full",
     "senses": [
         {"en": ["higher authorities"], "ja": "上層部", "qa": "llm_ok"},
         {"en": ["superiors"], "ja": "上司", "qa": "llm_fixed", "misc": ["coll"]},
     ]},
    {"word": "女", "pinyin": "rǔ", "moe": "none",
     "senses": [{"ja": "汝（rǔ）の旧字体", "qa": "derived",
                 "variant_of": [{"kind": "old", "w": "汝", "py": "ru3"}]}]},
    {"word": "运输机", "trad": "運輸機", "pinyin": "yùnshūjī", "src": "zh-ja-dict",
     "hsk3": 7, "senses": [{"ja": "輸送機", "qa": "machine_backed"}]},
]

JA_ZH_ROWS = [
    {"word": "明白", "zh": [{"s": "明白", "pinyin": "míngbai"}]},
    {"word": "と言うもの", "zh": [], "unsure": True},
]


def write_data(entries, ja_zh=None, directory=None):
    """作り物のデータを一時ディレクトリへ書く。"""
    data = pathlib.Path(directory)
    entries_file.write(data / ZH_JA,
                       (json.dumps(row, ensure_ascii=False) for row in entries))
    path = data / JA_ZH
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(
        "".join(json.dumps(row, ensure_ascii=False) + "\n"
                for row in (JA_ZH_ROWS if ja_zh is None else ja_zh)),
        encoding="utf-8")
    return data


def run(entries, ja_zh=None):
    """検証して違反の種類の一覧と、区分の数え上げを返す。"""
    with tempfile.TemporaryDirectory() as tmp:
        data = write_data(entries, ja_zh, tmp)
        violations = []
        zh_rows = v.read_entries(data / ZH_JA, violations, ZH_JA)
        zh_counts = v.validate_zh_ja_entries(data / ZH_JA, zh_rows, violations)
        ja_rows = v.read_jsonl(data / JA_ZH, violations, JA_ZH)
        ja_counts = v.validate_ja_zh_glosses(data / JA_ZH, ja_rows, violations)
        return [x.kind for x in violations], {ZH_JA: zh_counts, JA_ZH: ja_counts}


def manifest_for(entries, data: pathlib.Path):
    sizes = entries_file.sizes(data / ZH_JA)
    return {
        "schema_version": dataset_sources.SCHEMA_VERSION,
        "generated": "2026-09-06",
        "files": {
            ZH_JA: {
                "lines": len(entries),
                "entries_skeleton": sum(1 for e in entries if not e.get("src")),
                "entries_supplement": sum(1 for e in entries if e.get("src")),
                "senses": sum(len(e["senses"]) for e in entries),
                "compression": entries_file.COMPRESSION,
                "bytes": sizes.compressed,
                "uncompressed_bytes": sizes.uncompressed,
            },
            JA_ZH: {"lines": len(JA_ZH_ROWS)},
        },
        "sources": dataset_sources.SOURCES,
    }


def run_main(entries, manifest="auto", extra_files=(), extra_args=()):
    """`validate_data.main()` を通す。終了コードと標準出力を返す。"""
    with tempfile.TemporaryDirectory() as tmp:
        data = write_data(entries, None, tmp)
        for relative in extra_files:
            path = data / relative
            path.parent.mkdir(parents=True, exist_ok=True)
            path.write_text("{}\n", encoding="utf-8")
        if manifest == "auto":
            manifest = manifest_for(entries, data)
        if manifest is not None:
            (data / "manifest.json").write_text(
                json.dumps(manifest, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
        buffer = io.StringIO()
        with contextlib.redirect_stdout(buffer):
            code = v.main(["--data", str(data), *extra_args])
        return code, buffer.getvalue()


def changed(index, entry):
    """ENTRIES のうち1件だけ差し替えたデータを作る。"""
    rows = copy.deepcopy(ENTRIES)
    rows[index] = entry
    return rows


def with_sense(index, sense_index, sense):
    rows = copy.deepcopy(ENTRIES)
    rows[index]["senses"][sense_index] = sense
    return rows


class CleanData(unittest.TestCase):
    def test_正しいデータは違反ゼロ(self):
        kinds, _ = run(ENTRIES)
        self.assertEqual(kinds, [])

    def test_区分の合計が行数に一致する(self):
        _, counts = run(ENTRIES)
        exclusive = sum(value for key, value in counts[ZH_JA].items()
                        if not key.startswith("_"))
        self.assertEqual(exclusive, len(ENTRIES))

    def test_骨格と補遺を数える(self):
        _, counts = run(ENTRIES)
        self.assertEqual(counts[ZH_JA]["骨格"], 2)
        self.assertEqual(counts[ZH_JA]["補遺"], 1)


class EntryStructure(unittest.TestCase):
    def test_必須キーの欠落(self):
        kinds, _ = run(changed(0, {"word": "上级", "senses": [{"ja": "上", "qa": "llm_ok"}]}))
        self.assertIn("missing-key", kinds)

    def test_仕様に無いキー(self):
        kinds, _ = run(changed(0, {"word": "上级", "pinyin": "shàng jí", "nope": 1,
                                   "senses": [{"ja": "上", "qa": "llm_ok"}]}))
        self.assertIn("unknown-key", kinds)

    def test_退役したキー(self):
        # schema 2 の `gloss`・`reading_pos` は語ごとに1行だった名残。
        kinds, _ = run(changed(0, {"word": "上级", "pinyin": "shàng jí",
                                   "gloss": ["上司"],
                                   "senses": [{"ja": "上", "qa": "llm_ok"}]}))
        self.assertIn("retired-key", kinds)

    def test_senses_が空なら違反(self):
        kinds, _ = run(changed(0, {"word": "上级", "pinyin": "shàng jí", "senses": []}))
        self.assertIn("bad-type", kinds)

    def test_繁体が簡体と同じなら書かない(self):
        kinds, _ = run(changed(0, {"word": "女", "trad": "女", "pinyin": "rǔ",
                                   "senses": [{"ja": "汝", "qa": "llm_ok"}]}))
        self.assertIn("redundant-trad", kinds)

    def test_HSKの級が範囲外(self):
        rows = copy.deepcopy(ENTRIES)
        rows[0]["hsk3"] = 8      # 3.0 は7級まで
        self.assertIn("bad-hsk", run(rows)[0])
        rows = copy.deepcopy(ENTRIES)
        rows[0]["hsk2"] = 7      # 2.0 は6級まで
        self.assertIn("bad-hsk", run(rows)[0])

    def test_品詞は上流の略号だけ(self):
        rows = copy.deepcopy(ENTRIES)
        rows[0]["pos"] = ["noun"]
        self.assertIn("unknown-value", run(rows)[0])

    def test_srcとseedとmoeの値(self):
        for key, bad in (("src", "どこか"), ("seed", "そのうち"), ("moe", "たぶん")):
            rows = copy.deepcopy(ENTRIES)
            rows[0][key] = bad
            self.assertIn("unknown-value", run(rows)[0], key)

    def test_台湾の読みも読みとして検査する(self):
        rows = copy.deepcopy(ENTRIES)
        rows[0]["tw_pr"] = "xia4hai2"     # 数字が残っている＝変換し忘れ
        self.assertIn("bad-pinyin", run(rows)[0])

    def test_人名の中黒は読みとして通る(self):
        rows = copy.deepcopy(ENTRIES)
        rows[0]["pinyin"] = "Shǐ dì fēn · Hā pò"
        self.assertEqual(run(rows)[0], [])

    def test_見出しの数字はそのまま読みに出てよい(self):
        rows = copy.deepcopy(ENTRIES)
        rows[0]["word"] = "双11"
        rows[0]["pinyin"] = "Shuāng 11"
        self.assertEqual(run(rows)[0], [])


class Duplicates(unittest.TestCase):
    def test_同じ3つ組は重複(self):
        rows = copy.deepcopy(ENTRIES)
        rows.append(copy.deepcopy(rows[0]))
        self.assertIn("duplicate-entry", run(rows)[0])

    def test_繁体が違えば別のentry(self):
        rows = copy.deepcopy(ENTRIES)
        clone = copy.deepcopy(rows[0])
        clone["trad"] = "尚級"      # 繁体だけ違う
        rows.append(clone)
        self.assertEqual(run(rows)[0], [])

    def test_大小文字が違えば別のentry(self):
        # CC-CEDICT は固有名詞の読みを大文字で始める（`三 Sān` 姓 と `三 sān` 数詞）。
        rows = copy.deepcopy(ENTRIES)
        rows.append({"word": "三", "pinyin": "sān",
                     "senses": [{"ja": "3", "qa": "llm_ok"}]})
        rows.append({"word": "三", "pinyin": "Sān",
                     "senses": [{"ja": "サン（姓）", "qa": "llm_ok"}]})
        self.assertEqual(run(rows)[0], [])


class SenseStructure(unittest.TestCase):
    def test_ja_が無い(self):
        kinds, _ = run(with_sense(0, 0, {"en": ["x"], "qa": "llm_ok"}))
        self.assertIn("missing-key", kinds)

    def test_qa_が想定外(self):
        kinds, _ = run(with_sense(0, 0, {"ja": "上", "qa": "たぶん"}))
        self.assertIn("bad-qa", kinds)

    def test_語義に仕様に無いキー(self):
        kinds, _ = run(with_sense(0, 0, {"ja": "上", "qa": "llm_ok", "zh": "上"}))
        self.assertIn("unknown-key", kinds)

    def test_misc_は表の値だけ(self):
        kinds, _ = run(with_sense(0, 0, {"ja": "上", "qa": "llm_ok", "misc": ["computing"]}))
        self.assertIn("unknown-value", kinds)

    def test_参照の種類(self):
        kinds, _ = run(with_sense(1, 0, {
            "ja": "汝の異体字", "qa": "derived",
            "variant_of": [{"kind": "see", "w": "汝"}]}))   # see は see_also 側の種類
        self.assertIn("bad-kind", kinds)

    def test_参照の繁体が簡体と同じなら書かない(self):
        kinds, _ = run(with_sense(1, 0, {
            "ja": "汝の異体字", "qa": "derived",
            "variant_of": [{"kind": "old", "w": "汝", "t": "汝"}]}))
        self.assertIn("redundant-trad", kinds)

    def test_参照先の語に空白があれば違反(self):
        # `Israel 以色列` のように英語の説明が参照先へ混ざった状態を捕まえる。
        kinds, _ = run(with_sense(1, 0, {
            "ja": "以色列（Yǐ sè liè）の略", "qa": "derived",
            "see_also": [{"kind": "abbr", "w": "Israel 以色列"}]}))
        self.assertIn("text-in-ref", kinds)

    def test_量詞は語義の欄ではない(self):
        kinds, _ = run(with_sense(0, 0, {
            "ja": "上", "qa": "llm_ok", "cl": [{"w": "个"}]}))
        self.assertIn("unknown-key", kinds)

    def test_量詞にkindは無い(self):
        rows = copy.deepcopy(ENTRIES)
        rows[0]["cl"] = [{"kind": "see", "w": "个"}]
        self.assertIn("unknown-key", run(rows)[0])

    def test_unsure_は_true_のときだけ(self):
        kinds, _ = run(with_sense(0, 0, {"ja": "上", "qa": "llm_ok", "unsure": False}))
        self.assertIn("explicit-false", kinds)


class JapaneseText(unittest.TestCase):
    def test_中国語だけの訳(self):
        kinds, _ = run(with_sense(0, 0, {"en": ["x"], "ja": "shàng jí", "qa": "llm_ok"}))
        self.assertIn("bad-ja", kinds)

    def test_英訳がそのまま残る(self):
        kinds, _ = run(with_sense(0, 0,
                                  {"en": ["supply"], "ja": "supplyする", "qa": "llm_ok"}))
        self.assertIn("bad-ja", kinds)

    def test_許可表のラテン語だけの訳は通る(self):
        # `CD-ROM`・`APEC` は日本語でもそう書く。
        kinds, _ = run(with_sense(0, 0, {"en": ["CD-ROM"], "ja": "CD-ROM", "qa": "llm_ok"}))
        self.assertEqual(kinds, [])

    def test_生成した訳は24文字まで(self):
        kinds, _ = run(with_sense(0, 0,
                                  {"ja": "あ" * 25, "qa": "llm_ok"}))
        self.assertIn("bad-ja", kinds)

    def test_参照から作った訳は読みを含んでよい(self):
        kinds, _ = run(with_sense(1, 0, {
            "ja": "开金（kāi jīn）に同じ", "qa": "derived",
            "see_also": [{"kind": "see", "w": "开金", "py": "kai1 jin1"}]}))
        self.assertEqual(kinds, [])

    def test_旧版から引き継いだ訳は長くてよい(self):
        rows = copy.deepcopy(ENTRIES)
        rows[2]["senses"][0]["ja"] = "、".join(["輸送機"] * 8)   # 31文字
        self.assertEqual(run(rows)[0], [])

    def test_キリル文字(self):
        kinds, _ = run(with_sense(0, 0, {"ja": "материал材", "qa": "llm_ok"}))
        self.assertIn("bad-ja", kinds)


class Archive(unittest.TestCase):
    def test_壊れた圧縮ファイルを違反にする(self):
        with tempfile.TemporaryDirectory() as tmp:
            data = write_data(ENTRIES, None, tmp)
            path = data / ZH_JA
            path.write_bytes(path.read_bytes()[:-20])   # 末尾を欠けさせる
            violations = []
            v.read_entries(path, violations, ZH_JA)
            self.assertIn("broken-archive", [x.kind for x in violations])


class Manifest(unittest.TestCase):
    def test_正しいmanifestなら成功(self):
        code, _ = run_main(ENTRIES)
        self.assertEqual(code, 0)

    def test_manifest_が無い(self):
        code, out = run_main(ENTRIES, manifest=None)
        self.assertEqual(code, 1)
        self.assertIn("missing-manifest", out)

    def test_schema_version_が違う(self):
        with tempfile.TemporaryDirectory() as tmp:
            data = write_data(ENTRIES, None, tmp)
            manifest = manifest_for(ENTRIES, data)
        manifest["schema_version"] = 2
        code, out = run_main(ENTRIES, manifest=manifest)
        self.assertEqual(code, 1)
        self.assertIn("bad-schema-version", out)

    def test_行数が食い違う(self):
        with tempfile.TemporaryDirectory() as tmp:
            data = write_data(ENTRIES, None, tmp)
            manifest = manifest_for(ENTRIES, data)
        manifest["files"][ZH_JA]["lines"] = 99
        code, out = run_main(ENTRIES, manifest=manifest)
        self.assertEqual(code, 1)
        self.assertIn("line-count-mismatch", out)

    def test_骨格と補遺の数が食い違う(self):
        with tempfile.TemporaryDirectory() as tmp:
            data = write_data(ENTRIES, None, tmp)
            manifest = manifest_for(ENTRIES, data)
        manifest["files"][ZH_JA]["entries_supplement"] = 0
        code, out = run_main(ENTRIES, manifest=manifest)
        self.assertEqual(code, 1)
        self.assertIn("count-mismatch", out)

    def test_出どころの表と食い違う(self):
        with tempfile.TemporaryDirectory() as tmp:
            data = write_data(ENTRIES, None, tmp)
            manifest = manifest_for(ENTRIES, data)
        manifest["sources"] = {"どこか": {"license": "不明"}}
        code, out = run_main(ENTRIES, manifest=manifest)
        self.assertEqual(code, 1)
        self.assertIn("sources-mismatch", out)

    def test_骨格の数をCCCEDICTと突き合わせる(self):
        code, out = run_main(ENTRIES, extra_args=("--cedict-entries", "2"))
        self.assertEqual(code, 0)
        code, out = run_main(ENTRIES, extra_args=("--cedict-entries", "3"))
        self.assertEqual(code, 1)
        self.assertIn("skeleton-count-mismatch", out)

    def test_退役したファイルが残っている(self):
        code, out = run_main(ENTRIES, extra_files=("zh-ja/glosses.jsonl",))
        self.assertEqual(code, 1)
        self.assertIn("retired-file", out)


class ExistingCoverage(unittest.TestCase):
    def test_旧版の行がすべて対応していれば違反ゼロ(self):
        with tempfile.NamedTemporaryFile("w", suffix=".jsonl", delete=False,
                                         encoding="utf-8") as handle:
            for row in ({"word": "上级", "pinyin": "shàng jí", "gloss": ["上司"],
                         "qa": "llm_ok"},
                        {"word": "上級", "pinyin": "shàng jí", "gloss": ["上司"],
                         "qa": "llm_ok"},         # 繁体の見出しからも引ける
                        {"word": "运输机", "pinyin": "yùnshūjī", "gloss": ["輸送機"],
                         "qa": "llm_ok"}):
                handle.write(json.dumps(row, ensure_ascii=False) + "\n")
            path = handle.name
        code, out = run_main(ENTRIES, extra_args=("--existing", path))
        self.assertEqual(code, 0, out)

    def test_声調だけ違う行は一と不のときだけ対応とみなす(self):
        # `繃 bèng` を `繃 bēng` に当てて「対応済み」と数えると、旧版の読みと訳が
        # 消えたことを見逃す。変調を認めるのは `一`・`不` で始まる語だけ。
        rows = copy.deepcopy(ENTRIES)
        rows.append({"word": "繃", "pinyin": "bēng",
                     "senses": [{"ja": "ぴんと張る", "qa": "llm_ok"}]})
        rows.append({"word": "一路", "pinyin": "yī lù",
                     "senses": [{"ja": "道中", "qa": "llm_ok"}]})
        with tempfile.NamedTemporaryFile("w", suffix=".jsonl", delete=False,
                                         encoding="utf-8") as handle:
            for row in ({"word": "繃", "pinyin": "bèng", "gloss": ["ひび割れる"],
                         "qa": "llm_ok"},
                        {"word": "一路", "pinyin": "yí lù", "gloss": ["道中"],
                         "qa": "llm_ok"}):
                handle.write(json.dumps(row, ensure_ascii=False) + "\n")
            path = handle.name
        code, out = run_main(rows, extra_args=("--existing", path))
        self.assertEqual(code, 1)
        self.assertIn("繃 bèng", out)          # 変調ではないので見逃さない
        self.assertNotIn("一路 yí lù", out)    # 先頭の `一` の変調は対応とみなす

    def test_旧版にしかない行を報告する(self):
        with tempfile.NamedTemporaryFile("w", suffix=".jsonl", delete=False,
                                         encoding="utf-8") as handle:
            handle.write(json.dumps({"word": "没有", "pinyin": "méiyǒu",
                                     "gloss": ["ない"], "qa": "llm_ok"},
                                    ensure_ascii=False) + "\n")
            path = handle.name
        code, out = run_main(ENTRIES, extra_args=("--existing", path))
        self.assertEqual(code, 1)
        self.assertIn("existing-not-covered", out)


class HskCoverage(unittest.TestCase):
    """HSK の元データとの突き合わせ。データが消えたら止まること。"""

    def seed(self, entries):
        with tempfile.NamedTemporaryFile("w", suffix=".json", delete=False,
                                         encoding="utf-8") as handle:
            json.dump({"entries": entries}, handle, ensure_ascii=False)
            return handle.name

    def test_級がそろっていれば成功(self):
        path = self.seed([{"word": "上级", "hsk_levels": {"2.0": 5, "3.0": 6}}])
        code, out = run_main(ENTRIES, extra_args=("--hsk-seed", path))
        self.assertEqual(code, 0, out)

    def test_見出しが消えていれば違反(self):
        # 数えるだけで違反にしないと、データが消えても成功で終わってしまう。
        path = self.seed([{"word": "存在しない語", "hsk_levels": {"3.0": 1}}])
        code, out = run_main(ENTRIES, extra_args=("--hsk-seed", path))
        self.assertEqual(code, 1)
        self.assertIn("hsk-word-missing", out)

    def test_級が食い違えば違反(self):
        path = self.seed([{"word": "上级", "hsk_levels": {"3.0": 2}}])
        code, out = run_main(ENTRIES, extra_args=("--hsk-seed", path))
        self.assertEqual(code, 1)
        self.assertIn("hsk-not-kept", out)


class JaZh(unittest.TestCase):
    """日中は schema 3 でも形を変えていない。従来の検査が効いていることを見る。"""

    def test_中国語訳にかなが混じる(self):
        kinds, _ = run(ENTRIES, ja_zh=[
            {"word": "明白", "zh": [{"s": "明白する", "pinyin": "míngbai"}]}])
        self.assertIn("kana-in-chinese", kinds)

    def test_候補が空なのに_unsure_が無い(self):
        kinds, _ = run(ENTRIES, ja_zh=[{"word": "明白", "zh": []}])
        self.assertIn("empty-without-unsure", kinds)

    def test_見出し語の重複(self):
        kinds, _ = run(ENTRIES, ja_zh=[
            {"word": "明白", "zh": [{"s": "明白", "pinyin": "míngbai"}]},
            {"word": "明白", "zh": [{"s": "清楚", "pinyin": "qīngchu"}]}])
        self.assertIn("duplicate-word", kinds)


if __name__ == "__main__":
    unittest.main()
