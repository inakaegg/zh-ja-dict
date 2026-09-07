#!/usr/bin/env python3
"""CC-CEDICT の1行を、語義と注記に分けて読む。

CC-CEDICT の行はこの形をしている。

    繁體 简体 [pin1 yin1] /語義1/語義2/…/

語義の中に、量詞・語感・参照といった注記が半構造で埋まっている。ここでは
**規則で確実に取れるものだけ**を型のある欄へ移し、取り切れないものは語義の
文へ残す。取りこぼしを黙って捨てないのが目的なので、判定は必ず保守側へ倒す。

    from cedict import parse_line
    entry = parse_line("上級 上级 [shang4 ji2] /higher authorities/CL:個|个[ge4]/")

Python 3.9 以上。標準ライブラリだけを使う。
"""

from __future__ import annotations

import pathlib
import re
from typing import Iterator, NamedTuple, Optional

LINE = re.compile(r"^(\S+) (\S+) \[([^\]]*)\] /(.*)/$")

# 括弧書きのうち、語感・地域・修辞を表すものだけを印にする。分野の名前
# （computing・medicine・bird species of China など3千種）は語義の一部として
# 文に残す。印にすると分類の体系を1つ抱えることになり、この辞書には要らない。
MISC_LABELS = {
    "coll.": "coll",
    "literary": "written",
    "fig.": "fig",
    "dialect": "dial",
    "Tw": "tw",
    "HK": "hk",
    "loanword": "loan",
    "slang": "slang",
    "Internet slang": "net",
    "Internet": "net",
    "idiom": "idiom",
    "old": "old",
    "archaic": "arch",
    "arch.": "arch",
    "onom.": "onom",
    "bound form": "bound",
    "derog.": "derog",
    "honorific": "honor",
    "polite": "polite",
    "humble": "humble",
    "vulgar": "vulgar",
    "euphemism": "euph",
    "jocular": "joc",
    "neologism": "neo",
    "formal": "formal",
    "Cantonese": "cantonese",
    "proverb": "proverb",
    "saying": "proverb",
}

# 語義まるごとが注記のときに使う頭。`variant of` は `old`・`erhua` の前置きを取る。
_VARIANT = re.compile(r"^(old |erhua |)variant of (.+)$")
_SEE = re.compile(r"^see (also )?(.+)$")
_ABBR = re.compile(r"^abbr\. for (.+)$")
_USED_IN = re.compile(r"^used in (.+)$")

# 参照先の書き方。`繁體|简体[pin1 yin1]`、`词[pin1 yin1]`、ピンイン無しもある。
_REF = re.compile(r"^([^|\[\],]+?)(?:\|([^|\[\],]+?))?(?:\[([^\]]*)\])?$")

_CL = re.compile(r"\s*\(?CL:\s*([^()/]+?)\s*\)?$")
# 参照の並びのつなぎ。読点のほかに `and` を使う。
_AND = re.compile(r"\s+and\s+")
# 参照先はブラケット付きか、漢字と `|`・中黒だけでできている。`abbr. for X, 説明` の
# ように参照の後ろへ英語の説明が続くので、これを見分けないと説明まで参照にしてしまう。
_CJK_ONLY = re.compile(r"^[⺀-⿿々〇㐀-䶿一-鿿"
                       r"豈-﫿\U00020000-\U0003FFFF|·〇]+$")
# 文の中に埋まった `語[読み]` の形。`繁體|简体[pin1 yin1]` にも当たる。
_REF_IN_TEXT = re.compile(r"[^\s\[\]|]+(?:\|[^\s\[\]|]+)?\[[^\]]*\]")
# 漢字が1つでもあるか。参照の前置きが説明なのか、別の参照なのかを見分けるのに使う。
_CJK_ANY = re.compile(r"[⺀-⿿々〇㐀-䶿一-鿿豈-﫿\U00020000-\U0003FFFF]")
_TAIWAN_PR = re.compile(r"^Taiwan pr\. \[([^\]]*)\]$")
_ALSO_PR = re.compile(r"^also pr\. \[([^\]]*)\]$")
_LOANWORD = re.compile(r"\((?:loanword,? (?:from|via) ([^)]+))\)")
_LEADING_LABEL = re.compile(r"^\(([^()]{1,40})\)\s*")
_TRAILING_LABEL = re.compile(r"\s*\(([^()]{1,40})\)$")


class Ref(NamedTuple):
    """参照先の語。`w` は簡体、`t` は繁体（簡体と違うときだけ）。"""

    w: str
    t: Optional[str]
    py: Optional[str]

    def as_dict(self) -> dict:
        out = {"w": self.w}
        if self.t:
            out["t"] = self.t
        if self.py:
            out["py"] = self.py
        return out


class Sense(NamedTuple):
    en: list           # 英語の語義。`;` で分けた断片
    misc: list         # MISC_LABELS の印
    cl: list           # 量詞（Ref）。parse_line が entry へ吸い上げるので、
                       # ここに残るのは解析の途中の値だけ
    variant_of: list   # {"kind": variant|old|erhua, **Ref}
    see_also: list     # {"kind": see|see_also|abbr|used_in, **Ref}
    lsource: list      # 借用元（`(loanword from Japanese 一番, ichiban)` の中身）
    s_inf: list        # 型のある欄へ移せなかった注記


class Entry(NamedTuple):
    trad: str
    simp: str
    pinyin: str        # CC-CEDICT のまま（数字つき）
    senses: list       # Sense
    cl: list           # 量詞（Ref）。語ごとの性質なので entry の欄に置く
    tw_pr: Optional[str]
    also_pr: Optional[str]


def _split_around_ref(text: str) -> tuple:
    """参照の前後に付いた英語の説明を切り離す。

    CC-CEDICT は参照先の語の**前にも後ろにも**英語の説明を置く。

    - 前だけ: `abbr. for Israel 以色列[Yi3 se4 lie4]`
    - 前と後ろ: `Hunan 湖南省[Hu2 nan2 Sheng3] provinces together`
    - 後ろが記号だけ: `octopi 章魚|章鱼[zhang1 yu2])`

    **見出しに空白は入らない**（CC-CEDICT の見出しは空白区切りの欄なので構造上
    あり得ない）ので、`語[読み]` の形を見つけてその前後を説明として切り離す。

    **前後どちらかに漢字が残るときは切り離さない。** そちらも参照である可能性が
    高く、片方だけ取ると残りを落とす（`傢伙|家伙[…] and 傢俱|家俱[…]`）。

    返り値は (前の説明, 参照先の部分, 後ろの説明)。説明が無ければ空文字。
    """
    text = text.strip()
    matched = _REF_IN_TEXT.search(text)
    if not matched:
        return "", text, ""
    prefix = text[: matched.start()].strip()
    suffix = text[matched.end():].strip()
    if _CJK_ANY.search(prefix) or _CJK_ANY.search(suffix):
        # 前後に漢字が残るなら、そちらも参照である可能性が高い。片方だけ取ると
        # 残りを落とすので、参照として読まずに文のまま残す。
        return "", text, ""
    return prefix, matched.group(0), suffix


def _parse_ref(text: str) -> Optional[Ref]:
    """`繁體|简体[pin1 yin1]` を読む。読めない形なら None を返す。

    **語の部分に空白があるものは受け付けない。** 受け付けると
    `Israel 以色列` がまるごと参照先の語になり、英語が配るデータへ混ざる。
    """
    matched = _REF.match(text.strip())
    if not matched:
        return None
    first, second, py = matched.groups()
    first = first.strip()
    if not first or " " in first or (second and " " in second.strip()):
        return None
    if second:
        # `繁體|简体` の並び。簡体が後ろ。同じ綴りなら繁体を持たない。
        simple = second.strip()
        return Ref(w=simple, t=(first if first != simple else None), py=(py or None))
    return Ref(w=first, t=None, py=(py or None))


def _split_outside_brackets(text: str, separator: str = ",") -> list:
    """ブラケットの外にある区切りだけで割る。

    成語のピンインは `[yi1 shi4 yi1 , er4 shi4 er4]` のように読点を含むので、
    素朴に割ると参照が壊れる。
    """
    parts = []
    depth = 0
    current = ""
    for char in text:
        if char == "[":
            depth += 1
        elif char == "]":
            depth = max(0, depth - 1)
        if char == separator and depth == 0:
            parts.append(current)
            current = ""
            continue
        current += char
    parts.append(current)
    return [part.strip() for part in parts if part.strip()]


def _looks_like_ref(text: str) -> bool:
    """参照先の語に見えるか。

    ブラケット付き（`词[ci2]`）か、漢字と `|` だけでできているものを参照とみなす。
    `Shanghai Automotive Industry Corp. (SAIC)` のような英語の説明を弾くための境目。
    **語の部分に空白があれば参照とみなさない**（見出しに空白は入らない）。
    """
    text = text.strip()
    if not text:
        return False
    if "[" in text and text.endswith("]"):
        return " " not in text[: text.rindex("[")].strip()
    return bool(_CJK_ONLY.match(text))


def _parse_refs(text: str) -> tuple:
    """読点で区切られた参照の並びを読む。読めなかった残りも返す。

    `abbr. for 上海汽車工業集團|上海汽车工业集团, Shanghai Automotive Industry Corp.`
    のように、参照のあとへ説明が続くことがある。読めた分だけ取り、残りは呼び手が
    `s_inf` へ回す。残りは断片のまま返す（1本に潰すと元の区切りが分からなくなる）。
    """
    refs = []
    rest = []
    for part in _split_reference_list(text):
        prefix, candidate, suffix = _split_around_ref(part)
        ref = _parse_ref(candidate) if _looks_like_ref(candidate) else None
        if ref:
            for note in (prefix, suffix):
                cleaned = note.strip(" ,;:()")
                if cleaned:
                    rest.append(cleaned)
            refs.append(ref)
        else:
            rest.append(part)
    return refs, rest


def _split_reference_list(text: str) -> list:
    """参照の並びを1つずつに割る。

    CC-CEDICT は参照を読点と `and` でつなぐ。
    `abbr. for Shanghai 上海[…], Shenzhen 深圳[…] and Hong Kong 香港[…]` のように、
    **1つの語義に3つ以上の参照が並ぶことがある**。読点だけで割ると `and` でつないだ
    分を落とし、`沪深港` が「上海の略」になってしまう。
    """
    parts = []
    for chunk in _split_outside_brackets(text):
        for piece in _AND.split(chunk):
            piece = piece.strip()
            if piece:
                parts.append(piece)
    return parts


def _take_labels(text: str) -> tuple[list, list, str]:
    """先頭と末尾の括弧書きから印を取る。表に無いものは文に残す。

    返り値は (印, 借用元, 残りの文)。
    """
    misc: list = []
    lsource: list = []

    for matched in _LOANWORD.finditer(text):
        lsource.append(matched.group(1).strip())
    if lsource:
        text = _LOANWORD.sub("", text).strip()
        misc.append("loan")

    while True:
        matched = _LEADING_LABEL.match(text)
        if not matched:
            break
        labels = _split_label(matched.group(1))
        if labels is None:
            break
        misc.extend(labels)
        text = text[matched.end():]

    while True:
        matched = _TRAILING_LABEL.search(text)
        if not matched:
            break
        labels = _split_label(matched.group(1))
        if labels is None:
            break
        misc.extend(labels)
        text = text[: matched.start()]

    return misc, lsource, text.strip()


def _split_label(inside: str) -> Optional[list]:
    """`Tw, HK` のように複数の印が1つの括弧に入ることがある。

    1つでも表に無い語が混じっていたら、括弧ごと文に残す（None を返す）。
    """
    parts = [part.strip() for part in inside.split(",")]
    codes = []
    for part in parts:
        if part not in MISC_LABELS:
            return None
        codes.append(MISC_LABELS[part])
    return codes


def _split_en(text: str) -> list:
    """語義の文を `;` で分ける。括弧の中の `;` では分けない。"""
    out = []
    depth = 0
    current = ""
    for char in text:
        if char in "([":
            depth += 1
        elif char in ")]":
            depth = max(0, depth - 1)
        if char == ";" and depth == 0:
            out.append(current.strip())
            current = ""
            continue
        current += char
    out.append(current.strip())
    return [part for part in out if part]


def parse_sense(raw: str) -> Sense:
    """語義の断片1つを読む。"""
    text = raw.strip()
    misc, lsource, text = _take_labels(text)
    cl: list = []
    variant_of: list = []
    see_also: list = []
    s_inf: list = []

    # 量詞は語義の末尾に置かれる（`…/CL:個|个[ge4]/` か `…question (CL:道[dao4])`）。
    matched = _CL.search(text)
    if matched:
        for part in _split_outside_brackets(matched.group(1)):
            ref = _parse_ref(part)
            if ref:
                cl.append(ref.as_dict())
            else:
                s_inf.append(f"CL:{part}")
        text = text[: matched.start()].strip()

    matched = _VARIANT.match(text)
    if matched:
        kind = {"": "variant", "old ": "old", "erhua ": "erhua"}[matched.group(1)]
        refs, rest = _parse_refs(matched.group(2))
        if refs and not rest:
            for ref in refs:
                variant_of.append({"kind": kind, **ref.as_dict()})
            text = ""
        return _finish(text, misc, cl, variant_of, see_also, lsource, s_inf)

    for pattern, kind in ((_SEE, None), (_ABBR, "abbr"), (_USED_IN, "used_in")):
        matched = pattern.match(text)
        if not matched:
            continue
        if kind is None:
            kind = "see_also" if matched.group(1) else "see"
            body = matched.group(2)
        else:
            body = matched.group(1)
        refs, rest = _parse_refs(body)
        if refs and not rest:
            for ref in refs:
                see_also.append({"kind": kind, **ref.as_dict()})
            text = ""
        break

    return _finish(text, misc, cl, variant_of, see_also, lsource, s_inf)


def _finish(text, misc, cl, variant_of, see_also, lsource, s_inf) -> Sense:
    return Sense(
        en=_split_en(text),
        misc=list(dict.fromkeys(misc)),
        cl=cl,
        variant_of=variant_of,
        see_also=see_also,
        lsource=lsource,
        s_inf=s_inf,
    )


def parse_line(line: str) -> Optional[Entry]:
    """CC-CEDICT の1行を読む。見出し行・空行なら None。"""
    line = line.rstrip("\n")
    if not line or line.startswith("#"):
        return None
    matched = LINE.match(line)
    if not matched:
        raise ValueError(f"CC-CEDICT の行の形に合わない: {line!r}")
    trad, simp, pinyin_text, body = matched.groups()

    senses = []
    measures: list = []
    tw_pr = None
    also_pr = None
    for raw in body.split("/"):
        text = raw.strip()
        if not text:
            continue
        found = _TAIWAN_PR.match(text)
        if found:
            tw_pr = found.group(1)
            continue
        found = _ALSO_PR.match(text)
        if found:
            also_pr = found.group(1)
            continue
        sense = parse_sense(text)
        # **量詞は entry の欄へ集める。** CC-CEDICT は `CL:個|个[ge4]` を独立した
        # 断片として置くだけで、どの語義に掛かるかを書いていない。語義へ結び付けると
        # 「to map out」のような動詞の語義へ量詞が付いてしまう。
        for measure in sense.cl:
            if measure not in measures:
                measures.append(measure)
        sense = sense._replace(cl=[])
        if _is_empty(sense):
            continue
        senses.append(sense)
    senses = _absorb_label_only(senses)
    return Entry(trad=trad, simp=simp, pinyin=pinyin_text, senses=senses,
                 cl=measures, tw_pr=tw_pr, also_pr=also_pr)


def _absorb_label_only(senses: list) -> list:
    """印だけの断片を隣の語義へ寄せる。

    CC-CEDICT は語全体に掛かる印を独立した断片として置くことがある
    （`態 态 [tai4] /(bound form)/appearance/shape/…/`）。そのままだと英語の語義文が
    無い語義ができてしまう。印は後ろに続く語義へ寄せ、後ろが無ければ前へ寄せる。
    印しか無い entry（`吜 吜 [chou3] /(onom.)/`）は、寄せる先が無いのでそのまま残す。
    """
    if len(senses) < 2:
        return senses
    out: list = []
    pending: list = []
    for sense in senses:
        if _is_label_only(sense):
            pending.append(sense)
            continue
        for note in pending:
            sense = _merge(sense, note)
        pending = []
        out.append(sense)
    for note in pending:
        if out:
            out[-1] = _merge(out[-1], note)
        else:
            out.append(note)
    return out


def _is_label_only(sense: Sense) -> bool:
    """文も参照も無く、印か借用元だけの断片か。"""
    return not sense.en and not sense.variant_of and not sense.see_also


def _merge(sense: Sense, note: Sense) -> Sense:
    """印だけの断片 `note` を `sense` へ寄せる。文と参照は `sense` のものが残る。"""
    return Sense(
        en=sense.en,
        misc=list(dict.fromkeys(note.misc + sense.misc)),
        cl=sense.cl + note.cl,
        variant_of=sense.variant_of,
        see_also=sense.see_also,
        lsource=note.lsource + sense.lsource,
        s_inf=note.s_inf + sense.s_inf,
    )


def _is_empty(sense: Sense) -> bool:
    return not any((sense.en, sense.misc, sense.cl, sense.variant_of,
                    sense.see_also, sense.lsource, sense.s_inf))


def read(path: pathlib.Path) -> Iterator[Entry]:
    """CC-CEDICT のファイルを頭から読む。"""
    with path.open(encoding="utf-8") as source:
        for line in source:
            entry = parse_line(line)
            if entry is not None:
                yield entry


def declared_entries(path: pathlib.Path) -> Optional[int]:
    """見出しの `#! entries=…` を読む。入力の取り違えを防ぐための照合に使う。"""
    with path.open(encoding="utf-8") as source:
        for line in source:
            if not line.startswith("#"):
                break
            matched = re.match(r"^#!\s*entries=(\d+)", line)
            if matched:
                return int(matched.group(1))
    return None
