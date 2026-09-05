# zh-ja-dict

Japanese version: [README.ja.md](README.ja.md). **The Japanese text is the source of truth; this English version follows it.** / 日本語版が正本です。英語版はそれに追従します。

A Chinese–Japanese bilingual gloss dataset, built so that a language-learning app can show a short translation for each word. All glosses were generated with an LLM.

- 2 files, 136,326 lines, about 14 MB. All JSON Lines (UTF-8, LF)
- Two directions: Chinese→Japanese and Japanese→Chinese
- **In the Chinese→Japanese file, one line is one (headword, reading) pair.** A headword with several readings has several lines
- Lines have been checked to different degrees. The `qa` field tells them apart
- Licensed under **[CC BY-SA 4.0](https://creativecommons.org/licenses/by-sa/4.0/)** (see [License](#license))

## Contents

| File | Direction | Lines | Words | Content |
|---|---|---|---|---|
| `data/zh-ja/glosses.jsonl` | zh→ja | 96,326 | 95,478 | Short Japanese glosses with pinyin. 11,470 of the words carry an HSK level |
| `data/ja-zh/glosses.jsonl` | ja→zh | 40,000 | 40,000 | Chinese translations with pinyin |

There is also `data/manifest.json` (see [manifest.json](#manifestjson)).

In the zh→ja file, **(headword, reading) pairs are unique**. A word with several readings is split over several lines; 791 words have two or more lines (at most four). The ja→zh file stays at one line per word. There is no correspondence between the two files.

## Format

### data/zh-ja/glosses.jsonl

| Key | Type | Required | Meaning |
|---|---|---|---|
| `word` | string | yes | Headword. Mostly simplified characters, but some traditional headwords are included (`雙`, `時間`, `經過`, …) |
| `pinyin` | string | yes | The reading of this line |
| `gloss` | array of strings | yes | Japanese glosses. No upper limit on the count. When empty, `unsure: true` is set |
| `qa` | string | yes | Check category: one of `machine_backed` / `llm_ok` / `llm_fixed` / `human_reviewed` / `unchecked` |
| `unsure` | true | optional | Marks a gloss whose reliability is in doubt. See [What unsure means](#what-unsure-means) |
| `hsk2` | integer | optional | HSK 2.0 level (1–6). See [HSK levels](#hsk-levels) |
| `hsk3` | integer | optional | HSK 3.0 level (1–7) |
| `trad` | array of strings | optional | Traditional spellings, only those that differ from the headword |
| `pos` | array of strings | optional | Parts of speech, using the abbreviations of the [source](#sources) as they are (`n`, `v`, `u`, …; see that source for their meaning) |
| `reading_pos` | array of strings | optional | Parts of speech **of this reading**. Present only when it differs from the word-level `pos` |
| `alt_pinyin` | array of strings | optional | Other readings found in the [source](#sources). They are not tied to any gloss |

`hsk2`, `hsk3`, `trad`, `pos` and `alt_pinyin` are **word attributes**: every line of the same word carries the same value. Among the optional keys, only `reading_pos` is a **line attribute** whose value differs per line.
`reading_pos` appears only on words that have `pos` (there is no line with `reading_pos` but without `pos`).

```json
{"word": "美国", "pinyin": "Měiguó", "gloss": ["アメリカ"], "qa": "machine_backed"}
{"word": "幖", "pinyin": "biāo", "gloss": [], "unsure": true, "qa": "machine_backed"}
{"word": "爱好", "pinyin": "ài hào", "gloss": ["趣味", "愛好する"], "qa": "machine_backed", "hsk2": 2, "hsk3": 2, "trad": ["愛好"], "pos": ["v", "vn"]}
{"word": "着", "pinyin": "zhe", "gloss": ["〜している"], "qa": "machine_backed", "hsk2": 2, "hsk3": 1, "trad": ["著"], "pos": ["u", "v", "n", "q"], "reading_pos": ["u"]}
{"word": "着", "pinyin": "zháo", "gloss": ["触れる"], "qa": "human_reviewed", "hsk2": 2, "hsk3": 1, "trad": ["著"], "pos": ["u", "v", "n", "q"], "reading_pos": ["v"]}
```

Lines fall into three groups, and the counts add up to the line total.

| Group | Count |
|---|---|
| no `unsure` | 96,104 |
| `unsure: true`, `gloss` has one or more items | 219 |
| `unsure: true`, `gloss` is empty | 3 |

Lines and words that carry optional keys:

| Key | Lines | Words |
|---|---|---|
| `hsk2` | 5,033 | 4,991 |
| `hsk3` | 11,030 | 10,969 |
| `trad` | 6,867 | 6,830 |
| `pos` | 11,282 | 11,220 |
| `reading_pos` | 98 | 48 |
| `alt_pinyin` | 344 | 334 |

### What qa means

| Value | Count | Meaning |
|---|---|---|
| `machine_backed` | 66,815 | Cross-checked against existing dictionary resources and confirmed |
| `llm_ok` | 27,792 | Not confirmed by the cross-check; an LLM read it and judged it acceptable |
| `llm_fixed` | 856 | Same as above, but the LLM corrected the gloss |
| `human_reviewed` | 62 | A person confirmed the pairing of reading and sense for polyphonic words. **The wording of the gloss has not gone through the two-step check** (see [How it was made and checked](#how-it-was-made-and-checked)) |
| `unchecked` | 801 | **Not checked.** Lines imported from a file of per-reading senses |

**The 801 `unchecked` lines have not received the same check as the other lines.** The file they came from (the former `polyphonic.jsonl`) was generated and never checked.

### How to read reading_pos

`reading_pos` is present **only when** the part of speech of that reading differs from the word-level `pos`.

- A line that has `pos` but no `reading_pos` means **the part of speech of that reading is the same as the word's `pos`**
- Example: `着` has `pos` `["u","v","n","q"]` (the parts of speech pooled over the word), while the `zhe` line has `reading_pos` `["u"]` and the `zháo` line has `reading_pos` `["v"]`
- Values are the source's abbreviations, except that one English word, `interjection`, occurs (`哦`, `嗯`). The source's notation is kept as it is

### Words whose proper-noun reading is kept as a separate line

An uppercase initial in pinyin marks a proper noun. **When checking that (headword, reading) pairs are unique, letter case is ignored.** Where a word merely had the same reading spelled in upper and lower case, the spelling of the line that already existed in `glosses.jsonl` before the merge was kept (`俞` keeps `Yú`, and `yú` was dropped).

**The following two words are different words, so both lines are kept, distinguished by case.**

| Word | Line 1 | Line 2 |
|---|---|---|
| `包头` | `Bāotóu` = Baotou (place name) | `bāotóu` = headscarf; (shoe) toe cap |
| `酂` | `Zàn` = Zan (place name) | `zàn` = an ancient unit of villages |

In short: **pairs that differ only in case are merged into one line as a rule, and only these two words keep both.** Viewed case-sensitively, every pair in the file is unique; viewed case-insensitively, only these two words overlap (this matches what was measured). The validation script treats these two words as exceptions and then checks for duplicate pairs.

### Ordering

Lines of the same word are always adjacent. For a word with several readings, the second and later lines follow immediately after the word's first line.

Words are ordered as follows. The first 83,993 words are in descending frequency order of the word-segmentation dictionary (cppjieba); the following 11,470 words are HSK vocabulary in **ascending level order** (within a level, in the order of the source data). The last 15 words existed only in the retired `polyphonic.jsonl`.
The frequency figures themselves are not included, so a line number cannot be used in place of frequency.

### data/ja-zh/glosses.jsonl

| Key | Type | Required | Meaning |
|---|---|---|---|
| `word` | string | yes | Headword (Japanese) |
| `zh` | array of objects | yes | Candidate Chinese translations. No upper limit on the count. Each element has exactly two keys, `s` and `pinyin` |
| `unsure` | true | optional | Marks a translation whose reliability is in doubt |

In each element of `zh`, `s` is the Chinese spelling and `pinyin` its reading. Spellings are simplified characters as a rule, but loanwords used as-is in Chinese (`App`, `cosplay`, `AA制`, …) and kana in Japanese grammar terms (`サ行不规则活用`, …) also appear. Candidates are listed with the main one first.

```json
{"word": "明白", "zh": [{"s": "明白", "pinyin": "míngbai"}, {"s": "清楚", "pinyin": "qīngchu"}]}
{"word": "と言うもの", "zh": [], "unsure": true}
{"word": "初場所", "zh": [{"s": "新年场所", "pinyin": "xīnnián chǎngsuǒ"}], "unsure": true}
```

| Group | Count |
|---|---|
| no `unsure` | 38,565 |
| `unsure: true`, `zh` has one or more items | 493 |
| `unsure: true`, `zh` is empty | 942 |

Candidate counts: 942 words have 0, 15,979 have 1, 22,150 have 2, and 929 have 3.

### manifest.json

A small file that records the schema version and the line counts. It lets a reader avoid silently loading data of a version it does not expect.

`schema_version` is **the version of the format this document describes**, currently 2. It became 2 with the revision that made one line one (word, reading) pair.

```json
{
  "schema_version": 2,
  "generated": "2026-09-03",
  "files": {
    "zh-ja/glosses.jsonl": {"lines": 96326},
    "ja-zh/glosses.jsonl": {"lines": 40000}
  }
}
```

If you copy only `glosses.jsonl`, the manifest does not come with it. In that case, the presence of the retired key `hsk` tells you that the file is in the old format.

## What unsure means

`unsure` means "**do not take the gloss on this line at face value**". In neither `glosses.jsonl` does it mean that there is no gloss.

In the ja→zh file, 493 of the 1,435 `unsure: true` lines have translations. In the zh→ja file, 219 of 222 do. Whether a gloss exists and whether `unsure` is set are separate pieces of information.

- Reading `unsure` as "no gloss" and dropping those lines throws away 493 translations (ja→zh) and 219 (zh→ja)
- If you want to test for an empty gloss, look at the length of `gloss` or `zh` directly
- `unsure` is written only as `true` when set. No line spells out `false`

Readers are advised not to drop `unsure` lines at load time. Decide whether to hide them at display time.

## HSK levels

11,470 words carry an HSK level. These 11,470 words **do not overlap with any** of the 83,993 words chosen from the segmentation dictionary (cppjieba): HSK vocabulary was excluded when the zh→ja headwords were chosen, so merging produced no duplicates.

HSK has two versions, 2.0 (up to level 6) and 3.0 (up to level 7). **Each version is stored under its own key.**

| Key | Words | Level range |
|---|---|---|
| `hsk2` | 4,991 | 1–6 |
| `hsk3` | 10,969 | 1–7 |

4,490 words have both, 501 have only `hsk2`, and 6,479 have only `hsk3`. **Of the 4,490 words with both, 3,673 have different levels in the two versions.** Keep this in mind when comparing difficulty across versions.

Words per level:

| Level | 1 | 2 | 3 | 4 | 5 | 6 | 7 |
|---|---|---|---|---|---|---|---|
| `hsk2` | 150 | 147 | 298 | 598 | 1,298 | 2,500 | — |
| `hsk3` | 506 | 750 | 953 | 972 | 1,059 | 1,123 | 5,606 |

If you use the levels to pick "hard words", decide which version to use. Taking the easier of the two, or preferring 3.0 and falling back to 2.0, are both workable choices.

## Using it from Swift

The repository works as a SwiftPM package. It bundles the Chinese-to-Japanese data and `manifest.json` (the Japanese-to-Chinese direction is not included).

```swift
.package(url: "https://github.com/inakaegg/zh-ja-dict.git", from: "1.0.0")
```

```swift
import ZhJaDictData

let glosses = ZhJaDictData.glossesURL()   // data/zh-ja/glosses.jsonl
let manifest = ZhJaDictData.manifestURL() // data/manifest.json
```

### Pass a bundle when you ship it inside an app

Omit the argument and it looks in `Bundle.module`, which **you cannot rely on inside an `.app`**. The generated accessor searches exactly two places: next to the `.app` itself, and the `.build` path baked in with an absolute path at build time. An app that puts resources under `Contents/Resources/` misses the first and, on the machine that built it, **silently hits the second**. On any other machine neither matches.

Resolve the bundle yourself using `ZhJaDictData.bundleName` (`zh-ja-dict_ZhJaDictData.bundle`) and pass it in.

```swift
let bundle = Bundle(url: appResources.appendingPathComponent(ZhJaDictData.bundleName))
guard let glosses = ZhJaDictData.glossesURL(in: bundle) else {
    throw MyError.bundledDataMissing   // not "lookup failed" but "the bundled file is missing"
}
```

## Validating the data

`tools/validate_data.py` reads both data files and `manifest.json` in full and reports format violations. It runs on Python 3.9 or later with no extra installation.

```console
$ python3 tools/validate_data.py
## zh-ja/glosses.jsonl（96,326行）
  通常                        96,104
  ...
合計 136,326行
違反 0 件
```

The report is printed in Japanese. The last line, `違反 N 件`, is the number of violations found, and `合計` is the line total.

If there is even one violation, it exits with code 1. GitHub Actions (`.github/workflows/validate.yml`) runs the same command on push and pull request.

To see only the counts, add `--counts`; it then exits with code 0 even when there are violations.

The script checks ten things: that each line parses as JSON; that the keys match the tables above; that the optional arrays (`trad`, `pos`, `reading_pos`, `alt_pinyin`) are not empty; that no array contains duplicates; that there are no empty strings or leading/trailing spaces; **that (headword, reading) pairs are unique**; that word attributes agree across the lines of the same word; **that a line with `reading_pos` also has `pos`** (so the restoration rule in [How to read reading_pos](#how-to-read-reading_pos) holds); that the line counts in `manifest.json` match the files; and **that no other language has crept into a gloss**.

There is **no upper limit on the number of glosses or candidates**. An earlier limit of three was a guideline for generation, not a property of the format, so it was removed from the checks.

The last check needs an explanation. Both Japanese and Chinese write abbreviations, units and proper nouns in Latin letters (`USBメモリ`, `X光`, `AA制`). A gloss where an English word was left behind by a failed generation looks the same. Since there is no mechanical way to tell them apart, the Latin-letter words that are allowed are listed in `tools/allowlist-latin.txt` and anything else is reported as a violation. Words that may contain kana in a Chinese translation (Japanese grammar terms) are in `tools/allowlist-kana-in-chinese.txt`.

If you add or fix glosses and need a new word, confirm that the word is really written that way in that language before adding it to these files.

The validation script's own tests run with `python3 tools/test_validate_data.py`. They use small synthetic data and do not read the real data.

`tools/build_glosses.py`, which assembles the data, and its self-test `tools/test_build_glosses.py` are in the same directory. The HSK vocabulary data that the build takes as input is not part of this repository, so **the build cannot be reproduced from this repository alone**.

## How it was made and checked

All glosses were generated with an LLM (Claude Opus). The definition text of commercial dictionaries and OS-bundled dictionaries was not used as input and is not contained in this data. How headwords were chosen is described under [Sources](#sources).

The generation scripts and the selection sources are not included in this repository, nor is the vocabulary data behind the HSK levels. **With what is in this repository alone, the data cannot be regenerated, and the cross-check against the sources cannot be reproduced.**

Of the zh→ja `glosses.jsonl`, **95,463 lines** went through a two-step check after generation.

1. **Machine cross-check** — compared against existing dictionary resources; confirmed words become `machine_backed`
2. **LLM review** — words not confirmed by the cross-check are read by an LLM; acceptable ones become `llm_ok`, corrected ones `llm_fixed`

These 95,463 lines were produced in two batches. **Both went through the same two-step check, but the counts are separate.**

| | Lines | `machine_backed` | `llm_ok` | `llm_fixed` |
|---|---|---|---|---|
| First batch | 83,993 | 56,368 | 26,801 | 824 |
| HSK batch added later | 11,470 | 10,447 | 991 | 32 |
| **Subtotal** | **95,463** | **66,815** | **27,792** | **856** |

At the time, these 95,463 lines were one line per word. In the first batch, 28,492 words went to LLM review, of which 867 were removed as "not a word"; the 83,993 in the table is the count after removal.

**The remaining 863 lines did not go through this check.** They break down as follows.

| `qa` | Count | Origin |
|---|---|---|
| `unchecked` | 801 | Lines imported from a file of per-reading senses (never checked) |
| `human_reviewed` | 62 | Lines for 52 polyphonic HSK words whose reading–sense pairing a person confirmed |

What `human_reviewed` confirmed is **the pairing of reading and sense**, not the wording of the Japanese gloss.

The check has limits. In an inspection in September 2026, **17 lines were found in the zh→ja `glosses.jsonl` where an English or Russian word had crept into the Japanese gloss** (`operation開始`, `материал材積`, …). The retired `polyphonic.jsonl` had 7 more of the same kind. All were fixed as described in [Change history](#change-history).

16 of the 17 were `machine_backed`, the category said to be confirmed by the machine cross-check (the other was `llm_fixed`). The cross-check is a coarse substring match, so a gloss whose part is in another language can pass.

The ja→zh `glosses.jsonl` had only the machine cross-check; no LLM review was done.

## Sources

How headwords were chosen differs by direction and bears on the choice of license, so it is recorded here.

**ja→zh (`data/ja-zh/glosses.jsonl`)** — The headwords are the 40,000 headwords of [Jitendex](https://jitendex.org/) (a dictionary derived from JMdict) with the highest JMdict priority scores. All 40,000 are **Jitendex headwords**. For 27,250 of them (68.1%), the JMdict `common` mark alone decided inclusion; that is, two thirds of the entries are words JMdict marks as frequently used. Corpus frequency was not used.

JMdict is published by the [Electronic Dictionary Research and Development Group (EDRDG)](https://www.edrdg.org/edrdg/licence.html) under CC BY-SA 4.0. **Because the ja→zh headword selection derives from JMdict, the whole repository is provided under CC BY-SA 4.0.**

**zh→ja (`data/zh-ja/glosses.jsonl`)** — This direction **uses no JMdict-derived resource**. Headwords were taken from the union of the following two sets, ordered by cppjieba frequency.

1. Words outside the HSK range that appeared in actual usage logs
2. Words present both in the cppjieba vocabulary and in the headword lists of three commercial dictionaries

The commercial dictionaries were **used only to match headwords; their definition text was neither an input to generation nor part of the output**.

**HSK vocabulary (`hsk2`, `hsk3`, `trad`, `pos`, `alt_pinyin`)** — Taken from [complete-hsk-vocabulary](https://github.com/drkameleon/complete-hsk-vocabulary) (MIT license, commit `7ac65bf1a6387d35f1ade478906172a19311c7f9`). From it we took **per-version levels, headwords, pinyin, traditional spellings and candidate parts of speech**. The two versions (HSK 2.0 and HSK 3.0) also come from this source.
The Japanese glosses were generated independently, **without using the English definitions** it contains.
For 52 polyphonic words, a person confirmed the pairing of reading and sense (`qa: human_reviewed`). That review, and the writing of the short Japanese glosses, were done in this project's intermediate files `project-gloss-overrides` (glosses) and `project-sense-overrides` (reading and sense pairings). Neither is part of this repository.

The MIT license requires the copyright notice to be retained. The original notice is reproduced here.

```
MIT License

Copyright (c) 2026 Yanis Zafirópulos

Permission is hereby granted, free of charge, to any person obtaining a copy
of this software and associated documentation files (the "Software"), to deal
in the Software without restriction, including without limitation the rights
to use, copy, modify, merge, publish, distribute, sublicense, and/or sell
copies of the Software, and to permit persons to whom the Software is
furnished to do so, subject to the following conditions:

The above copyright notice and this permission notice shall be included in all
copies or substantial portions of the Software.

THE SOFTWARE IS PROVIDED "AS IS", WITHOUT WARRANTY OF ANY KIND, EXPRESS OR
IMPLIED, INCLUDING BUT NOT LIMITED TO THE WARRANTIES OF MERCHANTABILITY,
FITNESS FOR A PARTICULAR PURPOSE AND NONINFRINGEMENT. IN NO EVENT SHALL THE
AUTHORS OR COPYRIGHT HOLDERS BE LIABLE FOR ANY CLAIM, DAMAGES OR OTHER
LIABILITY, WHETHER IN AN ACTION OF CONTRACT, TORT OR OTHERWISE, ARISING FROM,
OUT OF OR IN CONNECTION WITH THE SOFTWARE OR THE USE OR OTHER DEALINGS IN THE
SOFTWARE.
```

## Known limitations

- Glosses favour brevity and contain no usage notes or examples
- A mismatch in the machine cross-check does not mean a mistranslation, and `machine_backed` is no guarantee of correctness either (17 intrusions passed it, as described in [How it was made and checked](#how-it-was-made-and-checked))
- Coverage of proper nouns, dialect and internet slang remains low
- Some lines have no gloss: 3 in zh→ja and 942 in ja→zh, all with `unsure: true`
- **Coverage of polyphonic words remains low.** 791 words have more than one reading, a small fraction of the 95,478 words
- `alt_pinyin` lists the readings found in the upstream source as they are, so **neutral-tone spelling variants and genuinely different readings are mixed** (`东西`'s `dōng xi`/`dōng xī` and `上`'s `shàng`/`shǎng` sit in the same field)
- Traditional spellings (`trad`) and readings (`alt_pinyin`) are not paired. That `发` is `發`/`fā` and `髮`/`fà` cannot be recovered from this format
- In the ja→zh direction, translations of Japanese grammar terms mix kana and romanised spellings (`ら行` vs `日语ra行`, `ya行`). The notation has not been unified
- The validation script detects language intrusion in glosses, but **it cannot detect mistranslations**
- Pinyin of HSK words has a space between syllables (`爱好` → `ài hào`); most other words are written joined (`星系` → `xīngxì`). **The notation is not uniform within the file.** The HSK part keeps the spelling of its source as it is, because the spaces carry syllable-boundary information; no conversion towards the joined form was made
- The language-intrusion check has gaps. The allowlist contains common English words (`live`, `house`, `look`, `boss`, `play`, `flag`) and single letters (`A`–`X`), so a new generation failure involving these words cannot be detected. The allowlist is also shared between the two directions, so a word legitimate in one passes in the other too

## Change history

### 2026-09-03 — Unit changed from "word" to "headword and reading"

Each line now represents a (headword, reading) pair. The per-reading sense file `polyphonic.jsonl` was retired and merged into the zh→ja `glosses.jsonl` (95,463 → 96,326 lines).

- **`polyphonic.jsonl` was retired.** 784 additional readings of words with two or more readings, and 17 lines of the 15 words that existed only in that file, were taken in. The rest were dropped: 4,038 senses with the same reading as an existing line, 402 single-reading senses whose reading differs, and 34 words without a gloss
- 62 per-reading sense lines were added for 52 polyphonic HSK words (`qa: human_reviewed`)
- **`hsk` was split into `hsk2` and `hsk3`.** Previously it was a combined value ("prefer 3.0, else 2.0"), so the data could not tell which version a level belonged to
- `trad`, `pos`, `reading_pos` and `alt_pinyin` were added
- `human_reviewed` and `unchecked` were added to `qa`
- `data/manifest.json` was added
- **The upper limit on the number of glosses (three) was removed from the format.** It had been a generation guideline written down as a format constraint
- Glosses of existing lines were not changed by a single character, except for the following 54 words
  - 52 words — senses of other readings were mixed into the first reading's line and were moved to the line of the matching reading (for example, "触れる" and "着る" were removed from the `zhe` line of `着`). The split is based on senses confirmed by a person
  - `赶` — the gloss "間に合う", which existed only in the upstream source, was added
  - `酪酸` — two identical glosses were reduced to one

### 2026-09-01 — HSK vocabulary merged

11,470 HSK words were appended to `data/zh-ja/glosses.jsonl` (83,993 → 95,463 lines). The existing 83,993 lines were not changed by a single byte.

- The appended words **do not overlap with any** existing headword
- The optional key `hsk` was added (see [HSK levels](#hsk-levels))
- Glosses were built on the Japanese glosses the source already had (mostly one word), adding further senses only where they exist. The average number of glosses rose from 1.01 to 2.01
- Original glosses were kept when adding. The 23 words whose original gloss was replaced are all `qa: llm_fixed`, where review corrected an error (for example `财经`'s "財経" → "経済金融", a gloss that had copied the Chinese characters as they were)

### 2026-09-01 — Format unification and language-intrusion fixes

88 lines found by a full scan were corrected. No headword was added, removed or changed, and the line counts did not change.

- **Language-intrusion fixes, 45** — lines where English or Russian remained in the gloss were repaired (`black话` → `黑话`, `嫁side` → `嫁側`, …). The glosses were not rewritten; the original was restored from the pinyin or the remaining part of the same line, so the replacement is unambiguous
- **Language-intrusion fixes where a gloss had to be chosen, 10** — lines whose whole gloss was in a foreign language and where the Japanese was not uniquely determined (`territory` → `領域`, `двойной` → `二つの`, …). **These 10 glosses did not go through the check above.** All 10 are zh→ja and the same line keeps another gloss. Two of them were in the `polyphonic.jsonl` of the time, which was never checked (the other 8 are in `glosses.jsonl`, where the other gloss was checked)
- **Pinyin field repairs, 11** — 8 lines with look-alike characters from other scripts (Cyrillic `т`/`е` in 2, IPA `ɡ` in 6), 1 with a leftover replacement character (U+FFFD), 1 with a stray digit sequence (`yījǐnr645guī`), and 1 that was empty. In all of them the Chinese spelling was correct and only the reading was broken. **None of the 11 could be spotted by eye; the validation script found them**
- **Pinyin notation unified, 3** — for words whose Chinese translation is written in Latin letters, the pinyin field now carries the same spelling
- **Broken candidates removed, 7** — broken candidates that added no information to a headword that already had a correct translation
- **Translations withdrawn, 2** — two words (`仕手`, `瘤鯛`) whose translation was not a translation and for which there was no clue to the right one had `zh` emptied and `unsure: true` kept
- **Structure unified, 4** — lines that departed from the format: 1 zh→ja line missing the `pinyin` key, 1 with `unsure` inside a `senses` element, and in ja→zh 1 with a top-level `pinyin: null` and 1 spelling out `unsure: false`
- **New translations added, 6** — six words that had only English or Russian received new Chinese translations. **These 6 translations did not go through the check above.** `unsure: true` was left in place

After this correction, each of the three files of the time had at most three kinds of lines. Before it, lines outside the format were mixed in.

## License

The data and documents in this repository are provided under **[CC BY-SA 4.0](https://creativecommons.org/licenses/by-sa/4.0/)**. The full text is in [`LICENSE`](LICENSE).

When redistributing or modifying, keep the attribution and publish under the same license. An example attribution:

```
zh-ja-dict by inakaegg, licensed under CC BY-SA 4.0.
Headword selection derives from JMdict/Jitendex (EDRDG), licensed under CC BY-SA 4.0.
```

ShareAlike was chosen for the reason given under [Sources](#sources): the ja→zh headword selection derives from JMdict. The zh→ja data uses no JMdict-derived resource, but the repository is treated under a single license.
