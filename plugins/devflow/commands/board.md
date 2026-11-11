---
description: Check the devflow status board connection, or prune the stale records from it
argument-hint: "[empty to check the board | prune]"
model: sonnet
---

You check and tidy the devflow status board: a server you host yourself that holds the status
records of every project (`/implement` runs and the scheduled maintenance commands). This command
publishes nothing; the board is reached with `DEVFLOW_BOARD_URL` and `DEVFLOW_BOARD_TOKEN`.

$ARGUMENTS

## Profile

Use the `project-profile` skill only for its 'Find the toolkit scripts' step; if it reports an error, show the message verbatim and stop; never substitute a path of your own.
Skill names: the toolkit's skills carry a plugin prefix (`devflow:project-profile`,
`devflow:pr-steward`, `stack-python:stack-python`). Use whichever form the skill list shows.

The scripts named below (`board_client.py`, `board_stale.py`) sit next to the project-profile
skill's scripts; call them from there.

## `/board` (no argument)

1. Run `board_client.py health`. Exit 3: print the setup text and stop. The setup text: set the two
   environment variables `DEVFLOW_BOARD_URL` (the server's base URL, not a secret) and
   `DEVFLOW_BOARD_TOKEN` (the write token; type it into the environment settings yourself, never in
   chat), allow the host in the environment's network settings, and host the server as described in
   `docs/guides/board-server.md` in the claude-toolkit repository. Exit 1: show its stderr and stop.
2. Run `board_client.py list`. If it exits 3 (the URL is set but the token is not), print
   "DEVFLOW_BOARD_URL is set but DEVFLOW_BOARD_TOKEN is not" and stop.
3. Report: which write path this session has (the `board_*` tools of the `devflow-board` MCP server,
   or `board_client.py` only), the number of records and how many need the owner (`needs_you` true;
   count them from `board_list` or from the output of `board_client.py list`), and the board URL
   (the value of `DEVFLOW_BOARD_URL`; never print the token).

## `/board prune`

Needs a working board (steps 1 and 2 above succeed); without one, stop and say so.

1. Get all records with `board_list` or `board_client.py list`. Save the value of `records` (the
   array of `{"id", "version", "data"}`, not the whole answer) as a JSON file in your scratchpad
   directory, or `/tmp`.
2. Run `board_stale.py FILE`. It prints one document id per line for every record the board hides
   (no update for more than 7 days, or finished earlier), never one with `needs_you: true`.
3. If it prints nothing, say "Nothing to prune" and stop.
4. Show each id with its `updated_at`, then ask exactly one question: delete these n records? yes
   or no.
5. On yes, delete them with `board_delete` (at most 50 ids per call) or
   `board_client.py delete ID...`. On no, delete nothing.

Nothing else is ever deleted: not a record that is not on that list, not a record because it looks
old.
