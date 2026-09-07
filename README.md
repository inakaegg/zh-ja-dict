# zh-ja-dict

Japanese version: [README.ja.md](README.ja.md). **The Japanese text is the source of truth; this English version follows it.** / 日本語版が正本です。英語版はそれに追従します。

A Chinese–Japanese bilingual gloss dataset, built so that a language-learning app can show a short translation for each word.

**The two directions have different formats.** The Chinese→Japanese side was rebuilt for this revision as schema 3: it splits senses the way CC-CEDICT does and carries a gloss per sense. The Japanese→Chinese side keeps the earlier format — one line per word, 40,000 words of Chinese translations.

The Chinese→Japanese side is built on [CC-CEDICT](https://www.mdbg.net/chinese/dictionary?page=cc-cedict) and carries **one short Japanese gloss per sense**. The English senses come from CC-CEDICT as they are; measure words, register labels, variants and cross-references are pulled out of CC-CEDICT's semi-structured notes into structured fields.

How a Japanese gloss was produced varies by sense. The total is 229,130.

| How it was produced | Senses |
|---|---|
| **Written by an LLM in this revision** | **187,335** |
| Inherited from the previous version, for words and readings CC-CEDICT lacks | 32,813 |
| Assembled mechanically from a cross-reference target | 8,980 |
| Written by hand after generation failed | 2 |

See [What qa means](#what-qa-means) for how each group was checked.

- zh→ja `data/zh-ja/entries.jsonl.deflate`: 157,798 entries, 229,130 senses (7,424,431 bytes compressed, 34,405,030 expanded). ja→zh `data/ja-zh/glosses.jsonl`: 40,000 lines
- One zh→ja line is **one entry**, unique by the triple (simplified, traditional, reading)
- **The zh→ja file ships compressed** as raw DEFLATE (RFC 1951). See [How it is compressed](#how-it-is-compressed)
- Senses have been checked to different degrees. The `qa` field tells them apart
- Licensed under **[CC BY-SA 4.0](https://creativecommons.org/licenses/by-sa/4.0/)** (see [License](#license))

## Contents

| File | Direction | Lines | Senses | Content |
|---|---|---|---|---|
| `data/zh-ja/entries.jsonl.deflate` | zh→ja | 157,798 | 229,130 | A short Japanese gloss per sense, with the English sense, pinyin, measure words and register labels |
| `data/ja-zh/glosses.jsonl` | ja→zh | 40,000 | — | Chinese translations with pinyin, one line per word |

There is also `data/manifest.json` (see [manifest.json](#manifestjson)).

There are two kinds of zh→ja entry.

| Kind | Count | Content |
|---|---|---|
| Skeleton entry | 124,985 | One CC-CEDICT line. Carries English senses |
| Supplement entry | 32,813 | A word or reading CC-CEDICT does not have, carried over from this dictionary's previous version. Marked with `src: "zh-ja-dict"` |

The supplement has two parts: **31,874 words CC-CEDICT has no headword for**, and **939 readings it lacks for headwords it does have** (`绷 bèng` "to crack open" is missing where CC-CEDICT carries only `bēng` and `běng`).

The supplement exists because CC-CEDICT does not list every word and reading that appears in real text. The previous version chose its headwords from a word-segmentation dictionary (cppjieba), so it holds about 30,000 ordinary words CC-CEDICT lacks — `运输机` (transport aircraft), `身旁` (beside), `三合板` (plywood). Dropping them lowers the share of words in running text that can be looked up, so they are kept as entries carrying the previous version's gloss. **Supplement entries have no English senses.**

## Format

### How it is compressed

`data/zh-ja/entries.jsonl.deflate` is JSON Lines (UTF-8, LF, one entry per line) packed with **raw DEFLATE** (RFC 1951). **There is no gzip or zlib header.**

From Python, pass a negative window size.

```python
import codecs, zlib
decompressor = zlib.decompressobj(-15)   # a negative value means "no header"
```

From Swift (Apple's Compression framework) it decompresses directly.

```swift
let plain = try (compressed as NSData).decompressed(using: .zlib) as Data
```

`NSData.DecompressionAlgorithm.zlib` and C's `COMPRESSION_ZLIB` mean **headerless DEFLATE**, despite the name. Adding a zlib header here breaks the reader while the writer notices nothing. `tools/entries_file.py` is the source of truth for both sides.

The shipped file is 7,424,431 bytes and expands to 34,405,030 (**21.6%**).

`zlib` raises no exception when the stream is cut short: it decompresses what it has and stops silently, so **check that the stream reached its end marker**. `tools/entries_file.py` does that.

### entry

| Key | Type | Required | Meaning |
|---|---|---|---|
| `word` | string | yes | Headword (simplified) |
| `trad` | string | optional | Traditional spelling, present only when it differs from `word` |
| `pinyin` | string | yes | Reading, with tone marks (`shàng jí`) |
| `tw_pr` | string | optional | Taiwanese reading |
| `also_pr` | string | optional | Alternative reading |
| `hsk2` | integer | optional | HSK 2.0 level (1–6). See [HSK levels](#hsk-levels) |
| `hsk3` | integer | optional | HSK 3.0 level (1–7) |
| `pos` | array of strings | optional | Parts of speech, using the HSK source's abbreviations as they are (`n`, `v`, `u`, …) |
| `cl` | array | optional | Measure words. Elements are `{"w": simplified, "t": traditional, "py": reading}` |
| `src` | string | optional | Present only on supplement entries, with the value `"zh-ja-dict"` |
| `seed` | string | optional | Present when the previous version's gloss was offered as a candidate; the value is that gloss's check category |
| `moe` | string | optional | Result of cross-checking against MoeDict. See [What moe means](#what-moe-means) |
| `senses` | array | yes | Senses; at least one |

```json
{"word": "计算机", "trad": "計算機", "pinyin": "jì suàn jī", "cl": [{"w": "台", "t": "臺", "py": "tai2"}], "hsk3": 2, "pos": ["n"], "seed": "machine_backed", "moe": "full", "senses": [{"en": ["computer"], "ja": "コンピュータ", "qa": "llm_ok"}, {"en": ["calculator"], "ja": "電卓", "qa": "llm_ok", "misc": ["tw"]}]}
{"word": "运输机", "trad": "運輸機", "pinyin": "yùnshūjī", "src": "zh-ja-dict", "moe": "none", "senses": [{"ja": "輸送機", "qa": "machine_backed"}]}
```

Entries carrying each optional key:

| Key | Entries |
|---|---|
| `trad` | 77,816 |
| `seed` | 64,390 |
| `pos` | 12,481 |
| `hsk3` | 12,196 |
| `hsk2` | 5,607 |
| `cl` | 1,552 |
| `tw_pr` | 510 |
| `also_pr` | 175 |

### The entry key is a triple

Entries are **unique by (simplified, traditional, reading)**. The pair (simplified, reading) alone is **not** unique: 1,065 pairs collide, because the same simplified spelling and reading can appear with different traditional spellings (`俊 jùn` has one entry with traditional `俊` and another with `儁`).

A different reading means a different entry. `东西` splits into `dōng xī` (east and west) and `dōng xi` (thing). A capitalized reading marks a proper noun, so `三 sān` (the number) and `三 Sān` (a surname) are also separate entries.

Entries for the same headword are not necessarily adjacent. Looking up by simplified headword gives 153,071 distinct words, some of which have several entries.

### Elements of senses

| Key | Type | Required | Meaning |
|---|---|---|---|
| `ja` | string | yes | Short Japanese gloss, one per sense |
| `qa` | string | yes | Where `ja` came from and how it was checked. See [What qa means](#what-qa-means) |
| `en` | array of strings | optional | English senses, split on CC-CEDICT's `;`. Absent on supplement entries |
| `unsure` | true | optional | The previous version marked this gloss as doubtful. Only on supplement entries |
| `misc` | array of strings | optional | Register, region and rhetoric labels. See [The misc labels](#the-misc-labels) |
| `variant_of` | array | optional | Variant targets. See [How to read cross-references](#how-to-read-cross-references) |
| `see_also` | array | optional | Synonym, abbreviation and other cross-reference targets |
| `lsource` | array of strings | optional | Loanword source, from CC-CEDICT's `(loanword from …)` |
| `s_inf` | array of strings | optional | Notes that could not be moved into a structured field. None in the current release |

Senses carrying each optional key:

| Key | Senses |
|---|---|
| `en` | 187,335 |
| `misc` | 13,206 |
| `see_also` | 5,475 |
| `variant_of` | 3,505 |
| `unsure` | 119 |
| `lsource` | 104 |

The 41,795 senses without `en` are 32,813 supplement senses, 8,980 senses that hold only a cross-reference with no English text, and 2 senses where CC-CEDICT gives nothing but a label (`吜` and `噶噶`, both `(onom.)`).

**Measure words live on the entry, not on the sense.** CC-CEDICT writes `CL:個|个[ge4]` as a standalone fragment and never says which sense it belongs to. Attaching it to a sense puts a measure word on verb senses such as `to map out` under `计划`. A measure word is a property of the word, so it is collected on the entry.

For the same reason, when **a label is the whole fragment** (as in `態 态 [tai4] /(bound form)/appearance/…/`), the label is folded into the neighbouring sense — the following one if there is one, otherwise the preceding one. Two entries consist of nothing but a label, and there the label-only sense is kept as it is.

### Senses with the same gloss are merged

CC-CEDICT lists English synonyms as separate senses (`age` and `era` under `时代`; `paring knife` and `fruit knife` under `水果刀`). They come out as the same Japanese gloss, so the screen would show the same gloss twice. **Within one entry, senses whose `ja` is identical are merged into one.**

- **No English is lost.** The `en` arrays are concatenated in order (`{"en": ["age", "era"], "ja": "時代"}`)
- Only senses whose **annotations are all identical** are merged. If `misc`, a cross-reference, `lsource`, `s_inf` or `unsure` differs, they stay separate — otherwise a colloquial or dialect label would spread to a sense that never carried it
- `qa` is taken from the first sense, except that any `llm_fixed` in the group wins

Across the whole dataset **1,174 senses** merged (230,304 before, 229,130 after).

`ja` is written in Japanese script. Latin words are limited to those listed in `tools/allowlist-latin.txt`, and the length limit is 24 characters. Glosses carried over from the previous version, and glosses assembled mechanically from cross-references, fall outside both limits (see [What qa means](#what-qa-means)).

### The misc labels

Only CC-CEDICT's parenthesized notes that express **register, region or rhetoric** became labels.

| Label | Meaning | Senses |
|---|---|---|
| `idiom` | set phrase (chengyu) | 3,965 |
| `written` | literary register | 1,368 |
| `fig` | figurative | 1,312 |
| `tw` | Taiwan usage | 1,305 |
| `coll` | colloquial | 941 |
| `loan` | loanword | 917 |
| `bound` | bound form | 792 |
| `old` | old usage | 653 |
| `dial` | dialect | 584 |
| `slang` | slang | 523 |
| `onom` | onomatopoeia | 228 |
| `arch` | archaic | 223 |
| `net` | internet usage | 157 |
| `proverb` | proverb | 95 |
| `derog` | derogatory | 90 |
| `cantonese` | Cantonese | 65 |
| `formal` | formal | 62 |
| `honor` | honorific | 62 |
| `hk` | Hong Kong usage | 61 |
| `neo` | neologism | 49 |
| `polite` | polite | 38 |
| `vulgar` | vulgar | 36 |
| `humble` | humble | 33 |
| `euph` | euphemism | 28 |
| `joc` | jocular | 24 |

**Field names did not become labels.** CC-CEDICT's parentheses hold 3,165 distinct field notes such as `(computing)`, `(medicine)` and `(bird species of China)`. Turning those into labels would mean maintaining a taxonomy this dataset does not need, so **they stay inside the sense text (`en`)**. They were used as a hint when writing the Japanese gloss, but never copied into it.

`(lit.)` is not a label either: it introduces the literal reading of a set phrase, which is a different thing from `(literary)`.

### How to read cross-references

`variant_of` and `see_also` point at another word. The elements have the same shape, and `kind` names the relation.

| Key | Meaning |
|---|---|
| `kind` | The relation (see below) |
| `w` | Target, simplified |
| `t` | Target, traditional. Only when it differs from `w` |
| `py` | Target reading, kept in CC-CEDICT's numbered notation |

| Field | `kind` | Meaning |
|---|---|---|
| `variant_of` | `variant` | variant character |
| | `old` | old form |
| | `erhua` | erhua form |
| `see_also` | `see` | same meaning |
| | `see_also` | see also |
| | `abbr` | what it abbreviates |
| | `used_in` | the word this character occurs in |

**Only `py` uses the numbered notation.** An entry's own `pinyin` carries tone marks, but target readings are kept exactly as CC-CEDICT writes them.

```json
{"en": ["to admonish"], "ja": "いさめる", "qa": "llm_ok"}
{"ja": "证（zhèng）の異体字", "qa": "derived", "variant_of": [{"kind": "variant", "w": "证", "py": "zheng4"}]}
```

### What qa means

Per sense, how the Japanese gloss was produced and checked.

| Value | Meaning | Length limit |
|---|---|---|
| `llm_ok` | Written by an LLM from CC-CEDICT's English sense, and passed the script and length checks | 24 |
| `llm_fixed` | Failed the checks and was rewritten | 24 |
| `derived` | Assembled mechanically from a cross-reference (`证（zhèng）の異体字`) | 200 |
| `machine_backed` | Carried over. The previous version matched it against an existing dictionary resource | 80 |
| `llm_ok` (supplement) | Carried over. The previous version found no match and had an LLM judge it sound | 80 |
| `llm_fixed` (supplement) | Same, but the LLM rewrote the gloss | 80 |
| `human_reviewed` | Carried over. A person confirmed the reading-to-sense mapping for a polyphonic character | 80 |
| `unchecked` | Carried over. **Not checked** | 80 |
| `hand_fixed` | Repeated rewriting never produced a conforming gloss, so a person wrote it | 24 |

`llm_ok` and `llm_fixed` appear both on newly written senses and on supplement entries; the entry's `src` tells them apart.

Senses per value:

| `qa` | Senses |
|---|---|
| `llm_ok` | 201,568 |
| `machine_backed` | 17,670 |
| `derived` | 8,980 |
| `llm_fixed` | 691 |
| `unchecked` | 219 |
| `hand_fixed` | 2 |

The two `hand_fixed` senses are listed in `tools/gloss-overrides.tsv` with headword, reading, sense number, gloss and reason. The build aborts if an override matches no sense, so a line that has stopped applying is always noticed.

There are three length limits because the glosses were produced differently. New glosses were generated under a "24 characters or fewer" rule. Carried-over glosses join the one to three glosses the previous version held per word with a comma, so they run longer. Glosses assembled from cross-references embed the target word and its reading.

**A sense becomes `derived` only when its text is fully accounted for by a relation word plus a list of references.** Where any prose remains (`in which … means …`, a trailing `(e.g. …)`, a separator such as `+ {verb} +`), the references are not extracted: the text stays in `en` and an LLM writes the gloss (`llm_ok`). Extracting partially would both drop references from a list and mistake a word inside the prose for a reference.

`derived` glosses follow fixed patterns. `DERIVED_FORMS` in `tools/build_entries.py` is the source of truth, and `tools/test_build_entries.py` pins it.

| `kind` | Pattern |
|---|---|
| `variant` | `它（tā）の異体字` |
| `old` | `汝（rǔ）の旧字体` |
| `erhua` | `词（cí）の儿化形` |
| `see` | `开金（kāi jīn）に同じ` |
| `see_also` | `词（cí）も参照` |
| `abbr` | `开金（kāi jīn）の略` |
| `used_in` | `㐖毒（Xié dú）に使われる字` |

Several targets are joined with `・` (`甲（jiǎ）・乙（yǐ）に同じ`).

### What moe means

The result of cross-checking against MoeDict (the Ministry of Education's *Revised Mandarin Chinese Dictionary*, published as JSON by g0v). **None of MoeDict's text is in this dataset.** Its licence forbids derivative works, so only the presence of a headword and the number of senses were read, leaving these three values.

| Value | Meaning | Entries |
|---|---|---|
| `full` | MoeDict has the headword, with at least as many senses as this dataset | 50,219 |
| `headword` | The headword is there, but with fewer senses | 22,153 |
| `none` | No headword | 85,426 |

The lookup uses the traditional spelling (`trad`, or `word` when there is none). MoeDict is a Taiwanese dictionary, so mainland-only and recent words are absent from it. **`none` does not mean an error.**

### Ordering

The first 124,985 entries follow CC-CEDICT's file order; the remaining 32,813 supplement entries follow the previous version's file order.

**This is not frequency order.** A word-segmentation dictionary (cppjieba) was consulted to decide which glosses to generate first, but neither those ranks nor the frequencies are in the data. Line numbers cannot stand in for importance.

### data/ja-zh/glosses.jsonl

The ja→zh format is unchanged.

| Key | Type | Required | Meaning |
|---|---|---|---|
| `word` | string | yes | Headword (Japanese) |
| `zh` | array of objects | yes | Chinese translation candidates. No upper limit on the count. Element keys are only `s` and `pinyin` |
| `unsure` | true | optional | Marks a translation whose reliability is in doubt |

In each `zh` element, `s` is the Chinese spelling and `pinyin` its reading. Spellings are mostly simplified characters, but they also include loanwords used as such in Chinese (`App`, `cosplay`, `AA制`) and kana in Japanese grammar terms (`サ行不规则活用`). Candidates are ordered with the main one first.

```json
{"word": "明白", "zh": [{"s": "明白", "pinyin": "míngbai"}, {"s": "清楚", "pinyin": "qīngchu"}]}
{"word": "と言うもの", "zh": [], "unsure": true}
```

| Group | Count |
|---|---|
| no `unsure` | 38,565 |
| `unsure: true`, `zh` has one or more items | 493 |
| `unsure: true`, `zh` is empty | 942 |

Candidate counts: 942 words have none, 15,979 have one, 22,150 have two, 929 have three.

The ja→zh file stays as it is from here on. A dictionary keyed by Japanese headwords is continued by [ja-learner-dict](https://github.com/inakaegg/ja-learner-dict).

### manifest.json

A small file declaring the format version, the counts and the sizes, so that a reader does not silently consume data in an unexpected format.

`schema_version` is **the version of the format this document describes**, currently 3. It became 3 with this revision, which rebuilt the zh→ja side on CC-CEDICT and made one line one entry.

An excerpt of the real file, with the body of `sources` elided.

```json
{
  "schema_version": 3,
  "generated": "2026-09-08",
  "files": {
    "zh-ja/entries.jsonl.deflate": {
      "lines": 157798,
      "entries_skeleton": 124985,
      "entries_supplement": 32813,
      "senses": 229130,
      "compression": "deflate",
      "bytes": 7424431,
      "uncompressed_bytes": 34405030
    },
    "ja-zh/glosses.jsonl": {"lines": 40000}
  },
  "sources": { "CC-CEDICT": { "…": "…" }, "…": "…" }
}
```

`sources` lists the upstream data — the same five entries as the [Sources](#sources) table. `tools/dataset_sources.py` is the source of truth for its contents, and the validator checks that the two agree. **Left free-form, this field could carry numbers the dataset is not allowed to hold** — BCCWJ frequencies, cppjieba ranks — and checking it against the table prevents that.

## What unsure means

`unsure` means "**do not take this gloss at face value**". It does not mean there is no gloss.

On the zh→ja side it appears on 119 supplement senses. On the ja→zh side, 493 of the 1,435 marked lines do carry a translation. Presence of a translation and `unsure` are separate pieces of information; to test for an empty translation, look at the length of `zh` directly. `unsure` is written only when set, as `true`; no line writes `false`.

Readers are advised not to drop `unsure` senses while reading. Decide whether to exclude them at display time.

## HSK levels

HSK has two editions: 2.0 (up to level 6) and 3.0 (up to level 7). **Each edition goes into its own key.**

| Key | Entries | Level range |
|---|---|---|
| `hsk2` | 5,607 | 1–6 |
| `hsk3` | 12,196 | 1–7 |

Entries per level:

| Level | 1 | 2 | 3 | 4 | 5 | 6 | 7 |
|---|---|---|---|---|---|---|---|
| `hsk2` | 222 | 216 | 379 | 696 | 1,438 | 2,656 | — |
| `hsk3` | 688 | 910 | 1,086 | 1,096 | 1,172 | 1,267 | 5,977 |

**A level is a property of the word.** The upstream data carries one level per word, so **every entry with that headword gets the same value**, regardless of reading. The number of entries with a level is therefore larger than the 11,470 words upstream.

Attaching levels only to the matching reading leaves gaps — `了 liǎo` would carry a level while `了 le` would not. The previous version also held them as "every line of the same word carries the same value".

All 11,470 upstream words are present as headwords in the new data; the 29 that CC-CEDICT lacks are kept as supplement entries with their level. `tools/validate_data.py --hsk-seed` reads the upstream data directly and checks this end to end.

5,068 entries carry a level in both editions. **The two editions often disagree, so difficulty cannot be compared across them.**

## Using it from Swift

The repository is a SwiftPM package. The zh→ja data and `manifest.json` are bundled (ja→zh is not).

No tag has been published yet, so pin the commit you want.

```swift
.package(url: "https://github.com/inakaegg/zh-ja-dict.git", revision: "<40-character commit SHA>")
```

```swift
import ZhJaDictData

let entries = ZhJaDictData.entriesURL()   // data/zh-ja/entries.jsonl.deflate
let manifest = ZhJaDictData.manifestURL() // data/manifest.json

let compressed = try Data(contentsOf: entries!)
let plain = try (compressed as NSData).decompressed(using: .zlib) as Data
```

### Pass a bundle when you ship it inside an app

Omitting the argument falls back to `Bundle.module`, and **that is not reliable inside a `.app`**. SwiftPM generates only two search locations: next to the `.app`, and a `.build` path baked in as an absolute path on the build machine. An app that puts resources in `Contents/Resources/` misses the former and **hits `.build` on the build machine, so it appears to work**. On the target machine there is no `.build`, and only then does the lookup fail.

Resolve the bundle yourself using `ZhJaDictData.bundleName` (`zh-ja-dict_ZhJaDictData.bundle`) and pass it in.

```swift
let bundle = Bundle(url: appResources.appendingPathComponent(ZhJaDictData.bundleName))
guard let entries = ZhJaDictData.entriesURL(in: bundle) else {
    throw MyError.bundledDataMissing   // "the bundled data is missing", not "the lookup failed"
}
```

## Validating the data

`tools/validate_data.py` reads both data files and `manifest.json` in full and reports format violations. It runs on Python 3.9 or newer with nothing to install.

```console
$ python3 tools/validate_data.py --cedict-entries 124985
## zh-ja/entries.jsonl.deflate（157,798行）
  骨格                       124,985
  補遺                        32,813
  ...
違反 0 件
```

A single violation exits with status 1. GitHub Actions (`.github/workflows/validate.yml`) runs the same command on push and pull request. Pass `--counts` to see only the tallies; that always exits 0.

The script checks: that the compressed stream is complete; that each line parses as JSON; that the keys match the tables above; that **(simplified, traditional, reading) triples do not repeat**; that HSK levels are in range; that parts of speech, `misc`, `qa`, `src`, `seed`, `moe` and cross-reference `kind`s hold only specified values; that readings are writable as pinyin; that no other language leaked into a gloss; that `manifest.json`'s counts, sizes and source table match the real files; and that the number of skeleton entries matches CC-CEDICT's entry count (`--cedict-entries`).

It can also confirm that every (headword, reading) of the previous version is covered. That file is not shipped, so take it out of git and pass it in.

```console
$ git show <old commit>:data/zh-ja/glosses.jsonl > tmp/old-glosses.jsonl
$ python3 tools/validate_data.py --existing tmp/old-glosses.jsonl
```

The language-leak check needs a word of explanation. Both Japanese and Chinese write abbreviations, units and proper nouns in Latin script (`CD-ROM`, `X線`, `AA制`). A gloss where an English word survived a failed generation looks exactly the same. Since no machine can tell the two apart, the Latin words that may appear are listed in `tools/allowlist-latin.txt` and everything else is reported. Words that may carry kana inside a Chinese translation (Japanese grammar terms) are in `tools/allowlist-kana-in-chinese.txt`.

When adding or fixing glosses needs a new word, confirm that the language really writes it that way before appending to those files.

The tools' self-tests run on the standard library alone, against small fabricated data; they never read the real files.

```console
$ python3 -m unittest discover -s tools -p 'test_*.py'
```

Point `ZH_JA_DICT_CEDICT` at the real CC-CEDICT file to also run the parser over every entry; without it that check is skipped.

```console
$ ZH_JA_DICT_CEDICT=<cedict_1_0_ts_utf-8_mdbg.txt.gz> \
    python3 -m unittest discover -s tools -p 'test_*.py'
```

## How it is made

Fetch the upstream data first, then run these in order. Intermediate files under `tmp/` are not version-controlled.

```sh
# 1. Build the skeleton from CC-CEDICT, HSK and the previous version's glosses
python3 tools/build_entries.py \
    --cedict <cedict_1_0_ts_utf-8_mdbg.txt.gz> \
    --hsk-seed <hsk-seed.json> \
    --existing <the previous glosses.jsonl> \
    --jieba <jieba.dict.utf8> \
    --out tmp/entries-base.jsonl --order tmp/order.tsv

# 2. Write the short Japanese glosses (prompt: tools/prompts/ja-gloss.md)
python3 tools/run_ja_shards.py --mode plan --full tmp/entries-base.jsonl \
    --order tmp/order.tsv --targets tmp/ja-full/targets.txt
python3 tools/run_ja_shards.py --mode run --full tmp/entries-base.jsonl \
    --targets tmp/ja-full/targets.txt --dir tmp/ja-full --shards 8
python3 tools/run_ja_shards.py --mode merge --dir tmp/ja-full --out tmp/ja-full.jsonl
python3 tools/run_ja_shards.py --mode verify --full tmp/entries-base.jsonl \
    --out tmp/ja-full.jsonl --targets tmp/ja-full/targets.txt

# 3. Merge the glosses, cross-check MoeDict, compress and write data/
python3 tools/build_dataset.py \
    --base tmp/entries-base.jsonl --glosses tmp/ja-full.jsonl \
    --repaired tmp/ja-full.jsonl.repaired \
    --moedict <dict-revised.json> --generated <YYYY-MM-DD> --out data

# 4. Validate everything. Pass the previous version and the HSK seed to catch losses
python3 tools/validate_data.py --cedict-entries 124985 \
    --existing <the previous glosses.jsonl> --hsk-seed <hsk-seed.json>
```

The same inputs produce the same bytes.

Glosses are written per sense. The model receives CC-CEDICT's English sense and register labels, plus the previous version's gloss as a candidate when the same (headword, reading) existed there. **The 8,980 senses that hold only a cross-reference and no English text are assembled mechanically instead** (see [What qa means](#what-qa-means)). Supplement entries reuse the previous version's gloss as it is.

Finished glosses go through the script and length checks, and only the failures are rewritten (`--repair`). The list of rewritten senses is left in `<out>.repaired`, which the build step takes via `--repaired`. **Without it, the 690 rewritten senses end up marked `llm_ok`.**

**None of the upstream data is in this repository.** Fetch CC-CEDICT, the HSK vocabulary, the cppjieba dictionary and MoeDict from their own sources. The previous version's glosses can be recovered from git history.

## Sources

| Upstream | How it is used | Where | Licence |
|---|---|---|---|
| CC-CEDICT | The zh→ja skeleton: headwords, readings, English senses, measure words, register notes | [MDBG](https://www.mdbg.net/chinese/dictionary?page=cc-cedict) | CC BY-SA 4.0 |
| complete-hsk-vocabulary | HSK 2.0 / 3.0 levels and parts of speech; only levels and parts of speech are stored | [GitHub](https://github.com/drkameleon/complete-hsk-vocabulary) | MIT |
| cppjieba | Consulted only to decide the generation order; no frequencies or ranks are stored | [GitHub](https://github.com/yanyiwu/cppjieba) | MIT |
| MoeDict (MoE *Revised Mandarin Chinese Dictionary*) | Consulted only to compare headwords and sense counts. **No text is stored** | [g0v](https://github.com/g0v/moedict-data) | CC BY-ND 3.0 TW |
| zh-ja-dict, previous version | The supplement for words and readings CC-CEDICT lacks (31,874 and 939), and gloss candidates | This repository's history | CC BY-SA 4.0 |
| Jitendex / JMdict | Headword selection for the ja→zh side | [Jitendex](https://jitendex.org/) | CC BY-SA 4.0 |

Most Japanese glosses were written by a large language model (Claude Opus). Cross-reference-only senses were assembled mechanically, two were written by hand, and words absent from CC-CEDICT carry glosses inherited from the previous version (see [the table at the top](#zh-ja-dict)). The Chinese glosses (ja→zh) were written by a large language model. No sense text from commercial or OS-bundled dictionaries was used as input, and none is present in the data.

**None of MoeDict's text enters the generation input or the output.** The build reads only each entry's headword (`title`) and its number of senses, and discards the definition text (`load_moedict` in `tools/build_dataset.py`). What survives into the data is the three `moe` values.

MoeDict's CC BY-ND 3.0 TW forbids derivative works. The basis for holding that this dataset does not engage that condition is the fact stated above: none of the text is kept anywhere. **No further legal reading is offered here.** To ingest MoeDict yourself, consult [the g0v distribution](https://github.com/g0v/moedict-data) and the Ministry's own terms directly.

The ja→zh headwords are the 40,000 highest-priority headwords of Jitendex (a dictionary derived from JMdict), ordered by JMdict's priority score. JMdict is published by [EDRDG](https://www.edrdg.org/edrdg/licence.html) under CC BY-SA 4.0.

The MIT licence requires the copyright notice to be preserved. Here it is verbatim.

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

- Glosses favour brevity and carry no usage notes or examples
- The validator detects language leaks, but **it cannot detect a wrong translation**
- Supplement entries have no English senses and only one sense each. They join the one to three glosses the previous version held per word, so **their sense divisions do not line up with skeleton entries**
- 693 supplement entries look more like word combinations than dictionary headwords (`两个` "two", `很少` "very few"). They are kept for the benefit of looking up segmented text
- Senses with `qa: "unchecked"` were never checked. They come from the previous version's separate file of per-reading senses
- `moe` only looks at headwords and sense counts. **It says nothing about whether a gloss is right**
- Cross-references are structured only when the sense text is fully accounted for by a relation word plus a list of references. Where prose follows (`abbr. for Hubei 湖北省[…] and Hunan 湖南省[…] provinces together`), the text stays in `en` and **the references are not navigable**. The gloss is written by an LLM reading the whole text
- Measure words live on the entry, so **there is no way to express which sense they apply to**. CC-CEDICT's own data does not carry that information
- Reading notation is not uniform. Skeleton entries convert CC-CEDICT's syllable-spaced readings into tone marks (`ài hào`), while supplement entries keep the previous version's notation, which is mostly unspaced (`yùnshūjī`)
- Traditional spellings are not paired with readings. Because CC-CEDICT splits entries by reading, `发` becomes one entry for `發`/`fā` and another for `髮`/`fà`; **the pairing holds only within one entry**
- On the ja→zh side, Japanese grammar terms mix kana and romanized notation (`ら行` alongside `日语ra行`, `ya行`). The notation was not unified
- The language-leak check has gaps. The allowlist holds ordinary English words (`live`, `house`, `look`, `boss`, `play`, `flag`) and single letters (`A`–`X`), so a new generation failure in those words goes undetected. The allowlist is also shared between the two directions, so a word valid in one passes in the other

## Change history

### 2026-09-06 — Rebuilt on CC-CEDICT (schema 3)

The zh→ja side was rebuilt on CC-CEDICT. The unit of a line changed from "headword and reading" to **one entry**, and **each sense now carries its own Japanese gloss** (96,326 lines → 157,798 entries, 229,130 senses (7.1 MB compressed, 32.7 MB expanded)).

- English senses, measure words, register labels, variants and cross-references are pulled out of CC-CEDICT by rule into structured fields. Measure words go on the entry, since they are a property of the word
- All 96,326 lines of the previous version are covered. The 32,813 words and readings CC-CEDICT lacks were kept as **supplement entries**, glosses included
- The zh→ja file is now **compressed with raw DEFLATE** and named `entries.jsonl.deflate`
- `data/zh-ja/glosses.jsonl` was retired. The old data can be recovered from git history
- A MoeDict cross-check was added in the `moe` field. **None of MoeDict's text is included**
- The Swift entry point changed from `glossesURL()` to `entriesURL()`

### 2026-09-03 — Unit changed from "word" to "headword and reading"

Lines came to represent (headword, reading); `polyphonic.jsonl`, which held per-reading senses, was retired and merged into the zh→ja `glosses.jsonl` (95,463 → 96,326 lines).

### 2026-09-01 — HSK vocabulary merged

11,470 HSK words were merged into the zh→ja `glosses.jsonl`, adding the `hsk2`, `hsk3`, `trad` and `pos` keys.

### 2026-09-01 — Format unification and language-intrusion fixes

Lines where an English or Russian word had leaked into a Japanese gloss were corrected: 17 on the zh→ja side and 7 in the retired `polyphonic.jsonl`.

## License

The data and documents in this repository are provided under [CC BY-SA 4.0](https://creativecommons.org/licenses/by-sa/4.0/). CC-CEDICT, which forms the skeleton, and JMdict, used to select the ja→zh headwords, are published under the same terms, so those terms carry over.

**What this project produced is under the same terms**: the Japanese glosses written by an LLM, the glosses assembled mechanically from cross-references, the two written by hand, the glosses inherited from the previous version, and the structure built by extracting CC-CEDICT's notes.

When redistributing, credit the three upstream works together with this repository.

> This work is based on CC-CEDICT, a Chinese-English dictionary published by MDBG, used under CC BY-SA 4.0.
>
> This work is based on JMdict, property of the Electronic Dictionary Research and Development Group (EDRDG), used under CC BY-SA 4.0.
>
> Japanese glosses and dataset structure from zh-ja-dict by inakaegg, used under CC BY-SA 4.0.

The HSK levels come from complete-hsk-vocabulary, which is MIT licensed. Preserve the copyright notice reproduced above.

MoeDict is CC BY-ND 3.0 TW. **This repository holds not one character of MoeDict's text.** What it ships is only the counting result: whether a headword exists, and whether it has more or fewer senses than this dataset (see [What moe means](#what-moe-means)).
