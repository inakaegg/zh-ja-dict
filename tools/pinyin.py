#!/usr/bin/env python3
"""ピンインの2つの書き方を行き来する。

CC-CEDICT は数字で声調を書く（`shang4 ji2`、`nu:3`）。この辞書が配るのは
声調記号つき（`shàng jí`、`nǚ`）で、既存データもそちらで書かれている。
突き合わせと出力の両方で要るので、変換規則をここ1か所に置く。

Python 3.9 以上。標準ライブラリだけを使う。
"""

from __future__ import annotations

import re
import unicodedata

# 声調記号（結合文字）。1=マクロン, 2=アキュート, 3=カロン, 4=グレイヴ。
_MARKS = {1: "̄", 2: "́", 3: "̌", 4: "̀"}
_MARK_TO_TONE = {mark: tone for tone, mark in _MARKS.items()}
_DIAERESIS = "̈"

_VOWELS = "aeiouv"

# CC-CEDICT の1音節。`lu:4`・`r5`・`xx5`。大文字で始まる固有名詞もある。
_SYLLABLE = re.compile(r"^([a-zA-Z]+:?[a-zA-Z]*)([1-5])$")

# 空白を挟まずに音節を並べた書き方（`da4bu4fen4`）。2音節以上のときだけ割る。
_SYLLABLE_IN_RUN = re.compile(r"[a-zA-Z]+:?[a-zA-Z]*[1-5]")
_RUN_OF_SYLLABLES = re.compile(r"(?:[a-zA-Z]+:?[a-zA-Z]*[1-5]){2,}")

# 突き合わせの鍵から落とす記号。音節の区切りや軽声の印は資料ごとに揺れる。
_DROP_IN_KEY = " '’-·,˙"


def _mark_index(syllable: str) -> int:
    """声調記号をどの母音へ乗せるか。

    規則は「a か e があればそれ、無くて `ou` ならその o、どちらでもなければ
    最後の母音」。`v` は ü を表すので母音に数える。
    """
    lowered = syllable.lower()
    for target in ("a", "e"):
        position = lowered.find(target)
        if position >= 0:
            return position
    position = lowered.find("ou")
    if position >= 0:
        return position
    vowels = [i for i, char in enumerate(lowered) if char in _VOWELS]
    if vowels:
        return vowels[-1]
    # 母音を持たない音節（`m2`→`ḿ`、`ng2`→`ńg`、`hm`・`hng`）。声調記号は
    # 鼻音の字に乗る。ここを取りこぼすと `m2` と `m4` が同じ綴りになってしまう。
    for index, char in enumerate(lowered):
        if char in "mn":
            return index
    return -1


def _split_numbered(text: str) -> list[str]:
    """数字つきピンインを音節へ割る。中黒は音節として残す。

    成語の句読点（`yi1 shi4 yi1 , er4 shi4 er4`）は CC-CEDICT では前後を空白で
    挟んで書かれる。読点は前の音節にくっつけて返し、組み立て直したときに
    `yī shì yī, èr shì èr` になるようにする。
    """
    tokens: list[str] = []
    # ハイフンは音節のまとまりの区切り（`yi1mo2-yi1yang4`）。前の音節へ付けて返す。
    for token in re.split(r"\s+", text.replace("-", "- ")):
        if not token:
            continue
        if token.endswith("-") and len(token) > 1:
            tokens.extend(_split_numbered(token[:-1]))
            if tokens:
                tokens[-1] += "-"
            continue
        if token in (",", "，") and tokens:
            tokens[-1] += ","
        elif _RUN_OF_SYLLABLES.fullmatch(token):
            # 台湾の読みは `[da4bu4fen4]` のように音節を続けて書くことがある。
            # 割らずに渡すと声調の数字が残ったまま出てしまう。
            tokens.extend(_SYLLABLE_IN_RUN.findall(token))
        else:
            tokens.append(token)
    return tokens


def syllable_to_marks(token: str) -> str:
    """`shang4` を `shàng` にする。声調の数字が無い断片はそのまま返す。"""
    if token and token[-1] in ",-":
        return syllable_to_marks(token[:-1]) + token[-1]
    matched = _SYLLABLE.match(token)
    if not matched:
        return token.replace("u:", "ü").replace("U:", "Ü")
    body, tone = matched.group(1), int(matched.group(2))
    # `u:` を先に ü へ戻すと母音の位置がずれないので、記号を乗せる前に済ませる。
    body = body.replace("u:", "v").replace("U:", "V")
    if tone != 5:
        index = _mark_index(body)
        if index >= 0:
            body = body[: index + 1] + _MARKS[tone] + body[index + 1 :]
    body = body.replace("v", "ü").replace("V", "Ü")
    return unicodedata.normalize("NFC", body)


def to_marks(numbered: str, separator: str = " ") -> str:
    """数字つきピンイン全体を声調記号つきにする。

    >>> to_marks("shang4 ji2")
    'shàng jí'
    >>> to_marks("nu:3")
    'nǚ'
    >>> to_marks("yi1 ge5")
    'yī ge'
    """
    joined = separator.join(syllable_to_marks(token) for token in _split_numbered(numbered))
    # ハイフンは音節を続けて書く印なので、後ろに区切りを入れない。
    return joined.replace("-" + separator, "-") if separator else joined


def _decompose(marked: str) -> list[tuple[str, int]]:
    """声調記号つきピンインを (字, 声調) の並びへ解く。

    声調記号は母音の直後に来るので、直前に置いた字へ結び付ける。ü の分解記号は
    その場で `v` へ畳む（`nǚ` の分解は n, u, 分音記号, カロン の順）。
    """
    out: list[tuple[str, int]] = []
    for char in unicodedata.normalize("NFD", marked):
        if char in _MARK_TO_TONE:
            if out:
                out[-1] = (out[-1][0], _MARK_TO_TONE[char])
            continue
        if char == _DIAERESIS:
            if out and out[-1][0] in "uU":
                out[-1] = ("v" if out[-1][0] == "u" else "V", out[-1][1])
            continue
        if unicodedata.combining(char):
            continue
        out.append((char, 0))
    return out


def key(pinyin: str) -> str:
    """突き合わせの鍵。どちらの書き方から作っても同じ文字列になる。

    音節の区切りの空白・アポストロフィ・中黒、軽声の印（末尾の 5 と `˙`）は
    資料ごとに違うので落とす。大小文字も無視する（CC-CEDICT は固有名詞を
    大文字で始めるが、既存データは揃っていない）。声調は残す。

    **声調の数字は、声調記号が乗る母音の直後へ置く。**音節の末尾ではない。
    既存データの `Měiguó` のように音節の区切りが書かれていないピンインがあり、
    区切りを当てずに鍵を作れるようにするためである。

    >>> key("shàng jí") == key("shang4 ji2")
    True
    >>> key("yī ge") == key("yi1 ge5")
    True
    """
    marked = to_marks(pinyin) if is_numbered(pinyin) else pinyin
    out = []
    for char, tone in _decompose(marked):
        if char in _DROP_IN_KEY:
            continue
        out.append(char.lower())
        if tone:
            out.append(str(tone))
    return "".join(out)


def toneless_key(pinyin: str) -> str:
    """声調を落とした鍵。声調だけが違う組を見つけるのに使う。"""
    return re.sub(r"[1-4]", "", key(pinyin))


def is_numbered(pinyin: str) -> bool:
    """CC-CEDICT 式（数字つき）に見えるか。"""
    # `nu:3` のように母音の代わりに `:` が来る音節があるので、直前の字に `:` も許す。
    return bool(re.search(r"[a-zA-Z:][1-5](?:$|[\s·])", pinyin + " "))


# 声調が変わる音節。`一` は yī/yí/yì、`不` は bù/bú と読みが変わる。
SANDHI_SYLLABLES = ("yi", "bu")


def sandhi_pattern(numbered: str):
    """CC-CEDICT の読みから、`一`・`不` の声調だけを自由にした照合の型を作る。

    旧版は変調を書き込んだ読みを持ち（`一点一滴 yìdiǎn yìdī`）、CC-CEDICT は
    変調前を書く（`yi1 dian3 yi1 di1`）。**変えてよいのはこの2音節の声調だけ**で、
    ほかの音節の声調や軽声の違いは別の読みなので、同じものとして扱ってはいけない。

    >>> bool(sandhi_pattern("yi1 dian3 yi1 di1").match(key("yìdiǎn yìdī")))
    True
    >>> bool(sandhi_pattern("yi1 chang2 kong1").match(key("yī chǎng kōng")))
    False
    """
    return _sandhi_regex([key(token) for token in _split_numbered(numbered)])


def sandhi_pattern_from_marks(marked: str):
    """声調記号つきの読みから同じ型を作る。配るデータ側はこちらの書き方。"""
    return _sandhi_regex(re.findall(r"[a-z]+[1-4]?", key(marked)))


def _sandhi_regex(syllables: list):
    """**先頭の音節が `一`・`不` のときだけ**、その声調を自由にした型を作る。

    ほかの音節や、先頭以外の `一`・`不` の違いは別の読みとして扱う。緩めるほど
    旧版の読みが黙って消えるので、迷ったら分けるほうへ倒す。
    """
    parts = []
    for index, piece in enumerate(syllables):
        base = re.sub(r"[1-5]", "", piece)
        if index == 0 and base in SANDHI_SYLLABLES:
            parts.append(re.escape(base) + r"[1-4]?")
        else:
            parts.append(re.escape(piece))
    return re.compile("^" + "".join(parts) + "$")
