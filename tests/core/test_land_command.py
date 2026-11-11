import json
import re
import subprocess
import sys

import pytest

from conftest import TLD, CLAUDE, tld_cmd

SCRIPT = TLD / "ops" / "land_order.py"
SCRIPT_CMD = tld_cmd("ops", "land-order")
FORBIDDEN = re.compile(r"privacyfence|ruff|pytest|src/privacyfence|connector", re.I)


def run(prs, *args):
    return subprocess.run([*SCRIPT_CMD, "-", *args], input=json.dumps(prs),
                          capture_output=True, text=True)


def pr(n, head=None, base="main"):
    return {"number": n, "head": head or f"b{n}", "base": base}


def order(prs, *args):
    r = run(prs, *args)
    assert r.returncode == 0, r.stderr
    return [int(x) for x in r.stdout.split()]


def test_ascending():
    assert order([pr(7), pr(3), pr(5)]) == [3, 5, 7]


def test_stacked_after_base():
    assert order([pr(3, base="b7"), pr(7)]) == [7, 3]


def test_chain_of_three():
    assert order([pr(1, base="b2"), pr(2, base="b3"), pr(3)]) == [3, 2, 1]


def test_cycle_is_error():
    r = run([pr(1, base="b2"), pr(2, base="b1")])
    assert r.returncode == 1
    assert r.stderr.strip() == "land_order: cycle between #1 and #2"
    assert r.stdout == ""


def test_max_truncates_oldest_first():
    assert order([pr(4), pr(2), pr(9)], "--max", "2") == [2, 4]


def test_unknown_base_is_ascending():
    assert order([pr(8, base="elsewhere"), pr(2, base="gone")]) == [2, 8]


def test_kahn_smallest_ready_first():
    assert order([pr(9), pr(12, base="b4"), pr(4)]) == [4, 9, 12]


def test_acceptance_example():
    assert order([pr(7), pr(5, base="b7"), pr(3)]) == [3, 7, 5]


@pytest.mark.parametrize("text", ["nope", "{}", '[{"number":"1","head":"a","base":"b"}]',
                                  '[{"number":1,"head":"a"}]'])
def test_bad_input(text):
    r = subprocess.run([*SCRIPT_CMD, "-"], input=text, capture_output=True, text=True)
    assert r.returncode == 1 and r.stderr.startswith("land_order: ")


def test_the_playbook_collects_stacked_pull_requests_and_fetches_every_head():
    """C11: stacked pull requests (base = another collected head) are in scope, and each head is fetched first."""
    from conftest import ROOT
    text = " ".join((ROOT / "playbooks" / "land.md").read_text().split())
    assert "with base `<main>` or **stacked**: its base is the head branch of another pull request collected here" in text
    assert "**Fetch every head** you will merge, by its branch name: `git fetch origin` with every head branch name" in text
    assert "Never merge a head you have not just fetched" in text
    assert order([pr(5, base="b9"), pr(9), pr(2)]) == [2, 9, 5]  # what the collected stacked set lands as
