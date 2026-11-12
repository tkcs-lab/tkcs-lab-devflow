"""The `tld` command line: `tld <group> <command> [args...]`, and `tld migrate`.

Every command hands its remaining arguments, unchanged, to the `main(argv)` of one module of the
package (see docs/reference/cli.md for the table). `tld --help` lists the commands, and
`tld <group> <command> --help` prints the help of that command.
"""
from __future__ import annotations

import importlib
import sys

import tld

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
    ("plan", "deviations"): ("tld.plan.deviations", (), "init | add | check: the deviations log next to a plan"),
    ("plan", "check-url"): ("tld.plan.phases", ("check-url",), "accept a plan URL (<plan_dir>/<n>/plan.md on main or its feature branch; plan/* deprecated)"),
    ("plan", "check-commands"): ("tld.plan.phases", ("check-commands",), "which verify_after_merge commands the profile trusts"),
    ("plan", "branch-name"): ("tld.plan.phases", ("branch-name",), "print a plan, review, feature, phase or fix branch"),
    ("plan", "phase-status"): ("tld.plan.phases", ("phase-status",), "done, gated, ready and waiting phases, as JSON"),
    ("plan", "active-run"): ("tld.plan.active", (), "is another run of make-plan or implement already going"),
    ("roles", "required"): ("tld.roles.dispatch", ("required",), "the roles required at a point, as JSON"),
    ("roles", "verify"): ("tld.roles.dispatch", ("verify",), "check a report against `tld roles required`"),
    ("dod", "exempt"): ("tld.dod.gate", ("--exempt",), "mark this checkout's session exempt from the DoD gate"),
    ("guard", "allow-profile"): ("tld.guard.protect_paths", ("--allow-profile",),
                                 "allow edits to the profile for the next 2 hours"),
    ("guard", "allow-workflow-install"): ("tld.guard.protect_paths", ("--allow-workflow-install",),
                                          "allow writing tld-land.yml / tld-release.yml for the next 15 minutes"),
    ("guard", "allow-git-ops"): ("tld.guard.protect_paths", ("--allow-git-ops",),
                                 "allow a git-ops dispatch with dry_run false for the next 10 minutes"),
    ("guard", "allow-plan"): ("tld.guard.protect_paths", ("--allow-plan",),
                              "let every session in this checkout edit files for 8 hours (a plan-gate marker for /implement workers)"),
    ("guard", "end-allow"): ("tld.guard.protect_paths", ("--end-allow",),
                             "end every allow-* marker (profile, workflow install, git-ops)"),
    ("board", "server"): ("tld.board.server", (), "serve the status board"),
    ("board", "client"): ("tld.board.client", (), "health | list | get | set | delete of status records"),
    ("board", "mcp-stdio"): ("tld.board.mcp_stdio", (), "MCP stdio bridge to the board server"),
    ("board", "stale"): ("tld.board.stale", (), "print the ids of hidden status records"),
    ("board", "resolve"): ("tld.board.resolve", (), "clear needs_you of a record whose pull requests are all merged or closed"),
    ("board", "build"): ("tld.board.build", (), "build the self-contained board page"),
    ("board", "validate-record"): ("tld.board.record", (), "validate a status record"),
    ("board", "project-slug"): ("tld.board.record", ("project-slug",), "the project slug of owner/name"),
    ("board", "validate-ask"): ("tld.board.ask", (), "validate an ask before posting it"),
    ("board", "ask"): ("tld.board.inbox", ("ask",), "post an ask to the owner's inbox; prints its id"),
    ("board", "answers"): ("tld.board.inbox", ("answers",), "print an ask's answers (or read them from an issue)"),
    ("board", "cancel"): ("tld.board.inbox", ("cancel",), "cancel an open ask"),
    ("board", "ask-text"): ("tld.board.inbox", ("text",), "the ask as a chat message for an attended session"),
    ("research", "check-prompt"): ("tld.research", ("check-prompt",), "check a research prompt before it is posted"),
    ("research", "report"): ("tld.research", ("report",), "the marked research report from the owner's reply"),
    ("ops", "land-order"): ("tld.ops.land_order", (), "order open pull requests for /land"),
    ("ops", "pick-release"): ("tld.ops.pick_release", (), "pick the newest eligible release tag"),
    ("ops", "upstream-sync"): ("tld.ops.upstream_sync", (), "plan | prepare: sync a fork to an upstream release"),
    ("ops", "repo-admin"): ("tld.ops.repo_admin", (), "validate-policy | whoami | audit | apply"),
    ("ops", "docs-index"): ("tld.ops.docs_index", (), "check | inventory | move: the docs index"),
    ("version", "show"): ("tld.cli", ("--version",), "print the running tld version"),
}

# One-word commands: `tld <command> [args...]`.
TOP: dict[str, tuple[str, str]] = {
    "migrate": ("tld.ops.migrate", "move a claude-toolkit (devflow) repository to tld; a dry run unless --write"),
}


# Commands whose module has no argparse `--help` of its own (or acts on any argument): `tld <group> <command>
# --help` prints the one-line help and the module's docstring instead of running it.
DOC_HELP = {("profile", "survey"), ("profile", "survey-docs"), ("profile", "survey-signals"),
            ("profile", "survey-proposal"), ("dod", "exempt"), ("guard", "allow-profile"),
            ("guard", "allow-workflow-install"), ("guard", "allow-git-ops"), ("guard", "allow-plan"),
            ("guard", "end-allow"),
            ("board", "mcp-stdio"), ("version", "show")}


def usage() -> str:
    lines = ["usage: tld <group> <command> [args...] | tld migrate [ROOT] [--write]", "", "commands:"]
    width = max(len(f"{g} {c}") for g, c in COMMANDS)
    for (group, command), (_, _, text) in COMMANDS.items():
        lines.append(f"  {f'{group} {command}':<{width}}  {text}")
    for command, (_, text) in TOP.items():
        lines.append(f"  {command:<{width}}  {text}")
    return "\n".join(lines)


def main(argv: list[str] | None = None) -> int:
    argv = list(sys.argv[1:] if argv is None else argv)
    if argv[:1] == ["--version"] or argv[:2] == ["version", "show"]:
        print(f"tld {tld.__version__}")
        return 0
    if not argv or argv[0] in ("-h", "--help", "help"):
        print(usage())
        return 0 if argv else 2
    if argv[0] in TOP:
        module = importlib.import_module(TOP[argv[0]][0])
        sys.argv = [f"tld {argv[0]}", *argv[1:]]
        code = module.main(argv[1:])
        return code if isinstance(code, int) else 0
    if len(argv) < 2 or (argv[0], argv[1]) not in COMMANDS:
        print(f"tld: unknown command '{' '.join(argv[:2])}'\n\n{usage()}", file=sys.stderr)
        return 2
    module_name, prefix, text = COMMANDS[(argv[0], argv[1])]
    module = importlib.import_module(module_name)
    if (argv[0], argv[1]) in DOC_HELP and any(a in ("-h", "--help") for a in argv[2:]):
        print(f"usage: tld {argv[0]} {argv[1]} ...  ({text})\n\n{(module.__doc__ or '').strip()}")
        return 0
    sys.argv = [f"tld {argv[0]} {argv[1]}", *prefix, *argv[2:]]
    code = module.main([*prefix, *argv[2:]])
    return code if isinstance(code, int) else 0


if __name__ == "__main__":
    sys.exit(main())
