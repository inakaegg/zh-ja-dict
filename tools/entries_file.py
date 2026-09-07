#!/usr/bin/env python3
"""配布する辞書データの入れ物。書く側・読む側・検査する側の正本。

`data/entries.jsonl.deflate` は、1行1 entry の JSON Lines（UTF-8、LF）を
**raw DEFLATE**（RFC 1951）で1ファイルにしたもの。**gzip・zlib のヘッダは付けない。**

読み手は Apple の Compression framework でそのまま展開する。

    let plain = try (data as NSData).decompressed(using: .zlib) as Data

Swift の `.zlib` と C の `COMPRESSION_ZLIB` は名前に反して**ヘッダ無しの DEFLATE**を
指す。ここで zlib ヘッダを付けると、Python 側は何も気付かないまま読み手だけが壊れる。
`tools/test_entries_file.py` がこの形を試験している。

Python 3.9 以上。標準ライブラリだけを使う。
"""

from __future__ import annotations

import codecs
import pathlib
import zlib
from typing import Iterable, Iterator, NamedTuple

NAME = "entries.jsonl.deflate"
COMPRESSION = "deflate"

# ヘッダ無しの DEFLATE を指す窓の大きさ。負の値がヘッダ無しの合図になる。
_RAW_DEFLATE = -15
# 同梱物なので大きさを優先する。作るのは2秒ほど、展開は0.4秒ほど（実測）。
_LEVEL = 9
_CHUNK = 1 << 20


class Sizes(NamedTuple):
    """圧縮後と展開後の大きさ（バイト）。manifest へ書く値。"""

    compressed: int
    uncompressed: int


def write(path: pathlib.Path, lines: Iterable[str]) -> Sizes:
    """1行1 entry の文字列（改行は付けずに渡す）を圧縮して書き、大きさを返す。"""
    compressor = zlib.compressobj(_LEVEL, zlib.DEFLATED, _RAW_DEFLATE)
    uncompressed = 0
    path.parent.mkdir(parents=True, exist_ok=True)
    with path.open("wb") as sink:
        for line in lines:
            block = (line + "\n").encode("utf-8")
            uncompressed += len(block)
            sink.write(compressor.compress(block))
        sink.write(compressor.flush())
    return Sizes(compressed=path.stat().st_size, uncompressed=uncompressed)


def _check_complete(decompressor: "zlib._Decompress") -> None:
    """圧縮の流れが最後まで在ったかを見る。

    **末尾が欠けても `decompress()` も `flush()` も例外を出さない。** 途中まで
    展開して黙って終わるので、切れたファイルが正しいものとして通ってしまう。
    流れの終わりの印（`eof`）と、その後ろに何も付いていないこと（`unused_data`）を
    必ず確かめる。
    """
    if not decompressor.eof:
        raise zlib.error("圧縮の流れが途中で終わっている（末尾が欠けている）")
    if decompressor.unused_data:
        raise zlib.error(f"圧縮の流れの後ろに余分なバイトがある（{len(decompressor.unused_data)} バイト）")


def read_lines(path: pathlib.Path) -> Iterator[str]:
    """展開しながら1行ずつ返す。全量（50MB近い）を記憶へ載せないため。

    かたまりの切れ目は文字の切れ目と一致しない。**1文字が2つのかたまりに跨るので、
    かたまりごとに `decode()` してはいけない。** 続きを持ち越せる復号器を使う。
    """
    decompressor = zlib.decompressobj(_RAW_DEFLATE)
    decoder = codecs.getincrementaldecoder("utf-8")()
    remainder = ""
    with path.open("rb") as source:
        while True:
            chunk = source.read(_CHUNK)
            if not chunk:
                break
            text = remainder + decoder.decode(decompressor.decompress(chunk))
            *complete, remainder = text.split("\n")
            yield from complete
    remainder += decoder.decode(decompressor.flush(), True)
    _check_complete(decompressor)
    for line in remainder.split("\n"):
        if line:
            yield line


def sizes(path: pathlib.Path) -> Sizes:
    """既にあるファイルの大きさを数える。展開して初めて分かる方も返す。"""
    decompressor = zlib.decompressobj(_RAW_DEFLATE)
    uncompressed = 0
    with path.open("rb") as source:
        while True:
            chunk = source.read(_CHUNK)
            if not chunk:
                break
            uncompressed += len(decompressor.decompress(chunk))
    uncompressed += len(decompressor.flush())
    _check_complete(decompressor)
    return Sizes(compressed=path.stat().st_size, uncompressed=uncompressed)
