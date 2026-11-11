import copy
import json
import re
import subprocess
import sys

import pytest

from conftest import DEVFLOW, _load

SCRIPT = DEVFLOW / "scripts" / "review_decisions.py"

GOOD = {
    "repository": "acme/widgets",
    "scope": "whole repository",
    "commit": "abc1234",
    "review_url": "https://github.com/acme/widgets/blob/review/repo-2026-10-14/docs/repo-2026-10-14-review.md",
    "items": [
        {"id": "SEC-1", "dimension": "security", "severity": "high", "title": "Token in log",
         "where": "src/a.py:10", "summary": "The token is logged.", "recommendation": "plan",
         "reason": "Cheap fix."},
        {"id": "WEB-2", "dimension": "website", "severity": "low", "title": "Old screenshot",
         "where": "site/index.md:3", "summary": "Shows the old UI.", "recommendation": "drop",
         "reason": "Your call."},
    ],
}


@pytest.fixture(scope="module")
def rd():
    return _load("review_decisions")


def test_good_input_is_valid(rd):
    assert rd.validate(GOOD) == []


@pytest.mark.parametrize("mutate, expected", [
    (lambda d: d.pop("commit"), "missing or empty 'commit'"),
    (lambda d: d.update(extra=1), "unknown key 'extra'"),
    (lambda d: d.update(review_url="http://x"), "https://"),
    (lambda d: d.update(items=[]), "'items' must be a non-empty list"),
    (lambda d: d["items"][0].update(id="SEC 1"), "may only use"),
    (lambda d: d["items"][0].update(id=".."), "may only use"),
    (lambda d: d["items"][1].update(id="SEC-1"), "duplicate id 'SEC-1'"),
    (lambda d: d["items"][0].update(severity="urgent"), "severity 'urgent'"),
    (lambda d: d["items"][0].update(dimension="style"), "dimension 'style'"),
    (lambda d: d["items"][0].update(recommendation="fix"), "recommendation 'fix'"),
    (lambda d: d["items"][0].update(summary="  "), "missing or empty 'summary'"),
    (lambda d: d["items"][0].update(owner="x"), "unknown key 'owner'"),
])
def test_bad_input_is_named(rd, mutate, expected):
    data = copy.deepcopy(GOOD)
    mutate(data)
    errors = rd.validate(data)
    assert any(expected in e for e in errors), errors


def test_embedded_data_cannot_close_the_script(rd):
    data = copy.deepcopy(GOOD)
    data["items"][0]["summary"] = "</script><script>alert(1)</script> &  "
    page = rd.render(data, (DEVFLOW / "scripts" / "review_decisions.html").read_text())
    block = re.search(r'<script type="application/json" id="review-data">(.*?)</script>', page, re.S).group(1)
    assert "<" not in block and ">" not in block and "&" not in block and " " not in block
    assert json.loads(block) == data
    assert page.count("</script>") == 2


def test_title_is_escaped_and_placeholders_are_gone(rd):
    data = copy.deepcopy(GOOD)
    data["repository"] = "acme/w<i>&"
    page = rd.render(data, (DEVFLOW / "scripts" / "review_decisions.html").read_text())
    assert "<title>w&lt;i&gt;&amp; review decisions</title>" in page
    assert "__REVIEW_" not in page


def test_template_follows_the_page_contract():
    page = (DEVFLOW / "scripts" / "review_decisions.html").read_text()
    assert page.startswith("<title>")
    assert "<html" not in page and "<body" not in page and "<!doctype" not in page.lower()
    assert "prefers-color-scheme: dark" in page and ':root[data-theme="dark"]' in page
    assert "innerHTML" not in page  # every text goes through textContent
    assert 'claude.use("db")' in page and 'collection("decisions")' in page and 'doc("meta/status")' in page


def test_cli(tmp_path):
    items = tmp_path / "items.json"
    items.write_text(json.dumps(GOOD))
    out = tmp_path / "page.html"
    ok = subprocess.run([sys.executable, str(SCRIPT), str(items), str(out)], capture_output=True, text=True)
    assert ok.returncode == 0, ok.stderr
    assert "SEC-1" in out.read_text()

    bad = copy.deepcopy(GOOD)
    bad["items"][0]["severity"] = "urgent"
    items.write_text(json.dumps(bad))
    fail = subprocess.run([sys.executable, str(SCRIPT), str(items), str(tmp_path / "x.html")],
                          capture_output=True, text=True)
    assert fail.returncode == 1 and "decisions: items[1]: severity 'urgent'" in fail.stderr
    assert not (tmp_path / "x.html").exists()

    items.write_text("{not json")
    assert subprocess.run([sys.executable, str(SCRIPT), str(items), str(out)]).returncode == 1
