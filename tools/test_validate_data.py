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
POLY = "zh-ja/polyphonic.jsonl"
JA_ZH = "ja-zh/glosses.jsonl"

CLEAN = {
    ZH_JA: [
        {"word": "美国", "pinyin": "Měiguó", "gloss": ["アメリカ"], "qa": "machine_backed"},
        {"word": "幖", "pinyin": "biāo", "gloss": [], "unsure": True, "qa": "llm_ok"},
    ],
    POLY: [
        {"word": "似", "senses": [{"pinyin": "sì", "gloss": ["似ている"]}, {"pinyin": "shì", "gloss": ["…のようだ"]}]},
        {"word": "乗", "senses": [], "unsure": True},
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
        kinds, _ = run(with_change(POLY, 0, {"word": "砉", "senses": [{"pinyin": "huā", "gloss": ["さっと"], "unsure": False}]}))
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

    def test_見出し語の重複を報告する(self):
        rows = {key: [dict(row) for row in value] for key, value in CLEAN.items()}
        rows[ZH_JA].append({"word": "美国", "pinyin": "Měiguó", "gloss": ["米国"], "qa": "llm_ok"})
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
        change = {"word": "衣锦荣归", "senses": [{"pinyin": "yījǐnr645guī", "gloss": ["錦を飾って帰る"]}]}
        kinds, _ = run(with_change(POLY, 0, change))
        self.assertIn("bad-pinyin", kinds)

    def test_ピンイン欄の全角数字を報告する(self):
        # ASCII の数字だけを確認済みtokenとして読み飛ばすので、全角 `１`（U+FF11）は残る。
        change = {"word": "衣锦荣归", "senses": [{"pinyin": "yījǐn１guī", "gloss": ["錦を飾って帰る"]}]}
        kinds, _ = run(with_change(POLY, 0, change))
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


class ItemCountTest(unittest.TestCase):
    def test_glossが上限を超えたら報告する(self):
        change = {"word": "美国", "pinyin": "Měiguó", "gloss": ["ア", "メ", "リ", "カ"], "qa": "llm_ok"}
        kinds, _ = run(with_change(ZH_JA, 0, change))
        self.assertIn("too-many-items", kinds)

    def test_zhが上限を超えたら報告する(self):
        change = {"word": "明白", "zh": [{"s": s, "pinyin": "x"} for s in ("明白", "清楚", "清晰", "了解")]}
        kinds, _ = run(with_change(JA_ZH, 0, change))
        self.assertIn("too-many-items", kinds)

    def test_sensesが上限を超えたら報告する(self):
        change = {"word": "似", "senses": [{"pinyin": p, "gloss": ["訳"]} for p in ("sì", "shì", "shí", "sī")]}
        kinds, _ = run(with_change(POLY, 0, change))
        self.assertIn("too-many-items", kinds)

    def test_上限ちょうどは違反にしない(self):
        change = {"word": "美国", "pinyin": "Měiguó", "gloss": ["ア", "メ", "リ"], "qa": "llm_ok"}
        kinds, _ = run(with_change(ZH_JA, 0, change))
        self.assertNotIn("too-many-items", kinds)


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
