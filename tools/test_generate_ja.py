#!/usr/bin/env python3
"""tools/generate_ja.py と tools/run_ja_shards.py の試験。

`claude -p` は呼ばない。応答を返す作り物の関数を差し込んで、まとめ方・受け取り方・
再開の仕方を確かめる。
"""

from __future__ import annotations

import contextlib
import io
import json
import pathlib
import sys
import tempfile
import unittest

sys.path.insert(0, str(pathlib.Path(__file__).resolve().parent))
import generate_ja as g  # noqa: E402
import run_ja_shards as r  # noqa: E402


def entry(entry_id, word="词", senses=None, **extra):
    return {"id": entry_id, "word": word, "pinyin": "cí",
            "senses": senses if senses is not None else [{"en": ["word"]}], **extra}


def answering(mapping, log=None):
    """頼まれた語義に `mapping` の訳を返す作り物の呼び出し。"""
    def call(prompt, system):
        if log is not None:
            log.append(prompt)
        payload = json.loads(prompt[prompt.index("["):])
        glosses = []
        for item in payload:
            for number in item["s"]:
                glosses.append({"id": item["id"], "sense": int(number),
                                "ja": mapping.get((item["id"], int(number)), "語")})
        return g.Reply(text=json.dumps({"glosses": glosses}, ensure_ascii=False),
                       usage={"input_tokens": 7, "output_tokens": 3}, seconds=0.5)
    return call


class Pending(unittest.TestCase):
    def test_訳のある語義は数えない(self):
        row = entry("c1", senses=[{"en": ["a"]}, {"ja": "既にある", "qa": "derived"},
                                  {"en": ["c"]}])
        self.assertEqual(g.pending_numbers(row), [1, 3])

    def test_番号は飛び番になる(self):
        row = entry("c1", senses=[{"ja": "x", "qa": "derived"}, {"en": ["b"]}])
        self.assertEqual(g.pending_numbers(row), [2])


class Prompt(unittest.TestCase):
    def test_本文は語だけで指示文を含まない(self):
        # 指示文は `--system-prompt` へ回す。本文に混ぜると呼び出しごとに読み込みが増える。
        body = g.build_prompt("", [entry("c1")])
        self.assertTrue(body.startswith("["))
        self.assertEqual(json.loads(body)[0]["id"], "c1")

    def test_作り直しの追い書きだけ本文の頭に付く(self):
        body = g.build_prompt("やり直し。", [entry("c1")])
        self.assertTrue(body.startswith("やり直し。\n["))


class Usage(unittest.TestCase):
    def test_使った量を足し合わせる(self):
        total = {}
        g.add_usage(total, {"input_tokens": 10, "output_tokens": 2})
        g.add_usage(total, {"input_tokens": 5, "cache_read_input_tokens": 700})
        self.assertEqual(total, {"input_tokens": 15, "output_tokens": 2,
                                 "cache_read_input_tokens": 700})

    def test_数でない値は無視する(self):
        self.assertEqual(g.add_usage({}, {"service_tier": "standard"}), {})

    def test_usage_が無くても落ちない(self):
        self.assertEqual(g.add_usage({}, None), {})


class Payload(unittest.TestCase):
    """本文は呼び出しごとに丸ごと送り直すので、短さがそのまま費用になる。"""

    def test_訳の要る語義だけを送る(self):
        row = entry("c1", senses=[{"en": ["a"]}, {"ja": "x", "qa": "derived"},
                                  {"en": ["c"], "misc": ["coll"]}])
        payload = json.loads(g.build_payload([row]))
        self.assertEqual(payload[0]["s"], {"1": "a", "3": "c"})
        self.assertEqual(payload[0]["m"], {"3": "coll"})

    def test_英語の語義は区切って1つの文字列にする(self):
        row = entry("c1", senses=[{"en": ["age", "era"]}])
        self.assertEqual(json.loads(g.build_payload([row]))[0]["s"], {"1": "age; era"})

    def test_印が無ければ送らない(self):
        payload = json.loads(g.build_payload([entry("c1")]))
        self.assertNotIn("m", payload[0])

    def test_既存の訳を手掛かりとして渡す(self):
        row = entry("c1", seed_gloss=["上司", "上層部"])
        payload = json.loads(g.build_payload([row]))
        self.assertEqual(payload[0]["h"], "上司、上層部")

    def test_手掛かりが無ければ送らない(self):
        payload = json.loads(g.build_payload([entry("c1")]))
        self.assertNotIn("h", payload[0])

    def test_区切りに空白を入れない(self):
        body = g.build_payload([entry("c1")])
        self.assertNotIn(", ", body)
        self.assertNotIn('": ', body)

    def test_鍵は短くする(self):
        payload = json.loads(g.build_payload([entry("c1", seed_gloss=["上司"])]))
        self.assertEqual(set(payload[0]), {"id", "w", "py", "s", "h"})


class Chunks(unittest.TestCase):
    def test_語義の数でまとめる(self):
        rows = [entry(f"c{i}", senses=[{"en": ["a"]}, {"en": ["b"]}]) for i in range(5)]
        groups = list(g.chunks(rows, batch=100, senses_per_call=4))
        self.assertEqual([len(x) for x in groups], [2, 2, 1])

    def test_訳のある語義は予算に数えない(self):
        rows = [entry(f"c{i}", senses=[{"ja": "x", "qa": "derived"}, {"en": ["b"]}])
                for i in range(5)]
        groups = list(g.chunks(rows, batch=100, senses_per_call=2))
        self.assertEqual([len(x) for x in groups], [2, 2, 1])

    def test_entry数の天井も効く(self):
        rows = [entry(f"c{i}") for i in range(5)]
        groups = list(g.chunks(rows, batch=2, senses_per_call=100))
        self.assertEqual([len(x) for x in groups], [2, 2, 1])


class Accept(unittest.TestCase):
    def setUp(self):
        self.chunk = [entry("c1", senses=[{"en": ["a"]}, {"ja": "x", "qa": "derived"}])]

    def test_頼んだ番号だけ受け取る(self):
        kept, rejected = g.accept(self.chunk, [
            {"id": "c1", "sense": 1, "ja": "語"},
            {"id": "c1", "sense": 2, "ja": "頼んでいない"},   # 訳は既にある
            {"id": "c9", "sense": 1, "ja": "知らない語"},
        ])
        self.assertEqual([x["sense"] for x in kept], [1])
        self.assertEqual(len(rejected), 2)

    def test_重複は落とす(self):
        kept, rejected = g.accept(self.chunk, [
            {"id": "c1", "sense": 1, "ja": "語"},
            {"id": "c1", "sense": 1, "ja": "二度目"},
        ])
        self.assertEqual(len(kept), 1)
        self.assertEqual(len(rejected), 1)

    def test_番号が数でなければ落とす(self):
        kept, rejected = g.accept(self.chunk, [{"id": "c1", "sense": "いち", "ja": "語"}])
        self.assertEqual(kept, [])
        self.assertEqual(len(rejected), 1)


class Finished(unittest.TestCase):
    def test_要る番号がそろって初めて済み(self):
        rows = [entry("c1", senses=[{"en": ["a"]}, {"en": ["b"]}])]
        self.assertEqual(g.finished_ids(rows, [{"id": "c1", "sense": 1, "ja": "語"}]), set())
        self.assertEqual(
            g.finished_ids(rows, [{"id": "c1", "sense": 1, "ja": "語"},
                                  {"id": "c1", "sense": 2, "ja": "語"}]), {"c1"})

    def test_飛び番でもそろえばよい(self):
        rows = [entry("c1", senses=[{"ja": "x", "qa": "derived"}, {"en": ["b"]}])]
        self.assertEqual(g.finished_ids(rows, [{"id": "c1", "sense": 2, "ja": "語"}]), {"c1"})


class Shard(unittest.TestCase):
    def test_剰余で分ける(self):
        rows = [entry(f"c{i}") for i in range(7)]
        parts = [g.select_shard(rows, i, 3) for i in range(3)]
        self.assertEqual([len(p) for p in parts], [3, 2, 2])
        self.assertEqual(sorted(x["id"] for part in parts for x in part),
                         sorted(x["id"] for x in rows))


class SampleEvenly(unittest.TestCase):
    def test_両端を含めて散らす(self):
        rows = [entry(f"c{i}") for i in range(10)]
        picked = g.sample_evenly(rows, 3)
        # 刻みは (10-1)/(3-1)=4.5。Python の round は偶数へ寄せるので 4 になる。
        self.assertEqual([x["id"] for x in picked], ["c0", "c4", "c9"])

    def test_数が足りればそのまま(self):
        rows = [entry("c1")]
        self.assertEqual(len(g.sample_evenly(rows, 5)), 1)


class Run(unittest.TestCase):
    def setUp(self):
        self.dir = pathlib.Path(tempfile.mkdtemp())
        self.out = self.dir / "ja.jsonl"

    @staticmethod
    def quietly(*args, **kwargs):
        """進み具合は標準エラーへ出る。試験の結果を読みにくくするので伏せる。"""
        with contextlib.redirect_stderr(io.StringIO()):
            return g.run(*args, **kwargs)

    def test_訳を書き足す(self):
        rows = [entry("c1", senses=[{"en": ["a"]}, {"en": ["b"]}])]
        written = self.quietly(rows, self.out, rules="", call=answering({}),
                               senses_per_call=10)
        self.assertEqual(written, 2)
        got = [json.loads(x) for x in self.out.read_text(encoding="utf-8").splitlines()]
        self.assertEqual([x["sense"] for x in got], [1, 2])

    def test_二度目は済んだ語を聞き直さない(self):
        rows = [entry("c1"), entry("c2")]
        self.quietly(rows, self.out, rules="", call=answering({}), senses_per_call=10)
        log = []
        written = self.quietly(rows, self.out, rules="", call=answering({}, log),
                        senses_per_call=10)
        self.assertEqual(written, 0)
        self.assertEqual(log, [])

    def test_読点を揃える(self):
        rows = [entry("c1")]
        self.quietly(rows, self.out, rules="",
                     call=answering({("c1", 1): "上司，上層部"}), senses_per_call=10)
        got = json.loads(self.out.read_text(encoding="utf-8").splitlines()[0])
        self.assertEqual(got["ja"], "上司、上層部")

    def test_max_callsで止まる(self):
        # 呼び方を測るときに、決めた回数だけ回して止められること。
        rows = [entry(f"c{i}") for i in range(10)]
        written = self.quietly(rows, self.out, rules="", call=answering({}),
                               senses_per_call=1, max_calls=3)
        self.assertEqual(written, 3)

    def test_壊れた応答でも止まらない(self):
        def broken(prompt, system):
            return g.Reply(text="JSONではない文章", usage={}, seconds=0.1)
        rows = [entry("c1")]
        written = self.quietly(rows, self.out, rules="", call=broken, senses_per_call=10)
        self.assertEqual(written, 0)


class Repair(unittest.TestCase):
    def test_検査に落ちた訳だけ落とす(self):
        rows = [{"id": "c1", "sense": 1, "ja": "上司"},
                {"id": "c2", "sense": 1, "ja": "shàng jí"}]
        kept, dropped = g.drop_invalid(rows, set())
        self.assertEqual([x["id"] for x in kept], ["c1"])
        self.assertEqual([x["id"] for x in dropped], ["c2"])

    def test_担当外の語は検査しない(self):
        rows = [{"id": "c2", "sense": 1, "ja": "shàng jí"}]
        kept, dropped = g.drop_invalid(rows, set(), mine={"c1"})
        self.assertEqual(len(kept), 1)
        self.assertEqual(dropped, [])


class Parsing(unittest.TestCase):
    def test_囲みつきの応答を読む(self):
        text = '前置き\n```json\n{"glosses":[{"id":"c1","sense":1,"ja":"語"}]}\n```\n'
        self.assertEqual(g.parse_response(text)[0]["ja"], "語")

    def test_キーが足りなければ例外(self):
        with self.assertRaises(g.BadResponse):
            g.parse_response('{"glosses":[{"id":"c1","sense":1}]}')

    def test_JSONが無ければ例外(self):
        with self.assertRaises(g.BadResponse):
            g.parse_response("できませんでした")


class RateLimit(unittest.TestCase):
    def test_上限の文面を見分ける(self):
        self.assertTrue(g.looks_rate_limited("Claude usage limit reached"))
        self.assertTrue(g.looks_rate_limited("HTTP 429"))
        self.assertFalse(g.looks_rate_limited("普通の失敗"))

    def test_待って掛け直す(self):
        calls = []

        def call(prompt, system):
            calls.append(prompt)
            if len(calls) < 3:
                raise g.RateLimited("usage limit")
            return g.Reply(text="ok", usage={}, seconds=0.1)
        wrapped = g.retrying(call, waits=(1, 1), sleep=lambda _: None, log=lambda _: None)
        self.assertEqual(wrapped("p", "規則").text, "ok")
        self.assertEqual(calls, ["p", "p", "p"])


class Shards(unittest.TestCase):
    def test_合流は重複を捨てて並べ替える(self):
        with tempfile.TemporaryDirectory() as tmp:
            directory = pathlib.Path(tmp)
            (directory / "shard-00.jsonl").write_text(
                '{"id":"c10","sense":1,"ja":"十"}\n{"id":"c2","sense":2,"ja":"二の二"}\n',
                encoding="utf-8")
            (directory / "shard-01.jsonl").write_text(
                '{"id":"c2","sense":1,"ja":"二"}\n{"id":"c10","sense":1,"ja":"重複"}\n'
                '{"id":"x1","sense":1,"ja":"補遺"}\n',
                encoding="utf-8")
            rows, duplicates = r.merge_rows(sorted(directory.glob("shard-*.jsonl")))
        self.assertEqual(duplicates, 1)
        # `c2` が `c10` より前（番号順）。補遺 `x` は後ろ。
        self.assertEqual([(x["id"], x["sense"]) for x in rows],
                         [("c2", 1), ("c2", 2), ("c10", 1), ("x1", 1)])

    def test_検査は足りない語義と違反を見つける(self):
        rows = [entry("c1", senses=[{"en": ["supply"]}, {"en": ["b"]}])]
        report = r.verify(rows, [{"id": "c1", "sense": 1, "ja": "supplyする"}])
        self.assertEqual(report.missing, ["c1"])
        self.assertEqual(len(report.violations), 1)

    def test_全部そろえば違反ゼロ(self):
        rows = [entry("c1", senses=[{"en": ["a"]}])]
        report = r.verify(rows, [{"id": "c1", "sense": 1, "ja": "語"}])
        self.assertEqual(report.missing, [])
        self.assertEqual(report.violations, [])

    def test_止まりの検知(self):
        history = [(0, 5), (60 * 31, 5)]
        self.assertTrue(r.stalled(history, 30))
        self.assertFalse(r.stalled([(0, 5), (60 * 31, 6)], 30))

    def test_パイロットは常用語と裾を混ぜる(self):
        rows = [entry(f"c{i}") for i in range(10)]
        targets = r.plan_targets(rows, set(), ["c9", "c8"], pilot=4, pilot_head=2)
        self.assertEqual(targets[:2], ["c9", "c8"])
        self.assertEqual(len(targets), 4)


if __name__ == "__main__":
    unittest.main()
