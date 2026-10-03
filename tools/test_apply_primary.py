"""主な語義の適用と停止条件の試験。入力は試験用の中日行。"""

import copy
import contextlib
import io
import json
import pathlib
import tempfile
import unittest

import apply_primary
import entries_file


class ApplyPrimaryTests(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory()
        self.addCleanup(self.temp.cleanup)
        self.root = pathlib.Path(self.temp.name)
        self.entries = self.root / entries_file.NAME
        self.primary = self.root / 'primary.jsonl'
        self.defaults = self.root / 'defaults.jsonl'
        self.manifest = self.root / 'manifest.json'
        self.rows = [
            {'word': '行', 'pinyin': 'xíng', 'senses': [{'ja': '行く'}, {'ja': 'よい'}],
             'primary': 1, 'default': True, 'moe': 'none'},
            {'word': '行', 'trad': '衍', 'pinyin': 'háng', 'senses': [{'ja': '列'}],
             'primary': 1},
            {'word': '好', 'pinyin': 'hǎo', 'senses': [{'ja': 'よい'}]},
        ]
        self.record = {'word': '行', 'trad': '', 'pinyin': 'xíng', 'sense': 2, 'ja': 'よい'}
        self.default = {'word': '行', 'trad': '衍', 'pinyin': 'háng'}
        self.write_inputs([self.record], [self.default])
        entries_file.write(self.entries, (json.dumps(row, ensure_ascii=False) for row in self.rows))
        self.manifest.write_text(json.dumps({'files': {apply_primary.FILE_KEY: {'other': 7}}}))

    def write_inputs(self, primary, defaults):
        for path, rows in ((self.primary, primary), (self.defaults, defaults)):
            path.write_text(''.join(json.dumps(row, ensure_ascii=False) + '\n' for row in rows))

    def run_apply(self):
        return apply_primary.apply_primary(self.entries, self.primary, self.defaults, self.manifest)

    def test_success_preserves_rows_and_other_keys_and_is_idempotent(self):
        self.assertEqual(self.run_apply(), (3, 1, 1))
        rows = [json.loads(line) for line in entries_file.read_lines(self.entries)]
        expected = copy.deepcopy(self.rows)
        for row in expected:
            row.pop('primary', None)
            row.pop('default', None)
        expected[0]['primary'] = 2
        expected[1]['default'] = True
        self.assertEqual(rows, expected)
        self.assertEqual([list(row) for row in rows], [list(row) for row in expected])
        before = (self.entries.read_bytes(), self.manifest.read_bytes())
        self.run_apply()
        self.assertEqual(before, (self.entries.read_bytes(), self.manifest.read_bytes()))
        info = json.loads(self.manifest.read_text())['files'][apply_primary.FILE_KEY]
        self.assertEqual(info['other'], 7)
        self.assertEqual(info['lines'], 3)
        self.assertEqual(info['senses'], 4)
        self.assertEqual(info['bytes'], self.entries.stat().st_size)
        self.assertEqual(info['uncompressed_bytes'], entries_file.sizes(self.entries).uncompressed)

    def test_all_stop_conditions_leave_artifacts_unchanged(self):
        unknown = dict(self.record, word='無')
        cases = [
            ([dict(self.record, ja='違う')], [self.default], '訳の不一致'),
            ([dict(self.record, sense=3)], [self.default], '訳の不一致'),
            ([unknown], [self.default], '行がデータに無い'),
            ([self.record], [dict(self.default, word='無')], '行がデータに無い'),
            ([self.record], [self.default, {k: self.record[k] for k in ('word', 'trad', 'pinyin')}], '既定が複数'),
            ([], [self.default], '主な語義の記録なし'),
            ([self.record], [], '既定なし'),
            ([self.record, self.record], [self.default], '記録の重複'),
            ([dict(self.record, sense=True)], [self.default], '番号または訳が不正'),
        ]
        before = (self.entries.read_bytes(), self.manifest.read_bytes())
        for primary, defaults, message in cases:
            with self.subTest(message=message):
                self.write_inputs(primary, defaults)
                with self.assertRaisesRegex(apply_primary.PrimaryError, message):
                    self.run_apply()
                self.assertEqual(before, (self.entries.read_bytes(), self.manifest.read_bytes()))
                output = io.StringIO()
                with contextlib.redirect_stderr(output):
                    result = apply_primary.main([
                        '--entries', str(self.entries), '--manifest', str(self.manifest),
                        '--primary-senses', str(self.primary), '--default-rows', str(self.defaults)])
                self.assertEqual(result, 1)
                self.assertIn(message, output.getvalue())

    def test_single_sense_record_is_checked_but_not_written(self):
        single = {'word': '好', 'pinyin': 'hǎo', 'sense': 1, 'ja': 'よい'}
        self.write_inputs([self.record, single], [self.default])
        self.run_apply()
        rows = [json.loads(line) for line in entries_file.read_lines(self.entries)]
        self.assertNotIn('primary', rows[-1])
