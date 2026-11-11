"""The `tld` command line: `tld <group> <command> [args...]`.

Every command hands its remaining arguments, unchanged, to the `main(argv)` of one module of the
package (see docs/reference/cli.md for the table). `tld --help` lists the commands, and
`tld <group> <command> --help` prints the help of that command.
"""
from __future__ import annotations

import importlib
import sys

# (group, command) -> (module, arguments put in front of the user's, one-line help)
COMMANDS: dict[tuple[str, str], tuple[str, tuple[str, ...], str]] = {
    ("profile", "validate"): ("tld.profile.validate", (), "validate a profile against the schema"),
    ("profile", "patch"): ("tld.profile.patch", (), "set-block | diff: text-level edits of the profile"),
    ("profile", "survey"): ("tld.profile.survey", (), "survey a repository and propose profile blocks"),
    ("profile", "survey-docs"): ("tld.profile.survey_docs", (), "the docs part of the survey"),
    ("profile", "survey-signals"): ("tld.profile.survey_signals", (), "the signals part of the survey"),
    ("profile", "survey-proposal"): ("tld.profile.survey_proposal", (), "turn survey signals into a proposal"),
    ("plan", "validate-manifest"): ("tld.plan.manifest", (), "validate a plan's implementation manifest"),
    ("plan", "scope-check"): ("tld.plan.scope", (), "check | disposition | record | section: scope drift"),
    ("roles", "required"): ("tld.roles.dispatch", ("required",), "the agents required at a point, as JSON"),
    ("roles", "verify"): ("tld.roles.dispatch", ("verify",), "check a report against `tld roles required`"),
    ("dod", "exempt"): ("tld.dod.gate", ("--exempt",), "mark this checkout's session exempt from the DoD gate"),
    ("guard", "allow-profile"): ("tld.guard.protect_paths", ("--allow-profile",),
                                 "allow edits to the profile for the next 2 hours"),
    ("guard", "end-allow"): ("tld.guard.protect_paths", ("--end-allow",), "protect the profile again"),
    ("board", "server"): ("tld.board.server", (), "serve the status board"),
    ("board", "client"): ("tld.board.client", (), "health | list | get | set | delete on the board server"),
    ("board", "mcp-stdio"): ("tld.board.mcp_stdio", (), "MCP stdio bridge to the board server"),
    ("board", "stale"): ("tld.board.stale", (), "print the ids of hidden status records"),
    ("board", "build"): ("tld.board.build", (), "build the self-contained board page"),
    ("board", "validate-record"): ("tld.board.record", (), "validate a status record"),
    ("ops", "land-order"): ("tld.ops.land_order", (), "order open pull requests for /land"),
    ("ops", "pick-release"): ("tld.ops.pick_release", (), "pick the newest eligible release tag"),
    ("ops", "upstream-sync"): ("tld.ops.upstream_sync", (), "plan | prepare: sync a fork to an upstream release"),
    ("ops", "repo-admin"): ("tld.ops.repo_admin", (), "validate-policy | whoami | audit | apply"),
    ("ops", "docs-index"): ("tld.ops.docs_index", (), "check | inventory | move: the docs index"),
    ("review", "decisions"): ("tld.review.decisions", (), "build the review decisions page (until WP5)"),
}


def usage() -> str:
    lines = ["usage: tld <group> <command> [args...]", "", "commands:"]
    width = max(len(f"{g} {c}") for g, c in COMMANDS)
    for (group, command), (_, _, text) in COMMANDS.items():
        lines.append(f"  {f'{group} {command}':<{width}}  {text}")
    return "\n".join(lines)


def main(argv: list[str] | None = None) -> int:
    argv = list(sys.argv[1:] if argv is None else argv)
    if not argv or argv[0] in ("-h", "--help", "help"):
        print(usage())
        return 0 if argv else 2
    if len(argv) < 2 or (argv[0], argv[1]) not in COMMANDS:
        print(f"tld: unknown command '{' '.join(argv[:2])}'\n\n{usage()}", file=sys.stderr)
        return 2
    module_name, prefix, _ = COMMANDS[(argv[0], argv[1])]
    module = importlib.import_module(module_name)
    sys.argv = [f"tld {argv[0]} {argv[1]}", *prefix, *argv[2:]]
    code = module.main([*prefix, *argv[2:]])
    return code if isinstance(code, int) else 0


if __name__ == "__main__":
    sys.exit(main())
