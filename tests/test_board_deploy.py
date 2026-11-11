"""The Dockerfile and docs/board-server.md match what the server needs and what the design promises."""
from __future__ import annotations

import ast
import json
import re
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
DEVFLOW = ROOT / "plugins" / "devflow"
SCRIPTS = DEVFLOW / "scripts"
DOCKERFILE = DEVFLOW / "board" / "Dockerfile"
DOC = ROOT / "docs" / "board-server.md"

sys.path.insert(0, str(SCRIPTS))
import validate_status_record  # noqa: E402

SECTIONS = [
    "What it is", "Run it locally", "Configuration", "Docker", "TLS and a reverse proxy",
    "Connect Claude Code sessions", "HTTP API", "MCP tools", "Security notes", "Backup and restore",
    "Troubleshooting", "Replacing the artifact board",
]


def _copied() -> set[str]:
    names: set[str] = set()
    for line in DOCKERFILE.read_text().splitlines():
        if line.startswith("COPY "):
            names.update(Path(p).name for p in line.split()[1:-1])
    return names


def _imports(path: Path) -> set[str]:
    found: set[str] = set()
    for node in ast.walk(ast.parse(path.read_text())):
        if isinstance(node, ast.Import):
            found.update(a.name.split(".")[0] for a in node.names)
        elif isinstance(node, ast.ImportFrom) and node.module and node.level == 0:
            found.add(node.module.split(".")[0])
    return found


def test_dockerfile_basics() -> None:
    text = DOCKERFILE.read_text()
    assert re.search(r"^FROM python:", text, re.M)
    users = re.findall(r"^USER (\S+)", text, re.M)
    assert users and users[-1] not in ("root", "0")
    assert re.search(r"^EXPOSE 8787$", text, re.M)
    assert re.search(r'^VOLUME \["/data"\]$', text, re.M)
    assert re.search(r"^HEALTHCHECK ", text, re.M)
    cmd = [line for line in text.splitlines() if line.startswith("CMD ")]
    assert len(cmd) == 1 and "board_server.py" in cmd[0]


def test_dockerfile_copies_every_sibling_module() -> None:
    copied = _copied()
    seen: set[str] = set()
    todo = ["board_server"]
    while todo:
        name = todo.pop()
        if name in seen:
            continue
        seen.add(name)
        path = SCRIPTS / f"{name}.py"
        assert f"{name}.py" in copied, f"{name}.py is not copied by the Dockerfile"
        todo.extend(m for m in _imports(path) if (SCRIPTS / f"{m}.py").exists())
    assert {"board_store", "board_mcp", "build_board", "validate_status_record"} <= seen


def test_dockerfile_copies_the_page_files() -> None:
    copied = _copied()
    assert {"board.html", "rules.js"} <= copied
    assert (DEVFLOW / "board" / "board.html").exists() and (DEVFLOW / "board" / "rules.js").exists()


def test_doc_has_the_sections_in_order() -> None:
    headings = re.findall(r"^## (.+)$", DOC.read_text(), re.M)
    assert headings == SECTIONS


def test_doc_names_every_variable_and_route_and_tool() -> None:
    text = DOC.read_text()
    for needle in (
        "DEVFLOW_BOARD_TOKEN", "DEVFLOW_BOARD_READ_TOKEN", "DEVFLOW_BOARD_URL", "DEVFLOW_BOARD_DB",
        "DEVFLOW_BOARD_ALLOW_HTTP", "--host", "--port", "--db", "--title", "--allow-origin",
        "/healthz", "/api/records", "/api/records/<id>", "/mcp", "/index.html",
        "board_get", "board_list", "board_set", "board_delete",
        "reverse_proxy", "proxy_pass", "client_max_body_size 1m", "unknown key 'status'",
        'sqlite3 board.sqlite3 ".backup',
    ):
        assert needle in text, needle


def test_doc_sample_record_is_valid() -> None:
    m = re.search(r"```json\n(.*?)\n```", DOC.read_text(), re.S)
    assert m, "no json block"
    rec = json.loads(m.group(1))
    assert rec["project"] == "example-project"
    assert validate_status_record.validate(rec, "example-project") == []


def test_doc_has_no_token_looking_value() -> None:
    text = DOC.read_text()
    assert not re.search(r"[A-Za-z0-9_-]{32,}", text)
    assert "mcp__plugin" not in text
