"""モデルを呼ばず、実際の圧縮形式とJSON応答で選択・再開を確かめる。"""
import json
import pathlib
import subprocess
import tempfile
import unittest
from unittest.mock import patch

import choose_primary as c
import entries_file
import generate_ja as g


def entry(word, pinyin, senses, trad=None):
    row = {"word": word, "pinyin": pinyin,
           "senses": [{"ja": ja, "en": [ja, "補足"]} for ja in senses]}
    if trad is not None:
        row["trad"] = trad
    return row


class ChoosePrimaryTests(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.addCleanup(self.tmp.cleanup)
        self.root = pathlib.Path(self.tmp.name)
        self.senses = self.root / "senses.jsonl"
        self.defaults = self.root / "defaults.jsonl"
        # CC-CEDICT由来の同梱物にある「被」「和」の構造を短くした試験データ。
        self.entries = [entry("被", "bèi", ["掛け布団", "〜される"]),
                        entry("和", "hé", ["〜と", "穏やか"]),
                        entry("和", "Hé", ["姓の和"], "和")]
        self.calls = []

    def call(self, payload, system):
        groups = json.loads(payload)
        self.calls.append(groups)
        reply = {"primary": [], "defaults": []}
        for group in groups:
            for row in group["rows"]:
                if len(row["s"]) >= 2:
                    reply["primary"].append({"w": group["w"], "r": row["r"], "n": 2})
            if len(group["rows"]) >= 2:
                reply["defaults"].append({"w": group["w"], "r": 1})
        return g.Reply(json.dumps(reply), {"input_tokens": 5, "output_tokens": 2}, 0)

    def run_selection(self, **kwargs):
        return c.run(self.entries, self.senses, self.defaults, self.call, "指示", **kwargs)

    def read(self, path):
        return [json.loads(line) for line in path.read_text().splitlines()]

    def test_outputs_and_all_rows(self):
        self.assertEqual(self.run_selection(), (2, 1))
        self.assertEqual(self.read(self.senses)[0],
                         {"word": "被", "trad": "", "pinyin": "bèi", "sense": 2, "ja": "〜される"})
        self.assertEqual(self.read(self.defaults), [{"word": "和", "trad": "", "pinyin": "hé"}])
        self.assertEqual(len(self.calls[0][1]["rows"]), 2)
        self.assertEqual(self.calls[0][0]["rows"][0]["s"]["1"]["en"], "掛け布団")

    def test_resume_and_changed_translation(self):
        self.run_selection()
        self.assertEqual(self.run_selection(), (0, 0))
        self.assertEqual(len(self.calls), 1)
        self.entries[1]["senses"][1]["ja"] = "平和な"
        self.assertEqual(self.run_selection(), (1, 0))
        self.assertEqual(len(self.calls[-1][0]["rows"]), 2)
        self.assertEqual(self.read(self.senses)[-1]["ja"], "平和な")

    def test_resume_missing_default(self):
        self.run_selection()
        self.defaults.write_text("")
        self.assertEqual(self.run_selection(), (0, 1))
        self.assertEqual([group["w"] for group in self.calls[-1]], ["和"])

    def test_invalid_elements_are_counted(self):
        reply = {"primary": [None, [], {"w": "外", "r": 1, "n": 1},
                             {"w": "被", "r": 0, "n": 1}, {"w": "被", "r": True, "n": 1},
                             {"w": "被", "r": 1, "n": 3}, {"w": "被", "r": 1, "n": True},
                             {"w": "和", "r": 2, "n": 1}, {"w": "被", "r": 1, "n": 2},
                             {"w": "被", "r": 1, "n": 1}],
                 "defaults": [1, {"w": "和", "r": 3}, {"w": "和", "r": 1},
                              {"w": "和", "r": 2}, {"w": "被", "r": 1}]}
        senses, defaults, dropped = c.parse_response(json.dumps(reply), c.grouped(self.entries))
        self.assertEqual((len(senses), len(defaults), dropped), (1, 1, 13))

    def test_bad_response(self):
        for reply in ("なし", '{"primary": null,"defaults":[]}', '{bad}'):
            with self.assertRaises(g.BadResponse):
                c.parse_response(reply, c.grouped(self.entries))

    def test_token_budget(self):
        self.assertEqual(self.run_selection(senses_per_call=1, token_budget=7), (1, 0))
        self.assertEqual(len(self.calls), 1)
        self.assertEqual(self.run_selection(token_budget=0), (0, 0))
        self.assertEqual(len(self.calls), 1)
        self.assertEqual(c.spent_tokens({"input_tokens": 1, "output_tokens": 2,
                                      "cache_creation_input_tokens": 3, "cache_read_input_tokens": 4}), 10)

    def test_bad_response_still_spends_budget(self):
        def call(payload, system):
            self.calls.append(payload)
            return g.Reply("壊れた応答", {"input_tokens": 7}, 0)
        c.run(self.entries, self.senses, self.defaults, call, "", senses_per_call=1, token_budget=7)
        self.assertEqual(len(self.calls), 1)

    def test_words_cli_and_resume(self):
        packed = self.root / "entries.jsonl.deflate"
        entries_file.write(packed, (json.dumps(row) for row in self.entries))
        words = self.root / "words.txt"
        words.write_text("和\n\n存在しない\n", encoding="utf-8")
        args = ["--packed", str(packed), "--out-senses", str(self.senses),
                "--out-defaults", str(self.defaults), "--words", str(words), "--no-retry"]
        self.assertEqual(c.main(args, call=self.call), 0)
        self.assertEqual([group["w"] for group in self.calls[0]], ["和"])
        self.assertEqual(c.main(args, call=self.call), 0)
        self.assertEqual(len(self.calls), 1)

    def test_backend_and_retry(self):
        packed = self.root / "entries.jsonl.deflate"
        entries_file.write(packed, (json.dumps(row) for row in self.entries))
        args = ["--packed", str(packed), "--out-senses", str(self.senses),
                "--out-defaults", str(self.defaults)]
        with patch.object(c, "call_codex", side_effect=lambda payload, system, **kwargs: self.call(payload, system)) as codex:
            c.main(args + ["--no-retry", "--codex-model", "試験モデル"])
            self.assertEqual(codex.call_args.kwargs, {"model": "試験モデル"})
        self.senses.write_text("")
        self.defaults.write_text("")
        with patch.object(g, "call_claude", side_effect=self.call), \
                patch.object(g, "retrying", wraps=g.retrying) as retry:
            c.main(args + ["--backend", "claude"])
            retry.assert_called_once()

    def test_codex_command_without_model_call(self):
        def runner(command, **kwargs):
            self.assertIn("gpt-6.1-sol", command)
            self.assertIn("model_reasoning_effort=medium", command)
            self.assertIn("--ephemeral", command)
            self.assertEqual(kwargs["stdin"], subprocess.DEVNULL)
            events = [{"type": "item.completed", "item": {"type": "agent_message", "text": "{}"}},
                      {"type": "turn.completed", "usage": {"input_tokens": 10}}]
            return subprocess.CompletedProcess(command, 0, "\n".join(map(json.dumps, events)), "")
        reply = c.call_codex("入力", "指示", runner=runner)
        self.assertEqual(reply.text, "{}")
        self.assertEqual(reply.usage, {"input_tokens": 10})


if __name__ == "__main__":
    unittest.main()
