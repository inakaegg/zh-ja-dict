#!/usr/bin/env python3
"""tools/cedict.py の試験。

例はすべて CC-CEDICT 2026-09-05 版の実際の行から取っている。
"""

from __future__ import annotations

import gzip
import os
import pathlib
import sys
import unittest

sys.path.insert(0, str(pathlib.Path(__file__).resolve().parent))
import cedict  # noqa: E402


def senses(line: str):
    return cedict.parse_line(line).senses


class Line(unittest.TestCase):
    def test_見出し行と空行はNone(self):
        self.assertIsNone(cedict.parse_line("# CC-CEDICT\n"))
        self.assertIsNone(cedict.parse_line("#! entries=124985\n"))
        self.assertIsNone(cedict.parse_line("\n"))

    def test_形が合わなければ例外(self):
        with self.assertRaises(ValueError):
            cedict.parse_line("上級 上级 shang4 ji2 /higher authorities/")

    def test_簡体と繁体と読み(self):
        entry = cedict.parse_line("上級 上级 [shang4 ji2] /higher authorities/")
        self.assertEqual(entry.trad, "上級")
        self.assertEqual(entry.simp, "上级")
        self.assertEqual(entry.pinyin, "shang4 ji2")


class Splitting(unittest.TestCase):
    def test_セミコロンで語義の断片を分ける(self):
        result = senses("3D打印 3D打印 [san1 D da3 yin4] /to 3D print; 3D printing/")
        self.assertEqual(result[0].en, ["to 3D print", "3D printing"])

    def test_括弧の中のセミコロンでは分けない(self):
        result = senses("X X [X] /thing (a; b); other/")
        self.assertEqual(result[0].en, ["thing (a; b)", "other"])

    def test_スラッシュで語義を分ける(self):
        result = senses("上級 上级 [shang4 ji2] /higher authorities/superiors/")
        self.assertEqual(len(result), 2)


class Measure(unittest.TestCase):
    """量詞は entry の欄に集める。

    CC-CEDICT は `CL:個|个[ge4]` を独立した断片として置くだけで、どの語義に掛かるかを
    書いていない。語義へ結び付けると、`计划` の「to map out」のような動詞の語義へ
    量詞が付いてしまう。
    """

    def test_量詞はentryの欄へ集める(self):
        entry = cedict.parse_line(
            "上級 上级 [shang4 ji2] /higher authorities/superiors/CL:個|个[ge4]/")
        self.assertEqual(entry.cl, [{"w": "个", "t": "個", "py": "ge4"}])
        self.assertEqual(len(entry.senses), 2)
        self.assertEqual([s.cl for s in entry.senses], [[], []])

    def test_量詞は複数取れる(self):
        entry = cedict.parse_line("汽車 汽车 [qi4 che1] /car/CL:輛|辆[liang4],部[bu4]/")
        self.assertEqual(entry.cl,
                         [{"w": "辆", "t": "輛", "py": "liang4"}, {"w": "部", "py": "bu4"}])

    def test_文の末尾の括弧に入った量詞も取る(self):
        entry = cedict.parse_line(
            "偏題 偏题 [pian1 ti2] /obscure question; catch question (CL:道[dao4])/")
        self.assertEqual(entry.senses[0].en, ["obscure question", "catch question"])
        self.assertEqual(entry.cl, [{"w": "道", "py": "dao4"}])

    def test_量詞だけの断片は語義を増やさない(self):
        # 中ほどに来ることもある。`/afternoon/CL:個|个[ge4]/p.m./`
        entry = cedict.parse_line("下午 下午 [xia4 wu3] /afternoon/CL:個|个[ge4]/p.m./")
        self.assertEqual([s.en for s in entry.senses], [["afternoon"], ["p.m."]])
        self.assertEqual(entry.cl, [{"w": "个", "t": "個", "py": "ge4"}])

    def test_動詞の語義へ量詞を付けない(self):
        entry = cedict.parse_line(
            "計劃 计划 [ji4 hua4] /plan/to plan/to map out/CL:個|个[ge4],項|项[xiang4]/")
        self.assertEqual([s.en for s in entry.senses],
                         [["plan"], ["to plan"], ["to map out"]])
        self.assertEqual([s.cl for s in entry.senses], [[], [], []])
        self.assertEqual(len(entry.cl), 2)


class Readings(unittest.TestCase):
    def test_台湾の読みはentryの欄へ(self):
        entry = cedict.parse_line("下頦 下颏 [xia4 ke1] /chin/Taiwan pr. [xia4hai2]/")
        self.assertEqual(entry.tw_pr, "xia4hai2")
        self.assertEqual([s.en for s in entry.senses], [["chin"]])

    def test_別の読みもentryの欄へ(self):
        entry = cedict.parse_line("X X [x1] /thing/also pr. [x2]/")
        self.assertEqual(entry.also_pr, "x2")
        self.assertEqual(len(entry.senses), 1)


class Labels(unittest.TestCase):
    def test_語感の印を取る(self):
        result = senses("CP值 CP值 [C P zhi2] /(Tw) value for money; bang for your buck/")
        self.assertEqual(result[0].misc, ["tw"])
        self.assertEqual(result[0].en, ["value for money", "bang for your buck"])

    def test_印が続けて付く(self):
        result = senses("QR扣 QR扣 [Q R kou4] /(Tw) (loanword) QR code/")
        self.assertEqual(result[0].misc, ["tw", "loan"])
        self.assertEqual(result[0].en, ["QR code"])

    def test_末尾の印も取る(self):
        result = senses("Q Q [Q] /cute (loanword)/")
        self.assertEqual(result[0].misc, ["loan"])
        self.assertEqual(result[0].en, ["cute"])

    def test_1つの括弧に複数の印(self):
        result = senses("X X [x1] /(Tw, HK) thing/")
        self.assertEqual(result[0].misc, ["tw", "hk"])

    def test_表に無い括弧は文に残す(self):
        # 分野の名前は3千種あるので印にしない。文の一部として残す。
        result = senses("白鶴 白鹤 [bai2 he4] /(bird species of China) Siberian crane/")
        self.assertEqual(result[0].misc, [])
        self.assertEqual(result[0].en, ["(bird species of China) Siberian crane"])

    def test_表に無い語が混じる括弧はまるごと文に残す(self):
        result = senses("X X [x1] /(Tw, biology) thing/")
        self.assertEqual(result[0].misc, [])
        self.assertEqual(result[0].en, ["(Tw, biology) thing"])

    def test_litとliteraryを混同しない(self):
        # `(literary)` は書面語、`(lit.)` は成語の字面の意味。別物なので分ける。
        self.assertEqual(senses("X X [x1] /(literary) thing/")[0].misc, ["written"])
        result = senses("X X [x1] /(lit.) thing/")
        self.assertEqual(result[0].misc, [])
        self.assertEqual(result[0].en, ["(lit.) thing"])


class LabelOnlyFragment(unittest.TestCase):
    """印だけの断片は語義を増やさず、隣の語義へ寄せる。"""

    def test_先頭の印は後ろの語義へ寄せる(self):
        entry = cedict.parse_line(
            "態 态 [tai4] /(bound form)/appearance/shape/(grammar) voice/")
        self.assertEqual([s.en for s in entry.senses],
                         [["appearance"], ["shape"], ["(grammar) voice"]])
        self.assertEqual(entry.senses[0].misc, ["bound"])

    def test_末尾の印は前の語義へ寄せる(self):
        entry = cedict.parse_line(
            'UP主 UP主 [U P zhu3] /(Internet slang) uploader/pronounced [a4 pu5 zhu3]/'
            '(loanword from Japanese うｐ主, "upunushi")/')
        self.assertEqual([s.en for s in entry.senses],
                         [["uploader"], ["pronounced [a4 pu5 zhu3]"]])
        self.assertEqual(entry.senses[1].misc, ["loan"])
        self.assertEqual(entry.senses[1].lsource, ['Japanese うｐ主, "upunushi"'])

    def test_寄せる先が無ければそのまま残す(self):
        # `吜 吜 [chou3] /(onom.)/` は印しか無い。語義0の entry を作らない。
        entry = cedict.parse_line("吜 吜 [chou3] /(onom.)/")
        self.assertEqual(len(entry.senses), 1)
        self.assertEqual(entry.senses[0].en, [])
        self.assertEqual(entry.senses[0].misc, ["onom"])


class Loanword(unittest.TestCase):
    def test_借用元を取る(self):
        result = senses('PUA PUA [P U A] /a person who does so (loanword from "pickup artist")/')
        self.assertEqual(result[0].lsource, ['"pickup artist"'])
        self.assertEqual(result[0].misc, ["loan"])
        self.assertEqual(result[0].en, ["a person who does so"])

    def test_借用元が言語名のこともある(self):
        result = senses("X X [x1] /thing (loanword from Japanese 一番, ichiban)/")
        self.assertEqual(result[0].lsource, ["Japanese 一番, ichiban"])


class References(unittest.TestCase):
    def test_異体字(self):
        result = senses("女 女 [ru3] /old variant of 汝[ru3]/")
        self.assertEqual(result[0].en, [])
        self.assertEqual(result[0].variant_of,
                         [{"kind": "old", "w": "汝", "py": "ru3"}])

    def test_儿化の異体字(self):
        result = senses("X X [x1] /erhua variant of 詞|词[ci2]/")
        self.assertEqual(result[0].variant_of,
                         [{"kind": "erhua", "w": "词", "t": "詞", "py": "ci2"}])

    def test_参照(self):
        result = senses("K金 K金 [K jin1] /see 開金|开金[kai1 jin1]/")
        self.assertEqual(result[0].see_also,
                         [{"kind": "see", "w": "开金", "t": "開金", "py": "kai1 jin1"}])

    def test_see_alsoとseeを分ける(self):
        result = senses("X X [x1] /see also 詞|词[ci2]/")
        self.assertEqual(result[0].see_also[0]["kind"], "see_also")

    def test_略語(self):
        result = senses("B超 B超 [B chao1] /abbr. for B型超聲|B型超声[B xing2 chao1 sheng1]/")
        self.assertEqual(result[0].see_also[0]["kind"], "abbr")
        self.assertEqual(result[0].see_also[0]["w"], "B型超声")

    def test_略語のあとに英語の説明が続けば構造化しない(self):
        result = senses("上汽 上汽 [Shang4 qi4] /abbr. for 上海汽車工業集團|上海汽车工业集团, "
                        "Shanghai Automotive Industry Corp. (SAIC)/")
        self.assertEqual(result[0].see_also, [])
        self.assertEqual(len(result[0].en), 1)

    def test_この字が使われる語(self):
        result = senses("㐖 㐖 [Xie2] /used in 㐖毒[Xie2 du2]/")
        self.assertEqual(result[0].see_also,
                         [{"kind": "used_in", "w": "㐖毒", "py": "Xie2 du2"}])

    def test_英語の説明が付いた参照は構造化しない(self):
        # `abbr. for Israel 以色列[...]` は説明が残るので文のまま置く。
        # 部分的に取り出すと `Israel 以色列` が参照先の語になったり、
        # 並んだ参照を取りこぼしたりする。
        result = senses("以 以 [Yi3] /abbr. for Israel 以色列[Yi3 se4 lie4]/")
        self.assertEqual(result[0].see_also, [])
        self.assertEqual(result[0].en, ["abbr. for Israel 以色列[Yi3 se4 lie4]"])

    def test_andでつないだ参照は両方読む(self):
        # `used in X and Y` の形。片方だけ取ると残りを落とすので、両方を読む。
        result = senses("家 家 [jia1] /used in 傢伙|家伙[jia1 huo5] and 傢俱|家俱[jia1 ju4]/")
        self.assertEqual([r["w"] for r in result[0].see_also], ["家伙", "家俱"])
        self.assertEqual(result[0].en, [])

    def test_前置きに漢字があれば参照として読まない(self):
        # 読点や `and` で割ったあとも漢字混じりの前置きが残る形は、参照として
        # 読まずに文のまま残す（取りこぼしを黙って捨てないため）。
        result = senses("X X [x1] /see also: 真分數|真分数[zhen1 fen1 shu4] の説明/")
        self.assertEqual(result[0].see_also, [])

    def test_参照先の語に空白を入れない(self):
        for line in ("以 以 [Yi3] /abbr. for Israel 以色列[Yi3 se4 lie4]/",
                     "斗 斗 [Dou3] /see the Big Dipper 北斗星[Bei3 dou3 xing1]/",
                     "以 以 [Yi3] /abbr. for 以色列[Yi3 se4 lie4]/"):
            for sense in senses(line):
                for ref in sense.see_also + sense.variant_of:
                    self.assertNotIn(" ", ref["w"])
                    self.assertNotIn(" ", ref.get("t") or "")

    def test_読点でつないだ参照を全部読む(self):
        result = senses("X X [x1] /abbr. for 上海[Shang4 hai3], 深圳[Shen1 zhen4] "
                        "and 香港[Xiang1 gang3]/")
        self.assertEqual([r["w"] for r in result[0].see_also], ["上海", "深圳", "香港"])

    def test_andでつないだ参照も読む(self):
        result = senses("嚓 嚓 [cha1] /used in 咔嚓[ka1 cha1], 喀嚓[ka1 cha1] and 啪嚓[pa1 cha1]/")
        self.assertEqual([r["w"] for r in result[0].see_also], ["咔嚓", "喀嚓", "啪嚓"])

    def test_成語の読点を含む参照を壊さない(self):
        # 成語のピンインは `[yi1 shi4 yi1 , er4 shi4 er4]` のように読点を含む。
        result = senses("X X [x1] /see 一是一，二是二[yi1 shi4 yi1 , er4 shi4 er4]/")
        self.assertEqual(result[0].see_also[0]["py"], "yi1 shi4 yi1 , er4 shi4 er4")


class OnlyWhenFullyConsumed(unittest.TestCase):
    """参照を構造化するのは、文が参照の並びだけで残らず説明できたときに限る。

    部分的に取り出すと、取りこぼし（`巴` の `巴基斯坦`・`巴西`）と過剰抽出
    （`不误` の `照`）のどちらも起きる。少しでも説明が残るなら文のまま残し、
    訳は LLM が全体を読んで作る。
    """

    def test_説明が続く形は参照にしない(self):
        line = ("不誤 不误 [bu4 wu4] /used in expressions of the form 照[zhao4] + {verb} + "
                "不誤|不误[bu4 wu4], in which 照[zhao4] means \"as before\"/")
        result = senses(line)
        self.assertEqual(result[0].see_also, [])
        self.assertEqual(len(result[0].en), 1)
        self.assertIn("in which", result[0].en[0])

    def test_参照のあとに説明が残る形も参照にしない(self):
        result = senses("楚 楚 [Chu3] /abbr. for Hubei 湖北省[Hu2 bei3 Sheng3] and "
                        "Hunan 湖南省[Hu2 nan2 Sheng3] provinces together/")
        self.assertEqual(result[0].see_also, [])
        self.assertEqual(len(result[0].en), 1)

    def test_参照だけなら構造化する(self):
        result = senses("以 以 [Yi3] /abbr. for 以色列[Yi3 se4 lie4]/")
        self.assertEqual([r["w"] for r in result[0].see_also], ["以色列"])
        self.assertEqual(result[0].en, [])

    def test_参照が並ぶだけなら構造化する(self):
        result = senses("嚓 嚓 [cha1] /used in 咔嚓[ka1 cha1], 喀嚓[ka1 cha1] and 啪嚓[pa1 cha1]/")
        self.assertEqual([r["w"] for r in result[0].see_also], ["咔嚓", "喀嚓", "啪嚓"])
        self.assertEqual(result[0].en, [])


class FullFile(unittest.TestCase):
    """CC-CEDICT の実物を渡されたときだけ走る全件の検査。

    元データはこのリポジトリに含めないので、置き場所を環境変数で受け取る。

        ZH_JA_DICT_CEDICT=<cedict_1_0_ts_utf-8_mdbg.txt.gz> python3 -m unittest ...
    """

    def test_宣言されたentry数と一致する(self):
        location = os.environ.get("ZH_JA_DICT_CEDICT")
        if not location:
            self.skipTest("ZH_JA_DICT_CEDICT が指定されていない")
        source = pathlib.Path(location)
        if not source.exists():
            self.skipTest(f"CC-CEDICT が見つからない: {source}")
        opener = gzip.open if source.suffix == ".gz" else open
        count = 0
        with opener(source, "rt", encoding="utf-8") as handle:
            for line in handle:
                if cedict.parse_line(line) is not None:
                    count += 1
        self.assertEqual(count, 124985)


if __name__ == "__main__":
    unittest.main()
