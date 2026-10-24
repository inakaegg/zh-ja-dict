"""品詞の上書き記録の適用と停止条件の試験。入力は試験用の中日行。"""

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
        self.records = self.root / 'pos-overrides.jsonl'
        self.manifest = self.root / 'manifest.json'
        self.rows = [
            {'word': '哇', 'pinyin': 'wā', 'pos': ['y', 'o'], 'senses': [{'ja': 'わあ'}], 'default': True},
            {'word': '哇', 'pinyin': 'wa', 'pos': ['y', 'o'], 'senses': [{'ja': 'わ'}]},
            {'word': '好', 'pinyin': 'hǎo', 'senses': [{'ja': 'よい'}]},
        ]
        self.record = {'word': '哇', 'trad': '', 'pinyin': 'wā', 'from': ['y', 'o'], 'pos': ['y', 'o', 'e'],
                       'reason': '感嘆詞'}
        self.write_records([self.record])
        entries_file.write(self.entries, (json.dumps(row, ensure_ascii=False) for row in self.rows))
        self.manifest.write_text(json.dumps({'files': {apply_pos.FILE_KEY: {'other': 7}}}))

    def write_records(self, records):
        self.records.write_text(''.join(json.dumps(row, ensure_ascii=False) + '\n' for row in records))

    def read_rows(self):
        return [json.loads(line) for line in entries_file.read_lines(self.entries)]

    def test_success_changes_only_the_recorded_row_and_is_idempotent(self):
        self.assertEqual(apply_pos.apply_pos(self.entries, self.records, self.manifest), (3, 1))
        rows = self.read_rows()
        self.assertEqual(rows[0]['pos'], ['y', 'o', 'e'])
        self.assertEqual(list(rows[0]), list(self.rows[0]))
        self.assertEqual(rows[1:], self.rows[1:])
        before = (self.entries.read_bytes(), self.manifest.read_bytes())
        apply_pos.apply_pos(self.entries, self.records, self.manifest)
        self.assertEqual(before, (self.entries.read_bytes(), self.manifest.read_bytes()))
        info = json.loads(self.manifest.read_text())['files'][apply_pos.FILE_KEY]
        self.assertEqual(info['other'], 7)
        self.assertEqual(info['lines'], 3)

    def test_row_without_pos_can_receive_pos(self):
        self.write_records([{'word': '好', 'trad': '', 'pinyin': 'hǎo', 'from': [], 'pos': ['a'], 'reason': '試験'}])
        apply_pos.apply_pos(self.entries, self.records, self.manifest)
        self.assertEqual(self.read_rows()[2]['pos'], ['a'])

    def test_stops_without_writing_when_records_do_not_match(self):
        cases = [
            ('品詞が記録と違う', {**self.record, 'from': ['y']}),
            ('行がデータに無い', {**self.record, 'pinyin': 'wà'}),
            ('未知の鍵', {**self.record, 'extra': 1}),
            ('品詞が不正', {**self.record, 'pos': []}),
            ('品詞が不正', {**self.record, 'pos': ['e', 'e']}),
            ('理由が無い', {key: value for key, value in self.record.items() if key != 'reason'}),
            ('変更が無い', {**self.record, 'pos': ['y', 'o']}),
        ]
        before = (self.entries.read_bytes(), self.manifest.read_bytes())
        for message, record in cases:
            with self.subTest(message):
                self.write_records([record])
                with self.assertRaisesRegex(apply_pos.PosError, message):
                    apply_pos.apply_pos(self.entries, self.records, self.manifest)
                self.assertEqual(before, (self.entries.read_bytes(), self.manifest.read_bytes()))
        self.write_records([self.record, self.record])
        with self.assertRaisesRegex(apply_pos.PosError, '記録の重複'):
            apply_pos.apply_pos(self.entries, self.records, self.manifest)

    def test_main_reports_errors_with_exit_code(self):
        self.write_records([{**self.record, 'from': ['y']}])
        with contextlib.redirect_stderr(io.StringIO()) as stderr:
            code = apply_pos.main(['--entries', str(self.entries), '--pos-overrides', str(self.records),
                                   '--manifest', str(self.manifest)])
        self.assertEqual(code, 1)
        self.assertIn('品詞が記録と違う', stderr.getvalue())


if __name__ == '__main__':
    unittest.main()
