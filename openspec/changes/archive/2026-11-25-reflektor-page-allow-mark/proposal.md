## Why

The Reflektor HTML change report was refused whenever the branch quoted the secret-scan allow mark anywhere in the page, which any change that touches or documents secret scanning does. The refusal was noted only in passing, so the pull request reader had no sign that the page was missing.

## What Changes

- The page check scans every line of the original page and its data for credentials, ignoring the allow mark, and then replaces each literal allow mark with a visible placeholder that cannot form the mark again. A page whose data still decodes to the mark (an escaped form) is refused.
- A new command `tld roles page-note` prints the one fixed line that says the HTML page was not stored and why.
- A new command `tld roles change-report` prints the change-report block with that note as its first line, so the note is placed by the command and the role's own text cannot forge or move it. `tld roles section` is not changed.

## Capabilities

### New Capabilities

None.

### Modified Capabilities

- `role-dispatch`: the page hardening and send requirement is modified; two requirements (the page note and the change report with a page note) are added.

## Impact

`src/tld/guard/secret_scan.py` (an option for the scan, default unchanged), `src/tld/roles/reflektor.py`, a new `src/tld/roles/page_note.py`, `src/tld/cli.py`, `roles/reflektor.md`, `playbooks/dod.md`, `playbooks/implement.md`, `docs/guides/reflektor.md`. The board and its page rule are unchanged.
