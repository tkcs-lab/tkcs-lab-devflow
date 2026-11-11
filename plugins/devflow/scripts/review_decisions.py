#!/usr/bin/env python3
"""Build the decisions page for /review's open items from a JSON file.

    review_decisions.py ITEMS.json OUT.html

ITEMS.json: {"repository", "scope", "commit", "review_url", "items": [{"id", "dimension",
"severity", "title", "where", "summary", "recommendation", "reason"}, ...]}. The page is
review_decisions.html (next to this script) with the items embedded as data; the page renders
every text with textContent, so nothing in the items is ever interpreted as HTML.
Exit 0, or 1 with one error per line. Python 3.11+, standard library only.
"""
from __future__ import annotations

import argparse
import html
import json
import re
import sys
from pathlib import Path

TEMPLATE = Path(__file__).resolve().with_name("review_decisions.html")
TITLE_MARK = "__REVIEW_TITLE__"
DATA_MARK = "__REVIEW_DATA__"

DIMENSIONS = {"security", "tests", "docs", "website"}
SEVERITIES = {"critical", "high", "medium", "low"}
RECOMMENDATIONS = {"plan", "issue", "drop"}
TOP_KEYS = ("repository", "scope", "commit", "review_url")
ITEM_KEYS = ("id", "dimension", "severity", "title", "where", "summary", "recommendation", "reason")
# An item id is a document id in the page's store: letters, digits and _ - . ~ : @ +, not "." or "..".
ID_RE = re.compile(r"[A-Za-z0-9_.~:@+-]{1,64}")


def _text(value) -> bool:
    return isinstance(value, str) and bool(value.strip())


def validate(data) -> list[str]:
    if not isinstance(data, dict):
        return ["top level must be an object"]
    errors = [f"missing or empty '{k}'" for k in TOP_KEYS if not _text(data.get(k))]
    unknown = sorted(set(data) - set(TOP_KEYS) - {"items"})
    errors += [f"unknown key '{k}'" for k in unknown]
    if _text(data.get("review_url")) and not data["review_url"].startswith("https://"):
        errors.append("'review_url' must be an https:// URL")
    items = data.get("items")
    if not isinstance(items, list) or not items:
        return errors + ["'items' must be a non-empty list"]
    seen = set()
    for n, item in enumerate(items, 1):
        where = f"items[{n}]"
        if not isinstance(item, dict):
            errors.append(f"{where}: must be an object")
            continue
        errors += [f"{where}: missing or empty '{k}'" for k in ITEM_KEYS if not _text(item.get(k))]
        errors += [f"{where}: unknown key '{k}'" for k in sorted(set(item) - set(ITEM_KEYS))]
        ident = item.get("id")
        if _text(ident):
            if not ID_RE.fullmatch(ident) or ident in {".", ".."}:
                errors.append(f"{where}: id '{ident}' may only use letters, digits and _ - . ~ : @ +")
            elif ident in seen:
                errors.append(f"{where}: duplicate id '{ident}'")
            seen.add(ident)
        for key, allowed in (("dimension", DIMENSIONS), ("severity", SEVERITIES),
                             ("recommendation", RECOMMENDATIONS)):
            if _text(item.get(key)) and item[key] not in allowed:
                errors.append(f"{where}: {key} '{item[key]}' is not one of {', '.join(sorted(allowed))}")
    return errors


def embed(data) -> str:
    """JSON safe inside <script type="application/json">: no '<', '>' or '&' survives literally."""
    text = json.dumps(data, ensure_ascii=False, separators=(",", ":"))
    for char, escaped in (("<", "\\u003c"), (">", "\\u003e"), ("&", "\\u0026"),
                          (" ", "\\u2028"), (" ", "\\u2029")):
        text = text.replace(char, escaped)
    return text


def render(data, template: str) -> str:
    if template.count(TITLE_MARK) != 1 or template.count(DATA_MARK) != 1:
        raise ValueError("template must contain each placeholder exactly once")
    name = data["repository"].rsplit("/", 1)[-1]
    title = html.escape(f"{name} review decisions", quote=False)
    return template.replace(TITLE_MARK, title).replace(DATA_MARK, embed(data))


def main(argv: list[str] | None = None) -> int:
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("items")
    ap.add_argument("out")
    args = ap.parse_args(argv)

    try:
        data = json.loads(Path(args.items).read_text())
    except FileNotFoundError:
        print(f"decisions: no such file '{args.items}'", file=sys.stderr)
        return 1
    except json.JSONDecodeError as exc:
        print(f"decisions: not valid JSON: {exc}", file=sys.stderr)
        return 1
    errors = validate(data)
    for e in errors:
        print(f"decisions: {e}", file=sys.stderr)
    if errors:
        return 1
    out = Path(args.out)
    out.parent.mkdir(parents=True, exist_ok=True)
    out.write_text(render(data, TEMPLATE.read_text()))
    print(f"decisions: wrote {out} ({len(data['items'])} items)")
    return 0


if __name__ == "__main__":
    sys.exit(main())
