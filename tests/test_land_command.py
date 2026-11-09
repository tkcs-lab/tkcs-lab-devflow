import json
import re
import subprocess
import sys

import pytest

from conftest import DEVFLOW

SCRIPT = DEVFLOW / "scripts" / "land_order.py"
COMMAND = DEVFLOW / "commands" / "land.md"
FORBIDDEN = re.compile(r"privacyfence|ruff|pytest|src/privacyfence|connector", re.I)


def run(prs, *args):
    return subprocess.run([sys.executable, str(SCRIPT), "-", *args], input=json.dumps(prs),
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
    r = subprocess.run([sys.executable, str(SCRIPT), "-"], input=text, capture_output=True, text=True)
    assert r.returncode == 1 and r.stderr.startswith("land_order: ")


@pytest.fixture(scope="module")
def text():
    return COMMAND.read_text()


def test_front_matter(text):
    head = text.split("---")[1]
    assert re.search(r"^description: .+", head, re.M)
    assert re.search(r"^model: sonnet$", head, re.M)
    assert re.search(r'^argument-hint: "\[PR numbers\]"$', head, re.M)


def test_profile_paragraph(text):
    assert ("Load the `project-profile` skill and follow its \"Loading the profile\" section. If it reports "
            "an error, show the message verbatim and stop; never substitute a value of your own for a "
            "missing key.") in text


def test_headings_in_order(text):
    heads = re.findall(r"^## .+$", text, re.M)
    assert heads == ["## Profile", "## Rules", "## 1. Collect and order", "## 2. Resolve conflicts before review",
                     "## 3. Run CI once", "## 4. Install the workflow", "## 5. Report and record", "## Never"]


@pytest.mark.parametrize("reason", [
    "Resolve conflict between #<a> and #<b>",
    "Fix red integration CI for land set",
    "Review PR #<n>",
    "Add .github/workflows/devflow-land.yml from the devflow template",
    "chore/land-<yyyymmdd-hhmm>",
    "chore/devflow-land-workflow",
    "land: integration <yyyymmdd-hhmm>",
    "<devflow root>/templates/devflow-land.yml",
    "__MAIN_BRANCH__",
])
def test_exact_strings(text, reason):
    assert reason in text


def test_never_section(text):
    never = text.split("## Never")[1].lower()
    for word in ("approve", "merge", "auto-merge", "force-push", "delete"):
        assert word in never


def test_names_secret_and_setting(text):
    assert "DEVFLOW_AGENT_TOKEN" in text
    assert "Allow auto-merge" in text


def test_no_forbidden_words(text):
    assert not FORBIDDEN.search(text)
    assert not FORBIDDEN.search(SCRIPT.read_text())
