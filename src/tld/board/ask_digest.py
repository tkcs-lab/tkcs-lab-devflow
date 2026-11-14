#!/usr/bin/env python3
"""Digest the board's asks into clusters of similar questions, for the weekly questions review.

    tld board ask-digest --repo OWNER/NAME [--since ISO] [--file FILE|-] [--vocab FILE] [--now ISO]

Reads the asks from the board (`GET /api/asks?limit=1000&order=asc[&since=ISO]`) or from `--file`, keeps the
asks of one repository, masks every question (urls, code, emails, logins, paths, hosts, hashes, hyphenated names
and numbers), optionally replaces every word that is not in `--vocab`, and groups similar questions. The asks of
other projects only add counts. No answer text and no text of a foreign ask leaves this module. Exit codes: 0 the
digest as one line of JSON; 1 the board answered an error or cannot be reached, the configuration is wrong, or a
file cannot be read; 2 usage error; 3 no board configured. Python 3.11+, stdlib only.
"""
from __future__ import annotations

import argparse
import hashlib
import json
import re
import statistics
import sys
from datetime import datetime, timezone
from pathlib import Path

from tld.board import ask as board_ask
from tld.board import client as board_client
from tld.board.record import TIMESTAMP, parse_doc_id, project_slug

MAX_TEMPLATE = 160
SIMILARITY = 0.5
REPOST_MINUTES = 30
MAX_CLUSTERS = 60
MAX_CLUSTER_ASKS = 20
TITLE_SOURCES = (("start ", "run"), ("phase ", "run"), ("plan #", "make-plan"))
MIN_COUNT = 3
MIN_RECORDS = 2
MIN_EMPTY_RATE = 0.8
MIN_REPOSTED = 2
MIN_CANCELLED = 3
TRUNCATION_SIZES = (200, 1000)
EXCLUDED_COMMAND = "questions"
MAX_INPUT = 2000  # characters of a question read before masking; only MAX_TEMPLATE are emitted
MAX_TOKEN = 200  # a longer run without whitespace is cut, so no pattern backtracks over it
KINDS = ("text", "choice", "confirm")

_PLACEHOLDERS = "code|url|email|login|path|host|n|sha|slug|word"
_PLACEHOLDER = re.compile(rf"#?<(?:{_PLACEHOLDERS})>")
_ANY_PLACEHOLDER = re.compile(r"<[^<>]*>")
_LETTERS = re.compile(r"[^\W\d_]+")
_MASKS = (
    (re.compile(r"`[^`]*`"), "<code>"),
    (re.compile(r"https?://[^\s`]+"), "<url>"),
    (re.compile(r"\S+@\S+\.\S+"), "<email>"),
    (re.compile(r"@[a-z0-9_-]+"), "<login>"),
    (re.compile(r"\S*[/\\]\S*"), "<path>"),
    (re.compile(r"\b[a-z0-9-]+(?:\.[a-z0-9-]+)+\b"), "<host>"),
    (re.compile(r"#\d+"), "#<n>"),
    (re.compile(r"\b[0-9a-f]{7,40}\b"), "<sha>"),
    (re.compile(r"\b[a-z0-9]+(?:-[a-z0-9]+)+\b"), "<slug>"),
    (re.compile(r"\d+"), "<n>"),
)


def mask(text: str) -> str:
    """The question text with every identifying token replaced, lower case, cut at MAX_TEMPLATE characters."""
    out = " ".join(tok[:MAX_TOKEN] for tok in text[:MAX_INPUT].lower().split())
    for pattern, repl in _MASKS:
        out = pattern.sub(repl, out)
    out = " ".join(out.split())
    if len(out) > MAX_TEMPLATE:
        cut = MAX_TEMPLATE
        for found in _PLACEHOLDER.finditer(out):
            if found.start() < MAX_TEMPLATE < found.end():
                cut = found.start()
                break
        out = out[:cut]
    return out.rstrip()


def _vocab_piece(text: str, vocab: set[str] | frozenset[str]) -> str:
    """Letter runs outside `vocab` become `<word>`; a character that is no letter, digit, space or ASCII
    punctuation (a circled letter, a symbol) becomes a space, so it cannot carry text."""
    text = "".join(c if c.isalnum() or c.isspace() or (c.isascii() and c.isprintable()) else " " for c in text)
    return _LETTERS.sub(lambda m: m.group(0) if m.group(0) in vocab else "<word>", text)


def apply_vocab(template: str, vocab: set[str] | frozenset[str]) -> str:
    """Replace every run of letters outside a placeholder that is not in `vocab` by `<word>`."""
    pieces: list[str] = []
    last = 0
    for found in _PLACEHOLDER.finditer(template):
        pieces.append(_vocab_piece(template[last:found.start()], vocab))
        pieces.append(found.group(0))
        last = found.end()
    pieces.append(_vocab_piece(template[last:], vocab))
    return "".join(pieces)


def words(template: str) -> frozenset[str]:
    """The words of three or more letters outside the placeholders."""
    return frozenset(re.findall(r"[a-z]{3,}", _ANY_PLACEHOLDER.sub(" ", template)))


def source_of(ask: dict) -> str | None:
    """The command that posted the ask: from its record id, or for an ask without a record from its title."""
    record = ask.get("record")
    if record is not None:
        parsed = parse_doc_id(record) if isinstance(record, str) else None
        if parsed is None:
            return None
        return "run" if parsed[1] == "run" else parsed[2]
    title = ask.get("title")
    lowered = title.lower() if isinstance(title, str) else ""
    for prefix, source in TITLE_SOURCES:
        if lowered.startswith(prefix):
            return source
    return None


def _seconds(start: str, end: str) -> int:
    fmt = "%Y-%m-%dT%H:%M:%SZ"
    return int((datetime.strptime(end, fmt) - datetime.strptime(start, fmt)).total_seconds())


def _shift(stamp: str, seconds: int) -> str:
    fmt = "%Y-%m-%dT%H:%M:%SZ"
    moment = datetime.strptime(stamp, fmt).replace(tzinfo=timezone.utc).timestamp() + seconds
    return datetime.fromtimestamp(moment, timezone.utc).strftime(fmt)


def _is_stamp(value: object) -> bool:
    if not (isinstance(value, str) and TIMESTAMP.match(value)):
        return False
    try:
        datetime.strptime(value, "%Y-%m-%dT%H:%M:%SZ")
    except ValueError:
        return False
    return True


def _questions(ask: dict) -> list[dict]:
    """The questions of an ask that have text and a known kind; an id that is no question id becomes `q<n>`."""
    raw = ask.get("questions")
    found = []
    for index, q in enumerate(raw if isinstance(raw, list) else []):
        if not (isinstance(q, dict) and isinstance(q.get("text"), str) and q.get("kind") in KINDS):
            continue
        qid = q.get("id")
        found.append({**q, "id": qid if isinstance(qid, str) and board_ask.QID_RE.match(qid) else f"q{index}"})
    return found


def _took_recommended(ask: dict, question: dict) -> bool | None:
    if ask.get("state") != "answered":
        return None
    answers = ask.get("answers")
    qid = question.get("id")
    if not isinstance(answers, dict) or qid not in answers:
        return None
    answer = answers[qid]
    kind = question.get("kind")
    if kind == "choice":
        options = question.get("options")
        if isinstance(options, list) and options and isinstance(options[0], dict):
            return answer == options[0].get("value")
        return None
    if kind == "confirm":
        return answer is True
    return None


def _empty(ask: dict, question: dict) -> bool:
    if question.get("kind") != "text" or question.get("required", True) is not False:
        return False
    if ask.get("state") != "answered":
        return False
    answers = ask.get("answers")
    answer = answers.get(question.get("id")) if isinstance(answers, dict) else None
    return answer is None or answer == ""


def _similar(seed_words: frozenset[str], seed: str, other_words: frozenset[str], other: str) -> bool:
    union = seed_words | other_words
    if not union:
        return seed == other
    return len(seed_words & other_words) / len(union) >= SIMILARITY


def _rate(flags: list[bool]) -> float | None:
    return round(sum(flags) / len(flags), 2) if flags else None


def _cluster_dict(number: int, members: list[dict], vocab: frozenset[str] | None) -> dict:
    seed = members[0]
    qids: dict[str, int] = {}
    for entry in members:
        qids[entry["qid"]] = qids.get(entry["qid"], 0) + 1
    top = max(qids.values())
    qid = next(entry["qid"] for entry in members if qids[entry["qid"]] == top)
    seen_records: set[object] = set()
    for index, entry in enumerate(members):
        seen_records.add(entry["record"] if entry["record"] is not None else ("none", index))
    recommended = [e["took_recommended"] for e in members if e["took_recommended"] is not None]
    kind = seed["kind"]
    answered = [e for e in members if e["state"] == "answered"]
    empty_rate = _rate([e["empty"] for e in answered]) if kind == "text" else None
    seconds = [e["seconds"] for e in members if e["seconds"] is not None]
    cancelled = sum(1 for e in members if e["cancelled"])
    reposted = sum(1 for e in members if e["reposted"])
    count = len(members)
    records = len(seen_records)
    candidate = ((count >= MIN_COUNT and records >= MIN_RECORDS)
                 or (count >= MIN_COUNT and empty_rate is not None and empty_rate >= MIN_EMPTY_RATE)
                 or reposted >= MIN_REPOSTED or cancelled >= MIN_CANCELLED)
    fingerprint = hashlib.sha256(f"{seed['source'] or '-'}|{kind}|{seed['raw']}".encode()).hexdigest()[:16]
    return {
        "id": f"c{number}",
        "fingerprint": fingerprint,
        "source": seed["source"],
        "qid": qid,
        "kind": kind,
        "template": apply_vocab(seed["raw"], vocab) if vocab is not None else seed["raw"],
        "count": count,
        "records": records,
        "asks": sorted({e["ask"] for e in members})[:MAX_CLUSTER_ASKS],
        "foreign_count": 0,
        "recommended_rate": _rate(recommended),
        "empty_rate": empty_rate,
        "cancelled": cancelled,
        "reposted": reposted,
        "median_seconds": int(statistics.median(seconds)) if seconds else None,
        "candidate": candidate,
        "first": min(e["created_at"] for e in members),
        "last": max(e["created_at"] for e in members),
    }


def digest(asks: list, repo: str, since: str | None, now: str, vocab: set[str] | frozenset[str] | None = None) -> dict:
    """The digest of `asks` for `repo` (pure: no network). `since` and `now` are timestamps YYYY-MM-DDTHH:MM:SSZ."""
    project = project_slug(repo)
    frozen = frozenset(vocab) if vocab is not None else None
    truncated = len(asks) in TRUNCATION_SIZES
    rows = [{**a, "record": a["record"] if isinstance(a.get("record"), str) else None,
             "answers": a["answers"] if isinstance(a.get("answers"), dict) else {}}
            for a in asks if isinstance(a, dict) and _is_stamp(a.get("created_at"))
            and isinstance(a.get("id"), str) and board_ask.ID_RE.match(a["id"])
            and (since is None or a["created_at"] > since)]
    own: list[dict] = []
    foreign: list[dict] = []
    for ask in rows:
        (own if ask.get("project") == project and ask.get("repo") == repo else foreign).append(ask)

    def is_excluded(ask: dict) -> bool:
        parsed = parse_doc_id(ask["record"]) if isinstance(ask.get("record"), str) else None
        return parsed is not None and parsed[1] == "command" and parsed[2] == EXCLUDED_COMMAND

    excluded = [a for a in own if is_excluded(a)]
    kept = [a for a in own if not is_excluded(a)]
    open_asks = [a for a in kept if a.get("state") == "open"]
    analysed = [a for a in kept if a.get("state") != "open"]

    by_record: dict[str, list[str]] = {}
    for ask in own:
        if isinstance(ask.get("record"), str):
            by_record.setdefault(ask["record"], []).append(ask["created_at"])

    entries: list[dict] = []
    for ask in analysed:
        source = source_of(ask)
        cancelled = ask.get("state") == "cancelled"
        reposted = False
        if cancelled and isinstance(ask.get("record"), str):
            reposted = any(0 < _seconds(ask["created_at"], later) <= REPOST_MINUTES * 60
                           for later in by_record[ask["record"]])
        answered_at = ask.get("answered_at")
        seconds = (_seconds(ask["created_at"], answered_at)
                   if ask.get("state") == "answered" and _is_stamp(answered_at) else None)
        for question in _questions(ask):
            raw = mask(question["text"])
            entries.append({
                "ask": str(ask.get("id")), "created_at": ask["created_at"], "source": source,
                "qid": str(question.get("id")), "kind": question.get("kind"), "raw": raw, "words": words(raw),
                "record": ask.get("record"), "state": ask.get("state"),
                "took_recommended": _took_recommended(ask, question), "empty": _empty(ask, question),
                "seconds": seconds, "cancelled": cancelled, "reposted": reposted,
            })
    entries.sort(key=lambda e: (e["created_at"], e["ask"], e["qid"]))

    groups: list[list[dict]] = []
    for entry in entries:
        for group in groups:
            seed = group[0]
            if (seed["source"] == entry["source"] and seed["kind"] == entry["kind"]
                    and _similar(seed["words"], seed["raw"], entry["words"], entry["raw"])):
                group.append(entry)
                break
        else:
            groups.append([entry])

    foreign_counts = [0] * len(groups)
    unmatched = 0
    for ask in foreign:
        source = source_of(ask)
        for question in _questions(ask):
            raw = mask(question["text"])
            raw_words = words(raw)
            for index, group in enumerate(groups):
                seed = group[0]
                if (seed["source"] == source and seed["kind"] == question.get("kind")
                        and _similar(seed["words"], seed["raw"], raw_words, raw)):
                    foreign_counts[index] += 1
                    break
            else:
                unmatched += 1

    clusters = []
    for group, extra in zip(groups, foreign_counts):
        cluster = _cluster_dict(0, group, frozen)
        cluster["foreign_count"] = extra
        clusters.append(cluster)
    clusters.sort(key=lambda c: (-c["count"], c["first"]))
    clusters = clusters[:MAX_CLUSTERS]
    for number, cluster in enumerate(clusters, 1):
        cluster["id"] = f"c{number}"

    cursor = None
    if own:
        cursor = max(a["created_at"] for a in own)
        if open_asks:
            cursor = min(cursor, _shift(min(a["created_at"] for a in open_asks), -1))
    return {
        "schema": 1,
        "project": project,
        "since": since,
        "now": now,
        "cursor": cursor,
        "truncated": truncated,
        "asks": len(rows),
        "analysed": len({e["ask"] for e in entries}),
        "open_asks": len(open_asks),
        "excluded_questions_asks": len(excluded),
        "foreign": {"asks": len(foreign), "unmatched_questions": unmatched},
        "clusters": clusters,
    }


def fetch(config: board_client.Config, since: str | None) -> list[dict]:
    """The asks the board lists, oldest first (at most 1000). Raises OSError when the board does not answer 200."""
    path = "/api/asks?limit=1000&order=asc" + (f"&since={since}" if since else "")
    status, payload = board_client.call(config, "GET", path)
    if status != 200:
        raise OSError(f"the board answered HTTP {status}")
    rows = payload.get("asks") if isinstance(payload, dict) else None
    if not isinstance(rows, list):
        raise OSError("the board answered without a list of asks")
    return rows


def _read_asks(source: str) -> list:
    text = sys.stdin.read() if source == "-" else Path(source).read_text(encoding="utf-8")
    doc = json.loads(text)
    rows = doc.get("asks") if isinstance(doc, dict) else doc
    if not isinstance(rows, list):
        raise ValueError("the file holds no list of asks")
    return rows


def _timestamp(value: str) -> str:
    if not _is_stamp(value):
        raise argparse.ArgumentTypeError("must be a timestamp YYYY-MM-DDTHH:MM:SSZ")
    return value


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(prog="tld board ask-digest",
                                     description="Digest the asks of one repository into clusters of similar questions.")
    parser.add_argument("--repo", required=True, metavar="OWNER/NAME")
    parser.add_argument("--since", type=_timestamp, help="keep only asks created after this time")
    parser.add_argument("--file", help="read the asks from a JSON file (- for stdin) instead of the board")
    parser.add_argument("--vocab", help="a file of allowed words, one per line, lower case")
    parser.add_argument("--now", type=_timestamp, help="the time to print as `now`")
    return parser


def main(argv: list[str] | None = None) -> int:
    args = build_parser().parse_args(argv)
    vocab = None
    try:
        if args.vocab:
            lines = Path(args.vocab).read_text(encoding="utf-8").splitlines()
            vocab = {line.strip() for line in lines if line.strip()}
        if args.file:
            rows = _read_asks(args.file)
        else:
            config = board_client.load_config()
            if config is None:
                print("tld board: no board configured", file=sys.stderr)
                return 3
            rows = fetch(config, args.since)
    except board_client.ConfigError as exc:
        print(f"tld board: {exc}", file=sys.stderr)
        return 1
    except (OSError, ValueError, RecursionError) as exc:
        print(f"tld board: cannot read the asks ({type(exc).__name__}: {exc})", file=sys.stderr)
        return 1
    now = args.now or datetime.now(timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ")
    try:
        result = digest(rows, args.repo, args.since, now, vocab)
    except (TypeError, ValueError, KeyError, AttributeError, RecursionError) as exc:
        print(f"tld board: cannot digest the asks ({type(exc).__name__})", file=sys.stderr)
        return 1
    print(json.dumps(result, separators=(",", ":")))
    return 0


if __name__ == "__main__":
    sys.exit(main())
