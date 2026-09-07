#!/usr/bin/env python3
"""zh-ja-dict のデータファイルを全件検証する。

schema 3（1行 = 1 entry。中日は raw DEFLATE で圧縮して同梱する）を対象とする。

使い方:
    python3 tools/validate_data.py              # 検証。違反が1件でもあれば終了コード1
    python3 tools/validate_data.py --counts     # 変種別の件数だけ出す。常に終了コード0
    python3 tools/validate_data.py --cedict-entries 124985 --existing tmp/old-glosses.jsonl

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

sys.path.insert(0, str(pathlib.Path(__file__).resolve().parent))
import dataset_sources  # noqa: E402
import entries_file  # noqa: E402

REPO_ROOT = pathlib.Path(__file__).resolve().parent.parent
DEFAULT_DATA_DIR = REPO_ROOT / "data"
ALLOWLIST_DIR = REPO_ROOT / "tools"

SCHEMA_VERSION = 3

QA_VALUES = {"machine_backed", "llm_ok", "llm_fixed", "human_reviewed", "unchecked",
             "derived", "hand_fixed"}

# 既存の訳を候補として渡した entry に付く印。その訳の検品の区分をそのまま持つ。
SEED_VALUES = {"machine_backed", "llm_ok", "llm_fixed", "human_reviewed", "unchecked"}

# 萌典との照合結果。本文は持たず、この3値だけを残す。
MOE_VALUES = {"full", "headword", "none"}

# 補遺 entry の出どころ。CC-CEDICT に無い語をこの辞書の旧版から補った印。
SRC_VALUES = {"zh-ja-dict"}

# 語感・地域・修辞の印。分野の名前（computing など3千種）は印にせず語義の文に残す。
MISC_VALUES = frozenset(
    "coll written fig dial tw hk cantonese loan slang net idiom proverb old arch "
    "onom bound derog honor polite humble vulgar euph joc neo formal".split()
)

VARIANT_KINDS = frozenset({"variant", "old", "erhua"})
XREF_KINDS = frozenset({"see", "see_also", "abbr", "used_in"})

ENTRY_REQUIRED = {"word", "pinyin", "senses"}
ENTRY_OPTIONAL = {"trad", "tw_pr", "also_pr", "cl", "hsk2", "hsk3", "pos",
                  "src", "seed", "moe"}
SENSE_REQUIRED = {"ja", "qa"}
SENSE_OPTIONAL = {"en", "unsure", "misc", "variant_of", "see_also", "lsource", "s_inf"}

# 旧版から引き継いだ訳は候補を「、」で繋ぐので長くなる。参照から機械で組み立てた訳は
# 参照先の語と読みを含む。出どころごとに上限を変える。
REUSED_MAX_LENGTH = 80
DERIVED_MAX_LENGTH = 200

# 退役したキー。schema 3 では語ごとに1行ではなくなり、意味を失った。
# 1件でもあれば古い形式のデータなので、未知のキーではなく専用の違反として報告する。
RETIRED_KEYS = {"hsk", "gloss", "reading_pos", "alt_pinyin"}

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


def _is_plain_number(token: str) -> bool:
    """`双11 [Shuāng 11]` のように、読みの中に数字がそのまま出ることがある。"""
    return token.isdigit()
ALNUM_RUN = re.compile(r"[A-Za-z0-9]+")
# 声調記号を合成で書く行がある（呒 `m̄`、呣 `m̀`）。
PINYIN_COMBINING = "̀́̄̌"
# 分かち書き・音節境界・区切り・省略の記号。実データで使われているものだけを載せる。
PINYIN_PUNCTUATION = " '-.,()（）／，…·"
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


# 日本語の簡潔訳の長さの上限。生成の規則（プロンプト）と同じ値。
JA_MAX_LENGTH = 24

# ピンインの声調記号。日本語訳に混じっていれば、読みが訳へ漏れている。
_TONE_MARKS = "\u0300\u0301\u0304\u030c" + "āáǎàēéěèīíǐìōóǒòūúǔùǖǘǚǜĀÁǍÀĒÉĚÈ"


def check_japanese(text, where: str, allowed_latin=None, en_words=(),
                   max_length: int = JA_MAX_LENGTH, allow_pinyin: bool = False):
    """日本語の簡潔訳として使えるかを見る。駄目なら理由を返し、良ければ None。

    生成の途中（`tools/generate_ja.py --repair`）と全件検査の両方から呼ぶ。
    `en_words` にその語義の英訳の語を渡すと、英語が訳へ残った場合を捕まえられる。
    `allow_pinyin` は、参照から機械で組み立てた訳のように読みを含むのが正しい訳に使う。
    """
    allowed = ALLOWED_LATIN if allowed_latin is None else allowed_latin
    if not isinstance(text, str) or not text:
        return f"{where}: 訳が空"
    if text != text.strip():
        return f"{where}: 前後に空白がある: {text!r}"
    if len(text) > max_length:
        return f"{where}: {max_length}文字を超える（{len(text)}文字）: {text!r}"
    if any(is_cyrillic(ch) for ch in text):
        return f"{where}: キリル文字が入っている: {text!r}"
    if not allow_pinyin:
        if any(ch in _TONE_MARKS for ch in text):
            return f"{where}: ピンインの声調記号が入っている: {text!r}"
        lowered = {word.lower() for word in en_words}
        for token in latin_tokens(text):
            if token not in allowed:
                # 許可表に無いラテン語は、英訳の残りか綴りの誤りのどちらか。
                if token.lower() in lowered:
                    return f"{where}: 英訳の語がそのまま残っている {token!r}: {text!r}"
                return f"{where}: 未登録のラテン語 {token!r}: {text!r}"
    # 日本語でもラテン文字で書く語がある（`CD-ROM`・`APEC`）。許可表を通った
    # ラテン語だけでできた訳は認める。数字だけの訳（`11`）も同じ。
    if not any(is_han(ch) or is_kana(ch) for ch in text) \
            and not latin_tokens(text) and not any(ch.isdigit() for ch in text):
        return f"{where}: 日本語の文字が無い: {text!r}"
    return None


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
        if (any(ch.isdigit() for ch in token) and token not in PINYIN_DIGIT_TOKENS
                and not _is_plain_number(token)):
            violations.append(
                Violation(name, number, word, "bad-pinyin",
                          f"{field} に未登録の数字入りの並び {token!r}: {pinyin!r}")
            )
            return
    for index, ch in enumerate(pinyin):
        if ch == ":" and not (index and pinyin[index - 1] in "uU"):
            # 書名の読みに1件だけコロンが出る（`毛泽东：鲜为人知的故事`）。
            # `u:` は ü を数字つきで書いたままの取りこぼしなので、そちらは通さない。
            continue
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




def check_ref_array(name, number, word, field, value, violations, *, kinds) -> None:
    """参照の配列（`variant_of`・`see_also`・`cl`）を見る。

    要素は `{"kind": …, "w": 簡体, "t": 繁体, "py": 読み}`。`cl`（量詞）に `kind` は無い。
    """
    if not isinstance(value, list) or not value:
        violations.append(Violation(name, number, word, "bad-type",
                                    f"{field} が空でない配列でない: {value!r}"))
        return
    for index, item in enumerate(value):
        where = f"{field}[{index}]"
        if not isinstance(item, dict):
            violations.append(Violation(name, number, word, "bad-type",
                                        f"{where} がオブジェクトでない: {item!r}"))
            continue
        allowed = {"w", "t", "py"} | ({"kind"} if kinds else set())
        for key in sorted(set(item) - allowed):
            violations.append(Violation(name, number, word, "unknown-key",
                                        f"{where} に仕様に無いキー {key!r}"))
        if kinds:
            if item.get("kind") not in kinds:
                violations.append(Violation(name, number, word, "bad-kind",
                                            f"{where}.kind が想定外: {item.get('kind')!r}"))
        for part in ("w", "t"):
            value = item.get(part)
            if value is None:
                continue
            if isinstance(value, str) and " " in value:
                # 見出しに空白は入らない。入っていれば `Israel 以色列` のように
                # 英語の説明を参照先として読み違えている。
                violations.append(
                    Violation(name, number, word, "text-in-ref",
                              f"{where}.{part} に空白がある（英語の説明の混入）: {value!r}"))
        if not isinstance(item.get("w"), str) or not item["w"]:
            violations.append(Violation(name, number, word, "bad-type",
                                        f"{where}.w が空でない文字列でない: {item.get('w')!r}"))
        if "t" in item and (not isinstance(item["t"], str) or not item["t"]):
            violations.append(Violation(name, number, word, "bad-type",
                                        f"{where}.t が空でない文字列でない: {item['t']!r}"))
        if "t" in item and item.get("t") == item.get("w"):
            violations.append(Violation(name, number, word, "redundant-trad",
                                        f"{where}.t が w と同じ: {item['t']!r}"))
        if "py" in item and (not isinstance(item["py"], str) or not item["py"]):
            violations.append(Violation(name, number, word, "bad-type",
                                        f"{where}.py が空でない文字列でない: {item['py']!r}"))


def check_sense(name, number, word, index, sense, violations, counts) -> None:
    """語義1つを見る。"""
    field = f"senses[{index}]"
    if not isinstance(sense, dict):
        violations.append(Violation(name, number, word, "bad-type",
                                    f"{field} がオブジェクトでない: {sense!r}"))
        return
    for key in sorted(SENSE_REQUIRED - set(sense)):
        violations.append(Violation(name, number, word, "missing-key",
                                    f"{field} に必須キー {key!r} が無い"))
    for key in sorted(set(sense) - SENSE_REQUIRED - SENSE_OPTIONAL):
        violations.append(Violation(name, number, word, "unknown-key",
                                    f"{field} に仕様に無いキー {key!r}"))

    qa = sense.get("qa")
    if "qa" in sense and qa not in QA_VALUES:
        violations.append(Violation(name, number, word, "bad-qa",
                                    f"{field}.qa が想定外の値: {qa!r}"))
    counts[f"_qa:{qa}"] += 1

    if "ja" in sense:
        # 長さの上限は出どころで変える。生成した訳は24文字まで（生成の規則と同じ）。
        # 旧版から引き継いだ訳は候補を「、」で繋ぐので長くなり、参照から機械で
        # 組み立てた訳は参照先の語と読みを含むので、それぞれ別の上限を当てる。
        limit = {"llm_ok": JA_MAX_LENGTH, "llm_fixed": JA_MAX_LENGTH,
                 "hand_fixed": JA_MAX_LENGTH,
                 "derived": DERIVED_MAX_LENGTH}.get(qa, REUSED_MAX_LENGTH)
        english = {token for text in sense.get("en") or []
                   if isinstance(text, str) for token in latin_tokens(text)}
        # 参照から機械で組み立てた訳は、参照先の語と読みをそのまま含む
        # （`开金（kāi jīn）に同じ`）。ピンインとラテン語の検査は当てない。
        message = check_japanese(sense["ja"], f"{field}.ja", en_words=english,
                                 max_length=limit, allow_pinyin=(qa == "derived"))
        if message:
            violations.append(Violation(name, number, word, "bad-ja", message))

    if "en" in sense:
        check_string_array(name, number, word, f"{field}.en", sense["en"], violations)
    if "misc" in sense:
        check_string_array(name, number, word, f"{field}.misc", sense["misc"],
                           violations, allowed=MISC_VALUES)
    if "s_inf" in sense:
        check_string_array(name, number, word, f"{field}.s_inf", sense["s_inf"], violations)
    if "lsource" in sense:
        check_string_array(name, number, word, f"{field}.lsource", sense["lsource"], violations)
    if "variant_of" in sense:
        check_ref_array(name, number, word, f"{field}.variant_of", sense["variant_of"],
                        violations, kinds=VARIANT_KINDS)
    if "see_also" in sense:
        check_ref_array(name, number, word, f"{field}.see_also", sense["see_also"],
                        violations, kinds=XREF_KINDS)
    if "unsure" in sense and sense["unsure"] is not True:
        violations.append(Violation(name, number, word, "explicit-false",
                                    f"{field}.unsure は true のときだけ書く"))


def check_duplicate_entries(name, rows, violations) -> None:
    """entry の鍵は (簡体, 繁体, 読み) の3つ組。CC-CEDICT の実測で重複0である。

    (簡体, 読み) の2つ組は 1,054 組が重なる（`俊 jun4` が繁体 `俊` と `儁` で2 entry など）
    ので、鍵にはできない。
    """
    seen: dict = {}
    for number, obj in rows:
        word, pinyin = obj.get("word"), obj.get("pinyin")
        if not isinstance(word, str) or not word or not isinstance(pinyin, str) or not pinyin:
            continue
        # CC-CEDICT は固有名詞の読みを大文字で始めて区別する（`三 Sān` 姓 と
        # `三 sān` 数詞）。大小文字を潰すと別の語を重複と誤判定する。
        key = (word, obj.get("trad"), pinyin.replace(" ", "").replace("'", ""))
        if key in seen:
            violations.append(
                Violation(name, number, word, "duplicate-entry",
                          f"(簡体, 繁体, 読み) が行 {seen[key]} と重複: {key}"))
        else:
            seen[key] = number


def validate_zh_ja_entries(path, rows, violations) -> Counter:
    name = f"zh-ja/{entries_file.NAME}"
    counts: Counter = Counter()
    for number, obj in rows:
        check_common_keys(name, number, obj, ENTRY_REQUIRED,
                          ENTRY_OPTIONAL | RETIRED_KEYS, violations)
        check_retired_keys(name, number, obj, violations)
        check_word(name, number, obj, violations)
        check_hsk_level(name, number, obj, "hsk2", HSK2_MIN_LEVEL, HSK2_MAX_LEVEL, violations)
        check_hsk_level(name, number, obj, "hsk3", HSK3_MIN_LEVEL, HSK3_MAX_LEVEL, violations)
        word = obj.get("word")

        for field in ("pinyin", "tw_pr", "also_pr"):
            if field in obj:
                check_pinyin(name, number, word, obj[field], violations, field=field)

        if "trad" in obj:
            if not isinstance(obj["trad"], str) or not obj["trad"]:
                violations.append(Violation(name, number, word, "bad-type",
                                            f"trad が空でない文字列でない: {obj['trad']!r}"))
            elif obj["trad"] == word:
                # 繁体が簡体と同じなら書かない（README の規則）。
                violations.append(Violation(name, number, word, "redundant-trad",
                                            "trad が word と同じ"))
        if "pos" in obj:
            check_string_array(name, number, word, "pos", obj["pos"], violations,
                               allowed=POS_VALUES)
        if "cl" in obj:
            # 量詞は語ごとの性質なので entry の欄に置く。CC-CEDICT は `CL:` を
            # 独立した断片として書くだけで、どの語義に掛かるかを示していない。
            check_ref_array(name, number, word, "cl", obj["cl"], violations, kinds=None)
        for field, allowed in (("src", SRC_VALUES), ("seed", SEED_VALUES), ("moe", MOE_VALUES)):
            if field in obj and obj[field] not in allowed:
                violations.append(Violation(name, number, word, "unknown-value",
                                            f"{field} が想定外の値: {obj[field]!r}"))

        senses = obj.get("senses")
        if not isinstance(senses, list) or not senses:
            violations.append(Violation(name, number, word, "bad-type",
                                        f"senses が空でない配列でない: {senses!r}"))
            continue
        for index, sense in enumerate(senses):
            check_sense(name, number, word, index, sense, violations, counts)

        counts["補遺" if obj.get("src") else "骨格"] += 1
        counts["_語義数:%d" % len(senses)] += 1
        for field in ("trad", "tw_pr", "also_pr", "cl", "hsk2", "hsk3", "pos",
                      "seed", "moe"):
            if field in obj:
                counts[f"_属性:{field}"] += 1
    check_duplicate_entries(name, rows, violations)
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


ZH_JA = f"zh-ja/{entries_file.NAME}"
JA_ZH = "ja-zh/glosses.jsonl"
MANIFEST = "manifest.json"


def read_entries(path: pathlib.Path, violations: list, name: str):
    """圧縮された entry を1行ずつ読む。壊れた行は違反として記録する。"""
    rows = []
    try:
        lines = list(entries_file.read_lines(path))
    except Exception as error:                      # zlib.error など
        violations.append(Violation(name, 0, None, "broken-archive", str(error)))
        return rows
    for number, line in enumerate(lines, start=1):
        try:
            obj = json.loads(line)
        except json.JSONDecodeError as error:
            violations.append(Violation(name, number, None, "broken-json", str(error)))
            continue
        if not isinstance(obj, dict):
            violations.append(Violation(name, number, None, "bad-type",
                                        f"行がオブジェクトでない: {obj!r}"))
            continue
        rows.append((number, obj))
    return rows


def check_existing_coverage(rows, existing: pathlib.Path, violations) -> None:
    """旧版の (語, 読み) がすべて新しいデータに対応しているか。

    旧版のファイルは配らないので、検査するときは git から取り出して渡す。

        git show <旧版のcommit>:data/zh-ja/glosses.jsonl > tmp/old-glosses.jsonl
    """
    import pinyin as pinyin_tools
    exact = set()
    toneless: dict = {}
    for _, obj in rows:
        reading = obj.get("pinyin") or ""
        key = pinyin_tools.key(reading)
        loose = pinyin_tools.toneless_key(reading)
        for spelling in {obj.get("word"), obj.get("trad")} - {None}:
            exact.add((spelling, key))
            toneless.setdefault((spelling, loose), []).append(reading)
    missing = []
    total = 0
    for line in existing.read_text(encoding="utf-8").splitlines():
        if not line.strip():
            continue
        total += 1
        old = json.loads(line)
        word, reading = old.get("word"), old.get("pinyin") or ""
        if (word, pinyin_tools.key(reading)) in exact:
            continue
        # **声調の違いを認めるのは `一`・`不` の変調だけ。** 音節ごとに突き合わせる。
        # ここを緩めると、`繃 bèng` が `繃 bēng` に当たって「対応済み」になり、
        # 旧版の読みと訳が消えたことを見逃す。
        loose = toneless.get((word, pinyin_tools.toneless_key(reading)), [])
        if any(pinyin_tools.sandhi_pattern_from_marks(other).match(
                pinyin_tools.key(reading)) for other in loose):
            continue
        missing.append(f"{word} {reading}")
    print(f"## 旧版との対応（{existing}）")
    print(f"  旧版 {total:,} 行 / 対応しない {len(missing):,} 行")
    for item in missing[:20]:
        print(f"    {item}")
    for item in missing:
        violations.append(Violation(ZH_JA, 0, item.split(" ")[0], "existing-not-covered",
                                    f"旧版の行が新しいデータに無い: {item}"))
    print()


def check_hsk_coverage(rows, seed: pathlib.Path, violations) -> None:
    """HSK の元データの級が、その見出し語のすべての entry に残っているか。

    級は語の属性なので、読みが違っても同じ見出し語なら同じ値を持つ。読みの一致する
    entry だけに付けると `了 liǎo` に級があって `了 le` に無い、という歯抜けができる。
    元データを直接読んで端から端まで突き合わせる。
    """
    entries_by_word: dict = {}
    for _, obj in rows:
        for spelling in {obj.get("word"), obj.get("trad")} - {None}:
            entries_by_word.setdefault(spelling, []).append(obj)
    root = json.loads(seed.read_text(encoding="utf-8"))
    total = missing_word = mismatched = 0
    for entry in root["entries"]:
        word = entry["word"]
        levels = entry.get("hsk_levels") or {}
        wanted = {"hsk2": levels.get("2.0"), "hsk3": levels.get("3.0")}
        found = entries_by_word.get(word)
        total += 1
        if not found:
            missing_word += 1
            violations.append(
                Violation(ZH_JA, 0, word, "hsk-word-missing",
                          "HSK の元データにある見出しが新しいデータに無い"))
            continue
        for obj in found:
            for key, value in wanted.items():
                if value is None:
                    continue
                if obj.get(key) != value:
                    mismatched += 1
                    violations.append(
                        Violation(ZH_JA, 0, word, "hsk-not-kept",
                                  f"{key} が {value} でない: {obj.get('pinyin')!r} は "
                                  f"{obj.get(key)!r}"))
    print(f"## HSK の元データとの突き合わせ（{seed}）")
    print(f"  元データ {total:,} 語 / 見出しが無い {missing_word:,} 語 / "
          f"級が残っていない {mismatched:,} 件")
    print()


def main(argv=None) -> int:
    parser = argparse.ArgumentParser(description="zh-ja-dict のデータを全件検証する")
    parser.add_argument("--data", type=pathlib.Path, default=DEFAULT_DATA_DIR,
                        help="データディレクトリ")
    parser.add_argument("--counts", action="store_true", help="件数だけ出して常に成功で終わる")
    parser.add_argument("--max-report", type=int, default=200,
                        help="表示する違反の上限（既定 200）")
    parser.add_argument("--cedict-entries", type=int,
                        help="骨格 entry の期待値（CC-CEDICT の entry 数）")
    parser.add_argument("--existing", type=pathlib.Path,
                        help="旧版の glosses.jsonl。全行が対応しているかを見る")
    parser.add_argument("--hsk-seed", type=pathlib.Path,
                        help="HSK の元データ。級がすべての entry に残っているかを見る")
    args = parser.parse_args(argv)

    violations: list = []
    summary = []
    line_counts = {}

    zh_path = args.data / ZH_JA
    ja_path = args.data / JA_ZH
    for path in (zh_path, ja_path):
        if not path.exists():
            print(f"データファイルが見つからない: {path}", file=sys.stderr)
            return 2

    zh_rows = read_entries(zh_path, violations, ZH_JA)
    zh_counts = validate_zh_ja_entries(zh_path, zh_rows, violations)
    line_counts[ZH_JA] = len(zh_rows)
    summary.append((ZH_JA, len(zh_rows), zh_counts))

    ja_rows = read_jsonl(ja_path, violations, JA_ZH)
    ja_counts = validate_ja_zh_glosses(ja_path, ja_rows, violations)
    line_counts[JA_ZH] = len(ja_rows)
    summary.append((JA_ZH, len(ja_rows), ja_counts))

    # 退役したファイルが残っていないか。
    for retired in ("zh-ja/polyphonic.jsonl", "zh-ja/glosses.jsonl"):
        if (args.data / retired).exists():
            violations.append(Violation(MANIFEST, 0, None, "retired-file",
                                        f"{retired} は schema 3 で廃止した。残っている"))

    skeleton = zh_counts.get("骨格", 0)
    supplement = zh_counts.get("補遺", 0)
    if args.cedict_entries is not None and skeleton != args.cedict_entries:
        violations.append(Violation(ZH_JA, 0, None, "skeleton-count-mismatch",
                                    f"骨格 entry が {skeleton:,}。"
                                    f"CC-CEDICT の {args.cedict_entries:,} と違う"))

    manifest_path = args.data / MANIFEST
    if not manifest_path.exists():
        violations.append(Violation(MANIFEST, 0, None, "missing-manifest",
                                    f"{manifest_path} が無い"))
    else:
        unreadable = object()
        try:
            manifest = json.loads(manifest_path.read_text(encoding="utf-8"))
        except json.JSONDecodeError as exc:
            manifest = unreadable
            violations.append(Violation(MANIFEST, 0, None, "broken-json", str(exc)))
        if manifest is not unreadable and not isinstance(manifest, dict):
            violations.append(Violation(MANIFEST, 0, None, "bad-type",
                                        f"manifest がオブジェクトでない: {manifest!r}"))
            manifest = unreadable
        if manifest is not unreadable:
            for key in ("schema_version", "generated", "files", "sources"):
                if key not in manifest:
                    violations.append(Violation(MANIFEST, 0, None, "missing-key",
                                                f"manifest に必須キー {key!r} が無い"))
            generated = manifest.get("generated")
            if "generated" in manifest and not (isinstance(generated, str) and generated):
                violations.append(Violation(MANIFEST, 0, None, "bad-type",
                                            f"generated が空でない文字列でない: {generated!r}"))
            if manifest.get("schema_version") != SCHEMA_VERSION:
                violations.append(Violation(MANIFEST, 0, None, "bad-schema-version",
                                            f"schema_version が {SCHEMA_VERSION} でない: "
                                            f"{manifest.get('schema_version')!r}"))
            if "sources" in manifest and manifest["sources"] != dataset_sources.SOURCES:
                violations.append(Violation(MANIFEST, 0, None, "sources-mismatch",
                                            "sources が tools/dataset_sources.py と違う"))
            files = manifest.get("files")
            if not isinstance(files, dict):
                violations.append(Violation(MANIFEST, 0, None, "bad-type",
                                            f"files がオブジェクトでない: {files!r}"))
            else:
                for relative, actual in line_counts.items():
                    entry = files.get(relative)
                    if entry is not None and not isinstance(entry, dict):
                        violations.append(Violation(MANIFEST, 0, None, "bad-type",
                                                    f"files[{relative!r}] がオブジェクトでない: "
                                                    f"{entry!r}"))
                        continue
                    if entry is None:
                        violations.append(Violation(MANIFEST, 0, None, "missing-key",
                                                    f"manifest に {relative!r} の項目が無い"))
                        continue
                    if "lines" not in entry:
                        violations.append(Violation(MANIFEST, 0, None, "missing-key",
                                                    f"files[{relative!r}] に lines が無い"))
                    elif entry["lines"] != actual:
                        violations.append(Violation(MANIFEST, 0, None, "line-count-mismatch",
                                                    f"{relative}: manifest {entry['lines']!r} / "
                                                    f"実ファイル {actual}"))
                zh_entry = files.get(ZH_JA)
                if isinstance(zh_entry, dict):
                    for key, actual in (("entries_skeleton", skeleton),
                                        ("entries_supplement", supplement),
                                        ("senses", sum(len(o["senses"]) for _, o in zh_rows
                                                       if isinstance(o.get("senses"), list)))):
                        if key not in zh_entry:
                            violations.append(Violation(MANIFEST, 0, None, "missing-key",
                                                        f"files[{ZH_JA!r}] に {key} が無い"))
                        elif zh_entry[key] != actual:
                            violations.append(Violation(MANIFEST, 0, None, "count-mismatch",
                                                        f"{key}: manifest {zh_entry[key]!r} / "
                                                        f"実データ {actual}"))
                    sizes = entries_file.sizes(zh_path)
                    if zh_entry.get("bytes") != sizes.compressed:
                        violations.append(Violation(MANIFEST, 0, None, "count-mismatch",
                                                    f"bytes: manifest {zh_entry.get('bytes')!r} / "
                                                    f"実ファイル {sizes.compressed}"))
                    if zh_entry.get("uncompressed_bytes") != sizes.uncompressed:
                        violations.append(
                            Violation(MANIFEST, 0, None, "count-mismatch",
                                      f"uncompressed_bytes: manifest "
                                      f"{zh_entry.get('uncompressed_bytes')!r} / "
                                      f"実ファイル {sizes.uncompressed}"))
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

    if args.existing:
        check_existing_coverage(zh_rows, args.existing, violations)
    if args.hsk_seed:
        check_hsk_coverage(zh_rows, args.hsk_seed, violations)

    print(f"合計 {sum(line_counts.values()):,}行")
    if args.counts:
        return 0
    if not violations:
        print("違反 0 件")
        return 0
    kinds = Counter(v.kind for v in violations)
    print(f"\n違反 {len(violations):,} 件")
    for kind, count in kinds.most_common():
        print(f"  {kind:<26} {count:>7,}")
    print()
    for violation in violations[:args.max_report]:
        print(violation)
    if len(violations) > args.max_report:
        print(f"… ほか {len(violations) - args.max_report:,} 件")
    return 1


if __name__ == "__main__":
    sys.exit(main())
