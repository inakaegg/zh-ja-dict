#!/usr/bin/env python3
"""entries_file.py の自己テスト。

    python3 tools/test_entries_file.py

配布する `data/entries.jsonl.deflate` の入れ物を試す。**形式が raw DEFLATE で
あること自体を試験する。** ここが zlib ヘッダ付きに変わると、Apple の
Compression framework が読めなくなり、読み手（アプリ）だけが壊れるため。
"""

from __future__ import annotations

import pathlib
import sys
import tempfile
import unittest
import zlib

sys.path.insert(0, str(pathlib.Path(__file__).resolve().parent))
import entries_file  # noqa: E402


LINES = ['{"id": "1", "k": "手紙"}', '{"id": "2", "k": "汽車"}', '{"id": "3", "zh": "学习"}']


class TestRoundTrip(unittest.TestCase):
    def write(self, lines=None):
        holder = tempfile.TemporaryDirectory()
        self.addCleanup(holder.cleanup)
        path = pathlib.Path(holder.name) / entries_file.NAME
        sizes = entries_file.write(path, lines if lines is not None else LINES)
        return path, sizes

    def test_what_was_written_comes_back_line_by_line(self):
        path, _ = self.write()
        self.assertEqual(list(entries_file.read_lines(path)), LINES)

    def test_japanese_and_chinese_survive_the_round_trip(self):
        path, _ = self.write(['{"t": "気をつける"}', '{"zh": "没问题、没事"}'])
        self.assertEqual(list(entries_file.read_lines(path)), ['{"t": "気をつける"}', '{"zh": "没问题、没事"}'])

    def test_no_file_is_left_empty_of_a_trailing_newline(self):
        # 行の区切りは改行。最後の行にも付けて、追記や連結で行が溶けないようにする
        path, _ = self.write()
        raw = zlib.decompressobj(-15).decompress(path.read_bytes())
        self.assertTrue(raw.endswith(b"\n"))

    def test_an_empty_dictionary_is_still_a_valid_file(self):
        path, sizes = self.write([])
        self.assertEqual(list(entries_file.read_lines(path)), [])
        self.assertEqual(sizes.uncompressed, 0)


class TestChunkBoundary(unittest.TestCase):
    """読むときのかたまりの切れ目。1文字が2つのかたまりに跨っても壊れないこと。"""

    def test_a_character_split_across_two_chunks_survives(self):
        holder = tempfile.TemporaryDirectory()
        self.addCleanup(holder.cleanup)
        path = pathlib.Path(holder.name) / entries_file.NAME
        lines = ['{"t": "気をつける", "zh": "小心、注意"}' for _ in range(200)]
        entries_file.write(path, lines)
        original = entries_file._CHUNK
        self.addCleanup(setattr, entries_file, "_CHUNK", original)
        # かたまりごとに decode する書き方は、この大きさで実際に UnicodeDecodeError になる
        for size in (1, 3, 7, 64):
            with self.subTest(chunk=size):
                entries_file._CHUNK = size
                self.assertEqual(list(entries_file.read_lines(path)), lines)


class TestTruncatedOrPadded(unittest.TestCase):
    """途中で切れた・後ろにごみが付いたファイルを正常として受け取らないこと。

    `decompress()` も `flush()` も、末尾が欠けているだけでは例外を出さない。
    ここを見ないと、切れた辞書が「読めた」ことになって件数の検査まで進んでしまう。
    """

    def written(self, lines=None):
        holder = tempfile.TemporaryDirectory()
        self.addCleanup(holder.cleanup)
        path = pathlib.Path(holder.name) / entries_file.NAME
        entries_file.write(path, lines if lines is not None else LINES * 40)
        return path

    def test_a_file_missing_its_last_bytes_is_rejected(self):
        for cut in (1, 2, 5, 100):
            with self.subTest(cut=cut):
                path = self.written()
                path.write_bytes(path.read_bytes()[:-cut])
                with self.assertRaises(zlib.error):
                    list(entries_file.read_lines(path))
                with self.assertRaises(zlib.error):
                    entries_file.sizes(path)

    def test_a_file_with_extra_bytes_at_the_end_is_rejected(self):
        path = self.written()
        path.write_bytes(path.read_bytes() + b"\x00\x01\x02")
        with self.assertRaises(zlib.error):
            list(entries_file.read_lines(path))
        with self.assertRaises(zlib.error):
            entries_file.sizes(path)

    def test_an_intact_file_is_accepted(self):
        path = self.written()
        self.assertEqual(len(list(entries_file.read_lines(path))), len(LINES) * 40)
        self.assertEqual(entries_file.sizes(path).compressed, path.stat().st_size)


class TestSizes(unittest.TestCase):
    def test_the_reported_sizes_match_the_file_and_its_contents(self):
        with tempfile.TemporaryDirectory() as tmp:
            path = pathlib.Path(tmp) / entries_file.NAME
            sizes = entries_file.write(path, LINES)
            self.assertEqual(sizes.compressed, path.stat().st_size)
            self.assertEqual(sizes.uncompressed, sum(len((line + "\n").encode("utf-8")) for line in LINES))
            self.assertEqual(entries_file.sizes(path), sizes)


class TestFormat(unittest.TestCase):
    """Apple の Compression framework が読める形であること。"""

    def raw(self):
        with tempfile.TemporaryDirectory() as tmp:
            path = pathlib.Path(tmp) / entries_file.NAME
            entries_file.write(path, LINES)
            return path.read_bytes()

    def test_the_bytes_are_raw_deflate(self):
        # ヘッダ無しの DEFLATE。`COMPRESSION_ZLIB` はこの形を期待する
        self.assertEqual(
            zlib.decompressobj(-15).decompress(self.raw()).decode("utf-8").splitlines(), LINES
        )

    def test_the_bytes_are_not_wrapped_in_a_zlib_or_gzip_header(self):
        # ヘッダを付けてしまう変更を止める。Python の既定（zlib ヘッダ）では読めないはず
        raw = self.raw()
        self.assertNotEqual(raw[:2], b"\x1f\x8b")
        with self.assertRaises(zlib.error):
            zlib.decompress(raw)

    def test_the_name_says_which_compression_it_is(self):
        self.assertTrue(entries_file.NAME.endswith("." + entries_file.COMPRESSION))


if __name__ == "__main__":
    unittest.main(verbosity=2)
