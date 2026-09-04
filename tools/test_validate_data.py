#!/usr/bin/env python3
"""validate_data.py の自己テスト。

    python3 tools/test_validate_data.py

小さな作り物のデータを渡し、検出すべき違反を検出し、正しいデータを違反にしないことを確かめる。
実データは使わない（実データの検証は tools/validate_data.py 自体が行う）。
"""

from __future__ import annotations

import json
import pathlib
import sys
import tempfile
import unittest

sys.path.insert(0, str(pathlib.Path(__file__).resolve().parent))
import validate_data as v  # noqa: E402

ZH_JA = "zh-ja/glosses.jsonl"
JA_ZH = "ja-zh/glosses.jsonl"

CLEAN = {
    ZH_JA: [
        {"word": "美国", "pinyin": "Měiguó", "gloss": ["アメリカ"], "qa": "machine_backed"},
        {"word": "幖", "pinyin": "biāo", "gloss": [], "unsure": True, "qa": "llm_ok"},
    ],
    JA_ZH: [
        {"word": "明白", "zh": [{"s": "明白", "pinyin": "míngbai"}]},
        {"word": "と言うもの", "zh": [], "unsure": True},
    ],
}


def run(rows_by_file):
    """作り物のデータを一時ディレクトリへ書き、検証して違反の種類を返す。"""
    with tempfile.TemporaryDirectory() as tmp:
        data = pathlib.Path(tmp)
        for relative, rows in rows_by_file.items():
            path = data / relative
            path.parent.mkdir(parents=True, exist_ok=True)
            path.write_text(
                "".join(json.dumps(row, ensure_ascii=False) + "\n" for row in rows),
                encoding="utf-8",
            )
        violations = []
        counts = {}
        for relative, validate in v.FILES:
            parsed = v.read_jsonl(data / relative, violations, relative)
            counts[relative] = validate(data / relative, parsed, violations)
        return [x.kind for x in violations], counts


def run_main(rows_by_file, manifest="auto", extra_files=()):
    """データと manifest を書き、`validate_data.main()` を通す。終了コードを返す。

    manifest の突き合わせと退役ファイルの検出は main() の側にあるので、
    そこを見るテストはこちらを使う。
    """
    import io
    import contextlib
    with tempfile.TemporaryDirectory() as tmp:
        data = pathlib.Path(tmp)
        for relative, rows in rows_by_file.items():
            path = data / relative
            path.parent.mkdir(parents=True, exist_ok=True)
            path.write_text("".join(json.dumps(r, ensure_ascii=False) + "\n" for r in rows),
                            encoding="utf-8")
        for relative in extra_files:
            path = data / relative
            path.parent.mkdir(parents=True, exist_ok=True)
            path.write_text("{}\n", encoding="utf-8")
        if manifest == "auto":
            manifest = {
                "schema_version": 2,
                "generated": "2026-09-03",
                "files": {rel: {"lines": len(rows)} for rel, rows in rows_by_file.items()},
            }
        if manifest is not None:
            (data / "manifest.json").write_text(
                json.dumps(manifest, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
        buffer = io.StringIO()
        with contextlib.redirect_stdout(buffer):
            code = v.main(["--data", str(data)])
        return code, buffer.getvalue()


def with_change(relative, index, change):
    """CLEAN のうち1行だけ差し替えたデータを作る。"""
    rows = {key: [dict(row) for row in value] for key, value in CLEAN.items()}
    rows[relative][index] = change
    return rows


class CleanDataTest(unittest.TestCase):
    def test_正しいデータは違反ゼロ(self):
        kinds, _ = run(CLEAN)
        self.assertEqual(kinds, [])

    def test_区分の合計が行数に一致する(self):
        _, counts = run(CLEAN)
        for relative, count in counts.items():
            exclusive = sum(value for key, value in count.items() if not key.startswith("_"))
            self.assertEqual(exclusive, len(CLEAN[relative]), relative)


class StructureTest(unittest.TestCase):
    def test_必須キーの欠落を報告する(self):
        kinds, _ = run(with_change(ZH_JA, 0, {"word": "美国", "gloss": ["アメリカ"], "qa": "llm_ok"}))
        self.assertIn("missing-key", kinds)

    def test_仕様に無いキーを報告する(self):
        kinds, _ = run(with_change(JA_ZH, 0, {"word": "一新", "pinyin": None, "zh": [{"s": "革新", "pinyin": "géxīn"}]}))
        self.assertIn("unknown-key", kinds)

    def test_入れ子の仕様に無いキーを報告する(self):
        # 入れ子のオブジェクトを持つのは日中の `zh[]` だけになった。
        change = {"word": "明白", "zh": [{"s": "明白", "pinyin": "míngbai", "note": "x"}]}
        kinds, _ = run(with_change(JA_ZH, 0, change))
        self.assertIn("unknown-key", kinds)

    def test_unsureにfalseを書いたら報告する(self):
        kinds, _ = run(with_change(JA_ZH, 0, {"word": "明白", "zh": [{"s": "明白", "pinyin": "míngbai"}], "unsure": False}))
        self.assertIn("explicit-false", kinds)

    def test_unsureなしで訳が空なら報告する(self):
        kinds, _ = run(with_change(ZH_JA, 1, {"word": "幖", "pinyin": "biāo", "gloss": [], "qa": "llm_ok"}))
        self.assertIn("empty-without-unsure", kinds)

    def test_unsureがあれば訳が空でも違反にしない(self):
        kinds, _ = run(CLEAN)
        self.assertNotIn("empty-without-unsure", kinds)

    def test_日中の見出し語の重複を報告する(self):
        # 日中は今も1語1行。中日は (語, 読み) が単位になったので WordPinyinTest で見る。
        rows = {key: [dict(row) for row in value] for key, value in CLEAN.items()}
        rows[JA_ZH].append({"word": "明白", "zh": [{"s": "清楚", "pinyin": "qīngchu"}]})
        kinds, _ = run(rows)
        self.assertIn("duplicate-word", kinds)

    def test_qaの想定外の値を報告する(self):
        kinds, _ = run(with_change(ZH_JA, 0, {"word": "美国", "pinyin": "Měiguó", "gloss": ["アメリカ"], "qa": "unknown"}))
        self.assertIn("bad-qa", kinds)

    def test_qaがnullでも報告する(self):
        kinds, _ = run(with_change(ZH_JA, 0, {"word": "美国", "pinyin": "Měiguó", "gloss": ["アメリカ"], "qa": None}))
        self.assertIn("bad-qa", kinds)

    def test_空文字と前後の空白を報告する(self):
        kinds, _ = run(with_change(JA_ZH, 0, {"word": "仕手", "zh": [{"s": "", "pinyin": ""}], "unsure": True}))
        self.assertIn("empty-string", kinds)
        self.assertIn("empty-pinyin", kinds)
        kinds, _ = run(with_change(ZH_JA, 0, {"word": "美国", "pinyin": "Měiguó", "gloss": [" アメリカ"], "qa": "llm_ok"}))
        self.assertIn("whitespace", kinds)

    def test_同じ見出し語の中の候補の重複を報告する(self):
        change = {"word": "明白", "zh": [{"s": "明白", "pinyin": "míngbai"}, {"s": "明白", "pinyin": "míngbai"}]}
        kinds, _ = run(with_change(JA_ZH, 0, change))
        self.assertIn("duplicate-candidate", kinds)


class LanguageTest(unittest.TestCase):
    def test_キリル文字を報告する(self):
        kinds, _ = run(with_change(ZH_JA, 0, {"word": "雙", "pinyin": "shuāng", "gloss": ["двойной"], "qa": "llm_ok"}))
        self.assertIn("cyrillic", kinds)

    def test_登録の無いラテン語を報告する(self):
        kinds, _ = run(with_change(ZH_JA, 0, {"word": "坐班", "pinyin": "zuòbān", "gloss": ["office勤務する"], "qa": "llm_ok"}))
        self.assertIn("foreign-latin", kinds)

    def test_登録済みのラテン語は違反にしない(self):
        # allowlist-latin.txt に載っている語（USB・EU など）は通す。
        change = {"word": "优盘", "pinyin": "yōupán", "gloss": ["USBメモリ"], "qa": "llm_ok"}
        kinds, _ = run(with_change(ZH_JA, 0, change))
        self.assertNotIn("foreign-latin", kinds)

    def test_中国語訳のかなを報告する(self):
        change = {"word": "試し", "zh": [{"s": "试す", "pinyin": "shì"}]}
        kinds, _ = run(with_change(JA_ZH, 0, change))
        self.assertIn("kana-in-chinese", kinds)

    def test_登録済みの文法用語のかなは違反にしない(self):
        change = {"word": "サ変", "zh": [{"s": "サ行不规则活用", "pinyin": "sà háng bù guīzé huóyòng"}]}
        kinds, _ = run(with_change(JA_ZH, 0, change))
        self.assertNotIn("kana-in-chinese", kinds)

    def test_数字だけの訳は違反にしない(self):
        change = {"word": "十一", "pinyin": "shíyī", "gloss": ["11"], "qa": "llm_ok"}
        kinds, _ = run(with_change(ZH_JA, 0, change))
        self.assertNotIn("no-japanese", kinds)

    def test_ピンイン欄のキリル文字の同形文字を報告する(self):
        # 'т' は U+0442（キリル文字）で、ラテン文字の 't' と見分けがつかない。
        change = {"word": "宇宙像", "zh": [{"s": "宇宙图景", "pinyin": "yǔzhòu тújǐng"}]}
        kinds, _ = run(with_change(JA_ZH, 0, change))
        self.assertIn("bad-pinyin", kinds)

    def test_ピンイン欄のかなを報告する(self):
        change = {"word": "ら行", "zh": [{"s": "日语ra行", "pinyin": "ら háng"}]}
        kinds, _ = run(with_change(JA_ZH, 0, change))
        self.assertIn("bad-pinyin", kinds)

    def test_ピンイン欄の数字混入を報告する(self):
        # 実データにあった `衣锦荣归 / yījǐnr645guī` の型。数字を無条件に許すと見逃す。
        change = {"word": "衣锦荣归", "pinyin": "yījǐnr645guī", "gloss": ["錦を飾って帰る"], "qa": "llm_ok"}
        kinds, _ = run(with_change(ZH_JA, 0, change))
        self.assertIn("bad-pinyin", kinds)

    def test_ピンイン欄の全角数字を報告する(self):
        # ASCII の数字だけを確認済みtokenとして読み飛ばすので、全角 `１`（U+FF11）は残る。
        change = {"word": "衣锦荣归", "pinyin": "yījǐn１guī", "gloss": ["錦を飾って帰る"], "qa": "llm_ok"}
        kinds, _ = run(with_change(ZH_JA, 0, change))
        self.assertIn("bad-pinyin", kinds)

    def test_ピンイン欄のアラビア数字を報告する(self):
        change = {"word": "明白", "zh": [{"s": "明白", "pinyin": "míngbai٣"}]}
        kinds, _ = run(with_change(JA_ZH, 0, change))
        self.assertIn("bad-pinyin", kinds)

    def test_確認済みの数字入りの略号は通す(self):
        change = {"word": "一代雑種", "zh": [{"s": "F1杂交种", "pinyin": "F1 zájiāozhǒng"}]}
        kinds, _ = run(with_change(JA_ZH, 0, change))
        self.assertNotIn("bad-pinyin", kinds)

    def test_ピンイン欄のIPAの同形文字を報告する(self):
        # 'ɡ' は U+0261。Unicode の名前が LATIN で始まるため、
        # 「ラテン文字かどうか」で判定すると素通しになる。
        change = {"word": "歌合わせ", "zh": [{"s": "和歌比赛", "pinyin": "héɡē bǐsài"}]}
        kinds, _ = run(with_change(JA_ZH, 0, change))
        self.assertIn("bad-pinyin", kinds)

    def test_ピンイン欄のギリシャ文字とゆれ記号は通す(self):
        # β-内酰胺类・θ函数の接頭辞、省略の `…`、声調の合成記号は実データで使われている。
        for pinyin in ("β-nèixiān'ànlèi", "θ hánshù", "xiàng…shì de", "m̄ shá", "xiānsheng／nǚshì"):
            change = {"word": "見出し", "zh": [{"s": "词条", "pinyin": pinyin}]}
            kinds, _ = run(with_change(JA_ZH, 0, change))
            self.assertNotIn("bad-pinyin", kinds, pinyin)

    def test_拡張漢字面の元素名を違反にしない(self):
        # 𨭆（U+28B46、ハッシウム）は BMP の外にある正規の中国語の元素名。
        change = {"word": "ハッシウム", "zh": [{"s": "𨭆", "pinyin": "hēi"}]}
        kinds, _ = run(with_change(JA_ZH, 0, change))
        self.assertEqual(kinds, [])


ABSENT = object()  # 「キーを書かない」を、値が None であることと区別するための印


class HskTest(unittest.TestCase):
    def base(self, key, level):
        row = {"word": "美国", "pinyin": "Měiguó", "gloss": ["アメリカ"], "qa": "machine_backed"}
        if level is not ABSENT:
            row[key] = level
        return with_change(ZH_JA, 0, row)

    def test_有効な級は違反にしない(self):
        for level in range(1, 7):
            self.assertEqual(run(self.base("hsk2", level))[0], [], f"hsk2={level}")
        for level in range(1, 8):
            self.assertEqual(run(self.base("hsk3", level))[0], [], f"hsk3={level}")

    def test_版ごとに上限が違う(self):
        # HSK 2.0 は6級まで。7級は 3.0 にしかない。
        self.assertIn("bad-hsk", run(self.base("hsk2", 7))[0])
        self.assertNotIn("bad-hsk", run(self.base("hsk3", 7))[0])

    def test_級が無くても違反にしない(self):
        self.assertEqual(run(self.base("hsk2", ABSENT))[0], [])

    def test_明示的なnullを報告する(self):
        self.assertIn("bad-hsk", run(self.base("hsk3", None))[0])

    def test_範囲の外を報告する(self):
        for level in (0, 8, -1, 99):
            self.assertIn("bad-hsk", run(self.base("hsk3", level))[0], f"hsk3={level}")

    def test_整数でない値を報告する(self):
        for level in ("3", 3.0, [3], {"3.0": 3}):
            self.assertIn("bad-hsk", run(self.base("hsk3", level))[0], f"hsk3={level!r}")

    def test_真偽値を報告する(self):
        # Python では bool が int の派生なので、True は素通しになりやすい。
        for level in (True, False):
            self.assertIn("bad-hsk", run(self.base("hsk3", level))[0], f"hsk3={level!r}")

    def test_級は区分ではなく属性として数える(self):
        _, counts = run(self.base("hsk3", 3))
        c = counts[ZH_JA]
        exclusive = sum(x for k, x in c.items() if not k.startswith("_"))
        self.assertEqual(exclusive, len(CLEAN[ZH_JA]))
        self.assertEqual(c["_属性:hsk3"], 1)
        self.assertEqual(c["_hsk3 3級"], 1)

    def test_退役キーhskを専用の違反として報告する(self):
        row = {"word": "美国", "pinyin": "Měiguó", "gloss": ["アメリカ"], "qa": "machine_backed", "hsk": 3}
        kinds, _ = run(with_change(ZH_JA, 0, row))
        self.assertIn("retired-key", kinds)
        self.assertNotIn("unknown-key", kinds)

    def test_日中に級を書いたら仕様外のキーとして報告する(self):
        kinds, _ = run(with_change(JA_ZH, 0, {"word": "明白", "zh": [{"s": "明白", "pinyin": "míngbai"}], "hsk3": 3}))
        self.assertIn("unknown-key", kinds)


class ItemCountTest(unittest.TestCase):
    """件数の上限は設けない。空でないことと重複がないことだけを見る。"""

    def test_訳が4件以上でも受理する(self):
        change = {"word": "美国", "pinyin": "Měiguó", "gloss": ["ア", "メ", "リ", "カ"], "qa": "llm_ok"}
        self.assertEqual(run(with_change(ZH_JA, 0, change))[0], [])

    def test_日中の候補が4件以上でも受理する(self):
        change = {"word": "明白", "zh": [{"s": s, "pinyin": "x"} for s in ("明白", "清楚", "清晰", "了解")]}
        self.assertEqual(run(with_change(JA_ZH, 0, change))[0], [])

    def test_訳の重複を報告する(self):
        # 実データにあった `酪酸 / ["酪酸","酪酸"]` の型。
        change = {"word": "酪酸", "pinyin": "lào suān", "gloss": ["酪酸", "酪酸"], "qa": "llm_ok"}
        self.assertIn("duplicate-item", run(with_change(ZH_JA, 0, change))[0])

    def test_日中の候補の重複を報告する(self):
        change = {"word": "明白", "zh": [{"s": "明白", "pinyin": "a"}, {"s": "明白", "pinyin": "b"}]}
        self.assertIn("duplicate-candidate", run(with_change(JA_ZH, 0, change))[0])


class ArrayKeyTest(unittest.TestCase):
    """`trad`・`pos`・`reading_pos`・`alt_pinyin` の検査。"""

    def row(self, **extra):
        row = {"word": "美国", "pinyin": "Měiguó", "gloss": ["アメリカ"], "qa": "machine_backed"}
        row.update(extra)
        return with_change(ZH_JA, 0, row)

    def test_正しい配列は違反にしない(self):
        kinds, _ = run(self.row(trad=["美國"], pos=["n"], reading_pos=["v"], alt_pinyin=["měiguo"]))
        self.assertEqual(kinds, [])

    def test_配列でない値を報告する(self):
        for key in ("trad", "pos", "alt_pinyin"):
            self.assertIn("bad-type", run(self.row(**{key: "n"}))[0], key)
        self.assertIn("bad-type", run(self.row(pos=["n"], reading_pos="v"))[0])

    def test_空配列を報告する(self):
        for key in ("trad", "pos", "alt_pinyin"):
            self.assertIn("empty-array", run(self.row(**{key: []}))[0], key)
        self.assertIn("empty-array", run(self.row(pos=["n"], reading_pos=[]))[0])

    def test_配列内の重複を報告する(self):
        self.assertIn("duplicate-item", run(self.row(trad=["美國", "美國"]))[0])
        self.assertIn("duplicate-item", run(self.row(pos=["n", "n"]))[0])

    def test_許容語彙にない品詞を報告する(self):
        self.assertIn("unknown-value", run(self.row(pos=["名詞"]))[0])
        self.assertIn("unknown-value", run(self.row(pos=["n"], reading_pos=["名詞"]))[0])

    def test_reading_posはinterjectionを受理する(self):
        # 上流の senses[].pos に英単語が1つだけ混じる（哦・嗯）。
        self.assertEqual(run(self.row(pos=["e"], reading_pos=["interjection"]))[0], [])
        self.assertIn("unknown-value", run(self.row(pos=["interjection"]))[0])

    def test_reading_posだけあってposが無い行を報告する(self):
        # README の復元規則（reading_pos が無い行は語の pos と同じ）を機械で保証する。
        self.assertIn("reading-pos-without-pos", run(self.row(reading_pos=["n"]))[0])
        self.assertNotIn("reading-pos-without-pos", run(self.row(pos=["n"], reading_pos=["v"]))[0])

    def test_alt_pinyinの不正なピンインを報告する(self):
        # ピンイン欄と同じ検査を各値へ掛ける（キリル文字の同形文字）。
        self.assertIn("bad-pinyin", run(self.row(alt_pinyin=["měiguó", "тújǐng"]))[0])

    def test_要素が文字列でないものを報告する(self):
        self.assertIn("bad-type", run(self.row(pos=["n", 3]))[0])
        self.assertIn("bad-type", run(self.row(trad=["美國", ""]))[0])


class WordPinyinTest(unittest.TestCase):
    """(語, 読み) の一意性と、語の属性の行間一致。"""

    def two(self, first, second):
        rows = {k: [dict(r) for r in v] for k, v in CLEAN.items()}
        rows[ZH_JA] = [first, second]
        return rows

    def test_同じ語の別の読みは重複にしない(self):
        kinds, _ = run(self.two(
            {"word": "着", "pinyin": "zhe", "gloss": ["〜している"], "qa": "machine_backed"},
            {"word": "着", "pinyin": "zháo", "gloss": ["触れる"], "qa": "human_reviewed"}))
        self.assertEqual(kinds, [])

    def test_同じ読みの重複を報告する(self):
        kinds, _ = run(self.two(
            {"word": "着", "pinyin": "zhe", "gloss": ["〜している"], "qa": "machine_backed"},
            {"word": "着", "pinyin": "zhe", "gloss": ["別の訳"], "qa": "llm_ok"}))
        self.assertIn("duplicate-word-pinyin", kinds)

    def test_空白と軽声の印の違いは同じ読みとみなす(self):
        # `sāng jiā` と `sāngjiā`、`yǒukòngr5` と `yǒukòngr` は同じ読み。
        for a, b in (("sāng jiā", "sāngjiā"), ("yǒukòngr", "yǒukòngr5"), ("guī ˙nü", "guī nü")):
            kinds, _ = run(self.two(
                {"word": "丧家", "pinyin": a, "gloss": ["訳1"], "qa": "llm_ok"},
                {"word": "丧家", "pinyin": b, "gloss": ["訳2"], "qa": "llm_ok"}))
            self.assertIn("duplicate-word-pinyin", kinds, f"{a} vs {b}")

    def test_大小文字は既定で同じ読みとみなす(self):
        kinds, _ = run(self.two(
            {"word": "俞", "pinyin": "Yú", "gloss": ["姓"], "qa": "llm_ok"},
            {"word": "俞", "pinyin": "yú", "gloss": ["承諾する"], "qa": "unchecked"}))
        self.assertIn("duplicate-word-pinyin", kinds)

    def test_一覧に載せた語は大小文字を区別する(self):
        # 包头 は Bāotóu（地名）と bāotóu（頭巾）が別の語である。
        kinds, _ = run(self.two(
            {"word": "包头", "pinyin": "Bāotóu", "gloss": ["包頭(地名)"], "qa": "llm_ok"},
            {"word": "包头", "pinyin": "bāotóu", "gloss": ["頭巾"], "qa": "unchecked"}))
        self.assertEqual(kinds, [])

    def test_語の属性の食い違いを報告する(self):
        kinds, _ = run(self.two(
            {"word": "着", "pinyin": "zhe", "gloss": ["〜している"], "qa": "machine_backed", "hsk3": 1},
            {"word": "着", "pinyin": "zháo", "gloss": ["触れる"], "qa": "human_reviewed", "hsk3": 2}))
        self.assertIn("attribute-mismatch", kinds)

    def test_行の属性reading_posは行ごとに違ってよい(self):
        kinds, _ = run(self.two(
            {"word": "着", "pinyin": "zhe", "gloss": ["〜している"], "qa": "machine_backed",
             "pos": ["u", "v"], "reading_pos": ["u"]},
            {"word": "着", "pinyin": "zháo", "gloss": ["触れる"], "qa": "human_reviewed",
             "pos": ["u", "v"], "reading_pos": ["v"]}))
        self.assertEqual(kinds, [])


class QaValueTest(unittest.TestCase):
    def test_新しい2値を受理する(self):
        for value in ("human_reviewed", "unchecked"):
            change = {"word": "美国", "pinyin": "Měiguó", "gloss": ["アメリカ"], "qa": value}
            self.assertEqual(run(with_change(ZH_JA, 0, change))[0], [], value)

    def test_想定外の値を報告する(self):
        change = {"word": "美国", "pinyin": "Měiguó", "gloss": ["アメリカ"], "qa": "reviewed"}
        self.assertIn("bad-qa", run(with_change(ZH_JA, 0, change))[0])


class ManifestTest(unittest.TestCase):
    """manifest と実ファイルの突き合わせ、退役ファイルの検出（main() 側）。"""

    def clean(self):
        return {k: [dict(r) for r in v] for k, v in CLEAN.items()}

    def test_正しいmanifestなら成功で終わる(self):
        code, _ = run_main(self.clean())
        self.assertEqual(code, 0)

    def test_manifestが無ければ失敗する(self):
        code, out = run_main(self.clean(), manifest=None)
        self.assertEqual(code, 1)
        self.assertIn("missing-manifest", out)

    def test_行数が食い違えば失敗する(self):
        code, out = run_main(self.clean(), manifest={
            "schema_version": 2, "generated": "2026-09-03",
            "files": {ZH_JA: {"lines": 999}, JA_ZH: {"lines": 2}}})
        self.assertEqual(code, 1)
        self.assertIn("line-count-mismatch", out)

    def test_schema_versionが違えば失敗する(self):
        code, out = run_main(self.clean(), manifest={
            "schema_version": 1, "generated": "2026-09-03",
            "files": {ZH_JA: {"lines": 2}, JA_ZH: {"lines": 2}}})
        self.assertEqual(code, 1)
        self.assertIn("bad-schema-version", out)

    def test_filesの値がオブジェクトでなければ報告する(self):
        # 手で書いた manifest でも例外にならず、違反として報告すること。
        code, out = run_main(self.clean(), manifest={
            "schema_version": 2, "generated": "2026-09-03",
            "files": {ZH_JA: 2, JA_ZH: {"lines": 2}}})
        self.assertEqual(code, 1)
        self.assertIn("bad-type", out)

    def test_filesがオブジェクトでなければ報告する(self):
        code, out = run_main(self.clean(), manifest={
            "schema_version": 2, "generated": "2026-09-03", "files": []})
        self.assertEqual(code, 1)
        self.assertIn("bad-type", out)

    def test_廃止したpolyphonicが残っていれば失敗する(self):
        code, out = run_main(self.clean(), extra_files=("zh-ja/polyphonic.jsonl",))
        self.assertEqual(code, 1)
        self.assertIn("retired-file", out)


class NonStringCandidateTest(unittest.TestCase):
    def test_sが配列でも例外にならず報告する(self):
        # set へ入れると TypeError になる型。重複検査を飛ばして bad-type だけ出す。
        change = {"word": "明白", "zh": [{"s": ["明白"], "pinyin": "míngbai"}]}
        kinds, _ = run(with_change(JA_ZH, 0, change))
        self.assertIn("bad-type", kinds)


class BrokenFileTest(unittest.TestCase):
    def write(self, tmp, text):
        data = pathlib.Path(tmp)
        for relative, rows in CLEAN.items():
            path = data / relative
            path.parent.mkdir(parents=True, exist_ok=True)
            path.write_text(
                "".join(json.dumps(row, ensure_ascii=False) + "\n" for row in rows),
                encoding="utf-8",
            )
        (data / ZH_JA).write_text(text, encoding="utf-8")
        violations = []
        for relative, validate in v.FILES:
            validate(data / relative, v.read_jsonl(data / relative, violations, relative), violations)
        return [x.kind for x in violations]

    def test_壊れたJSONを報告する(self):
        with tempfile.TemporaryDirectory() as tmp:
            self.assertIn("broken-json", self.write(tmp, '{"word": "美国"\n'))

    def test_文字化けの跡を報告する(self):
        with tempfile.TemporaryDirectory() as tmp:
            line = '{"word": "側頭骨", "pinyin": "niè�", "gloss": ["側頭骨"], "qa": "llm_ok"}\n'
            self.assertIn("replacement-char", self.write(tmp, line))

    def test_末尾の改行の欠落を報告する(self):
        with tempfile.TemporaryDirectory() as tmp:
            line = '{"word": "美国", "pinyin": "Měiguó", "gloss": ["アメリカ"], "qa": "llm_ok"}'
            self.assertIn("no-final-newline", self.write(tmp, line))

    def test_CRLFを報告する(self):
        with tempfile.TemporaryDirectory() as tmp:
            line = '{"word": "美国", "pinyin": "Měiguó", "gloss": ["アメリカ"], "qa": "llm_ok"}\r\n'
            self.assertIn("crlf", self.write(tmp, line))

    def test_BOMを報告しても行は読める(self):
        with tempfile.TemporaryDirectory() as tmp:
            line = '﻿{"word": "美国", "pinyin": "Měiguó", "gloss": ["アメリカ"], "qa": "llm_ok"}\n'
            kinds = self.write(tmp, line)
            self.assertIn("bom", kinds)
            # BOM を剥がして読むので、JSON の解析までは失敗しない。
            self.assertNotIn("broken-json", kinds)

    def test_UTF8として読めないバイトを報告する(self):
        with tempfile.TemporaryDirectory() as tmp:
            data = pathlib.Path(tmp)
            for relative, rows in CLEAN.items():
                path = data / relative
                path.parent.mkdir(parents=True, exist_ok=True)
                path.write_text(
                    "".join(json.dumps(row, ensure_ascii=False) + "\n" for row in rows),
                    encoding="utf-8",
                )
            (data / ZH_JA).write_bytes(
                b'{"word": "\xff\xfe", "pinyin": "x", "gloss": ["\xe3\x81\x82"], "qa": "llm_ok"}\n'
            )
            violations = []
            for relative, validate in v.FILES:
                validate(data / relative, v.read_jsonl(data / relative, violations, relative), violations)
            kinds = [x.kind for x in violations]
            self.assertIn("invalid-utf8", kinds)


if __name__ == "__main__":
    unittest.main(verbosity=2)
