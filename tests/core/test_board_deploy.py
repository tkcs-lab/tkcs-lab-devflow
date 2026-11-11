"""The Dockerfile and docs/guides/board-server.md match what the server needs and what the design promises."""
from __future__ import annotations

import ast
import json
import re

from conftest import ROOT
from tld.board import record as validate_status_record

DOCKERFILE = ROOT / "deploy" / "board" / "Dockerfile"
DOC = ROOT / "docs" / "guides" / "board-server.md"

SECTIONS = [
    "What it is", "Run it locally", "Configuration", "Docker", "TLS and a reverse proxy",
    "Connect Claude Code sessions", "HTTP API", "MCP tools", "Security notes", "Backup and restore",
    "Troubleshooting", "Replacing the artifact board",
]


def _copied() -> set[str]:
    """Repository paths the Dockerfile copies (the build context is the repository root)."""
    paths: set[str] = set()
    for line in DOCKERFILE.read_text().splitlines():
        if line.startswith("COPY "):
            paths.update(line.split()[1:-1])
    return paths


def _imports(path) -> set[str]:
    """The tld modules a module imports, as dotted names."""
    found: set[str] = set()
    for node in ast.walk(ast.parse(path.read_text())):
        if isinstance(node, ast.Import):
            found.update(a.name for a in node.names if a.name.startswith("tld."))
        elif isinstance(node, ast.ImportFrom) and node.module and node.level == 0 and node.module.startswith("tld"):
            for a in node.names:
                sub = f"{node.module}.{a.name}"
                found.add(sub if (ROOT / "src" / (sub.replace(".", "/") + ".py")).exists() else node.module)
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
    assert len(cmd) == 1 and '"tld.board.server"' in cmd[0]
    assert "PYTHONPATH=/app/src" in text


def test_dockerfile_copies_every_module_the_server_imports() -> None:
    copied = _copied()
    seen: set[str] = set()
    todo = ["tld.board.server"]
    while todo:
        name = todo.pop()
        if name in seen:
            continue
        seen.add(name)
        rel = "src/" + name.replace(".", "/") + ".py"
        assert rel in copied, f"{rel} is not copied by the Dockerfile"
        parts = name.split(".")
        for i in range(1, len(parts)):
            init = "src/" + "/".join(parts[:i]) + "/__init__.py"
            assert init in copied, f"{init} is not copied by the Dockerfile"
        todo.extend(_imports(ROOT / rel))
    assert {"tld.board.store", "tld.board.mcp", "tld.board.build", "tld.board.record"} <= seen


def test_dockerfile_copies_the_page_files() -> None:
    copied = _copied()
    assert {"src/tld/board/web/board.html", "src/tld/board/web/rules.js"} <= copied
    for path in copied:
        assert (ROOT / path).is_file(), path


def test_doc_has_the_sections_in_order() -> None:
    headings = re.findall(r"^## (.+)$", DOC.read_text(), re.M)
    assert headings == SECTIONS


def test_doc_names_every_variable_and_route_and_tool() -> None:
    text = DOC.read_text()
    for needle in (
        "TLD_BOARD_TOKEN", "TLD_BOARD_READ_TOKEN", "TLD_BOARD_URL", "TLD_BOARD_DB",
        "TLD_BOARD_ALLOW_HTTP", "--host", "--port", "--db", "--title", "--allow-origin",
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
