#!/usr/bin/env python3
"""中国語の主な語義と既定の行を選び、JSON Linesへ追記する。

同じコマンドで再開できる。トークン上限は呼び出し後の使用量で判定するため、
最後の1回で上限を超えうる。Python 3.9以上、標準ライブラリだけを使う。
"""
from __future__ import annotations

import argparse
import json
import pathlib
import subprocess
import sys
import tempfile
import time
from typing import Callable, Optional

sys.path.insert(0, str(pathlib.Path(__file__).resolve().parent))
import generate_ja as g
import entries_file

CODEX_MODEL = "gpt-6.1-sol"
CODEX_EFFORT = "medium"
PROMPT_PATH = pathlib.Path(__file__).resolve().parent / "prompts" / "primary-sense.md"
DEFAULT_PACKED = pathlib.Path(__file__).resolve().parent.parent / "data/zh-ja/entries.jsonl.deflate"
DEFAULT_SENSES_PER_CALL = 300


def spent_tokens(usage: dict) -> int:
    return sum(usage.get(key, 0) for key in (
        "input_tokens", "output_tokens", "cache_creation_input_tokens", "cache_read_input_tokens"))


CODEX_DISABLED_FEATURES = tuple(
    part for name in ("apps", "browser_use", "browser_use_external", "computer_use",
                      "image_generation", "goals", "in_app_browser", "hooks")
    for part in ("--disable", name))


def call_codex(prompt: str, system: str, effort: Optional[str] = None,
               runner: Callable = subprocess.run, model: Optional[str] = None) -> g.Reply:
    """`codex exec` を1回呼ぶ。`call_claude` と同じく毎回まっさらのセッションで聞く。

    指示文は `model_instructions_file` で組み込みの指示と置き換える。設定・規則・
    作業directoryの文書は読ませず、道具は読み取り専用にする。
    認証の置き場所は動かさない。
    """
    workdir = tempfile.mkdtemp(prefix="generate-ja-codex-")
    instructions = pathlib.Path(workdir) / "instructions.md"
    instructions.write_text(system, encoding="utf-8")
    command = [
        "codex", "exec",
        "--ephemeral", "--ignore-user-config", "--ignore-rules",
        "--skip-git-repo-check", "-s", "read-only", "-C", workdir,
        "-m", model or CODEX_MODEL,
        "-c", f"model_reasoning_effort={effort or CODEX_EFFORT}",
        "-c", "project_doc_max_bytes=0",
        "-c", f'model_instructions_file="{instructions}"',
        "-c", "mcp_servers={}",
        "-c", 'web_search="disabled"',
        *CODEX_DISABLED_FEATURES,
        "--json",
        prompt,
    ]
    started = time.time()
    # 標準入力を閉じる。開いていると本文の後ろへ追記を待って止まる。
    finished = runner(command, capture_output=True, text=True,
                      stdin=subprocess.DEVNULL, cwd=workdir, check=False)
    seconds = time.time() - started
    if finished.returncode != 0:
        # `--json` では失敗の出来事が標準出力に出る。標準エラーには無関係な行が
        # 出ることがあるので、上限かどうかは両方を合わせて見る。
        note = "\n".join(part for part in (finished.stderr, finished.stdout) if part).strip()
        if g.looks_rate_limited(note):
            raise g.RateLimited(note[-200:])
        raise g.BadResponse(f"codex が終了コード {finished.returncode}: {note[-200:]!r}")
    text = None
    usage: dict = {}
    for line in (finished.stdout or "").splitlines():
        try:
            event = json.loads(line)
        except json.JSONDecodeError:
            continue
        kind = event.get("type")
        item = event.get("item") or {}
        if kind == "item.completed" and item.get("type") == "agent_message":
            text = item.get("text")
        elif kind == "turn.completed":
            usage = event.get("usage") or {}
        elif kind in ("turn.failed", "error"):
            message = json.dumps(event, ensure_ascii=False)
            if g.looks_rate_limited(message):
                raise g.RateLimited(message[:200])
            raise g.BadResponse(f"codex が失敗した: {message[:200]!r}")
    if text is None:
        raise g.BadResponse("codex の応答に発言が無い")
    return g.Reply(text=text, usage=usage, seconds=seconds)


def row_key(row: dict) -> tuple:
    return row.get("word"), row.get("trad", ""), row.get("pinyin")


def identity(row: dict) -> dict:
    return {"word": row["word"], "trad": row.get("trad", ""), "pinyin": row["pinyin"]}


def grouped(entries: list, words: Optional[set] = None) -> list:
    groups: dict = {}
    for entry in entries:
        if words is None or entry["word"] in words:
            groups.setdefault(entry["word"], []).append(entry)
    return list(groups.values())


def build_payload(groups: list) -> str:
    return json.dumps([
        {"w": rows[0]["word"], "rows": [
            {"r": number, "trad": row.get("trad", ""), "pinyin": row["pinyin"],
             "s": {str(n): {"ja": sense["ja"], "en": (sense.get("en") or [""])[0]}
                   for n, sense in enumerate(row["senses"], 1)}}
            for number, row in enumerate(rows, 1)]} for rows in groups
    ], ensure_ascii=False, separators=(",", ":"))


def parse_response(text: str, groups: list) -> tuple:
    fenced = g._FENCE.search(text)
    found = g._OBJECT.search(fenced.group(1) if fenced else text)
    if not found:
        raise g.BadResponse("JSONが見つからない")
    try:
        parsed = json.loads(found.group(0))
    except json.JSONDecodeError as error:
        raise g.BadResponse(f"JSONとして読めない: {error}") from error
    if not all(isinstance(parsed.get(key), list) for key in ("primary", "defaults")):
        raise g.BadResponse("primary と defaults は配列が必要")
    by_word = {rows[0]["word"]: rows for rows in groups}
    senses, defaults, dropped = [], [], 0
    for kind, sink in (("primary", senses), ("defaults", defaults)):
        seen = set()
        for item in parsed[kind]:
            if not isinstance(item, dict):
                dropped += 1
                continue
            rows = by_word.get(item.get("w")) if isinstance(item.get("w"), str) else None
            number = item.get("r")
            if rows is None or type(number) is not int or not 1 <= number <= len(rows):
                dropped += 1
                continue
            row = rows[number - 1]
            key = row_key(row) if kind == "primary" else row["word"]
            n = item.get("n")
            if key in seen or (kind == "primary" and (
                    len(row["senses"]) < 2 or type(n) is not int or not 1 <= n <= len(row["senses"]))) \
                    or (kind == "defaults" and len(rows) < 2):
                dropped += 1
                continue
            seen.add(key)
            record = identity(row)
            if kind == "primary":
                record.update(sense=n, ja=row["senses"][n - 1]["ja"])
            sink.append(record)
    return senses, defaults, dropped


def chunks(groups: list, senses_per_call: int):
    current, count = [], 0
    for rows in groups:
        size = sum(len(row["senses"]) for row in rows)
        # 読みの比較に全行が要るため、1語だけで目安を超えても分割しない。
        if current and count + size > senses_per_call:
            yield current
            current, count = [], 0
        current.append(rows)
        count += size
    if current:
        yield current


def records(path: pathlib.Path) -> list:
    return [row for row in g.read_glosses([path]) if isinstance(row, dict)]


def run(entries: list, out_senses: pathlib.Path, out_defaults: pathlib.Path,
        call: Callable, system: str, senses_per_call: int = DEFAULT_SENSES_PER_CALL,
        token_budget: Optional[int] = None, words: Optional[set] = None) -> tuple:
    groups = grouped(entries, words)
    current = {row_key(row): row for rows in groups for row in rows if len(row["senses"]) >= 2}
    done_senses = set()
    for record in records(out_senses):
        row = current.get(row_key(record))
        n = record.get("sense")
        if row is not None and type(n) is int and 1 <= n <= len(row["senses"]) \
                and row["senses"][n - 1]["ja"] == record.get("ja"):
            done_senses.add(row_key(row))
    candidates = {row_key(row) for rows in groups if len(rows) >= 2 for row in rows}
    done_defaults = {row["word"] for row in records(out_defaults) if row_key(row) in candidates}
    pending_senses = set(current) - done_senses
    pending_defaults = {rows[0]["word"] for rows in groups if len(rows) >= 2} - done_defaults
    left = [rows for rows in groups if rows[0]["word"] in pending_defaults
            or any(row_key(row) in pending_senses for row in rows)]
    usage: dict = {}
    written_senses = written_defaults = 0
    for path in (out_senses, out_defaults):
        path.parent.mkdir(parents=True, exist_ok=True)
    with out_senses.open("a", encoding="utf-8") as sense_sink, \
            out_defaults.open("a", encoding="utf-8") as default_sink:
        for chunk in chunks(left, senses_per_call):
            if token_budget is not None and spent_tokens(usage) >= token_budget:
                print(f"トークン上限 {token_budget:,} に達した（使った量 {spent_tokens(usage):,}）", file=sys.stderr)
                break
            try:
                reply = call(build_payload(chunk), system)
                g.add_usage(usage, reply.usage)
                senses, defaults, dropped = parse_response(reply.text, chunk)
            except g.BadResponse as error:
                print(f"取り込めなかった（次回聞き直す）: {error}", file=sys.stderr)
                continue
            for row in senses:
                if row_key(row) in pending_senses:
                    sense_sink.write(json.dumps(row, ensure_ascii=False) + "\n")
                    pending_senses.remove(row_key(row))
                    written_senses += 1
            for row in defaults:
                if row["word"] in pending_defaults:
                    default_sink.write(json.dumps(row, ensure_ascii=False) + "\n")
                    pending_defaults.remove(row["word"])
                    written_defaults += 1
            sense_sink.flush()
            default_sink.flush()
            print(f"主な語義 {written_senses} 行、既定 {written_defaults} 語、"
                  f"使った量 {spent_tokens(usage):,}、捨てた {dropped}", file=sys.stderr)
    return written_senses, written_defaults


def main(argv=None, call: Optional[Callable] = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    parser.add_argument("--packed", type=pathlib.Path, default=DEFAULT_PACKED)
    parser.add_argument("--out-senses", required=True, type=pathlib.Path)
    parser.add_argument("--out-defaults", required=True, type=pathlib.Path)
    parser.add_argument("--words", type=pathlib.Path, help="対象の語（1行1語）")
    parser.add_argument("--token-budget", type=int, help="到達後は新しい呼び出しをしない")
    parser.add_argument("--senses-per-call", type=int, default=DEFAULT_SENSES_PER_CALL)
    parser.add_argument("--backend", choices=("codex", "claude"), default="codex")
    parser.add_argument("--codex-model", help=f"既定は {CODEX_MODEL}")
    parser.add_argument("--no-retry", action="store_true", help="利用上限で待たない")
    args = parser.parse_args(argv)
    if args.senses_per_call <= 0 or (args.token_budget is not None and args.token_budget < 0):
        parser.error("語義数は正数、トークン上限は0以上が必要")
    if args.out_senses.resolve() == args.out_defaults.resolve():
        parser.error("出力2種は別ファイルが必要")
    if args.backend != "codex" and args.codex_model is not None:
        parser.error("--codex-model は --backend codex のときだけ使える")
    if call is None:
        call = (lambda prompt, system: call_codex(prompt, system, model=args.codex_model)) \
            if args.backend == "codex" else g.call_claude
        if not args.no_retry:
            call = g.retrying(call)
    entries = [json.loads(line) for line in entries_file.read_lines(args.packed) if line.strip()]
    words = {line.strip() for line in args.words.read_text(encoding="utf-8").splitlines()
             if line.strip()} if args.words else None
    senses, defaults = run(entries, args.out_senses, args.out_defaults, call,
                           PROMPT_PATH.read_text(encoding="utf-8"), args.senses_per_call,
                           args.token_budget, words)
    print(f"主な語義 {senses} 行を {args.out_senses}、既定 {defaults} 語を {args.out_defaults} へ書いた")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
