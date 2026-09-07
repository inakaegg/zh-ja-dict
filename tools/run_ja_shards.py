#!/usr/bin/env python3
"""日本語簡潔訳の全量生成を並列で回す。

`generate_ja.py --full` を担当（shard）ごとに立ち上げ、様子を見て、落ちたら
起こし直し、最後に1本へ合流させる。長い実行のあいだ人が張り付かなくて済むように、
進み具合の記録・止まりの検知・利用上限での起こし直しをここへ集めてある。

    # 1. 回す順番を決めて対象の一覧を書く（常用語が先、パイロットは裾も混ぜる）
    python3 tools/run_ja_shards.py --mode plan --full tmp/entries-base.jsonl \\
        --order tmp/order.tsv --targets tmp/ja-full/targets.txt \\
        --pilot 5000 --pilot-head 4000

    # 2. 並列で回す（tmux の別 window で）
    python3 tools/run_ja_shards.py --mode run --full tmp/entries-base.jsonl \\
        --targets tmp/ja-full/targets.txt --dir tmp/ja-full --shards 4

    # 3. 1本へ合流し、全語義が埋まったか・文字種が正しいかを見る
    python3 tools/run_ja_shards.py --mode merge --dir tmp/ja-full \\
        --out tmp/ja-full.jsonl
    python3 tools/run_ja_shards.py --mode verify --full tmp/entries-base.jsonl \\
        --out tmp/ja-full.jsonl --targets tmp/ja-full/targets.txt

Python 3.9 以上。標準ライブラリだけを使う。
"""

from __future__ import annotations

import argparse
import json
import pathlib
import subprocess
import sys
import time
from typing import Iterable, NamedTuple

sys.path.insert(0, str(pathlib.Path(__file__).resolve().parent))
import generate_ja  # noqa: E402
import validate_data  # noqa: E402

TOOLS = pathlib.Path(__file__).resolve().parent

DEFAULT_SHARDS = 4
DEFAULT_POLL_SECONDS = 20
# これだけ進まなければ止まったとみなす。契約の停止条件（30分）に合わせてある。
DEFAULT_STALL_MINUTES = 30
# 落ちた担当を起こし直す間隔。利用上限の直後に飛びつかないよう間を置く。
RESTART_WAITS = (60, 120, 300, 600, 900)


def shard_path(directory: pathlib.Path, index: int) -> pathlib.Path:
    return directory / f"shard-{index:02d}.jsonl"


def log_path(directory: pathlib.Path, index: int) -> pathlib.Path:
    return directory / f"shard-{index:02d}.log"


def load_entries(path: pathlib.Path) -> list:
    """骨組みのうち、訳が要る語義を持つ entry だけを返す。"""
    return generate_ja.load_entries(path)


def finished_entry_ids(entries: list, paths: Iterable[pathlib.Path]) -> set:
    return generate_ja.finished_ids(entries, generate_ja.read_glosses(paths))


# --- 回す順番を決める -------------------------------------------------------

def plan_targets(entries: list, done: set, ranked: Iterable[str],
                 pilot=None, pilot_head: int = 0) -> list:
    """回す順に entry ID を並べる。

    順位の付いた常用語を先に置く。時間切れになっても価値の高い語から埋まる。
    パイロットでは、先頭の常用語 `pilot_head` 件に加えて、残り（CC-CEDICT の裾）
    から等間隔で取る。裾は品質が崩れやすいので、確認の前に必ず見ておきたい。
    """
    left = [entry for entry in entries if entry["id"] not in done]
    ordered = generate_ja.order_entries(left, ranked)
    if pilot is None:
        return [entry["id"] for entry in ordered]
    head = ordered[:pilot_head]
    tail = generate_ja.sample_evenly(ordered[pilot_head:], pilot - len(head))
    return [entry["id"] for entry in head + tail]


# --- 並列で回す -------------------------------------------------------------

def shard_command(args, index: int) -> list:
    """担当1つ分の `generate_ja.py` の呼び出しを組み立てる。"""
    command = [
        sys.executable, str(TOOLS / "generate_ja.py"),
        "--full", str(args.full),
        "--shard", f"{index}/{args.shards}",
        "--out", str(shard_path(args.dir, index)),
    ]
    if args.targets:
        command += ["--only", str(args.targets)]
    for seed in args.seed:
        command += ["--seed", str(seed)]
    if args.senses_per_call:
        command += ["--senses-per-call", str(args.senses_per_call)]
    if args.max_calls:
        command += ["--max-calls", str(args.max_calls)]
    return command


def count_lines(path: pathlib.Path) -> int:
    if not path.exists():
        return 0
    with path.open("rb") as handle:
        return sum(1 for _ in handle)


class Progress(NamedTuple):
    written: int
    elapsed: float
    total: int

    def line(self) -> str:
        """進み具合の1行。残り時間の見込みまで出す。"""
        rate = self.written / self.elapsed if self.elapsed > 0 else 0.0
        share = 100 * self.written / self.total if self.total else 0.0
        left = (self.total - self.written) / rate if rate > 0 else float("inf")
        eta = "不明" if left == float("inf") else f"{left / 3600:.1f}時間"
        return (f"[{time.strftime('%H:%M:%S')}] 語義 {self.written}/{self.total}"
                f"（{share:.1f}%） {rate * 60:.0f}語義/分 残り{eta}")


def stalled(history: list, minutes: float) -> bool:
    """`minutes` のあいだ1件も増えていなければ止まったとみなす。"""
    if not history:
        return False
    now, written = history[-1]
    old = [count for moment, count in history if now - moment >= minutes * 60]
    return bool(old) and written <= old[-1]


def expected_senses(args) -> int:
    """この実行で埋めるはずの語義の数。進み具合の分母に使う。"""
    entries = load_entries(args.full)
    if args.targets:
        wanted = set(generate_ja.only_ids(args.targets))
        entries = [entry for entry in entries if entry["id"] in wanted]
    done = finished_entry_ids(entries, args.seed)
    return sum(len(generate_ja.pending_numbers(entry))
               for entry in entries if entry["id"] not in done)


def supervise(args) -> int:
    """担当を立ち上げ、様子を見て、落ちたら起こし直す。"""
    args.dir.mkdir(parents=True, exist_ok=True)
    logs = args.log or args.dir
    logs.mkdir(parents=True, exist_ok=True)

    total_senses = expected_senses(args)
    started = time.time()
    history: list = []
    running: dict = {}
    handles: dict = {}
    restarts = {index: 0 for index in range(args.shards)}
    finished: set = set()
    wake_at: dict = {}

    def launch(index: int) -> None:
        handle = log_path(logs, index).open("a", encoding="utf-8")
        handle.write(f"\n=== {time.strftime('%Y-%m-%d %H:%M:%S')} 起動 "
                     f"(起こし直し {restarts[index]} 回目) ===\n")
        handle.flush()
        running[index] = subprocess.Popen(
            shard_command(args, index), stdout=handle, stderr=subprocess.STDOUT)
        handles[index] = handle

    for index in range(args.shards):
        launch(index)
    print(f"担当 {args.shards} 個を立ち上げた。出力は {args.dir}", flush=True)

    while len(finished) < args.shards:
        time.sleep(args.poll_seconds)
        for index in sorted(set(range(args.shards)) - finished):
            if index in wake_at:
                if time.time() >= wake_at.pop(index):
                    launch(index)
                continue
            process = running.get(index)
            if process is None or process.poll() is None:
                continue
            handles[index].close()
            if process.returncode == 0:
                finished.add(index)
                print(f"担当 {index} が終わった", flush=True)
                continue
            if restarts[index] >= len(RESTART_WAITS):
                print(f"担当 {index} を起こし直す回数を使い切った（終了コード "
                      f"{process.returncode}）。{log_path(logs, index)} を見ること",
                      flush=True)
                finished.add(index)
                continue
            wait = RESTART_WAITS[restarts[index]]
            restarts[index] += 1
            wake_at[index] = time.time() + wait
            print(f"担当 {index} が終了コード {process.returncode} で落ちた。"
                  f"{wait}秒後に起こし直す", flush=True)

        written = sum(count_lines(shard_path(args.dir, index))
                      for index in range(args.shards))
        history.append((time.time(), written))
        print(Progress(written, time.time() - started, total_senses).line(), flush=True)
        if stalled(history, args.stall_minutes):
            print(f"{args.stall_minutes}分のあいだ1件も進まない。全部止めて報告する",
                  flush=True)
            for process in running.values():
                if process.poll() is None:
                    process.terminate()
            return 2

    # 担当が終了コード0で終わっても、壊れた応答を握って進んだ分は埋まっていない。
    # 「終わった」だけを見て次へ進まないよう、埋まり具合をここで突き合わせる。
    written = sum(count_lines(shard_path(args.dir, index)) for index in range(args.shards))
    print(f"すべての担当が終わった。書けた語義 {written}/{total_senses}", flush=True)
    if written < total_senses:
        print(f"  まだ {total_senses - written} 語義が埋まっていない。"
              f"同じコマンドをもう一度実行すれば聞き直す（確認は --mode verify）", flush=True)
    return 0


# --- 合流と検査 -------------------------------------------------------------

def entry_sort_key(entry_id: str):
    """`c123`・`x45` を種別と番号で並べる。文字列順だと `c10` が `c9` より前に来る。"""
    kind, number = entry_id[:1], entry_id[1:]
    return (kind, int(number) if number.isdigit() else 0, entry_id)


def merge_rows(sources: Iterable[pathlib.Path]) -> tuple:
    """訳を1本にまとめる。(並べ替えた行, 捨てた重複の数) を返す。

    同じ語義が2つ以上あれば先に読んだものを残す。種（既にある訳）を先に渡すこと。
    並びは entry ID 順・語義番号順にして、いつ回しても同じ形になるようにする。
    """
    seen: dict = {}
    duplicates = 0
    for row in generate_ja.read_glosses(sources):
        key = (str(row["id"]), int(row["sense"]))
        if key in seen:
            duplicates += 1
            continue
        seen[key] = {"id": str(row["id"]), "sense": int(row["sense"]), "ja": row["ja"]}
    rows = [seen[key] for key in
            sorted(seen, key=lambda key: (entry_sort_key(key[0]), key[1]))]
    return rows, duplicates


class Report(NamedTuple):
    entries: int
    senses: int
    translated: int
    missing: list
    unknown: list
    violations: list


def verify(entries: list, rows: list) -> Report:
    """訳の要る全語義に訳があるか、文字種と長さが正しいかを見る。"""
    wanted = {entry["id"]: set(generate_ja.pending_numbers(entry)) for entry in entries}
    english = {entry["id"]: {
        word
        for sense in entry["senses"]
        for text in sense.get("en", [])
        for word in validate_data.latin_tokens(text)
    } for entry in entries}
    got: dict = {}
    violations = []
    for row in rows:
        entry_id, number = str(row["id"]), int(row["sense"])
        got.setdefault(entry_id, set()).add(number)
        message = validate_data.check_japanese(
            row["ja"], f"id={entry_id} sense={number}",
            en_words=english.get(entry_id, ()))
        if message:
            violations.append(message)
    missing = [entry_id for entry_id, numbers in wanted.items()
               if not numbers <= got.get(entry_id, set())]
    unknown = [entry_id for entry_id in got if entry_id not in wanted]
    return Report(
        entries=len(wanted),
        senses=sum(len(numbers) for numbers in wanted.values()),
        translated=sum(len(numbers) for numbers in got.values()),
        missing=missing,
        unknown=unknown,
        violations=violations,
    )


def main(argv=None) -> int:
    parser = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    parser.add_argument("--mode", required=True,
                        choices=("plan", "run", "merge", "verify"))
    parser.add_argument("--full", type=pathlib.Path, help="骨組みの JSONL")
    parser.add_argument("--order", type=pathlib.Path, help="order.tsv。順位の順に先へ回す")
    parser.add_argument("--seed", action="append", type=pathlib.Path, default=[],
                        help="既にある訳。ここで済んだ語は作り直さない")
    parser.add_argument("--targets", type=pathlib.Path,
                        help="回す順に並べた entry ID の一覧")
    parser.add_argument("--dir", type=pathlib.Path, help="担当ごとの出力を置く場所")
    parser.add_argument("--out", type=pathlib.Path, help="合流させた先／検査する訳")
    parser.add_argument("--log", type=pathlib.Path,
                        help="担当ごとの記録の置き場（既定は --dir）")
    parser.add_argument("--shards", type=int, default=DEFAULT_SHARDS)
    parser.add_argument("--pilot", type=int, help="パイロットとして回す entry の数")
    parser.add_argument("--pilot-head", type=int, default=0,
                        help="そのうち順位の上位から取る数。残りは裾から等間隔で取る")
    parser.add_argument("--senses-per-call", type=int)
    parser.add_argument("--max-calls", type=int,
                        help="担当ごとの呼び出し回数の上限（呼び方を測るときに使う）")
    parser.add_argument("--poll-seconds", type=int, default=DEFAULT_POLL_SECONDS)
    parser.add_argument("--stall-minutes", type=float, default=DEFAULT_STALL_MINUTES)
    args = parser.parse_args(argv)

    if args.mode == "plan":
        entries = load_entries(args.full)
        done = finished_entry_ids(entries, args.seed)
        ranked = generate_ja.ranked_ids(args.order) if args.order else []
        targets = plan_targets(entries, done, ranked, args.pilot, args.pilot_head)
        args.targets.parent.mkdir(parents=True, exist_ok=True)
        args.targets.write_text("".join(f"{entry_id}\n" for entry_id in targets),
                                encoding="utf-8")
        senses = {entry["id"]: len(generate_ja.pending_numbers(entry))
                  for entry in entries}
        print(f"対象 {len(targets)} entry / {sum(senses[i] for i in targets)} sense を "
              f"{args.targets} へ書いた（済み {len(done)} entry は除いた）")
        return 0

    if args.mode == "run":
        return supervise(args)

    if args.mode == "merge":
        sources = [*args.seed, *sorted(args.dir.glob("shard-*.jsonl"))]
        rows, duplicates = merge_rows(sources)
        args.out.parent.mkdir(parents=True, exist_ok=True)
        args.out.write_text(
            "".join(json.dumps(row, ensure_ascii=False) + "\n" for row in rows),
            encoding="utf-8")
        print(f"語義 {len(rows)} 件を {args.out} へ書いた（重複 {duplicates} 件は捨てた）")
        return 0

    entries = load_entries(args.full)
    if args.targets:
        wanted = set(generate_ja.only_ids(args.targets))
        seeded = {str(row["id"]) for row in generate_ja.read_glosses(args.seed)}
        entries = [entry for entry in entries
                   if entry["id"] in wanted or entry["id"] in seeded]
    report = verify(entries, generate_ja.read_glosses([args.out]))
    print(f"entry {report.entries} / 訳の要る sense {report.senses} / 訳 {report.translated}")
    print(f"語義の足りない entry: {len(report.missing)} 件 {report.missing[:5]}")
    print(f"対象外の entry: {len(report.unknown)} 件 {report.unknown[:5]}")
    print(f"文字種・長さの違反: {len(report.violations)} 件")
    for violation in report.violations[:10]:
        print(f"  {violation}")
    return 1 if report.missing or report.unknown or report.violations else 0


if __name__ == "__main__":
    sys.exit(main())
