#!/usr/bin/env python3
"""zh-ja-dict schema 3 と共通辞書形式v1の相互変換・検査。"""

from __future__ import annotations

import copy
import hashlib
import itertools
import json
import os
import pathlib
from collections import OrderedDict
from typing import NamedTuple, Optional

import entries_file


SCHEMA_NAME = "learner-dictionary"
SCHEMA_VERSION = 1
DICTIONARY = "zh-ja-dict"
SOURCE_LANGUAGE = "zh"
TRANSLATION_LANGUAGES = ["ja"]
EXTENSION_KEY = "zh-ja-dict"
NATIVE_ENTRIES_KEY = f"zh-ja/{entries_file.NAME}"

COMMON_ENTRY_KEYS = ("id", "headwords", "readings", "levels", "verification",
                     "extensions", "senses")
NATIVE_ENTRY_KEYS = ("word", "trad", "pinyin", "tw_pr", "also_pr", "cl",
                     "hsk2", "hsk3", "pos", "src", "seed", "moe", "senses")
NATIVE_SENSE_KEYS = ("en", "ja", "qa", "unsure", "misc", "variant_of",
                     "see_also", "lsource", "s_inf")


class CommonFormatError(ValueError):
    """共通形式へ安全に写せない、または共通形式が契約と違う。"""


class ValidationStats(NamedTuple):
    entries: int
    senses: int
    translations: int


def sha256_file(path: pathlib.Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as source:
        while True:
            chunk = source.read(1 << 20)
            if not chunk:
                break
            digest.update(chunk)
    return digest.hexdigest()


def _load_json(path: pathlib.Path, label: str) -> dict:
    try:
        value = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, UnicodeError, json.JSONDecodeError) as error:
        raise CommonFormatError(f"{label}を読めない: {error}") from error
    if not isinstance(value, dict):
        raise CommonFormatError(f"{label}のルートがobjectでない")
    return value


def _native_file_info(manifest: dict) -> dict:
    files = manifest.get("files")
    if not isinstance(files, dict) or not isinstance(files.get(NATIVE_ENTRIES_KEY), dict):
        raise CommonFormatError(f"native manifestに{NATIVE_ENTRIES_KEY}がない")
    return files[NATIVE_ENTRIES_KEY]


def _check_native_artifact(entries: pathlib.Path, manifest: dict) -> entries_file.Sizes:
    if type(manifest.get("schema_version")) is not int:
        raise CommonFormatError("native manifest.schema_versionが整数でない")
    if not isinstance(manifest.get("generated"), str) or not manifest["generated"]:
        raise CommonFormatError("native manifest.generatedが空でない文字列でない")
    if not isinstance(manifest.get("sources"), dict):
        raise CommonFormatError("native manifest.sourcesがobjectでない")
    info = _native_file_info(manifest)
    sizes = entries_file.sizes(entries)
    expected = {
        "compression": entries_file.COMPRESSION,
        "bytes": sizes.compressed,
        "uncompressed_bytes": sizes.uncompressed,
    }
    for key, value in expected.items():
        if info.get(key) != value:
            raise CommonFormatError(
                f"native manifest.files.{NATIVE_ENTRIES_KEY}.{key}が実物と違う: "
                f"{info.get(key)!r} / {value!r}")
    return sizes


def _require_native_entry(entry: dict) -> None:
    if not isinstance(entry, dict):
        raise CommonFormatError("native entryがobjectでない")
    for key in ("word", "pinyin"):
        if not isinstance(entry.get(key), str) or not entry[key]:
            raise CommonFormatError(f"native entry.{key}が空でない文字列でない")
    senses = entry.get("senses")
    if not isinstance(senses, list) or not senses:
        raise CommonFormatError(f"{entry['word']}: native sensesが空でない配列でない")
    unknown = [key for key in entry if key not in NATIVE_ENTRY_KEYS]
    if unknown:
        raise CommonFormatError(f"{entry['word']}: native entryに未知のキーがある: {unknown}")


def _evidence(subject: str, method: str, result: str,
              source_value: Optional[str] = None) -> OrderedDict:
    value = OrderedDict([
        ("subject", subject),
        ("method", method),
        ("result", result),
    ])
    if source_value is not None:
        value["source_value"] = source_value
    return value


def _entry_verification(entry: dict) -> list:
    moe = entry.get("moe")
    if moe is None:
        return []
    if moe not in {"full", "headword", "none"}:
        raise CommonFormatError(f"{entry['word']}: moeが想定外: {moe!r}")
    return [_evidence("entry_headword_and_sense_count", "moedict_crosscheck", moe, moe)]


def _provenance(entry: dict, sense: dict) -> OrderedDict:
    qa = sense.get("qa")
    if not isinstance(qa, str) or not qa:
        raise CommonFormatError(f"{entry['word']}: sense.qaが空でない文字列でない")
    if entry.get("src") == "zh-ja-dict":
        method = "legacy"
    else:
        methods = {
            "llm_ok": "llm",
            "llm_fixed": "llm",
            "derived": "derived",
            "hand_fixed": "manual_override",
        }
        method = methods.get(qa)
        if method is None:
            raise CommonFormatError(
                f"{entry['word']}: 骨格entryのqa組合せが共通形式で未定義: {qa!r}")
    return OrderedDict([
        ("method", method),
        ("source", DICTIONARY),
        ("source_value", qa),
    ])


def _translation_verification(entry: dict, sense: dict) -> list:
    qa = sense["qa"]
    if entry.get("src") != "zh-ja-dict":
        if qa in {"llm_ok", "llm_fixed", "hand_fixed"}:
            return [_evidence("translation", "script_and_length", "passed", qa)]
        if qa == "derived":
            return []
        raise CommonFormatError(
            f"{entry['word']}: 骨格entryのqa組合せが共通形式で未定義: {qa!r}")

    mappings = {
        "llm_ok": ("legacy_entry_translation_set", "legacy_llm_review", "passed"),
        "llm_fixed": ("legacy_entry_translation_set", "legacy_llm_review", "corrected"),
        "machine_backed": (
            "legacy_entry_translation_set", "legacy_dictionary_overlap", "reported_overlap"),
        "unchecked": ("legacy_entry_translation_set", "legacy_review", "unchecked"),
        "human_reviewed": ("reading_sense_alignment", "legacy_human_review", "passed"),
    }
    mapped = mappings.get(qa)
    if mapped is None:
        raise CommonFormatError(
            f"{entry['word']}: 補遺entryのqa組合せが共通形式で未定義: {qa!r}")
    return [_evidence(*mapped, source_value=qa)]


def _common_id(entry: dict) -> OrderedDict:
    value = json.dumps(
        [entry["word"], entry.get("trad"), entry["pinyin"]],
        ensure_ascii=False, separators=(",", ":"))
    return OrderedDict([("source", DICTIONARY), ("value", value)])


def _headwords(entry: dict) -> list:
    values = [OrderedDict([("text", entry["word"]), ("kind", "primary")])]
    trad = entry.get("trad")
    if trad is not None:
        if not isinstance(trad, str) or not trad or trad == entry["word"]:
            raise CommonFormatError(f"{entry['word']}: tradが有効な別表記でない: {trad!r}")
        values.append(OrderedDict([("text", trad), ("kind", "traditional")]))
    return values


def _readings(entry: dict) -> list:
    values = [OrderedDict([
        ("text", entry["pinyin"]), ("system", "pinyin"), ("kind", "primary")])]
    for field, kind in (("tw_pr", "taiwan"), ("also_pr", "alternate")):
        if field in entry:
            text = entry[field]
            if not isinstance(text, str) or not text:
                raise CommonFormatError(f"{entry['word']}: {field}が空でない文字列でない")
            values.append(OrderedDict([
                ("text", text), ("system", "pinyin"), ("kind", kind)]))
    return values


def _levels(entry: dict) -> list:
    values = []
    for field, version in (("hsk2", "2.0"), ("hsk3", "3.0")):
        if field in entry:
            level = entry[field]
            if isinstance(level, bool) or not isinstance(level, int):
                raise CommonFormatError(f"{entry['word']}: {field}が整数でない")
            values.append(OrderedDict([
                ("system", "HSK"), ("version", version), ("value", str(level))]))
    return values


def _common_sense(entry: dict, sense: dict) -> OrderedDict:
    if not isinstance(sense, dict):
        raise CommonFormatError(f"{entry['word']}: native senseがobjectでない")
    unknown = [key for key in sense if key not in NATIVE_SENSE_KEYS]
    if unknown:
        raise CommonFormatError(f"{entry['word']}: native senseに未知のキーがある: {unknown}")
    text = sense.get("ja")
    if not isinstance(text, str) or not text:
        raise CommonFormatError(f"{entry['word']}: sense.jaが空でない文字列でない")
    english = sense.get("en", [])
    if not isinstance(english, list) or any(not isinstance(item, str) for item in english):
        raise CommonFormatError(f"{entry['word']}: sense.enが文字列配列でない")
    glosses = [OrderedDict([("language", "en"), ("text", item)]) for item in english]
    extension = OrderedDict(
        (key, copy.deepcopy(value)) for key, value in sense.items() if key != "ja")
    translation = OrderedDict([
        ("language", "ja"),
        ("text", text),
        ("provenance", _provenance(entry, sense)),
        ("verification", _translation_verification(entry, sense)),
        ("uncertain", sense.get("unsure") is True),
    ])
    return OrderedDict([
        ("glosses", glosses),
        ("translations", [translation]),
        ("extensions", OrderedDict([(EXTENSION_KEY, extension)])),
    ])


def to_common_entry(entry: dict) -> OrderedDict:
    """native entryを、意味を増やさず共通形式へ写す。"""
    _require_native_entry(entry)
    source = entry.get("src")
    if source is not None and source != "zh-ja-dict":
        raise CommonFormatError(f"{entry['word']}: srcが想定外: {source!r}")
    extension = OrderedDict(
        (key, copy.deepcopy(value)) for key, value in entry.items() if key != "senses")
    senses = [_common_sense(entry, sense) for sense in entry["senses"]]
    return OrderedDict([
        ("id", _common_id(entry)),
        ("headwords", _headwords(entry)),
        ("readings", _readings(entry)),
        ("levels", _levels(entry)),
        ("verification", _entry_verification(entry)),
        ("extensions", OrderedDict([(EXTENSION_KEY, extension)])),
        ("senses", senses),
    ])


def project_native_entry(entry: dict) -> OrderedDict:
    """共通entryのnative拡張からschema 3を復元する。"""
    try:
        extension = entry["extensions"][EXTENSION_KEY]
        common_senses = entry["senses"]
    except (KeyError, TypeError) as error:
        raise CommonFormatError("共通entryのextensionsまたはsensesが不正") from error
    if not isinstance(extension, dict) or not isinstance(common_senses, list):
        raise CommonFormatError("共通entryのnative extensionまたはsensesが不正")

    native = OrderedDict()
    for key in NATIVE_ENTRY_KEYS:
        if key == "senses":
            continue
        if key in extension:
            native[key] = copy.deepcopy(extension[key])
    native_senses = []
    for common_sense in common_senses:
        try:
            native_extension = common_sense["extensions"][EXTENSION_KEY]
            translations = common_sense["translations"]
        except (KeyError, TypeError) as error:
            raise CommonFormatError("共通senseのnative extensionまたはtranslationsが不正") from error
        if not isinstance(native_extension, dict) or not isinstance(translations, list) \
                or len(translations) != 1 or not isinstance(translations[0], dict):
            raise CommonFormatError("共通senseのnative extensionまたはtranslation件数が不正")
        translation = translations[0]
        if translation.get("language") != "ja" or not isinstance(translation.get("text"), str):
            raise CommonFormatError("共通translationの言語または本文が不正")
        native_sense = OrderedDict()
        for key in NATIVE_SENSE_KEYS:
            if key == "ja":
                native_sense[key] = translation["text"]
            elif key in native_extension:
                native_sense[key] = copy.deepcopy(native_extension[key])
        native_senses.append(native_sense)
    native["senses"] = native_senses
    return native


def _json_lines(entries: pathlib.Path, counters: dict, seen: set,
                limit: Optional[int]):
    for number, line in enumerate(entries_file.read_lines(entries), start=1):
        if limit is not None and number > limit:
            break
        try:
            native = json.loads(line)
        except json.JSONDecodeError as error:
            raise CommonFormatError(f"native entry {number}がJSONでない: {error}") from error
        common = to_common_entry(native)
        identity = (common["id"]["source"], common["id"]["value"])
        if identity in seen:
            raise CommonFormatError(f"native entry {number}の共通IDが重複: {identity!r}")
        seen.add(identity)
        counters["entries"] += 1
        counters["senses"] += len(common["senses"])
        yield json.dumps(common, ensure_ascii=False, separators=(",", ":"))


def _reject_input_output_collisions(native_entries: pathlib.Path,
                                    native_manifest: pathlib.Path,
                                    target: pathlib.Path,
                                    manifest_target: pathlib.Path) -> None:
    inputs = {
        "native entries": native_entries,
        "native manifest": native_manifest,
    }
    outputs = {
        "共通entries": target,
        "共通manifest": manifest_target,
    }
    for input_label, input_path in inputs.items():
        for output_label, output_path in outputs.items():
            resolved_input = input_path.resolve()
            resolved_output = output_path.resolve()
            try:
                same_existing_file = input_path.samefile(output_path)
            except FileNotFoundError:
                same_existing_file = False
            except OSError as error:
                raise CommonFormatError(
                    f"入力と出力の実体を確認できない: {input_path} / {output_path}: "
                    f"{error}") from error
            if resolved_input == resolved_output or same_existing_file:
                raise CommonFormatError(
                    f"入力と出力が同じpathを指す: {input_label} / {output_label} / "
                    f"{resolved_input} / {resolved_output}")


def export_common(native_entries: pathlib.Path, native_manifest: pathlib.Path,
                  out: pathlib.Path, limit: Optional[int] = None) -> ValidationStats:
    """確定済みnative artifactから共通形式を決定論的に生成する。"""
    native_entries = pathlib.Path(native_entries)
    native_manifest = pathlib.Path(native_manifest)
    out = pathlib.Path(out)
    target = out / entries_file.NAME
    manifest_target = out / "manifest.json"
    _reject_input_output_collisions(
        native_entries, native_manifest, target, manifest_target)
    if limit is not None and limit <= 0:
        raise CommonFormatError("limitは正の整数でなければならない")
    manifest = _load_json(native_manifest, "native manifest")
    _check_native_artifact(native_entries, manifest)
    out.mkdir(parents=True, exist_ok=True)

    temporary = out / f".{entries_file.NAME}.tmp"
    manifest_temporary = out / ".manifest.json.tmp"
    counters = {"entries": 0, "senses": 0}
    seen = set()
    try:
        sizes = entries_file.write(temporary, _json_lines(native_entries, counters, seen, limit))
        native_info = _native_file_info(manifest)
        if limit is None:
            for key, actual in (("lines", counters["entries"]),
                                ("senses", counters["senses"])):
                if native_info.get(key) != actual:
                    raise CommonFormatError(
                        f"native manifestの{key}が実データと違う: "
                        f"{native_info.get(key)!r} / {actual}")

        common_manifest = OrderedDict([
            ("schema", OrderedDict([("name", SCHEMA_NAME), ("version", SCHEMA_VERSION)])),
            ("dictionary", DICTIONARY),
            ("source_language", SOURCE_LANGUAGE),
            ("translation_languages", TRANSLATION_LANGUAGES),
            ("generated", manifest["generated"]),
            ("files", OrderedDict([(entries_file.NAME, OrderedDict([
                ("lines", counters["entries"]),
                ("senses", counters["senses"]),
                ("compression", entries_file.COMPRESSION),
                ("bytes", sizes.compressed),
                ("uncompressed_bytes", sizes.uncompressed),
                ("sha256", sha256_file(temporary)),
            ]))])),
            ("sources", copy.deepcopy(manifest["sources"])),
            ("source_artifact", OrderedDict([
                ("schema_version", manifest["schema_version"]),
                ("sha256", sha256_file(native_entries)),
            ])),
        ])
        manifest_temporary.write_text(
            json.dumps(common_manifest, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
        os.replace(temporary, target)
        os.replace(manifest_temporary, manifest_target)
    finally:
        if temporary.exists():
            temporary.unlink()
        if manifest_temporary.exists():
            manifest_temporary.unlink()
    return ValidationStats(counters["entries"], counters["senses"], counters["senses"])


def _check_common_manifest(common: dict, native: dict, common_entries: pathlib.Path,
                           native_entries: pathlib.Path) -> None:
    schema = common.get("schema")
    if not isinstance(schema, dict) or schema.get("name") != SCHEMA_NAME \
            or type(schema.get("version")) is not int or schema["version"] != SCHEMA_VERSION:
        raise CommonFormatError(f"共通manifest.schemaが未対応: {schema!r}")
    fixed = {
        "dictionary": DICTIONARY,
        "source_language": SOURCE_LANGUAGE,
        "translation_languages": TRANSLATION_LANGUAGES,
        "generated": native.get("generated"),
        "sources": native.get("sources"),
    }
    for key, expected in fixed.items():
        if common.get(key) != expected:
            raise CommonFormatError(f"共通manifest.{key}が契約と違う")
    expected_source = {
        "schema_version": native.get("schema_version"),
        "sha256": sha256_file(native_entries),
    }
    if common.get("source_artifact") != expected_source:
        raise CommonFormatError("共通manifest.source_artifactがnative実物と違う")
    files = common.get("files")
    if not isinstance(files, dict) or not isinstance(files.get(entries_file.NAME), dict):
        raise CommonFormatError(f"共通manifest.files.{entries_file.NAME}がない")
    info = files[entries_file.NAME]
    for key in ("lines", "senses", "bytes", "uncompressed_bytes"):
        if type(info.get(key)) is not int or info[key] < 0:
            raise CommonFormatError(f"共通manifest.files.{entries_file.NAME}.{key}が非負整数でない")
    sizes = entries_file.sizes(common_entries)
    expected_file = {
        "compression": entries_file.COMPRESSION,
        "bytes": sizes.compressed,
        "uncompressed_bytes": sizes.uncompressed,
        "sha256": sha256_file(common_entries),
    }
    for key, expected in expected_file.items():
        if info.get(key) != expected:
            raise CommonFormatError(f"共通manifestの{key}が実物と違う")


def _check_key_order(common: dict, number: int) -> None:
    if tuple(common) != COMMON_ENTRY_KEYS:
        raise CommonFormatError(f"共通entry {number}のキー順または構成が違う: {list(common)}")
    for sense_index, sense in enumerate(common.get("senses", []), start=1):
        if tuple(sense) != ("glosses", "translations", "extensions"):
            raise CommonFormatError(
                f"共通entry {number} sense {sense_index}のキー順または構成が違う")
        translations = sense.get("translations")
        if not isinstance(translations, list) or len(translations) != 1:
            raise CommonFormatError(
                f"共通entry {number} sense {sense_index}のtranslation件数が1でない")


def _artifact_counts(path: pathlib.Path, label: str) -> tuple[int, int]:
    entries = senses = 0
    for number, line in enumerate(entries_file.read_lines(path), start=1):
        try:
            entry = json.loads(line)
        except json.JSONDecodeError as error:
            raise CommonFormatError(f"{label} entry {number}がJSONでない: {error}") from error
        if not isinstance(entry, dict) or not isinstance(entry.get("senses"), list):
            raise CommonFormatError(f"{label} entry {number}のsensesが配列でない")
        entries += 1
        senses += len(entry["senses"])
    return entries, senses


def validate_common(common_entries: pathlib.Path, common_manifest: pathlib.Path,
                    native_entries: pathlib.Path, native_manifest: pathlib.Path,
                    limit: Optional[int] = None) -> ValidationStats:
    """manifest、共通行、nativeへの逆投影をstreamingで全件検査する。"""
    common_entries = pathlib.Path(common_entries)
    common_manifest = pathlib.Path(common_manifest)
    native_entries = pathlib.Path(native_entries)
    native_manifest = pathlib.Path(native_manifest)
    if limit is not None and limit <= 0:
        raise CommonFormatError("limitは正の整数でなければならない")
    common_meta = _load_json(common_manifest, "共通manifest")
    native_meta = _load_json(native_manifest, "native manifest")
    _check_native_artifact(native_entries, native_meta)
    _check_common_manifest(common_meta, native_meta, common_entries, native_entries)

    if limit is not None:
        common_counts = _artifact_counts(common_entries, "共通")
        native_counts = _artifact_counts(native_entries, "native")
        common_info = common_meta["files"][entries_file.NAME]
        native_info = _native_file_info(native_meta)
        for label, info, actual_counts in (
                ("共通", common_info, common_counts),
                ("native", native_info, native_counts)):
            for key, actual in zip(("lines", "senses"), actual_counts):
                if info.get(key) != actual:
                    raise CommonFormatError(
                        f"{label} manifestの{key}が実データと違う: "
                        f"{info.get(key)!r} / {actual}")
        comparison_entries = min(limit, native_counts[0])
        if common_counts[0] < comparison_entries or common_counts[0] > native_counts[0]:
            raise CommonFormatError(
                "共通artifactの件数では指定範囲を比較できない: "
                f"{common_counts[0]} / {comparison_entries}")
        common_lines = itertools.islice(
            entries_file.read_lines(common_entries), comparison_entries)
        native_lines = itertools.islice(
            entries_file.read_lines(native_entries), comparison_entries)
    else:
        common_lines = entries_file.read_lines(common_entries)
        native_lines = entries_file.read_lines(native_entries)
    pairs = itertools.zip_longest(
        enumerate(common_lines, start=1),
        enumerate(native_lines, start=1))
    entries = senses = translations = 0
    seen = set()
    for common_item, native_item in pairs:
        if common_item is None or native_item is None:
            raise CommonFormatError("共通entryとnative entryの件数が違う")
        number, common_line = common_item
        _, native_line = native_item
        try:
            common = json.loads(common_line)
            native = json.loads(native_line)
        except json.JSONDecodeError as error:
            raise CommonFormatError(f"entry {number}がJSONでない: {error}") from error
        _check_key_order(common, number)
        expected = to_common_entry(native)
        if common != expected:
            raise CommonFormatError(f"共通entry {number}がnativeからの決定的変換と違う")
        identity = (common["id"]["source"], common["id"]["value"])
        if identity in seen:
            raise CommonFormatError(f"共通entry {number}のIDが重複: {identity!r}")
        seen.add(identity)
        projected = project_native_entry(common)
        if projected != native:
            raise CommonFormatError(f"共通entry {number}をnativeへ逆投影すると差がある")
        entries += 1
        senses += len(common["senses"])
        translations += sum(len(sense["translations"]) for sense in common["senses"])

    if limit is None:
        info = common_meta["files"][entries_file.NAME]
        for key, actual in (("lines", entries), ("senses", senses)):
            if info.get(key) != actual:
                raise CommonFormatError(
                    f"共通manifestの{key}が実データと違う: "
                    f"{info.get(key)!r} / {actual}")
        native_info = _native_file_info(native_meta)
        for key, actual in (("lines", entries), ("senses", senses)):
            if native_info.get(key) != actual:
                raise CommonFormatError(
                    f"native manifestの{key}が実データと違う: {native_info.get(key)!r} / {actual}")
    return ValidationStats(entries, senses, translations)
