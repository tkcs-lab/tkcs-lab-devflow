#!/usr/bin/env python3
"""Order open pull requests for /land.

Usage: land_order.py [FILE|-] [--max N]

Input is a JSON list of {"number": int, "head": str, "base": str}. Output is the pull request
numbers, one per line: Kahn's topological sort where a pull request whose base equals another
listed pull request's head comes after that one (stacked); among the ready ones the smallest
number goes first. A base that no listed pull request has as head adds no constraint. --max N keeps
the first N lines of that order.

Exit 0 ok; 1 bad input or a cycle (`land_order: <message>`).
"""
import argparse
import heapq
import json
import sys


class OrderError(Exception):
    """Bad input or a cycle (exit 1)."""


def parse(text):
    try:
        data = json.loads(text)
    except ValueError as exc:
        raise OrderError(f"input is not valid JSON ({exc})")
    if not isinstance(data, list):
        raise OrderError("input must be a JSON list")
    prs = {}
    for i, item in enumerate(data):
        if not isinstance(item, dict):
            raise OrderError(f"item {i} must be an object")
        n = item.get("number")
        if isinstance(n, bool) or not isinstance(n, int) or n < 1:
            raise OrderError(f"item {i}: 'number' must be a positive integer")
        for key in ("head", "base"):
            if not isinstance(item.get(key), str) or not item[key]:
                raise OrderError(f"item {i}: '{key}' must be a non-empty string")
        if n in prs:
            raise OrderError(f"duplicate pull request #{n}")
        prs[n] = item
    return prs


def order(prs):
    by_head = {}
    for n, pr in prs.items():
        by_head.setdefault(pr["head"], []).append(n)
    parents = {n: sorted(by_head.get(pr["base"], [])) for n, pr in prs.items()}
    waiting = {n: len(ps) for n, ps in parents.items()}
    children = {n: [] for n in prs}
    for n, ps in parents.items():
        for p in ps:
            children[p].append(n)
    ready = [n for n, w in waiting.items() if w == 0]
    heapq.heapify(ready)
    result = []
    while ready:
        n = heapq.heappop(ready)
        result.append(n)
        for c in children[n]:
            waiting[c] -= 1
            if waiting[c] == 0:
                heapq.heappush(ready, c)
    if len(result) < len(prs):
        stuck = {n for n, w in waiting.items() if w > 0}
        node, seen = min(stuck), []
        while node not in seen:
            seen.append(node)
            node = min(p for p in parents[node] if p in stuck)
        cycle = seen[seen.index(node):]
        a = min(cycle)
        b = min(p for p in parents[a] if p in cycle)
        raise OrderError(f"cycle between #{min(a, b)} and #{max(a, b)}")
    return result


def main(argv=None):
    ap = argparse.ArgumentParser(prog="land_order.py")
    ap.add_argument("file", nargs="?", default="-")
    ap.add_argument("--max", type=int, dest="max_n")
    args = ap.parse_args(argv)
    try:
        if args.max_n is not None and args.max_n < 1:
            raise OrderError("--max must be at least 1")
        text = sys.stdin.read() if args.file == "-" else open(args.file).read()
        numbers = order(parse(text))
    except OSError as exc:
        print(f"land_order: cannot read input ({exc.strerror})", file=sys.stderr)
        return 1
    except OrderError as exc:
        print(f"land_order: {exc}", file=sys.stderr)
        return 1
    if args.max_n is not None:
        numbers = numbers[: args.max_n]
    for n in numbers:
        print(n)
    return 0


if __name__ == "__main__":
    sys.exit(main())
