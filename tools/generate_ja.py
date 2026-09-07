#!/usr/bin/env python3
"""語義ごとの日本語簡潔訳を `claude -p` で作る。

    # パイロット（上限つき）
    python3 tools/generate_ja.py --entries tmp/entries-base.jsonl \
        --order tmp/order.tsv --out tmp/ja-pilot.jsonl --limit 5000

    # 全量。担当を `--shard i/N`（通し番号の剰余）で分け、別のファイルへ書く
    python3 tools/generate_ja.py --full tmp/entries-base.jsonl \
        --only tmp/ja-full/targets.txt --shard 0/4 \
        --seed tmp/ja-pilot.jsonl --out tmp/ja-full/shard-00.jsonl

まとめて回す手順は `tools/run_ja_shards.py` にある。

**API課金の経路を使わない。** サブスクリプション枠の `claude -p` を呼び、実行前に
`ANTHROPIC_API_KEY` を環境から外す。**パイロットの上限は機械的に守る**（`--limit`）。
上限を外せるのは `--full` を明示したときだけとする。

**呼び出しは毎回まっさらにする。** 既定の `claude -p` は道具の一覧・設定・作業directoryの
見取り図を毎回送るので、1回あたり約49,000トークンかかる（監視役の実測）。この用途では
どれも要らないので、次の4つを付け、作業directoryを空の一時dirにする。実測で1回
**731トークン**まで下がる。

- `--system-prompt` に `prompts/ja-gloss.md` の指示文を入れる（既定の指示文を置き換える）
- `--tools ""` で道具を全部止める
- `--strict-mcp-config` で MCP を読ませない
- `--setting-sources ""` で設定を読ませない

`--resume` は使わない。会話を続けるより、毎回まっさらのほうが安い。

訳が要るのは `ja` を持たない語義だけである。参照だけの語義（`variant of …`）には
`tools/build_entries.py` が既に機械で訳を当てているので、ここでは聞かない。
語義の番号は entry の中の通し番号（1から）で、飛び番になりうる。

途中経過は1行1語義で `--out` へ書き足す。同じコマンドをもう一度実行すれば、
済んだ語を飛ばして続きから進む。

Python 3.9 以上。標準ライブラリだけを使う。
"""

from __future__ import annotations

import argparse
import json
import os
import pathlib
import re
import subprocess
import sys
import tempfile
import time
from typing import Callable, Iterable, NamedTuple, Optional

sys.path.insert(0, str(pathlib.Path(__file__).resolve().parent))
import validate_data  # noqa: E402

DEFAULT_PILOT_LIMIT = 5000
# 1回へ入れる entry 数の天井。語義の予算（`DEFAULT_SENSES_PER_CALL`）より先にここへ
# 当たると1回の中身が薄くなるので、語義の予算が効くだけの余裕を持たせる。
# CC-CEDICT は1 entry あたり 1.6 語義なので、語義200なら entry は最大でも 200 で足りる。
DEFAULT_BATCH = 200

# 1回の呼び出しへ入れる語義の目安。CC-CEDICT は1 entry あたり 1.6 語義しかないので、
# entry の数で切ると1回の中身が薄くなって呼び出し回数が増える。**語義の数**でまとめる。
#
# 1回にはどうしても固定の分（指示文と呼び出しの下ごしらえ、あわせて約1,200トークン）が
# 乗る。語義を多く詰めるほどこれが薄まるので、1語義あたりが安くなる。
DEFAULT_SENSES_PER_CALL = 200

# 利用上限に当たったときの待ち時間（秒）。最後まで待っても駄目なら shard を落とし、
# 呼び出し元（run_ja_shards.py）が間を置いて起こし直す。
BACKOFF = (30, 60, 120, 240, 480, 600, 600, 600)

RATE_LIMIT_HINTS = (
    "usage limit", "rate limit", "rate_limit", "429", "overloaded",
    "quota", "too many requests", "capacity",
)

MODEL = "opus"
EFFORT = "low"

PROMPT_PATH = pathlib.Path(__file__).resolve().parent / "prompts" / "ja-gloss.md"

_FENCE = re.compile(r"```(?:json)?\s*(.*?)```", re.DOTALL)
_OBJECT = re.compile(r"\{.*\}", re.DOTALL)


class Reply(NamedTuple):
    """1回の呼び出しの結果。使った量も返して、実行中に見えるようにする。"""

    text: str
    usage: dict
    seconds: float


def add_usage(total: dict, usage: dict) -> dict:
    """`claude -p` の usage を足し合わせる。数でない値は無視する。"""
    for key, value in (usage or {}).items():
        if isinstance(value, int):
            total[key] = total.get(key, 0) + value
    return total


class BadResponse(Exception):
    """モデルの応答を取り込めない。黙って捨てずここで止める。"""


class RateLimited(Exception):
    """利用上限か混雑で断られた。待てば直るので、失敗とは分けて扱う。"""


def normalize(text: str) -> str:
    """訳の書き方を揃える。候補の区切りは「、」に寄せる。"""
    return text.replace("，", "、").replace(",", "、").strip()


def pending_numbers(entry: dict) -> list:
    """訳がまだ無い語義の番号（1から）。"""
    return [number for number, sense in enumerate(entry["senses"], start=1)
            if not sense.get("ja")]


def build_payload(entries: Iterable[dict]) -> str:
    """モデルへ渡す語の配列。判断に要るものだけを、できるだけ短い形で送る。

    本文は呼び出しごとに丸ごと送り直すので、書き方の冗長さがそのまま費用になる。
    次のように詰めてある。**意味は落としていない。**

    - 鍵は1文字（`w` 見出し、`s` 語義、`m` 印、`h` 既存の訳）
    - 語義は `{"1": "英語の語義"}` の対応表。`{"n": 1, "en": [...]}` の並びより短い
    - 英語の語義が複数あるときは `; ` で繋ぐ（CC-CEDICT 自身の区切りと同じ）
    - 印は付く語義だけ `m` に載せる（全体の7%）
    - JSON の区切りに空白を入れない
    """
    items = []
    for entry in entries:
        senses = {}
        marks = {}
        for number in pending_numbers(entry):
            sense = entry["senses"][number - 1]
            senses[str(number)] = "; ".join(sense.get("en") or [])
            if sense.get("misc"):
                marks[str(number)] = ",".join(sense["misc"])
        payload = {"id": entry["id"], "w": entry["word"], "py": entry["pinyin"],
                   "s": senses}
        if marks:
            payload["m"] = marks
        if entry.get("seed_gloss"):
            payload["h"] = "、".join(entry["seed_gloss"])
        items.append(payload)
    return json.dumps(items, ensure_ascii=False, separators=(",", ":"))


def build_prompt(rules: str, entries: Iterable[dict]) -> str:
    """呼び出しの本文。指示文は `--system-prompt` へ回すので、ここは語だけ。

    `rules` は作り直しの追い書き（`REPAIR_NOTE`）にだけ使う。
    """
    return f"{rules}\n{build_payload(entries)}" if rules else build_payload(entries)


def parse_response(text: str) -> list:
    """応答から `glosses` を取り出す。"""
    fenced = _FENCE.search(text)
    body = fenced.group(1) if fenced else text
    found = _OBJECT.search(body)
    if not found:
        raise BadResponse(f"JSONが見つからない: {text[:120]!r}")
    try:
        parsed = json.loads(found.group(0))
    except json.JSONDecodeError as error:
        raise BadResponse(f"JSONとして読めない: {error}") from error
    glosses = parsed.get("glosses")
    if not isinstance(glosses, list):
        raise BadResponse("glosses が配列でない")
    for item in glosses:
        if not {"id", "sense", "ja"} <= set(item):
            raise BadResponse(f"key が足りない: {item}")
    return glosses


def chunks(left: list, batch: int, senses_per_call: Optional[int] = None):
    """1回の呼び出しへ入れる語をまとめて返す。

    `senses_per_call` を渡すと**訳が要る語義の数**を目安にまとめ、`batch` は
    そのときの entry 数の天井になる。予算を1語で超える語もそのまま1回で送る。
    """
    if senses_per_call is None:
        for start in range(0, len(left), batch):
            yield left[start:start + batch]
        return
    current: list = []
    senses = 0
    for entry in left:
        count = len(pending_numbers(entry))
        if current and (senses + count > senses_per_call or len(current) >= batch):
            yield current
            current, senses = [], 0
        current.append(entry)
        senses += count
    if current:
        yield current


def select_shard(entries: list, index: int, total: int) -> list:
    """並列の担当を通し番号の剰余で分ける。

    連続範囲で切ると、若い番号の側へ常用で多義の語が集まって終わる時刻が揃わない。
    剰余なら重さが均等に散り、語は必ず1つの担当に入る。
    """
    return [entry for number, entry in enumerate(entries) if number % total == index]


def sample_evenly(entries: list, count: int) -> list:
    """並びを保ったまま、全体へ等間隔に散らして `count` 件を取る。"""
    if count >= len(entries):
        return list(entries)
    if count <= 0:
        return []
    if count == 1:
        return [entries[0]]
    step = (len(entries) - 1) / (count - 1)
    return [entries[round(number * step)] for number in range(count)]


def order_entries(entries: list, ranked: Iterable[str]) -> list:
    """順位の付いた語を先に、残りを元の並びのまま後ろへ置く。"""
    by_id = {entry["id"]: entry for entry in entries}
    head, seen = [], set()
    for entry_id in ranked:
        entry = by_id.get(entry_id)
        if entry is not None and entry_id not in seen:
            head.append(entry)
            seen.add(entry_id)
    return head + [entry for entry in entries if entry["id"] not in seen]


def finished_ids(entries: list, glosses: Iterable[dict]) -> set:
    """**訳が要る語義の番号がすべてそろった**語だけを「済み」とする。

    数だけを見ると、2語義の語に番号 {1, 3} が来たときに済みと数えてしまい、
    語義2が永久に埋まらないまま最後の取り込みで落ちる。番号の集合で見る。
    """
    wanted = {entry["id"]: set(pending_numbers(entry)) for entry in entries}
    got: dict = {}
    for item in glosses:
        got.setdefault(str(item["id"]), set()).add(int(item["sense"]))
    return {
        entry_id for entry_id, numbers in got.items()
        if entry_id in wanted and wanted[entry_id] <= numbers
    }


def accept(chunk: list, glosses: Iterable[dict]) -> tuple:
    """応答のうち、頼んだ語の頼んだ語義番号だけを受け取る。

    範囲外の番号・重複・頼んでいない語をそのまま書くと、途中経過が壊れて
    再開できなくなる。捨てたものは呼び出し側が数えて報告する（黙って捨てない）。
    """
    wanted = {entry["id"]: set(pending_numbers(entry)) for entry in chunk}
    kept: list = []
    rejected: list = []
    seen: set = set()
    for item in glosses:
        entry_id = str(item["id"])
        try:
            number = int(item["sense"])
        except (TypeError, ValueError):
            rejected.append(item)
            continue
        if number not in wanted.get(entry_id, ()) or (entry_id, number) in seen:
            rejected.append(item)
            continue
        seen.add((entry_id, number))
        kept.append(item)
    return kept, rejected


def merge(entries: list, glosses: Iterable[dict]) -> list:
    """語義の番号を頼りに、訳を entry へ入れる。"""
    by_id = {entry["id"]: entry for entry in entries}
    for item in glosses:
        entry = by_id.get(str(item["id"]))
        if entry is None:
            continue
        number = int(item["sense"])
        if not 1 <= number <= len(entry["senses"]):
            raise BadResponse(f"語義の番号が範囲外: id={item['id']} sense={number}")
        entry["senses"][number - 1]["ja"] = item["ja"]
    return entries


def looks_rate_limited(text: str) -> bool:
    lowered = (text or "").lower()
    return any(hint in lowered for hint in RATE_LIMIT_HINTS)


def retrying(
    call: Callable,
    waits: Iterable[int] = BACKOFF,
    sleep: Callable = time.sleep,
    log: Callable = lambda message: print(message, file=sys.stderr),
) -> Callable:
    """利用上限で断られたら待って掛け直す呼び出しを作る。"""
    def wrapped(prompt: str, system: str) -> Reply:
        failure = None
        for wait in (None, *waits):
            if wait is not None:
                log(f"  利用上限で待つ: {wait}秒")
                sleep(wait)
            try:
                return call(prompt, system)
            except RateLimited as error:
                failure = error
        raise failure if failure is not None else RateLimited("再試行できなかった")
    return wrapped


# 呼び出しの作業directory。空にしておかないと、`claude` がそこの見取り図を
# 毎回読み込んで送ってしまう。プロセスが終わるまで使い回す。
_EMPTY_DIR: Optional[str] = None


def empty_directory() -> str:
    global _EMPTY_DIR
    if _EMPTY_DIR is None:
        _EMPTY_DIR = tempfile.mkdtemp(prefix="generate-ja-")
    return _EMPTY_DIR


def call_claude(prompt: str, system: str) -> Reply:
    """`claude -p` を1回呼ぶ。毎回まっさらのセッションで聞く。

    プロンプトは `-p` の直後に置く。可変長のフラグの後ろへ置くと空実行になる。

    **既定の呼び方を使わない。** 道具の一覧・設定・MCP・作業directoryの見取り図は
    この用途では要らないのに、毎回およそ49,000トークンを占める。指示文を
    `--system-prompt` で置き換え、残りを止め、作業directoryを空にする。
    """
    command = [
        "claude", "-p", prompt,
        "--model", MODEL, "--effort", EFFORT,
        "--output-format", "json",
        "--system-prompt", system,
        "--tools", "",
        "--strict-mcp-config",
        "--setting-sources", "",
    ]
    environment = dict(os.environ)
    # サブスクリプション枠だけを使う。API keyの経路へ落ちないよう外す
    environment.pop("ANTHROPIC_API_KEY", None)
    started = time.time()
    finished = subprocess.run(command, capture_output=True, text=True,
                              env=environment, cwd=empty_directory(), check=False)
    seconds = time.time() - started
    if finished.returncode != 0:
        note = (finished.stderr or finished.stdout or "").strip()
        if looks_rate_limited(note):
            raise RateLimited(note[:200])
        raise BadResponse(f"claude が終了コード {finished.returncode}: {note[:200]!r}")
    try:
        payload = json.loads(finished.stdout)
    except json.JSONDecodeError as error:
        raise BadResponse(f"claude の出力を読めない: {error}") from error
    if payload.get("is_error"):
        result = str(payload.get("result"))
        if looks_rate_limited(result):
            raise RateLimited(result[:200])
        raise BadResponse(f"claude が失敗した: {result[:200]!r}")
    return Reply(text=payload["result"], usage=payload.get("usage") or {},
                 seconds=seconds)


def read_glosses(paths: Iterable[pathlib.Path]) -> list:
    """途中経過のファイルを読む。壊れた行は数えて報せる。"""
    rows: list = []
    broken = 0
    for path in paths:
        if not path.exists():
            continue
        for line in path.read_text(encoding="utf-8").splitlines():
            if not line.strip():
                continue
            try:
                rows.append(json.loads(line))
            except json.JSONDecodeError:
                broken += 1
    if broken:
        print(f"  読めなかった行 {broken} 件は無視した（その語は聞き直す）", file=sys.stderr)
    return rows


def run(
    entries: list,
    out: pathlib.Path,
    rules: str,
    call: Callable = call_claude,
    system: str = "",
    batch: int = DEFAULT_BATCH,
    limit: Optional[int] = None,
    senses_per_call: Optional[int] = None,
    seed: Iterable[pathlib.Path] = (),
    max_calls: Optional[int] = None,
) -> int:
    """訳を作って `out` へ書き足す。書けた語義の数を返す。

    `max_calls` を渡すと、その回数だけ呼んで止める（呼び方を測るときに使う）。
    """
    done = finished_ids(entries, read_glosses([*seed, out]))
    left = [entry for entry in entries if entry["id"] not in done]
    if limit is not None:
        left = left[:limit]

    written = dropped = failed = calls = seen_entries = 0
    usage_total: dict = {}
    elapsed = 0.0
    out.parent.mkdir(parents=True, exist_ok=True)
    with out.open("a", encoding="utf-8") as sink:
        for chunk in chunks(left, batch, senses_per_call):
            if max_calls is not None and calls >= max_calls:
                break
            seen_entries += len(chunk)
            try:
                reply = call(build_prompt(rules, chunk), system)
                calls += 1
                add_usage(usage_total, reply.usage)
                elapsed += reply.seconds
                # 1回ずつ残す。長い実行の途中で累計を数えられるようにするため
                # （実行の終わりにしか出さないと、回している最中に分からない）。
                print(f"  usage cc={reply.usage.get('cache_creation_input_tokens', 0)}"
                      f" cr={reply.usage.get('cache_read_input_tokens', 0)}"
                      f" in={reply.usage.get('input_tokens', 0)}"
                      f" out={reply.usage.get('output_tokens', 0)}"
                      f" {reply.seconds:.1f}s", file=sys.stderr)
                kept, rejected = accept(chunk, parse_response(reply.text))
            except BadResponse as error:
                # 1回の壊れた応答で数時間の実行を止めない。その語は未完のまま残り、
                # 同じコマンドをもう一度実行すれば聞き直される
                print(f"  応答を取り込めなかった（{len(chunk)} 語は後で聞き直す）: {error}",
                      file=sys.stderr)
                failed += len(chunk)
                continue
            if rejected:
                print(f"  受け取れなかった語義 {len(rejected)} 件: {rejected[:3]}",
                      file=sys.stderr)
                dropped += len(rejected)
            for item in kept:
                item["ja"] = normalize(item["ja"])
                sink.write(json.dumps(item, ensure_ascii=False) + "\n")
                written += 1
            sink.flush()
            print(f"  {seen_entries}/{len(left)} 語", file=sys.stderr)
    if calls:
        print(f"呼び出し {calls} 回 / {elapsed:.1f}秒（1回 {elapsed / calls:.1f}秒）",
              file=sys.stderr)
        print(f"  使った量の合計: {json.dumps(usage_total, ensure_ascii=False)}",
              file=sys.stderr)
        for key in ("input_tokens", "output_tokens",
                    "cache_creation_input_tokens", "cache_read_input_tokens"):
            if key in usage_total:
                print(f"  1回あたり {key}: {usage_total[key] / calls:,.0f}", file=sys.stderr)
    if dropped:
        print(f"受け取れなかった語義は合わせて {dropped} 件。もう一度実行すれば聞き直す",
              file=sys.stderr)
    if failed:
        print(f"応答を取り込めなかった語は合わせて {failed} 語。もう一度実行すれば聞き直す",
              file=sys.stderr)
    return written


REPAIR_NOTE = """
**やり直し。** 直前の訳が、この辞書の決まりに合わなかった。次のどれかに当たる。

- **英語の単語をそのまま残している**（`related`、`supply` のような英訳の残り）。
  ただし**日本語で定着したラテン文字の表記はそのまま書いてよい**（`DNA`、`GPU`、`iPhone` など）
- **ピンイン・声調記号を書いている。** 中国語の文をそのまま残している。
  `把A变成B` のような型も、A・B ではなく `…を…に変える` と書く
- **英語やロシア語などの単語が混じっている**
- **24文字を超えている。** 成語やことわざでも、要点だけを24文字以内にまとめる。
  逐語訳を並べず、日本語のことわざが当たるならそれを使う
- **日本語の文字が1つも無い。** 記号や数式だけの訳にせず、何を指すかを日本語で書く
  （`☰` なら `八卦の乾の記号` のように）
"""


def repaired_path(out: pathlib.Path) -> pathlib.Path:
    """作り直した語義の記録の置き場。途中経過のファイルの隣に置く。"""
    return out.with_suffix(out.suffix + ".repaired")


def drop_invalid(glosses: list, allowed_latin: set, mine=None) -> tuple:
    """文字種の検査に落ちた訳を分ける。(残すもの, 落としたもの) を返す。

    `mine` を渡すと、そこに無い語の行は検査せずそのまま残す。担当を `--only` で
    分けているとき、**作り直さない語の行まで捨ててしまうと、その語義は空のまま消える。**
    """
    kept, dropped = [], []
    for item in glosses:
        if mine is not None and str(item["id"]) not in mine:
            kept.append(item)
            continue
        where = f"id={item['id']} sense={item['sense']}"
        if validate_data.check_japanese(item["ja"], where, allowed_latin):
            dropped.append(item)
        else:
            kept.append(item)
    return kept, dropped


def parse_shard(text: str) -> tuple:
    """`i/N` を読む。番号は0から数える。"""
    index, _, total = text.partition("/")
    return int(index), int(total)


def only_ids(path: pathlib.Path) -> list:
    """担当する entry ID を並び順ごと読む。1行1件、`#` はコメント。"""
    return [line.strip() for line in path.read_text(encoding="utf-8").splitlines()
            if line.strip() and not line.startswith("#")]


def ranked_ids(order: pathlib.Path) -> list:
    """order.tsv の並びで entry ID を返す。"""
    ids = []
    for line in order.read_text(encoding="utf-8").splitlines()[1:]:
        columns = line.split("\t")
        if columns and columns[0]:
            ids.append(columns[0])
    return ids


def take_in_order(by_id: dict, wanted: Iterable[str]) -> list:
    """指示された順に語を並べる。知らない ID は飛ばす。"""
    return [by_id[entry_id] for entry_id in wanted if entry_id in by_id]


def load_entries(path: pathlib.Path) -> list:
    """骨組みのうち、訳が要る語義を持つ entry だけを返す。"""
    entries = []
    with path.open(encoding="utf-8") as source:
        for line in source:
            if not line.strip():
                continue
            row = json.loads(line)
            if pending_numbers(row):
                entries.append(row)
    return entries


def main(argv=None, call: Callable = call_claude) -> int:
    parser = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    parser.add_argument("--entries", type=pathlib.Path,
                        help="パイロット: 骨組みの JSONL")
    parser.add_argument("--order", type=pathlib.Path,
                        help="パイロット: 回す順番の TSV")
    parser.add_argument("--full", type=pathlib.Path,
                        help="全量モード: 骨組みの JSONL。パイロットの上限を外す")
    parser.add_argument("--only", type=pathlib.Path,
                        help="全量モード: 担当する entry ID の一覧。書かれた順に回す")
    parser.add_argument("--shard", help="全量モード: 担当を `i/N` で指定する")
    parser.add_argument("--seed", action="append", type=pathlib.Path, default=[],
                        help="既にある訳のファイル。ここで済んだ語は聞き直さない")
    parser.add_argument("--out", required=True, type=pathlib.Path)
    parser.add_argument("--limit", type=int)
    parser.add_argument("--pilot-head", type=int, default=0,
                        help="パイロット: 先頭の常用語から取る数。残りは裾から等間隔")
    parser.add_argument("--batch", type=int, default=DEFAULT_BATCH)
    parser.add_argument("--senses-per-call", type=int)
    parser.add_argument("--max-calls", type=int,
                        help="この回数だけ呼んで止める（呼び方を測るときに使う）")
    parser.add_argument("--no-retry", action="store_true",
                        help="利用上限で待たずに落とす（試験用）")
    parser.add_argument("--repair", action="store_true",
                        help="文字種の検査に落ちた訳を捨てて、その語だけ作り直す")
    args = parser.parse_args(argv)

    if args.full and (args.entries or args.order):
        print("generate_ja: --full とパイロットの --entries/--order は混ぜない",
              file=sys.stderr)
        return 1
    if not args.full and not (args.entries and args.order):
        print("generate_ja: --entries と --order、または --full が要る", file=sys.stderr)
        return 1

    if args.full:
        planned = plan_full(args)
    else:
        planned = plan_pilot(args)
    if planned is None:
        return 1
    entries, limit, senses_per_call = planned

    # 指示文は `--system-prompt` へ回す。本文はその回の語だけにして、呼び出し1回の
    # 読み込みを減らす。作り直しの追い書きだけ本文の頭へ付ける。
    system = PROMPT_PATH.read_text(encoding="utf-8")
    rules = ""
    if args.repair and args.out.exists():
        existing = read_glosses([args.out])
        kept, dropped = drop_invalid(
            existing, validate_data.ALLOWED_LATIN, {entry["id"] for entry in entries})
        args.out.write_text(
            "".join(json.dumps(item, ensure_ascii=False) + "\n" for item in kept),
            encoding="utf-8")
        # どの語義を作り直したかを隣のファイルへ残す。`tools/build_dataset.py` が
        # これを読んで `qa` を `llm_fixed` にする。捨てるだけだと区別が消える。
        with repaired_path(args.out).open("a", encoding="utf-8") as sink:
            for item in dropped:
                sink.write(json.dumps(
                    {"id": str(item["id"]), "sense": int(item["sense"])},
                    ensure_ascii=False) + "\n")
        print(f"作り直す語義 {len(dropped)} 件")
        if not dropped:
            return 0
        rules = REPAIR_NOTE

    if not args.no_retry:
        call = retrying(call)
    written = run(entries, args.out, rules=rules, call=call, system=system,
                  batch=args.batch, limit=limit, senses_per_call=senses_per_call,
                  seed=args.seed, max_calls=args.max_calls)
    print(f"語義 {written} 件を {args.out} へ書いた")
    return 0


def plan_pilot(args):
    """パイロットの対象を決める。上限は機械的に守る。

    先頭の常用語 `--pilot-head` 件に加えて、残り（CC-CEDICT の裾）から等間隔で取る。
    裾は品質が崩れやすいので、確認の前に必ず見ておきたい。
    """
    limit = DEFAULT_PILOT_LIMIT if args.limit is None else args.limit
    if limit > DEFAULT_PILOT_LIMIT:
        print(f"generate_ja: パイロットの上限は {DEFAULT_PILOT_LIMIT} 語まで（契約）。"
              f"全量は --full を使う", file=sys.stderr)
        return None
    entries = load_entries(args.entries)
    ordered = order_entries(entries, ranked_ids(args.order))
    head = ordered[:args.pilot_head]
    tail = sample_evenly(ordered[args.pilot_head:], limit - len(head))
    target = head + tail
    target_ids = {entry["id"] for entry in target}

    # 上限は1回の実行ではなく**通算**で守る。途中経過に対象外の語が混ざっていたら止める。
    if args.out.exists():
        already = {str(row["id"]) for row in read_glosses([args.out])}
        outside = sorted(already - target_ids)
        if outside:
            print(f"generate_ja: 途中経過に対象外の語がある: {outside[:5]}", file=sys.stderr)
            return None
    senses = sum(len(pending_numbers(entry)) for entry in target)
    print(f"パイロットの対象: {len(target)} 語 / 語義 {senses}"
          f"（常用 {len(head)} ＋ 裾 {len(tail)}）", file=sys.stderr)
    return target, None, args.senses_per_call or DEFAULT_SENSES_PER_CALL


def plan_full(args):
    """全量モードの対象を決める。担当（shard）の切り出しまでを引き受ける。

    **上限を外すのはこの経路だけ。**
    """
    entries = load_entries(args.full)
    by_id = {entry["id"]: entry for entry in entries}
    if args.only:
        entries = take_in_order(by_id, only_ids(args.only))
    if args.shard:
        index, total = parse_shard(args.shard)
        if total < 1 or not 0 <= index < total:
            print(f"generate_ja: 担当の指定が範囲外: {args.shard}", file=sys.stderr)
            return None
        entries = select_shard(entries, index, total)
    senses_per_call = args.senses_per_call or DEFAULT_SENSES_PER_CALL
    return entries, args.limit, senses_per_call


if __name__ == "__main__":
    raise SystemExit(main())
