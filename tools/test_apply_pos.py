"""品詞を足す記録の適用と停止条件の試験。入力は試験用の中日行。"""

import contextlib
import io
import json
import pathlib
import tempfile
import unittest

import apply_pos
import entries_file


class ApplyPosTests(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory()
        self.addCleanup(self.temp.cleanup)
        self.root = pathlib.Path(self.temp.name)
        self.entries = self.root / entries_file.NAME
        self.records = self.root / 'pos-additions.jsonl'
        self.manifest = self.root / 'manifest.json'
        self.rows = [
            {'word': '哇', 'pinyin': 'wā', 'pos': ['y', 'o'], 'senses': [{'ja': 'わあ'}], 'default': True},
            {'word': '哇', 'pinyin': 'wa', 'pos': ['y', 'o'], 'senses': [{'ja': 'わ'}]},
            {'word': '好', 'pinyin': 'hǎo', 'hsk2': 1, 'seed': 'x', 'senses': [{'ja': 'よい'}], 'primary': 1},
        ]
        self.record = {'word': '哇', 'trad': '', 'pinyin': 'wā', 'add': ['e'], 'reason': '感嘆詞'}
        self.write_records([self.record])
        self.write_rows(self.rows)
        self.manifest.write_text(json.dumps({'files': {apply_pos.FILE_KEY: {'other': 7}}}))

    def write_rows(self, rows):
        entries_file.write(self.entries, (json.dumps(row, ensure_ascii=False) for row in rows))

    def write_records(self, records):
        self.records.write_text(''.join(json.dumps(row, ensure_ascii=False) + '\n' for row in records))

    def read_rows(self):
        return [json.loads(line) for line in entries_file.read_lines(self.entries)]

    def run_apply(self):
        with contextlib.redirect_stderr(io.StringIO()) as stderr:
            result = apply_pos.apply_pos(self.entries, self.records, self.manifest)
        return result, stderr.getvalue()

    def test_adds_only_missing_codes_to_the_recorded_row_and_is_idempotent(self):
        self.assertEqual(self.run_apply()[0], (3, 1, 0))
        rows = self.read_rows()
        self.assertEqual(rows[0]['pos'], ['y', 'o', 'e'])
        self.assertEqual(list(rows[0]), list(self.rows[0]))
        self.assertEqual(rows[1:], self.rows[1:])
        before = (self.entries.read_bytes(), self.manifest.read_bytes())
        # 2回目は足す品詞が既にあるので、変えずに「既にあった」と数える。
        self.assertEqual(self.run_apply()[0], (3, 0, 1))
        self.assertEqual(before, (self.entries.read_bytes(), self.manifest.read_bytes()))
        info = json.loads(self.manifest.read_text())['files'][apply_pos.FILE_KEY]
        self.assertEqual(info['other'], 7)
        self.assertEqual(info['lines'], 3)

    def test_keeps_upstream_changes_to_other_codes(self):
        # 上流の品詞が変わっても止めず、足す品詞だけを足す。
        self.rows[0]['pos'] = ['o']
        self.write_rows(self.rows)
        self.run_apply()
        self.assertEqual(self.read_rows()[0]['pos'], ['o', 'e'])

    def test_row_without_pos_gets_pos_in_the_key_order(self):
        # 鍵の並びを決まった位置にし、apply_primary と順を入れ替えても同じバイト列にする。
        self.write_records([{'word': '好', 'trad': '', 'pinyin': 'hǎo', 'add': ['a'], 'reason': '試験'}])
        self.run_apply()
        row = self.read_rows()[2]
        self.assertEqual(list(row), ['word', 'pinyin', 'hsk2', 'pos', 'seed', 'senses', 'primary'])
        self.assertEqual(row['pos'], ['a'])

    def test_missing_row_only_warns(self):
        self.write_records([{**self.record, 'pinyin': 'wà'}])
        result, stderr = self.run_apply()
        self.assertEqual(result, (3, 0, 0))
        self.assertIn('行がデータに無い', stderr)
        self.assertEqual(self.read_rows(), self.rows)

    def test_stops_without_writing_when_records_are_invalid(self):
        cases = [
            ('未知の鍵', {**self.record, 'extra': 1}),
            ('品詞が不正', {**self.record, 'add': []}),
            ('品詞が不正', {**self.record, 'add': ['e', 'e']}),
            ('品詞が不正', {**self.record, 'add': ['wow']}),
            ('理由が無い', {key: value for key, value in self.record.items() if key != 'reason'}),
        ]
        before = (self.entries.read_bytes(), self.manifest.read_bytes())
        for message, record in cases:
            with self.subTest(message):
                self.write_records([record])
                with self.assertRaisesRegex(apply_pos.PosError, message):
                    self.run_apply()
                self.assertEqual(before, (self.entries.read_bytes(), self.manifest.read_bytes()))
        self.write_records([self.record, self.record])
        with self.assertRaisesRegex(apply_pos.PosError, '記録の重複'):
            self.run_apply()
        self.records.write_text(json.dumps(self.record, ensure_ascii=False) + '\n\n')
        with self.assertRaisesRegex(apply_pos.PosError, ':2: JSONとして読めない'):
            self.run_apply()

    def test_stops_on_duplicate_data_rows(self):
        self.write_rows(self.rows + [self.rows[0]])
        with self.assertRaisesRegex(apply_pos.PosError, 'データの行の重複'):
            self.run_apply()

    def test_main_reports_errors_with_exit_code(self):
        self.write_records([{**self.record, 'add': []}])
        with contextlib.redirect_stderr(io.StringIO()) as stderr:
            code = apply_pos.main(['--entries', str(self.entries), '--pos-additions', str(self.records),
                                   '--manifest', str(self.manifest)])
        self.assertEqual(code, 1)
        self.assertIn('品詞が不正', stderr.getvalue())


if __name__ == '__main__':
    unittest.main()
