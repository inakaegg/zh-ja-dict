# zh-ja-dict

中国語と日本語の対訳データ集です。学習アプリで単語の訳を表示することを目的に作りました。

**中日と日中で形式が違います。** 中日はこの改訂で作り直した schema 3 で、CC-CEDICT の entry ごとに語義を分け、語義ごとに訳を持ちます。日中は従来の形式のままで、1語1行の中国語訳を 40,000 語ぶん収めたものです。

中日は [CC-CEDICT](https://www.mdbg.net/chinese/dictionary?page=cc-cedict) を骨格にして、**語義ごとに短い日本語訳を1つ**付けます。英語の語義は CC-CEDICT のものをそのまま使い、量詞・語感の印・異体字や参照といった注記は、規則で取り出して構造化したフィールドへ移しました。

日本語訳の作り方は語義によって違います。合計は 229,130 語義です。

| 作り方 | 語義数 |
|---|---|
| **この改訂で LLM が書いた** | **187,335** |
| CC-CEDICT に無い語と読みのため、旧版の訳を引き継いだ | 32,813 |
| 参照だけの語義なので、参照先から機械で組み立てた | 8,980 |
| 生成で直らず、人が書いた | 2 |

区分ごとの検品の度合いは [qa の意味](#qa-の意味) を見てください。

- 中日 `data/zh-ja/entries.jsonl.deflate` 157,798 entry・229,130 語義（圧縮後 7,424,431 バイト、展開すると 34,405,030 バイト）。日中 `data/ja-zh/glosses.jsonl` 40,000行
- 中日の1行は **1 entry**です。(簡体字, 繁体字, 読み) の3つ組で一意になります
- **中日は圧縮して同梱します。** raw DEFLATE（RFC 1951）です（[圧縮の形](#圧縮の形)）
- 検品の度合いは語義ごとに違います。`qa` の欄で見分けられます
- **[CC BY-SA 4.0](https://creativecommons.org/licenses/by-sa/4.0/)** で提供します（[ライセンス](#ライセンス)）

## 収録データ

| ファイル | 方向 | 行数 | 語義 | 内容 |
|---|---|---|---|---|
| `data/zh-ja/entries.jsonl.deflate` | 中日 | 157,798 | 229,130 | 語義ごとの簡潔な日本語訳。英語の語義・ピンイン・量詞・語感の印つき |
| `data/ja-zh/glosses.jsonl` | 日中 | 40,000 | — | 中国語訳（ピンイン付き）。1語1行 |

このほかに `data/manifest.json` があります（[manifest.json](#manifestjson)）。

中日の entry は2種類あります。

| 種類 | 件数 | 中身 |
|---|---|---|
| 骨格 entry | 124,985 | CC-CEDICT の1行。英語の語義を持ちます |
| 補遺 entry | 32,813 | CC-CEDICT に無い語と読み。この辞書の旧版から引き継いだもので、`src: "zh-ja-dict"` が付きます |

補遺の内訳は2つです。**31,874 件は CC-CEDICT に見出しが無い語**、**939 件は見出しはあるが読みが違うもの**です（`绷 bèng`「ひび割れる」は CC-CEDICT が `bēng`・`běng` しか持ちません）。

補遺があるのは、CC-CEDICT が実文に現れる語と読みをすべて載せているわけではないからです。旧版の見出し語は分かち書き辞書（cppjieba）の語彙から選んでおり、`运输机`（輸送機）・`身旁`・`三合板`（合板）のように、CC-CEDICT に無い普通の語が3万語あります。これらを落とすと、文章中に現れた語を引ける割合が下がります。旧版の訳をそのまま持つ entry として残しました。**補遺 entry には英語の語義がありません。**

## 形式

### 圧縮の形

`data/zh-ja/entries.jsonl.deflate` は、1行1 entry の JSON Lines（UTF-8、LF）を **raw DEFLATE**（RFC 1951）で固めたものです。**gzip・zlib のヘッダは付いていません。**

Python から読むときは窓の大きさに負の値を渡します。

```python
import codecs, zlib
decompressor = zlib.decompressobj(-15)   # 負の値がヘッダ無しの合図
```

Swift（Apple の Compression framework）ではそのまま展開できます。

```swift
let plain = try (compressed as NSData).decompressed(using: .zlib) as Data
```

`NSData.DecompressionAlgorithm.zlib` と C の `COMPRESSION_ZLIB` は、名前に反して**ヘッダ無しの DEFLATE** を指します。ここで zlib ヘッダを付けると、書く側は何も気付かないまま読む側だけが壊れます。読み書きの正本は `tools/entries_file.py` です。

同梱しているのは 7,424,431 バイトで、展開すると 34,405,030 バイトになります（**21.6%**）。

`zlib` は圧縮の流れが途中で切れていても例外を出しません。途中まで展開して黙って終わるので、**流れの終わりの印を確かめてください**。`tools/entries_file.py` はこれを確かめます。

### entry

| キー | 型 | 必須 | 意味 |
|---|---|---|---|
| `word` | string | 必須 | 見出し語（簡体字） |
| `trad` | string | 任意 | 繁体字の綴り。`word` と異なるときだけ置きます |
| `pinyin` | string | 必須 | 読み。声調記号つき（`shàng jí`） |
| `tw_pr` | string | 任意 | 台湾での読み |
| `also_pr` | string | 任意 | 別の読み |
| `hsk2` | 整数 | 任意 | HSK 2.0 の級（1〜6）。[HSKの級](#hskの級)を参照 |
| `hsk3` | 整数 | 任意 | HSK 3.0 の級（1〜7） |
| `pos` | string の配列 | 任意 | 品詞。HSK の資料の略号をそのまま使います（`n`・`v`・`u` など） |
| `cl` | 配列 | 任意 | 量詞。要素は `{"w": 簡体字, "t": 繁体字, "py": 読み}` |
| `src` | string | 任意 | 補遺 entry にだけ付き、値は `"zh-ja-dict"` です |
| `seed` | string | 任意 | 旧版の訳を作成の候補として渡した entry に付き、値はその訳の検品の区分です |
| `moe` | string | 任意 | 萌典との照合結果。[moe の意味](#moe-の意味)を参照 |
| `senses` | 配列 | 必須 | 語義。1件以上あります |

```json
{"word": "计算机", "trad": "計算機", "pinyin": "jì suàn jī", "cl": [{"w": "台", "t": "臺", "py": "tai2"}], "hsk3": 2, "pos": ["n"], "seed": "machine_backed", "moe": "full", "senses": [{"en": ["computer"], "ja": "コンピュータ", "qa": "llm_ok"}, {"en": ["calculator"], "ja": "電卓", "qa": "llm_ok", "misc": ["tw"]}]}
{"word": "运输机", "trad": "運輸機", "pinyin": "yùnshūjī", "src": "zh-ja-dict", "moe": "none", "senses": [{"ja": "輸送機", "qa": "machine_backed"}]}
```

任意キーを持つ entry の数は次のとおりです。

| キー | entry 数 |
|---|---|
| `trad` | 77,816 |
| `seed` | 64,390 |
| `pos` | 12,481 |
| `hsk3` | 12,196 |
| `hsk2` | 5,607 |
| `cl` | 1,552 |
| `tw_pr` | 510 |
| `also_pr` | 175 |

### entry の鍵は3つ組です

**(簡体字, 繁体字, 読み) の3つ組で一意**になります。(簡体字, 読み) の2つ組では**1,065組が重なります**。同じ簡体字と読みに、繁体字だけが違う entry が並ぶためです（`俊 jùn` は繁体字が `俊` の entry と `儁` の entry の2つ）。

読みが違えば別の entry です。`东西` は `dōng xī`（東と西）と `dōng xi`（もの）で2 entry に分かれます。大文字で始まる読みは固有名詞で、`三 sān`（数の3）と `三 Sān`（姓）も別の entry です。

同じ見出し語を持つ entry は隣り合うとは限りません。見出し語（簡体字）で引くと 153,071 語、うち複数の entry を持つ語があります。

### senses の要素

| キー | 型 | 必須 | 意味 |
|---|---|---|---|
| `ja` | string | 必須 | 日本語の簡潔訳。1語義に1つ |
| `qa` | string | 必須 | `ja` の出どころと検品の区分。[qa の意味](#qa-の意味)を参照 |
| `en` | string の配列 | 任意 | 英語の語義。CC-CEDICT の語義を `;` で分けたものです。補遺 entry にはありません |
| `unsure` | true | 任意 | 旧版で訳の確からしさに不安があるとされた印。補遺 entry にだけ付きます |
| `misc` | string の配列 | 任意 | 語感・地域・修辞の印。[misc の印](#misc-の印)を参照 |
| `variant_of` | 配列 | 任意 | 異体字の参照先。[参照の読み方](#参照の読み方)を参照 |
| `see_also` | 配列 | 任意 | 同義語・略語などの参照先 |
| `lsource` | string の配列 | 任意 | 借用元。CC-CEDICT の `(loanword from …)` の中身 |
| `s_inf` | string の配列 | 任意 | 構造化したフィールドへ移せなかった注記。いまの版では0件 |

任意キーを持つ語義の数は次のとおりです。

| キー | 語義数 |
|---|---|
| `en` | 187,335 |
| `misc` | 13,206 |
| `see_also` | 5,475 |
| `variant_of` | 3,505 |
| `unsure` | 119 |
| `lsource` | 104 |

`en` を持たない 41,795 語義の内訳は、補遺 entry の 32,813 と、英語の語義文が無く参照だけが書かれた 8,980、それに CC-CEDICT が印しか書いていない2語義（`吜`・`噶噶`、どちらも `(onom.)` だけ）です。

**量詞は entry の欄です。**CC-CEDICT は `CL:個|个[ge4]` を独立した断片として置くだけで、どの語義に掛かるかを書いていません。語義へ結び付けると、`计划` の「to map out」のような動詞の語義にまで量詞が付いてしまいます。量詞は語の性質なので entry の欄に集めました。

同じ理由で、`(bound form)` のように**印だけが独立した断片になっている場合**は、その印を隣の語義へ寄せます（後ろに語義があればそちらへ、無ければ前へ）。印だけで語義がまったく無い entry は2つあり、そこでは印だけの語義がそのまま残ります。

### 訳が同じ語義はまとめます

CC-CEDICT は英語の同義語を別々の語義として並べます（`时代` の `age` と `era`、`水果刀` の `paring knife` と `fruit knife`）。日本語にすると同じ訳になるので、そのままでは画面に同じ訳が並びます。**同じ entry の中で `ja` が同じ語義は1つにまとめます。**

- **英語の語義は捨てません。** `en` を出てきた順に連ねます（`{"en": ["age", "era"], "ja": "時代"}`）
- まとめるのは**注記がすべて同じ語義どうし**に限ります。`misc`・参照・借用元・`s_inf`・`unsure` のどれかが違えば別の語義のままです。口語や方言の印が付いていない語義にまで印を広げないためです
- `qa` は最初の語義のものを引き継ぎます。ただし1つでも `llm_fixed` があれば `llm_fixed` にします

全量では **1,174 語義**がまとまりました（まとめる前は 230,304、後は 229,130）。

`ja` は日本語の文字（漢字・かな）で書きます。ラテン文字は `tools/allowlist-latin.txt` に載せた語だけ、長さは24文字までです。旧版から引き継いだ訳と、参照から機械で組み立てた訳は、この2つの制限の外にあります（[qa の意味](#qa-の意味)）。

### misc の印

CC-CEDICT の丸括弧の注記のうち、**語感・地域・修辞を表すものだけ**を印にしました。

| 印 | 意味 | 語義数 |
|---|---|---|
| `idiom` | 成語 | 3,965 |
| `written` | 書面語 | 1,368 |
| `fig` | 比喩的な用法 | 1,312 |
| `tw` | 台湾での用法 | 1,305 |
| `coll` | 口語 | 941 |
| `loan` | 外来語 | 917 |
| `bound` | 単独では使わない形態素 | 792 |
| `old` | 古い用法 | 653 |
| `dial` | 方言 | 584 |
| `slang` | 俗語 | 523 |
| `onom` | 擬音語・擬態語 | 228 |
| `arch` | 廃語 | 223 |
| `net` | ネット用語 | 157 |
| `proverb` | ことわざ | 95 |
| `derog` | 見下した言い方 | 90 |
| `cantonese` | 広東語 | 65 |
| `formal` | 改まった言い方 | 62 |
| `honor` | 敬語 | 62 |
| `hk` | 香港での用法 | 61 |
| `neo` | 新語 | 49 |
| `polite` | 丁寧な言い方 | 38 |
| `vulgar` | 下品な言い方 | 36 |
| `humble` | へりくだった言い方 | 33 |
| `euph` | 婉曲な言い方 | 28 |
| `joc` | おどけた言い方 | 24 |

**分野の名前は印にしていません。** CC-CEDICT の丸括弧には `(computing)`・`(medicine)`・`(bird species of China)` のような分野の注記が3,165種あり、これを印にすると分類の体系をひとつ抱えることになります。この辞書には要らないので、**語義の文（`en`）の一部としてそのまま残しました**。日本語訳を作るときは手掛かりに使い、訳文へは写していません。

`(lit.)` も印にしていません。これは成語の字面の意味を導く言葉で、書面語を表す `(literary)` とは別物だからです。

### 参照の読み方

`variant_of` と `see_also` は、参照先の語を指します。要素の形は同じで、`kind` が関係の種類を表します。

| キー | 意味 |
|---|---|
| `kind` | 関係の種類（下の表） |
| `w` | 参照先の簡体字 |
| `t` | 参照先の繁体字。`w` と異なるときだけ |
| `py` | 参照先の読み。CC-CEDICT の数字つきの書き方のまま |

| 欄 | `kind` | 意味 |
|---|---|---|
| `variant_of` | `variant` | 異体字 |
| | `old` | 旧字体 |
| | `erhua` | 儿化形 |
| `see_also` | `see` | 同じ意味の語 |
| | `see_also` | あわせて見る語 |
| | `abbr` | 略語の元 |
| | `used_in` | この字が使われる語 |

**`py` だけは数字つきの書き方です。** entry の `pinyin` は声調記号つきですが、参照先の読みは CC-CEDICT の表記をそのまま残しています。

```json
{"en": ["to admonish"], "ja": "いさめる", "qa": "llm_ok"}
{"ja": "证（zhèng）の異体字", "qa": "derived", "variant_of": [{"kind": "variant", "w": "证", "py": "zheng4"}]}
```

### qa の意味

語義ごとに、その日本語訳をどう作り、どう確かめたかを表します。

| 値 | 意味 | 長さの上限 |
|---|---|---|
| `llm_ok` | CC-CEDICT の英語の語義から LLM が作り、文字種と長さの検査を通った | 24文字 |
| `llm_fixed` | 検査に落ちたので作り直した | 24文字 |
| `derived` | 参照から機械で組み立てた（`证（zhèng）の異体字` など） | 200文字 |
| `machine_backed` | 旧版から引き継いだ。旧版で既存の辞書資源と突き合わせ、裏付けが取れた | 80文字 |
| `llm_ok`（補遺） | 旧版から引き継いだ。旧版で照合の裏付けが取れず、LLM に読ませて妥当と判断した | 80文字 |
| `llm_fixed`（補遺） | 同上で、LLM が訳を直した | 80文字 |
| `human_reviewed` | 旧版から引き継いだ。多音字の読みと語義の対応を人が確認した | 80文字 |
| `unchecked` | 旧版から引き継いだ。**検品を通していない** | 80文字 |
| `hand_fixed` | 作り直しを繰り返しても決まりに合う訳が出ず、人が書いた | 24文字 |

`llm_ok` と `llm_fixed` は、新しく作った語義と補遺 entry の両方に現れます。どちらであるかは entry の `src` で見分けられます。

語義ごとの内訳は次のとおりです。

| `qa` | 語義数 |
|---|---|
| `llm_ok` | 201,568 |
| `machine_backed` | 17,670 |
| `derived` | 8,980 |
| `llm_fixed` | 691 |
| `unchecked` | 219 |
| `hand_fixed` | 2 |

`hand_fixed` の2語義は `tools/gloss-overrides.tsv` に見出し語・読み・語義の番号・訳・理由を書いてあります。組み立てのときに当たる語義が無ければ止まります。無効になった行が残っていれば必ず気付きます。

長さの上限が3通りあるのは、訳の作られ方が違うからです。新しく作った訳は「24文字以内」という規則のもとで生成しています。旧版から引き継いだ訳は、旧版が語ごとに1〜3件持っていた訳を読点でつないだものなので長くなります。参照から組み立てた訳は、参照先の語と読みをそのまま含みます。

**`derived` にするのは、語義の文が「関係を表す語＋参照の並び」だけで残らず説明できたときに限ります。**少しでも説明が残る形は、参照として取り出さずに文のまま `en` へ残し、訳は LLM が作ります（`llm_ok`）。`in which … means …` が続くもの、`(e.g. …)` が付くもの、`+ {verb} +` のような別の区切りがあるものがこれに当たります。

部分的に取り出すと不具合が2方向に出ます。並んだ参照を取りこぼす場合と、説明の中の語を参照と読み違える場合です。

`derived` の訳は決まった形で組み立てます。文面は `tools/build_entries.py` の `DERIVED_FORMS` が正本で、`tools/test_build_entries.py` が固定しています。

| `kind` | 文面 |
|---|---|
| `variant` | `它（tā）の異体字` |
| `old` | `汝（rǔ）の旧字体` |
| `erhua` | `词（cí）の儿化形` |
| `see` | `开金（kāi jīn）に同じ` |
| `see_also` | `词（cí）も参照` |
| `abbr` | `开金（kāi jīn）の略` |
| `used_in` | `㐖毒（Xié dú）に使われる字` |

参照先が複数あるときは中黒でつなぎます（`甲（jiǎ）・乙（yǐ）に同じ`）。

### moe の意味

萌典（教育部「重編國語辭典（修訂本）」を g0v が JSON 化したもの）と突き合わせた結果です。**萌典の本文はこのデータに一切含みません。** 萌典は改変を許さないライセンスのため、見出しの有無と語義の数だけを見て、次の3値を残しています。

| 値 | 意味 | entry 数 |
|---|---|---|
| `full` | 萌典に見出しがあり、語義の数がこの辞書と同じかそれ以上 | 50,219 |
| `headword` | 見出しはあるが、語義の数が少ない | 22,153 |
| `none` | 見出しが無い | 85,426 |

照合は繁体字（`trad`、無ければ `word`）で行います。萌典は台湾の辞典なので、大陸でしか使わない語や新しい語には見出しがありません。**`none` は誤りを意味しません。**

### 並び順

先頭から 124,985 entry が CC-CEDICT のファイルの順、そのあとの 32,813 entry が補遺で、旧版のファイルの順です。

**頻度の順ではありません。** 訳を作る順番を決めるときには分かち書き辞書（cppjieba）の頻度を参照しましたが、その順位も頻度の数値もこのデータには入れていません。行番号を重要度の代わりに使うことはできません。

### data/ja-zh/glosses.jsonl

日中の形式は変えていません。

| キー | 型 | 必須 | 意味 |
|---|---|---|---|
| `word` | string | 必須 | 見出し語（日本語） |
| `zh` | オブジェクトの配列 | 必須 | 中国語訳の候補。件数の上限はありません。要素のキーは `s` と `pinyin` の2つだけ |
| `unsure` | true | 任意 | 訳の確からしさに不安がある印 |

`zh` の要素は、`s` が中国語の表記、`pinyin` がその読みです。表記は簡体字が基本ですが、中国語でそのまま使われる借用語（`App`・`cosplay`・`AA制` など）や、日本語の文法用語のかな（`サ行不规则活用` など）も含みます。候補は主要なものから順に並べています。

```json
{"word": "明白", "zh": [{"s": "明白", "pinyin": "míngbai"}, {"s": "清楚", "pinyin": "qīngchu"}]}
{"word": "と言うもの", "zh": [], "unsure": true}
```

| 区分 | 件数 |
|---|---|
| `unsure` なし | 38,565 |
| `unsure: true`、`zh` は1件以上 | 493 |
| `unsure: true`、`zh` は空配列 | 942 |

候補の数は 0件が942語、1件が15,979語、2件が22,150語、3件が929語です。

日中は今後この形のまま据え置きます。日本語を見出しにする辞書は [ja-learner-dict](https://github.com/inakaegg/ja-learner-dict) が引き継ぎます。

### manifest.json

データの版・件数・大きさを書いた小さなファイルです。読み込む側が、想定と違う版のデータを黙って読んでしまうことを防ぎます。

`schema_version` は**この文書が説明している形式の版**で、現在は 3 です。CC-CEDICT を骨格にして1行を1 entry にした今回の改訂で 3 になりました。

実物から `sources` の中身だけを省いた抜粋です。

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

`sources` には元データの一覧が入ります（[出どころ](#出どころ)の表と同じ5件）。中身は `tools/dataset_sources.py` が正本で、検証スクリプトが両者の一致を確かめます。**この欄を自由記述にすると、収録しないと決めた数値——BCCWJ の頻度や cppjieba の順位——をここへ書けてしまいます。**表と突き合わせることでそれを防いでいます。

## unsure の意味

`unsure` は「**この訳を鵜呑みにしないでほしい**」という印です。訳が無いことを意味しません。

中日では補遺 entry の119語義に付いています。日中では1,435行のうち493行が訳を持っています。訳の有無と `unsure` は別の情報です。「訳が空かどうか」で判定したい場合は、`zh` の長さを直接見てください。`unsure` は立てるときだけ `true` で書きます。`false` を明示した行はありません。

読み込む側では、`unsure` の語義を読み取りの段階で捨てないことを勧めます。除外するかどうかは、表示のときに判断してください。

## HSKの級

HSK には 2.0（6級まで）と 3.0（7級まで）の2つの版があります。**版ごとに別のキーへ入れています。**

| キー | entry 数 | 級の範囲 |
|---|---|---|
| `hsk2` | 5,607 | 1〜6 |
| `hsk3` | 12,196 | 1〜7 |

級ごとの entry 数は次のとおりです。

| 級 | 1 | 2 | 3 | 4 | 5 | 6 | 7 |
|---|---|---|---|---|---|---|---|
| `hsk2` | 222 | 216 | 379 | 696 | 1,438 | 2,656 | — |
| `hsk3` | 688 | 910 | 1,086 | 1,096 | 1,172 | 1,267 | 5,977 |

**級は語の属性です。**元データは語ごとに級を持つので、**同じ見出し語のすべての entry へ同じ値を付けます**。読みが違っても級は変わりません。そのため、級を持つ entry の数は元データの語数（11,470語）より多くなります。

読みが一致する entry だけに付けると、`了 liǎo` に級があって `了 le` に無い、といった歯抜けができます。旧版も「同じ語のすべての行が同じ値を持つ」形でした。

元データの 11,470 語はすべて、見出し語として新しいデータにあります（CC-CEDICT に無い 29 語も補遺 entry として級ごと残しました）。`tools/validate_data.py --hsk-seed` が、元データを直接読んで端から端まで突き合わせます。

両方の版の級を持つ entry が 5,068 あります。**版によって級が違う語が多いため、この2つを混ぜて難易度を比べることはできません。**

## Swiftから使う

SwiftPMのpackageとして参照できます。中日のデータと `manifest.json` が同梱されます（日中は含みません）。

タグはまだ発行していないので、取り込む commit を直接指定してください。

```swift
.package(url: "https://github.com/inakaegg/zh-ja-dict.git", revision: "<40桁のcommit SHA>")
```

```swift
import ZhJaDictData

let entries = ZhJaDictData.entriesURL()   // data/zh-ja/entries.jsonl.deflate
let manifest = ZhJaDictData.manifestURL() // data/manifest.json

let compressed = try Data(contentsOf: entries!)
let plain = try (compressed as NSData).decompressed(using: .zlib) as Data
```

### アプリに組み込むときは、bundleを渡してください

引数を省くと `Bundle.module` から探しますが、**これは `.app` の中では当てになりません**。SwiftPMが生成する探索先は2か所だけで、`.app` 直下と、ビルドした機械の絶対パスで焼き込まれた `.build` です。資源を `Contents/Resources/` へ収めるアプリでは前者に当たらず、**ビルドした機械では `.build` に当たって動いてしまいます**。配布先には `.build` が無いので、そこで初めて見つかりません。

アプリ側で `ZhJaDictData.bundleName`（`zh-ja-dict_ZhJaDictData.bundle`）を手掛かりにbundleを解決し、渡してください。

```swift
let bundle = Bundle(url: appResources.appendingPathComponent(ZhJaDictData.bundleName))
guard let entries = ZhJaDictData.entriesURL(in: bundle) else {
    throw MyError.bundledDataMissing   // 「引けない」ではなく「同梱物が欠けている」として扱う
}
```

## データを検証する

`tools/validate_data.py` が2つのデータファイルと `manifest.json` を全件読み、形式の違反を報告します。Python 3.9以上があれば動きます。追加のインストールは要りません。

```console
$ python3 tools/validate_data.py --cedict-entries 124985
## zh-ja/entries.jsonl.deflate（157,798行）
  骨格                       124,985
  補遺                        32,813
  ...
違反 0 件
```

違反が1件でもあれば終了コード1で終わります。GitHub Actions（`.github/workflows/validate.yml`）が push と pull request で同じコマンドを実行します。件数だけを見たいときは `--counts` を付けます。このときは違反があっても終了コード0で終わります。

このスクリプトが調べるのは次の点です。圧縮の流れが最後まで在るか。JSONとして読めるか。キーの構成が上の表と合っているか。**(簡体字, 繁体字, 読み) の3つ組が重複していないか**。HSKの級が範囲内か。品詞・`misc`・`qa`・`src`・`seed`・`moe`・参照の `kind` が仕様の値だけか。読みがピンインとして書けているか。訳文に別の言語が紛れ込んでいないか。`manifest.json` の件数・大きさ・出どころの表が実ファイルと合っているか。骨格 entry の数が CC-CEDICT の entry 数（`--cedict-entries`）と合っているか。

旧版のすべての (見出し語, 読み) が新しいデータに対応しているかも確かめられます。旧版のファイルは配らないので、git から取り出して渡してください。

```console
$ git show <旧版のcommit>:data/zh-ja/glosses.jsonl > tmp/old-glosses.jsonl
$ python3 tools/validate_data.py --existing tmp/old-glosses.jsonl
```

訳文の言語混入の検査には説明が要ります。日本語も中国語も、略語・単位・固有名詞をラテン文字のまま書きます（`CD-ROM`、`X線`、`AA制`）。一方、生成の失敗で英単語がそのまま残った訳も見た目は同じです。両者を機械で見分ける方法が無いため、使ってよいラテン文字の語を `tools/allowlist-latin.txt` に並べ、それ以外を違反として報告します。中国語訳にかなを含んでよい語（日本語の文法用語）は `tools/allowlist-kana-in-chinese.txt` に置いています。

訳を足したり直したりして新しい語が必要になったら、その語がその言語で実際にそう書かれることを確かめてから、これらのファイルへ追記してください。

道具の自己テストは標準ライブラリだけで動きます。作り物の小さなデータを使い、実データは読みません。

```console
$ python3 -m unittest discover -s tools -p 'test_*.py'
```

CC-CEDICT の実物を渡すと、解析器を全 entry へ通す検査も走ります。渡さなければ飛ばします。

```console
$ ZH_JA_DICT_CEDICT=<cedict_1_0_ts_utf-8_mdbg.txt.gz> \
    python3 -m unittest discover -s tools -p 'test_*.py'
```

## 作り方

元データは手元に置いてから、次の順に実行します。`tmp/` の中間物は版管理しません。

```sh
# 1. CC-CEDICT・HSK・旧版の訳から骨組みを作る
python3 tools/build_entries.py \
    --cedict <cedict_1_0_ts_utf-8_mdbg.txt.gz> \
    --hsk-seed <hsk-seed.json> \
    --existing <旧版の glosses.jsonl> \
    --jieba <jieba.dict.utf8> \
    --out tmp/entries-base.jsonl --order tmp/order.tsv

# 2. 日本語の簡潔訳を作る（プロンプトは tools/prompts/ja-gloss.md）
python3 tools/run_ja_shards.py --mode plan --full tmp/entries-base.jsonl \
    --order tmp/order.tsv --targets tmp/ja-full/targets.txt
python3 tools/run_ja_shards.py --mode run --full tmp/entries-base.jsonl \
    --targets tmp/ja-full/targets.txt --dir tmp/ja-full --shards 8
python3 tools/run_ja_shards.py --mode merge --dir tmp/ja-full --out tmp/ja-full.jsonl
python3 tools/run_ja_shards.py --mode verify --full tmp/entries-base.jsonl \
    --out tmp/ja-full.jsonl --targets tmp/ja-full/targets.txt

# 3. 訳を入れ、萌典と突き合わせ、圧縮して data/ を書く
python3 tools/build_dataset.py \
    --base tmp/entries-base.jsonl --glosses tmp/ja-full.jsonl \
    --repaired tmp/ja-full.jsonl.repaired \
    --moedict <dict-revised.json> --generated <YYYY-MM-DD> --out data

# 4. 全件検査。旧版と HSK の元データを渡すと、取りこぼしまで見る
python3 tools/validate_data.py --cedict-entries 124985 \
    --existing <旧版の glosses.jsonl> --hsk-seed <hsk-seed.json>
```

同じ入力からは同じバイト列が出ます。

訳は語義ごとに作ります。CC-CEDICT の英語の語義と語感の印をモデルへ渡し、旧版に同じ (見出し語, 読み) の訳があればそれも候補として添えます。**参照だけで英語の語義が無い 8,980 語義は、モデルを通さず機械で組み立てます**（[qa の意味](#qa-の意味)）。補遺 entry の訳は旧版のものをそのまま使います。

作った訳は文字種と長さの検査を通し、落ちたものだけ作り直します（`--repair`）。作り直した語義の一覧は `<出力>.repaired` へ残るので、組み立てのときに `--repaired` で渡します。**渡さないと、作り直した 690 語義の `qa` が `llm_ok` になってしまいます。**

**元データはこのリポジトリに含めていません。** CC-CEDICT・HSK の語彙・cppjieba の辞書・萌典は、それぞれの配布元から取得してください。旧版の訳は git の履歴から取り出せます。

## 出どころ

| 元データ | 使い方 | 出どころ | ライセンス |
|---|---|---|---|
| CC-CEDICT | 中日の骨格。見出し・読み・英語の語義・量詞・語感の注記 | [MDBG](https://www.mdbg.net/chinese/dictionary?page=cc-cedict) | CC BY-SA 4.0 |
| complete-hsk-vocabulary | HSK 2.0 / 3.0 の級と品詞。級と品詞だけを収録 | [GitHub](https://github.com/drkameleon/complete-hsk-vocabulary) | MIT |
| cppjieba | 訳を作る順番を決める内部の作業にだけ参照。頻度・順位は収録していない | [GitHub](https://github.com/yanyiwu/cppjieba) | MIT |
| 萌典（教育部 重編國語辭典 修訂本） | 見出しと語義の数の突き合わせにだけ参照。**本文は収録していない** | [g0v](https://github.com/g0v/moedict-data) | CC BY-ND 3.0 TW |
| zh-ja-dict 旧版 | CC-CEDICT に無い語と読みの補遺（31,874 と 939）、訳を作るときの候補 | このリポジトリの履歴 | CC BY-SA 4.0 |
| Jitendex / JMdict | 日中の見出し語の選定 | [Jitendex](https://jitendex.org/) | CC BY-SA 4.0 |

日本語訳は大規模言語モデル（Claude Opus）で作ったものが大部分です。参照だけの語義は機械で組み立て、2語義は人が書き、CC-CEDICT に無い語は旧版の訳を引き継いでいます（[冒頭の表](#zh-ja-dict)）。中国語訳（日中）は大規模言語モデルで作りました。市販辞書やOS付属辞書の語義本文は生成の入力に使っておらず、本データにも含まれません。

**萌典の本文は、生成の入力にも成果物にも入れていません。** 組み立てのときに読むのは各 entry の見出し（`title`）と語義の数だけで、語義の文は読み捨てます（`tools/build_dataset.py` の `load_moedict`）。データに残るのは `moe` の3値だけです。

萌典の CC BY-ND 3.0 TW は改変を許しません。この辞書がその条件に触れないと判断した根拠は、上に書いた「本文をどこにも持たない」という事実です。**それ以上の法的な解釈はこの文書では扱いません。**萌典を自分で取り込む場合は、[g0v の配布元](https://github.com/g0v/moedict-data)と教育部の利用条件を直接確認してください。

日中の見出し語は Jitendex（JMdict から派生した辞書）の見出し語を、JMdict の優先スコアの高い順に40,000語採りました。JMdict は [EDRDG](https://www.edrdg.org/edrdg/licence.html) が CC BY-SA 4.0 で公開しています。

MITライセンスは著作権表示の保持を求めます。原本の表示をそのまま載せます。

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

## 既知の限界

- 訳は簡潔さを優先しており、語法・用例を含みません
- 訳の言語混入は検証スクリプトが検出しますが、**誤訳そのものは検出できません**
- 補遺 entry には英語の語義がなく、語義がひとつだけです。旧版が語ごとに1〜3件の訳を持っていたものを読点でつないでいるので、**語義の分かれ方は骨格 entry と揃っていません**
- 補遺 entry には、`两个`（2つ）や`很少`（ごくわずか）のように、辞書の見出しというより語の組み合わせに見えるものが693語あります。分かち書きの単位として引ける利点を取って残しています
- `qa: "unchecked"` の語義は検品を通していません。旧版の読み別の語義を集めたファイルから取り込んだものです
- `moe` は見出しと語義の数しか見ていません。**訳の正しさとは無関係です**
- 参照を構造化するのは、語義の文が「関係を表す語＋参照の並び」だけで残らず説明できたときに限ります。説明が続く形（`abbr. for Hubei 湖北省[…] and Hunan 湖南省[…] provinces together`）は文のまま `en` に残るので、**参照としては引けません**。訳は LLM が文全体を読んで作ります
- 量詞は entry の欄なので、**どの語義に掛かるかは表せません**。CC-CEDICT の元データがその情報を持っていないためです
- 読みの表記が揃っていません。骨格 entry は CC-CEDICT の音節ごとの空白をそのまま声調記号へ直しますが（`ài hào`）、補遺 entry は旧版の表記のままで、繋げて書くものが多数あります（`yùnshūjī`）
- 繁体字の綴りと読みの対応は持っていません。CC-CEDICT が読みごとに entry を分けているので、`发` は `發`/`fā` の entry と `髮`/`fà` の entry に分かれますが、**1 entry の中で綴りと読みが対応しているだけ**です
- 日中方向で、日本語の文法用語の訳にかな表記とローマ字表記が混在します（`ら行` と `日语ra行`、`ya行`）。表記を統一していません
- 言語混入の検査にも抜けがあります。許可リストには一般的な英単語（`live` `house` `look` `boss` `play` `flag`）や単独の英字（`A`〜`X`）が載っており、これらの語で新しい生成失敗が起きても検出できません。また許可リストは中日と日中で共用のため、片方でだけ正当な語がもう片方でも通ります

## 修正履歴

### 2026-09-06 — CC-CEDICT を骨格に作り直し（schema 3）

中日を CC-CEDICT を骨格とする形へ作り直しました。1行の単位を「語と読みの組」から **1 entry** へ変え、**語義ごとに日本語訳を付ける**ようにしました（96,326行 → 157,798 entry・229,130語義）。

- 英語の語義・量詞・語感の印・異体字や参照の注記を、CC-CEDICT から規則で取り出して構造化したフィールドへ移しました。量詞は語の性質なので entry の欄に置きます
- 旧版の 96,326 行はすべて新しいデータに対応します。CC-CEDICT に無い語と読み 32,813 件は**補遺 entry** として訳ごと残しました
- 中日を **raw DEFLATE で圧縮**して同梱するようにしました。ファイル名は `entries.jsonl.deflate` で、圧縮後 7,424,431 バイト・展開後 34,405,030 バイトです
- `data/zh-ja/glosses.jsonl` を廃止しました。旧版のデータは git の履歴から取り出せます
- 萌典との照合結果を `moe` の欄に加えました。**萌典の本文は収録していません**
- Swift の入口を `glossesURL()` から `entriesURL()` へ変えました

### 2026-09-03 — 単位を「語」から「語と読みの組」へ

1行が (見出し語, 読み) を表すようにし、読み別の語義を集めた `polyphonic.jsonl` を廃止して中日の `glosses.jsonl` へ統合しました（95,463行 → 96,326行）。

### 2026-09-01 — HSK語彙の統合

HSK の 11,470 語を中日の `glosses.jsonl` へ統合し、`hsk2`・`hsk3`・`trad`・`pos` のキーを加えました。

### 2026-09-01 — 形式の統一と言語混入の訂正

英語やロシア語の単語が日本語訳に食い込んだ行を訂正しました。中日で17件、廃止した `polyphonic.jsonl` で7件でした。

## ライセンス

このリポジトリのデータと文書は [CC BY-SA 4.0](https://creativecommons.org/licenses/by-sa/4.0/) で提供します。骨格の CC-CEDICT と、日中の見出し語の選定に使った JMdict が同じ条件で提供されているため、その条件を引き継ぎます。

**このプロジェクトが作った部分も同じ条件です。** 具体的には、LLM が書いた日本語訳、参照から機械で組み立てた訳、人が書いて差し替えた訳、旧版から引き継いだ訳、そして注記を取り出して組み直した構造のすべてを指します。

再配布するときは、上流3つとこのリポジトリを併せて示してください。

> This work is based on CC-CEDICT, a Chinese-English dictionary published by MDBG, used under CC BY-SA 4.0.
>
> This work is based on JMdict, property of the Electronic Dictionary Research and Development Group (EDRDG), used under CC BY-SA 4.0.
>
> Japanese glosses and dataset structure from zh-ja-dict by inakaegg, used under CC BY-SA 4.0.

HSK の級は MIT ライセンスの complete-hsk-vocabulary に由来します。上に載せた著作権表示を保持してください。

萌典は CC BY-ND 3.0 TW です。**このリポジトリは萌典の本文を1文字も収録していません。**配っているのは、見出しが存在するかどうかと、語義の数がこの辞書と比べて多いか少ないかという、数え上げの結果だけです（[moe の意味](#moe-の意味)）。
