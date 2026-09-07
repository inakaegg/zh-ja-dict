#!/usr/bin/env python3
"""tools/pinyin.py の試験。"""

from __future__ import annotations

import pathlib
import sys
import unittest

sys.path.insert(0, str(pathlib.Path(__file__).resolve().parent))
import pinyin  # noqa: E402


class ToMarks(unittest.TestCase):
    def test_声調記号の位置(self):
        # a・e があればそこ、無くて ou ならその o、どちらでもなければ最後の母音。
        self.assertEqual(pinyin.to_marks("shang4 ji2"), "shàng jí")
        self.assertEqual(pinyin.to_marks("hao3"), "hǎo")
        self.assertEqual(pinyin.to_marks("gou3"), "gǒu")
        self.assertEqual(pinyin.to_marks("gui4"), "guì")
        self.assertEqual(pinyin.to_marks("liu2"), "liú")
        self.assertEqual(pinyin.to_marks("xue2"), "xué")

    def test_軽声は記号を付けない(self):
        self.assertEqual(pinyin.to_marks("yi1 ge5"), "yī ge")
        self.assertEqual(pinyin.to_marks("dong1 xi5"), "dōng xi")

    def test_ウムラウトのu(self):
        self.assertEqual(pinyin.to_marks("nu:3"), "nǚ")
        self.assertEqual(pinyin.to_marks("lu:4"), "lǜ")
        self.assertEqual(pinyin.to_marks("nu:3 hai2 zi5"), "nǚ hái zi")

    def test_大文字の固有名詞を保つ(self):
        self.assertEqual(pinyin.to_marks("Mei3 guo2"), "Měi guó")
        self.assertEqual(pinyin.to_marks("Qi1 xi1 jie2"), "Qī xī jié")

    def test_数字だけの音節や記号はそのまま(self):
        # `11 Qu1`・`san1 C` のように数字やラテン字が混じる見出しがある。
        self.assertEqual(pinyin.to_marks("11 Qu1"), "11 Qū")
        self.assertEqual(pinyin.to_marks("san1 C"), "sān C")

    def test_成語の読点は前の音節へ付ける(self):
        # CC-CEDICT は読点の前後を空白で挟む。そのまま繋ぐと `yī, èr` にならない。
        self.assertEqual(pinyin.to_marks("yi1 shi4 yi1 , er4 shi4 er4"),
                         "yī shì yī, èr shì èr")

    def test_人名の中黒を残す(self):
        self.assertEqual(pinyin.to_marks("Jia1 li4 lu:e4 · Jia1 li4 lei2"),
                         "Jiā lì lüè · Jiā lì léi")

    def test_母音を持たない音節(self):
        # `m`・`n`・`ng` は鼻音の字に声調記号が乗る。取りこぼすと `m2` と `m4` が
        # 同じ綴りになり、別の entry が重複と判定される。
        self.assertEqual(pinyin.to_marks("m2"), "ḿ")
        self.assertEqual(pinyin.to_marks("ng2"), "ńg")
        self.assertNotEqual(pinyin.to_marks("m2"), pinyin.to_marks("m4"))
        self.assertEqual(pinyin.to_marks("hng5"), "hng")

    def test_ハイフンは後ろの音節へ続ける(self):
        self.assertEqual(pinyin.to_marks("yi1mo2-yi1yang4"), "yī mó-yī yàng")

    def test_区切りを変えられる(self):
        self.assertEqual(pinyin.to_marks("shang4 ji2", separator=""), "shàngjí")

    def test_合成済みの文字を返す(self):
        # NFC でないと、既存データと文字列として一致しない。
        import unicodedata
        marked = pinyin.to_marks("nu:3")
        self.assertEqual(marked, unicodedata.normalize("NFC", marked))


class Key(unittest.TestCase):
    def test_両方の書き方から同じ鍵(self):
        self.assertEqual(pinyin.key("shàng jí"), pinyin.key("shang4 ji2"))
        self.assertEqual(pinyin.key("nǚ hái zi"), pinyin.key("nu:3 hai2 zi5"))
        self.assertEqual(pinyin.key("Měi guó"), pinyin.key("Mei3 guo2"))

    def test_音節の区切りを無視する(self):
        # 既存データは `Měiguó` と `ài hào` が混在する（README の既知の限界）。
        self.assertEqual(pinyin.key("Měiguó"), pinyin.key("Měi guó"))
        self.assertEqual(pinyin.key("ài hào"), pinyin.key("àihào"))
        self.assertEqual(pinyin.key("xī'ān"), pinyin.key("xi1 an1"))

    def test_軽声の印の揺れを無視する(self):
        self.assertEqual(pinyin.key("yī ge"), pinyin.key("yi1 ge5"))
        self.assertEqual(pinyin.key("guī ˙nü"), pinyin.key("guī nü"))

    def test_大小文字を無視する(self):
        self.assertEqual(pinyin.key("Yáng"), pinyin.key("yáng"))

    def test_声調は残す(self):
        self.assertNotEqual(pinyin.key("yī gè"), pinyin.key("yí gè"))

    def test_声調を落とした鍵(self):
        # 一・不の変調は既存データにだけ入っている（`一个 yí gè` / CC-CEDICT `yi1 ge5`）。
        self.assertEqual(pinyin.toneless_key("yí gè"), pinyin.toneless_key("yi1 ge5"))
        # 声調以外が違えば、落としても別物のままでなければ困る。
        self.assertNotEqual(pinyin.toneless_key("yí gè"), pinyin.toneless_key("yí gù"))

    def test_鍵は声調記号の位置に数字を置く(self):
        # 音節の区切りが書かれていないピンインでも鍵を作れるようにするための形。
        self.assertEqual(pinyin.key("shang4 ji2"), "sha4ngji2")


class Sandhi(unittest.TestCase):
    """`一`・`不` の変調だけを自由にした照合。

    旧版は変調を書き込んだ読みを持ち、CC-CEDICT は変調前を書く。認めるのは
    **先頭の音節が `一`・`不` のときのその声調だけ**で、ほかの違いは別の読みとする。
    """

    def test_先頭の一と不の声調は自由(self):
        self.assertTrue(pinyin.sandhi_pattern("yi1 lu4").match(pinyin.key("yí lù")))
        self.assertTrue(pinyin.sandhi_pattern("bu4 shi4").match(pinyin.key("bú shì")))

    def test_ほかの音節の声調は自由でない(self):
        # `一场空` の chǎng／cháng は別の読み。同じものにすると旧版の訳が消える。
        self.assertFalse(
            pinyin.sandhi_pattern("yi1 chang2 kong1").match(pinyin.key("yī chǎng kōng")))
        self.assertFalse(
            pinyin.sandhi_pattern("bu4 zu2 chi3 shu4").match(pinyin.key("bù zú chǐ shǔ")))

    def test_軽声の違いも別の読みとする(self):
        self.assertFalse(pinyin.sandhi_pattern("yi1 ge5").match(pinyin.key("yí gè")))
        self.assertFalse(pinyin.sandhi_pattern("bu4 an1 fen5").match(pinyin.key("bù ān fèn")))

    def test_先頭以外の一と不は自由でない(self):
        self.assertFalse(pinyin.sandhi_pattern("ke3 bu5").match(pinyin.key("kěbù")))

    def test_声調記号つきからも同じ型を作れる(self):
        self.assertTrue(pinyin.sandhi_pattern_from_marks("yī lù").match(pinyin.key("yí lù")))
        self.assertFalse(
            pinyin.sandhi_pattern_from_marks("yī cháng kōng").match(pinyin.key("yī chǎng kōng")))


class IsNumbered(unittest.TestCase):
    def test_見分ける(self):
        self.assertTrue(pinyin.is_numbered("shang4 ji2"))
        self.assertTrue(pinyin.is_numbered("nu:3"))
        self.assertFalse(pinyin.is_numbered("shàng jí"))
        self.assertFalse(pinyin.is_numbered("Měiguó"))


if __name__ == "__main__":
    unittest.main()
