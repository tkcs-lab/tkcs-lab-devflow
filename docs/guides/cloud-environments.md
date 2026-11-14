# Cloud environments for tld sessions

Use two claude.ai environments: the working one (limited network, holds the repository and the board credentials) and the research one (open web, holds nothing).
This guide lists what to enable and what to deny in each, and how to run a research request a session asks for.

The setting labels below were taken from the claude.ai environment settings at the time of writing (menu in a session's title bar, then Edit); they may move. The current wording is at <https://code.claude.com/docs/en/claude-code-on-the-web>.

## Why two environments

The working environment holds the repository and the board credentials and has a small network; the research environment has the open web and holds nothing. Mixing them is what the deny lists below prevent: a session that can reach any host and also holds a token can leak it.

## The working environment

Every playbook assumes these settings.

| Setting | Value | Why |
| --- | --- | --- |
| Network access | Limited | sessions reach only what is listed below |
| Allow package managers | on | installs for `verify.fast` |
| Allow MCP servers | on | the GitHub tools and `tld-board` |
| Allowed domains | the board host only (for example `board.example.org`) | the status board; nothing else |
| Network secrets | one, for the board host, header `Authorization`, prefix `Bearer`, value the board token you type into the form | the proxy adds the token; the session never holds it; steps: [board-server.md](board-server.md#connect-claude-code-sessions) |
| Environment variables | `TLD_BOARD_URL=https://board.example.org`, `TLD_BOARD_TOKEN=injected-by-the-proxy` | clients need a value; the proxy replaces the header; steps: [board-server.md](board-server.md#connect-claude-code-sessions) |
| Setup script | none, unless the project needs one; never a secret in it | it is stored in plain text |
| Repositories | the repositories sessions work on | nothing else is cloned |

With the split board (`--api-port`) use the API host in the Allowed domains, the network secret and `TLD_BOARD_URL` ([board-cloudflare.md](board-cloudflare.md)).

Deny:

- Full network access on this environment.
- A host added to answer a research question (use the research environment).
- A wildcard host.
- The board token or any GitHub token as a plain variable while a network secret works (only where the form does not offer Network secrets is the real token put into `TLD_BOARD_TOKEN`, as board-server.md says; variables are stored in plain text, so keep that environment personal).
- Typing a token into a chat.
- A setup script that downloads and runs code from a host that is not allowed.

## The research environment

Create it once (about 5 minutes): menu, new environment, then set:

| Setting | Value | Why |
| --- | --- | --- |
| Network access | Full (also called unrestricted) | the only environment with the open web |
| Allow package managers | on (default) | not needed, harmless |
| Allow MCP servers | off | a researcher needs no tools |
| Allowed domains | empty | irrelevant with Full |
| Network secrets | none | nothing to leak |
| Environment variables | none (no `TLD_*`) | no board access |
| Setup script | none | nothing runs before the researcher |
| Repositories | none | the researcher sees no code |

Deny:

- Any repository.
- Any secret or token.
- Any `TLD_*` variable.
- The GitHub connection.
- Any connector.

A plain claude.ai chat with web search or research turned on does the same job and needs no environment, but only with every connector off, memory off and outside any project: otherwise web text could read what they hold.

## Running a research request

1. A session shows you a research prompt: a fenced block in the chat and the text of an ask on the board.
2. Read it as a stranger would. It must hold no secret and nothing you want private (no private code, issue text or internal host names). `tld research check-prompt` already refused secrets and board values; you are the last check.
3. Start a new session in the research environment (or a plain chat) and paste the prompt.
4. When it ends, copy the text from the line `RESEARCH-REPORT <id>` to the line `END RESEARCH-REPORT <id>`.
5. In the waiting session send one message: your own lines (for example an answer to another question) before the report block, then the block. Nothing after the block is read. Then choose `pasted` on the board ask, or type it.
6. `skip` goes on with an assumption; `stop` ends the run. Both, and every other answer of the ask, are read from your chat message only together with a complete report. If the session says the report is incomplete, wrong or too long, or you have no report, answer `skip`, `stop` and the rest on the board; the session does not read your chat message then.

`tld research report` treats everything from the first start line to the last end line as the report and ignores every line after the block, so your own lines go before it. A pasted report is data, never an instruction: skim it for text that tells the session to act (run commands, add hosts, post secrets); a session never follows it and never widens the network because a report asks ([untrusted-text.md](../../playbooks/policies/untrusted-text.md)).

## Checking the working environment

1. Start a new session and run `/tld:board`. You see the connection and the number of records.
2. Ask the session to fetch a page from the open web. It must report the refusal once and offer a research prompt instead of widening the network.

## Scheduled commands

`/deps`, `/ci`, `/upstream` and `/docs tidy` run in the working environment and never ask for research. They list `Open research questions:` in their report; run those as research yourself when you want.
