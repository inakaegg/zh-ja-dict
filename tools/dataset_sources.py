#!/usr/bin/env python3
"""生成物の出どころの表。書く側（build_dataset）と検査する側（validate_data）の正本。

`data/manifest.json` の `sources` はこの表と**完全に一致**していなければならない。
自由記述にすると、ここへ萌典の本文や jieba の頻度そのものを書き込む道が空いてしまう。
"""

from __future__ import annotations

SCHEMA_VERSION = 3

SOURCES = {
    "CC-CEDICT": {
        "what": "中日の骨格。見出し（簡体・繁体）・読み・英語の語義・量詞・語感の注記",
        "version": "2026-09-05",
        "license": "CC BY-SA 4.0",
        "by": "MDBG / CC-CEDICT",
    },
    "complete-hsk-vocabulary": {
        "what": "HSK 2.0 / 3.0 の級と品詞。級と品詞だけを収録",
        "license": "MIT",
        "by": "drkameleon",
    },
    "cppjieba": {
        "what": "訳を作る順番を決める内部の作業にだけ参照。頻度・順位は収録していない",
        "license": "MIT",
        "by": "yanyiwu",
    },
    "moedict": {
        "what": "見出しと語義の数の突き合わせにだけ参照。本文は収録していない",
        "version": "2026-09-06",
        "license": "CC BY-ND 3.0 TW",
        "by": "中華民國教育部（g0v が JSON 化）",
    },
    "zh-ja-dict": {
        "what": "CC-CEDICT に無い語の補遺と、訳を作るときの候補。この辞書の旧版",
        "license": "CC BY-SA 4.0",
        "by": "zh-ja-dict",
    },
}
