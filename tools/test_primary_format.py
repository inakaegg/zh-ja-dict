"""主な語義・既定の行の型と共通形式への対応を検査する。"""

import copy
import unittest

import common_format
import validate_data
import test_common_format
from test_common_format import sample_rows


class PrimaryFormatTests(unittest.TestCase):
    setUp = test_common_format.CommonFixture.setUp
    tearDown = test_common_format.CommonFixture.tearDown
    native_fixture = test_common_format.CommonFixture.native_fixture
    def test_export_and_validation(self):
        import json
        import entries_file
        rows, entries, manifest = self.native_fixture(10)
        rows[0].update(primary=2, default=True)
        sizes = entries_file.write(entries, (json.dumps(row, ensure_ascii=False) for row in rows))
        meta = json.loads(manifest.read_text())
        meta['files'][common_format.NATIVE_ENTRIES_KEY].update(
            bytes=sizes.compressed, uncompressed_bytes=sizes.uncompressed)
        manifest.write_text(json.dumps(meta))
        out = self.root / 'common'
        common_format.export_common(entries, manifest, out)
        stats = common_format.validate_common(out / entries_file.NAME, out / 'manifest.json', entries, manifest)
        self.assertEqual(stats.entries, 10)
        common = json.loads(next(entries_file.read_lines(out / entries_file.NAME)))
        extension = common['extensions']['zh-ja-dict']
        self.assertEqual(extension['primary_sense'], 2)
        self.assertIs(extension['default_row'], True)
        self.assertNotIn('primary', extension)
        self.assertNotIn('default_row', common_format.to_common_entry(rows[1])['extensions'].get('zh-ja-dict', {}))

    def test_native_acceptance_and_rejection(self):
        row = sample_rows(1)[0]
        for primary, default, accepted in ((1, True, True), (2, True, True),
                (True, True, False), (1.0, True, False), (0, True, False),
                (3, True, False), ('1', True, False), (1, False, False), (1, 1, False)):
            with self.subTest(primary=primary, default=default):
                native = dict(row, primary=primary, default=default)
                violations = []
                validate_data.validate_zh_ja_entries(None, [(1, native)], violations)
                self.assertEqual(not violations, accepted, [str(v) for v in violations])
                if accepted:
                    common_format.to_common_entry(native)
                else:
                    with self.assertRaises(common_format.CommonFormatError):
                        common_format.to_common_entry(native)
        with self.assertRaises(common_format.CommonFormatError):
            common_format.to_common_entry(dict(sample_rows(2)[1], primary=1))
        violations = []
        validate_data.validate_zh_ja_entries(None, [(1, dict(row, default=True)),
            (2, dict(row, pinyin='jì suàn', default=True))], violations)
        self.assertIn('duplicate-default', [v.kind for v in violations])

    def test_missing_primary_and_default_are_violations(self):
        # 適用を忘れたデータを正常として通さない。
        row = sample_rows(1)[0]
        self.assertGreaterEqual(len(row['senses']), 2)
        violations = []
        validate_data.validate_zh_ja_entries(None, [(1, dict(row, default=True))], violations)
        self.assertIn('missing-primary', [v.kind for v in violations])
        violations = []
        validate_data.validate_zh_ja_entries(None, [(1, dict(row, primary=1)),
            (2, dict(row, pinyin='jì suàn', primary=1))], violations)
        self.assertIn('missing-default', [v.kind for v in violations])

    def test_common_rejects_wrong_types_unknown_keys_and_missing_values(self):
        native = dict(sample_rows(1)[0], primary=1, default=True)
        common = common_format.to_common_entry(native)
        common_format.check_information_preserved(native, common)
        for key, value in (('primary_sense', True), ('primary_sense', 1.0),
                           ('primary_sense', 0), ('primary_sense', 3),
                           ('default_row', 1), ('default_row', False), ('unknown', 1)):
            with self.subTest(key=key, value=value):
                changed = copy.deepcopy(common)
                changed['extensions']['zh-ja-dict'][key] = value
                with self.assertRaises(common_format.CommonFormatError):
                    common_format.check_information_preserved(native, changed)
        for key in ('primary_sense', 'default_row'):
            changed = copy.deepcopy(common)
            del changed['extensions']['zh-ja-dict'][key]
            with self.assertRaises(common_format.CommonFormatError):
                common_format.check_information_preserved(native, changed)
