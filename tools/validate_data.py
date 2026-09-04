#!/usr/bin/env python3
"""zh-ja-dict のデータファイルを全件検証する。

schema 2（1行 = (語, 読み)）を対象とする。

使い方:
    python3 tools/validate_data.py              # 検証。違反が1件でもあれば終了コード1
    python3 tools/validate_data.py --counts     # 変種別の件数だけ出す。常に終了コード0
    python3 tools/validate_data.py --max-report 50

Python 3.9 以上。標準ライブラリだけを使う。
"""

from __future__ import annotations

import argparse
import json
import pathlib
import re
import sys
import unicodedata
from collections import Counter

REPO_ROOT = pathlib.Path(__file__).resolve().parent.parent
DEFAULT_DATA_DIR = REPO_ROOT / "data"
ALLOWLIST_DIR = REPO_ROOT / "tools"

SCHEMA_VERSION = 2

QA_VALUES = {"machine_backed", "llm_ok", "llm_fixed", "human_reviewed", "unchecked"}

# 退役したキー。schema 2 では意味を失った（`hsk2`/`hsk3` へ分けた）。
# 1件でもあれば古い形式のデータなので、未知のキーではなく専用の違反として報告する。
RETIRED_KEYS = {"hsk"}

# 品詞。上流（complete-hsk-vocabulary）の略号をそのまま使う。
# `interjection` だけ英単語だが、上流の `senses[].pos` に実在する（`哦`・`嗯`）。
POS_VALUES = frozenset(
    "Mg Rg a ad an b c cc d e f g h k l m mq n nr ns nt nz o p q qt qv r s t tg u v vn y z".split()
)
READING_POS_VALUES = POS_VALUES | {"interjection"}

# 大小文字だけが違う組のうち、人が「本当に別の語」と判定した語（TASK.md D5）。
CASE_KEEP = {"包头", "酂"}

# 訳・候補・読みの件数に上限は設けない。形式としては「空でない・重複がない」だけを見る。
# 生成のときは1〜3件を目安にしたが、それは生成方針であって形式の制約ではない。

# HSK の級の範囲。版ごとに上限が違う（2.0 は6級まで、3.0 は7級まで）。
HSK2_MIN_LEVEL, HSK2_MAX_LEVEL = 1, 6
HSK3_MIN_LEVEL, HSK3_MAX_LEVEL = 1, 7

# 漢字（CJK統合漢字と拡張面、互換漢字）。中国語の元素名には拡張B・C面の字が使われる。
HAN_RANGES = (
    (0x3400, 0x4DBF),    # 拡張A
    (0x4E00, 0x9FFF),    # 統合漢字
    (0xF900, 0xFAFF),    # 互換漢字
    (0x20000, 0x2A6DF),  # 拡張B
    (0x2A700, 0x2EBEF),  # 拡張C〜F
    (0x2F800, 0x2FA1F),  # 互換漢字補助
    (0x30000, 0x323AF),  # 拡張G・H
)
KANA_RANGES = ((0x3041, 0x30FF), (0x31F0, 0x31FF))
CYRILLIC_RANGES = ((0x0400, 0x04FF), (0x0500, 0x052F))

# ピンイン欄に置いてよい文字。ここに無い文字はすべて違反にする。
#
# 「キリル文字を弾く」ではなく「使ってよい文字だけ通す」向きにしてある。
# 実データには、キリル文字の `т`（U+0442）がラテン文字の `t` の位置に入っていた例や、
# IPA の `ɡ`（U+0261）が `g` の代わりに入っていた例がある。どちらも見た目で気づけない。
# 弾く側を列挙する方式では、次に別のスクリプトの同形文字が入ったときに素通しになる。
PINYIN_LETTERS = (
    "abcdefghijklmnopqrstuvwxyz"
    "ABCDEFGHIJKLMNOPQRSTUVWXYZ"
    "āáǎàēéěèīíǐìōóǒòūúǔùǖǘǚǜüêḿńňǹ"
    "ĀÁǍÀĒÉĚÈĪÍǏÌŌÓǑÒŪÚǓÙǕǗǙǛÜÊŃŇǸ"
)
# ピンインの音節に数字は出てこない。数字が出るのは `F1杂交种` のような
# ラテン文字の略号の一部としてだけである。そこで数字そのものは許さず、
# 「数字を含む英数字の並び」を確認済みのものだけ通す。
# 無条件に数字を許していたとき、`衣锦荣归` の壊れたピンイン `yījǐnr645guī` を
# 見逃していた（独立レビューの指摘、2026-09-01）。
PINYIN_DIGIT_TOKENS = frozenset({"F1"})
ALNUM_RUN = re.compile(r"[A-Za-z0-9]+")
# 声調記号を合成で書く行がある（呒 `m̄`、呣 `m̀`）。
PINYIN_COMBINING = "̀́̄̌"
# 分かち書き・音節境界・区切り・省略の記号。実データで使われているものだけを載せる。
PINYIN_PUNCTUATION = " '-.,()（）／，…"
# 学術用語の接頭辞（β-内酰胺类、θ函数）。
PINYIN_GREEK = "βθ"
PINYIN_ALLOWED = frozenset(PINYIN_LETTERS + PINYIN_COMBINING + PINYIN_PUNCTUATION + PINYIN_GREEK)


def normalized_pinyin(word: str, pinyin: str) -> str:
    """(語, 読み) の一意性を見るための鍵（TASK.md D5）。

    空白・アポストロフィ・ハイフン・軽声の印（末尾の `5`、`˙`）を除き、
    原則として小文字化する。`CASE_KEEP` の語だけ大小文字を保つ。
    """
    text = pinyin.replace(" ", "").replace("'", "").replace("-", "").replace("\u02d9", "")
    if text.endswith("5"):
        text = text[:-1]
    return text if word in CASE_KEEP else text.lower()


def _in_ranges(ch: str, ranges) -> bool:
    code = ord(ch)
    return any(low <= code <= high for low, high in ranges)


def is_han(ch: str) -> bool:
    return _in_ranges(ch, HAN_RANGES)


def is_kana(ch: str) -> bool:
    return _in_ranges(ch, KANA_RANGES)


def is_cyrillic(ch: str) -> bool:
    return _in_ranges(ch, CYRILLIC_RANGES)


def is_latin_letter(ch: str) -> bool:
    return ch.isalpha() and ord(ch) < 0x0250


def latin_tokens(text: str) -> list[str]:
    """連続するラテン文字を1つの語として取り出す。"""
    tokens, current = [], []
    for ch in text:
        if is_latin_letter(ch):
            current.append(ch)
        else:
            if current:
                tokens.append("".join(current))
                current = []
    if current:
        tokens.append("".join(current))
    return tokens


class Violation:
    __slots__ = ("path", "line", "word", "kind", "detail")

    def __init__(self, path: str, line: int, word, kind: str, detail: str):
        self.path = path
        self.line = line
        self.word = word
        self.kind = kind
        self.detail = detail

    def __str__(self) -> str:
        word = self.word if isinstance(self.word, str) and self.word else "?"
        return f"{self.path}:{self.line}\t[{self.kind}]\t{word}\t{self.detail}"


def load_allowlist(name: str) -> set[str]:
    path = ALLOWLIST_DIR / name
    if not path.exists():
        return set()
    entries = set()
    for raw in path.read_text(encoding="utf-8").splitlines():
        line = raw.split("#", 1)[0].strip()
        if line:
            entries.add(line)
    return entries


ALLOWED_LATIN = load_allowlist("allowlist-latin.txt")
ALLOWED_KANA_IN_CHINESE = load_allowlist("allowlist-kana-in-chinese.txt")


def read_jsonl(path: pathlib.Path, violations: list[Violation], name: str | None = None):
    """1行ずつ読む。壊れた行は違反として記録し、読めた行だけ返す。

    `name` は違反の表示に使う相対名。2つの `glosses.jsonl` を区別するために要る。
    """
    name = name or path.name
    rows = []
    raw = path.read_bytes()
    if raw.startswith(b"\xef\xbb\xbf"):
        violations.append(Violation(name, 0, None, "bom", "先頭にBOMがある"))
    if b"\r" in raw:
        violations.append(Violation(name, 0, None, "crlf", "改行にCRが混じっている"))
    if raw and not raw.endswith(b"\n"):
        violations.append(Violation(name, 0, None, "no-final-newline", "末尾に改行が無い"))
    try:
        # BOM があっても最初の行を壊さないよう utf-8-sig で読む（BOM 自体は上で報告済み）。
        text = raw.decode("utf-8-sig")
    except UnicodeDecodeError as exc:
        # 途中で止めず、読めない箇所を U+FFFD にして続ける。下の replacement-char が拾う。
        violations.append(Violation(name, 0, None, "invalid-utf8", f"UTF-8として読めない箇所がある: {exc}"))
        text = raw.decode("utf-8-sig", errors="replace")
    for number, line in enumerate(text.splitlines(), start=1):
        if not line.strip():
            violations.append(Violation(name, number, None, "blank-line", "空行"))
            continue
        try:
            obj = json.loads(line)
        except json.JSONDecodeError as exc:
            violations.append(Violation(name, number, None, "broken-json", str(exc)))
            continue
        if not isinstance(obj, dict):
            violations.append(Violation(name, number, None, "not-object", f"{type(obj).__name__} を得た"))
            continue
        if "�" in line:
            # 文字化けの跡。元の文字が失われているので、機械では直せない。
            violations.append(Violation(name, number, obj.get("word"), "replacement-char", f"U+FFFD がある: {line}"))
        rows.append((number, obj))
    return rows


def check_common_keys(name, number, obj, required, optional, violations) -> bool:
    keys = set(obj)
    missing = required - keys
    unknown = keys - required - optional
    ok = True
    for key in sorted(missing):
        violations.append(Violation(name, number, obj.get("word"), "missing-key", f"必須キー {key!r} が無い"))
        ok = False
    for key in sorted(unknown):
        violations.append(Violation(name, number, obj.get("word"), "unknown-key", f"仕様に無いキー {key!r}（値 {obj[key]!r}）"))
        ok = False
    return ok


def check_word(name, number, obj, violations) -> None:
    word = obj.get("word")
    if not isinstance(word, str) or not word:
        violations.append(Violation(name, number, None, "bad-word", f"word が文字列でないか空: {word!r}"))
    elif word != word.strip():
        violations.append(Violation(name, number, word, "whitespace", "word の前後に空白がある"))


def check_hsk_level(name, number, obj, key, low, high, violations) -> None:
    """`hsk2` / `hsk3` は版ごとの HSK の級。任意のキー。"""
    if key not in obj:
        return
    level = obj[key]
    # bool は int の派生なので、先に弾かないと True が 1級として通る。
    if isinstance(level, bool) or not isinstance(level, int):
        violations.append(
            Violation(name, number, obj.get("word"), "bad-hsk", f"{key} が整数でない: {level!r}")
        )
        return
    if not low <= level <= high:
        violations.append(
            Violation(name, number, obj.get("word"), "bad-hsk",
                      f"{key} が {low}〜{high} の外: {level}")
        )


def check_retired_keys(name, number, obj, violations) -> None:
    """退役キーを持つ行は古い形式である。未知のキーと区別して報告する。"""
    for key in sorted(RETIRED_KEYS & set(obj)):
        violations.append(
            Violation(name, number, obj.get("word"), "retired-key",
                      f"退役したキー {key!r} がある（schema 2 では hsk2 / hsk3 に分かれた）")
        )


def check_string_array(name, number, word, field, value, violations, *, allowed=None) -> bool:
    """任意キーの文字列配列。配列であること・空でないこと・重複がないことを見る。"""
    if not isinstance(value, list):
        violations.append(Violation(name, number, word, "bad-type", f"{field} が配列でない: {value!r}"))
        return False
    if not value:
        violations.append(Violation(name, number, word, "empty-array", f"{field} が空配列"))
        return False
    ok = True
    seen = set()
    for index, item in enumerate(value):
        if not isinstance(item, str) or not item:
            violations.append(Violation(name, number, word, "bad-type", f"{field}[{index}] が空でない文字列でない: {item!r}"))
            ok = False
            continue
        if item != item.strip():
            violations.append(Violation(name, number, word, "whitespace", f"{field}[{index}] の前後に空白がある: {item!r}"))
            ok = False
        if item in seen:
            violations.append(Violation(name, number, word, "duplicate-item", f"{field} に重複 {item!r}"))
            ok = False
        seen.add(item)
        if allowed is not None and item not in allowed:
            violations.append(Violation(name, number, word, "unknown-value", f"{field} に仕様にない値 {item!r}"))
            ok = False
    return ok


def check_unsure(name, number, obj, violations) -> None:
    """`unsure` は「立てるときだけ true で書く」。false を明示しない。"""
    if "unsure" in obj and obj["unsure"] is not True:
        violations.append(
            Violation(name, number, obj.get("word"), "explicit-false",
                      f"unsure は true のときだけ書く。{obj['unsure']!r} が入っている")
        )


def check_text(name, number, word, field, text, violations, *, language) -> None:
    """訳の文字列そのものを見る。空・前後空白・言語混入を検出する。"""
    if not isinstance(text, str):
        violations.append(Violation(name, number, word, "bad-type", f"{field} が文字列でない: {text!r}"))
        return
    if not text:
        violations.append(Violation(name, number, word, "empty-string", f"{field} が空文字"))
        return
    if text != text.strip():
        violations.append(Violation(name, number, word, "whitespace", f"{field} の前後に空白がある: {text!r}"))
    if any(is_cyrillic(ch) for ch in text):
        violations.append(Violation(name, number, word, "cyrillic", f"{field} にキリル文字: {text!r}"))
    for token in latin_tokens(text):
        if token not in ALLOWED_LATIN:
            violations.append(
                Violation(name, number, word, "foreign-latin",
                          f"{field} に未登録のラテン語 {token!r}: {text!r}")
            )
    # 数字だけの訳（「十一」→「11」など）は正しいので、内容の判定から除く。
    has_digit = any(ch.isdigit() for ch in text)
    if language == "zh":
        if any(is_kana(ch) for ch in text) and text not in ALLOWED_KANA_IN_CHINESE:
            violations.append(Violation(name, number, word, "kana-in-chinese", f"{field} にかな: {text!r}"))
        if not any(is_han(ch) for ch in text) and not latin_tokens(text) and not has_digit:
            violations.append(Violation(name, number, word, "no-han", f"{field} に中国語の文字が無い: {text!r}"))
    elif language == "ja":
        if not any(is_han(ch) or is_kana(ch) for ch in text) and not latin_tokens(text) and not has_digit:
            violations.append(Violation(name, number, word, "no-japanese", f"{field} に日本語の文字が無い: {text!r}"))


def check_pinyin(name, number, word, pinyin, violations, *, field="pinyin") -> None:
    if not isinstance(pinyin, str):
        violations.append(Violation(name, number, word, "bad-type", f"{field} が文字列でない: {pinyin!r}"))
        return
    if not pinyin:
        violations.append(Violation(name, number, word, "empty-pinyin", f"{field} が空文字"))
        return
    if pinyin != pinyin.strip():
        violations.append(Violation(name, number, word, "whitespace", f"{field} の前後に空白がある: {pinyin!r}"))
    for token in ALNUM_RUN.findall(pinyin):
        if any(ch.isdigit() for ch in token) and token not in PINYIN_DIGIT_TOKENS:
            violations.append(
                Violation(name, number, word, "bad-pinyin",
                          f"{field} に未登録の数字入りの並び {token!r}: {pinyin!r}")
            )
            return
    for ch in pinyin:
        if ch.isascii() and ch.isdigit():
            # 上のループで、ASCIIの数字を含む並びは確認済みのものだけと分かっている。
            # ASCII以外の数字（全角 `１`、アラビア数字 `٣` など）はここを通さず、
            # PINYIN_ALLOWED に無いものとして下で違反にする。
            continue
        if ch not in PINYIN_ALLOWED:
            violations.append(
                Violation(name, number, word, "bad-pinyin",
                          f"{field} に U+{ord(ch):04X} {unicodedata.name(ch, '名前なし')} が入っている: {pinyin!r}")
            )
            break


def check_duplicate_words(name, rows, violations) -> None:
    """見出し語の重複を見る。`ja-zh` は語が単位なので今も1語1行である。"""
    seen: dict[str, int] = {}
    for number, obj in rows:
        word = obj.get("word")
        if not isinstance(word, str) or not word:
            continue
        if word in seen:
            violations.append(Violation(name, number, word, "duplicate-word", f"行 {seen[word]} と重複"))
        else:
            seen[word] = number


def check_duplicate_word_pinyin(name, rows, violations) -> None:
    """中日は (語, 読み) が単位。D5 の正規化をしたうえで重複を見る。"""
    seen: dict[tuple, int] = {}
    for number, obj in rows:
        word, pinyin = obj.get("word"), obj.get("pinyin")
        if not isinstance(word, str) or not word or not isinstance(pinyin, str) or not pinyin:
            continue
        key = (word, normalized_pinyin(word, pinyin))
        if key in seen:
            violations.append(
                Violation(name, number, word, "duplicate-word-pinyin",
                          f"読み {pinyin!r} が行 {seen[key]} と重複（正規化後 {key[1]!r}）")
            )
        else:
            seen[key] = number


# 語の属性。同じ語のすべての行で一致していなければならない（TASK.md D12）。
# `reading_pos` は行の属性なので入れない。
WORD_ATTRIBUTES = ("hsk2", "hsk3", "trad", "pos", "alt_pinyin")


def check_word_attributes(name, rows, violations) -> None:
    first: dict[str, tuple] = {}
    for number, obj in rows:
        word = obj.get("word")
        if not isinstance(word, str) or not word:
            continue
        current = tuple(json.dumps(obj.get(k), ensure_ascii=False, sort_keys=True) for k in WORD_ATTRIBUTES)
        if word not in first:
            first[word] = (number, current)
            continue
        before_number, before = first[word]
        if before != current:
            differing = [k for k, a, b in zip(WORD_ATTRIBUTES, before, current) if a != b]
            violations.append(
                Violation(name, number, word, "attribute-mismatch",
                          f"語の属性が行 {before_number} と食い違う: {differing}")
            )


def validate_zh_ja_glosses(path, rows, violations) -> Counter:
    name = "zh-ja/glosses.jsonl"
    counts: Counter = Counter()
    required = {"word", "pinyin", "gloss", "qa"}
    optional = {"unsure", "hsk2", "hsk3", "trad", "pos", "reading_pos", "alt_pinyin"}
    for number, obj in rows:
        check_common_keys(name, number, obj, required, optional | RETIRED_KEYS, violations)
        check_retired_keys(name, number, obj, violations)
        check_word(name, number, obj, violations)
        check_unsure(name, number, obj, violations)
        check_hsk_level(name, number, obj, "hsk2", HSK2_MIN_LEVEL, HSK2_MAX_LEVEL, violations)
        check_hsk_level(name, number, obj, "hsk3", HSK3_MIN_LEVEL, HSK3_MAX_LEVEL, violations)
        word = obj.get("word")

        if "pinyin" in obj:
            check_pinyin(name, number, word, obj["pinyin"], violations)

        qa = obj.get("qa")
        # 値が null でも違反にする（キーが無い場合は上の missing-key が拾う）。
        if "qa" in obj and qa not in QA_VALUES:
            violations.append(Violation(name, number, word, "bad-qa", f"qa が想定外の値: {qa!r}"))

        # 任意の配列キー。
        if "trad" in obj:
            check_string_array(name, number, word, "trad", obj["trad"], violations)
        if "pos" in obj:
            check_string_array(name, number, word, "pos", obj["pos"], violations, allowed=POS_VALUES)
        if "reading_pos" in obj:
            check_string_array(name, number, word, "reading_pos", obj["reading_pos"], violations,
                               allowed=READING_POS_VALUES)
            # README の復元規則（`reading_pos` が無い行は語の `pos` と同じ）が成り立つには、
            # `reading_pos` を持つ行が `pos` も持っていなければならない。
            if "pos" not in obj:
                violations.append(
                    Violation(name, number, word, "reading-pos-without-pos",
                              "reading_pos があるのに pos が無い（復元規則が成り立たない）")
                )
        if "alt_pinyin" in obj and check_string_array(name, number, word, "alt_pinyin",
                                                      obj["alt_pinyin"], violations):
            for index, value in enumerate(obj["alt_pinyin"]):
                check_pinyin(name, number, word, value, violations, field=f"alt_pinyin[{index}]")

        gloss = obj.get("gloss")
        unsure = obj.get("unsure") is True
        if not isinstance(gloss, list):
            violations.append(Violation(name, number, word, "bad-type", f"gloss が配列でない: {gloss!r}"))
            continue
        seen_gloss = set()
        for item in gloss:
            check_text(name, number, word, "gloss", item, violations, language="ja")
            if isinstance(item, str):
                if item in seen_gloss:
                    violations.append(Violation(name, number, word, "duplicate-item", f"gloss に重複 {item!r}"))
                seen_gloss.add(item)
        if not gloss and not unsure:
            violations.append(Violation(name, number, word, "empty-without-unsure", "gloss が空なのに unsure が無い"))

        # 区分は排他。合計が行数に一致する。
        if "pinyin" not in obj:
            counts["pinyinキー欠落"] += 1
        elif unsure and gloss:
            counts["unsure・gloss非空"] += 1
        elif unsure:
            counts["unsure・gloss空"] += 1
        else:
            counts["通常"] += 1
        counts["_qa:" + str(qa)] += 1
        # 属性（区分をまたぐ数え方）。合計には足さない。
        for key in ("hsk2", "hsk3", "trad", "pos", "reading_pos", "alt_pinyin"):
            if key in obj:
                counts["_属性:" + key] += 1
        for key, low, high in (("hsk2", HSK2_MIN_LEVEL, HSK2_MAX_LEVEL),
                               ("hsk3", HSK3_MIN_LEVEL, HSK3_MAX_LEVEL)):
            level = obj.get(key)
            if isinstance(level, int) and not isinstance(level, bool) and low <= level <= high:
                counts["_%s %d級" % (key, level)] += 1
    check_duplicate_word_pinyin(name, rows, violations)
    check_word_attributes(name, rows, violations)
    return counts


def validate_ja_zh_glosses(path, rows, violations) -> Counter:
    name = "ja-zh/glosses.jsonl"
    counts: Counter = Counter()
    for number, obj in rows:
        check_common_keys(name, number, obj, {"word", "zh"}, {"unsure"}, violations)
        check_word(name, number, obj, violations)
        check_unsure(name, number, obj, violations)
        word = obj.get("word")

        candidates = obj.get("zh")
        unsure = obj.get("unsure") is True
        if not isinstance(candidates, list):
            violations.append(Violation(name, number, word, "bad-type", f"zh が配列でない: {candidates!r}"))
            continue
        seen_surfaces = set()
        for index, candidate in enumerate(candidates):
            if not isinstance(candidate, dict):
                violations.append(Violation(name, number, word, "bad-type", f"zh[{index}] がオブジェクトでない: {candidate!r}"))
                continue
            extra = set(candidate) - {"s", "pinyin"}
            for key in sorted(extra):
                violations.append(
                    Violation(name, number, word, "unknown-key",
                              f"zh[{index}] に仕様に無いキー {key!r}（値 {candidate[key]!r}）")
                )
            if "s" not in candidate:
                violations.append(Violation(name, number, word, "missing-key", f"zh[{index}] に s が無い"))
            else:
                check_text(name, number, word, f"zh[{index}].s", candidate["s"], violations, language="zh")
                # s が文字列でないときは check_text が bad-type を出している。
                # set へ入れると非hashableな型（配列など）で TypeError になるため、重複検査は飛ばす。
                if isinstance(candidate["s"], str):
                    if candidate["s"] in seen_surfaces:
                        violations.append(Violation(name, number, word, "duplicate-candidate", f"zh[{index}].s が重複: {candidate['s']!r}"))
                    seen_surfaces.add(candidate["s"])
            if "pinyin" not in candidate:
                violations.append(Violation(name, number, word, "missing-key", f"zh[{index}] に pinyin が無い"))
            else:
                check_pinyin(name, number, word, candidate["pinyin"], violations, field=f"zh[{index}].pinyin")

        if not candidates and not unsure:
            violations.append(Violation(name, number, word, "empty-without-unsure", "zh が空なのに unsure が無い"))
        # 区分は排他。合計が行数に一致する。
        if "unsure" in obj and obj["unsure"] is False:
            counts["unsure:false（明示的な偽）"] += 1
        elif unsure and candidates:
            counts["unsure・zh非空"] += 1
        elif unsure:
            counts["unsure・zh空"] += 1
        else:
            counts["通常"] += 1
        # 属性（区分をまたぐ数え方）。合計には足さない。
        counts["_候補数:%d" % len(candidates)] += 1
        if "pinyin" in obj:
            counts["_属性:トップレベルpinyin"] += 1
        if any(isinstance(c, dict) and c.get("s") == "" for c in candidates):
            counts["_属性:空文字の候補"] += 1
        if any(isinstance(c, dict) and c.get("pinyin") == "" for c in candidates):
            counts["_属性:空文字のpinyin"] += 1
    check_duplicate_words(name, rows, violations)
    return counts


FILES = (
    ("zh-ja/glosses.jsonl", validate_zh_ja_glosses),
    ("ja-zh/glosses.jsonl", validate_ja_zh_glosses),
)

MANIFEST = "manifest.json"


def main(argv=None) -> int:
    parser = argparse.ArgumentParser(description="zh-ja-dict のデータを全件検証する")
    parser.add_argument("--data", type=pathlib.Path, default=DEFAULT_DATA_DIR, help="データディレクトリ")
    parser.add_argument("--counts", action="store_true", help="件数だけ出して常に成功で終わる")
    parser.add_argument("--max-report", type=int, default=200, help="表示する違反の上限（既定 200）")
    args = parser.parse_args(argv)

    violations: list[Violation] = []
    total_lines = 0
    summary = []
    line_counts = {}

    for relative, validate in FILES:
        path = args.data / relative
        if not path.exists():
            print(f"データファイルが見つからない: {path}", file=sys.stderr)
            return 2
        rows = read_jsonl(path, violations, relative)
        counts = validate(path, rows, violations)
        total_lines += len(rows)
        line_counts[relative] = len(rows)
        summary.append((relative, len(rows), counts))

    # 退役したファイルが残っていないか。
    retired = args.data / "zh-ja" / "polyphonic.jsonl"
    if retired.exists():
        violations.append(Violation(MANIFEST, 0, None, "retired-file",
                                    "zh-ja/polyphonic.jsonl は schema 2 で廃止した。残っている"))

    # manifest と実ファイルの突き合わせ。
    manifest_path = args.data / MANIFEST
    if not manifest_path.exists():
        violations.append(Violation(MANIFEST, 0, None, "missing-manifest", f"{manifest_path} が無い"))
    else:
        try:
            manifest = json.loads(manifest_path.read_text(encoding="utf-8"))
        except json.JSONDecodeError as exc:
            manifest = None
            violations.append(Violation(MANIFEST, 0, None, "broken-json", str(exc)))
        if manifest is not None:
            if manifest.get("schema_version") != SCHEMA_VERSION:
                violations.append(Violation(MANIFEST, 0, None, "bad-schema-version",
                                            f"schema_version が {SCHEMA_VERSION} でない: {manifest.get('schema_version')!r}"))
            files = manifest.get("files")
            if not isinstance(files, dict):
                violations.append(Violation(MANIFEST, 0, None, "bad-type", f"files がオブジェクトでない: {files!r}"))
            else:
                for relative, actual in line_counts.items():
                    entry = files.get(relative)
                    # 値がオブジェクトでない manifest を手で書かれても落ちないようにする。
                    if entry is not None and not isinstance(entry, dict):
                        violations.append(Violation(MANIFEST, 0, None, "bad-type",
                                                    f"files[{relative!r}] がオブジェクトでない: {entry!r}"))
                        continue
                    recorded = (entry or {}).get("lines")
                    if recorded != actual:
                        violations.append(Violation(MANIFEST, 0, None, "line-count-mismatch",
                                                    f"{relative}: manifest {recorded!r} / 実ファイル {actual}"))
                for key in sorted(set(files) - set(line_counts)):
                    violations.append(Violation(MANIFEST, 0, None, "unknown-file",
                                                f"manifest に実在しないファイル {key!r}"))

    for relative, line_count, counts in summary:
        print(f"## {relative}（{line_count:,}行）")
        variants = {k: v for k, v in counts.items() if not k.startswith("_")}
        for key in sorted(variants, key=lambda k: -variants[k]):
            print(f"  {key:<24} {variants[key]:>7,}")
        subtotal = sum(variants.values())
        mark = "一致" if subtotal == line_count else "不一致"
        print(f"  {'区分の合計':<24} {subtotal:>7,}  （行数と{mark}）")
        for key in sorted(k for k in counts if k.startswith("_")):
            print(f"  {key[1:]:<24} {counts[key]:>7,}")
        print()

    print(f"合計 {total_lines:,}行")

    if args.counts:
        print(f"（--counts のため検証結果を終了コードに反映しない。違反 {len(violations):,} 件）")
        return 0

    if not violations:
        print("違反 0 件")
        return 0

    by_kind = Counter(v.kind for v in violations)
    print(f"\n違反 {len(violations):,} 件")
    for kind, count in by_kind.most_common():
        print(f"  {kind:<24} {count:>7,}")
    print()
    for violation in violations[: args.max_report]:
        print(violation)
    if len(violations) > args.max_report:
        print(f"... 残り {len(violations) - args.max_report:,} 件（--max-report で増やせる）")
    return 1


if __name__ == "__main__":
    sys.exit(main())
