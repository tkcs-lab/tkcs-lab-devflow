---
description: Publish the devflow status board page once, or prune the stale records from it
argument-hint: "[empty to publish the board | prune]"
model: sonnet
---

You publish and tidy the devflow status board: one private `Artifact` page that shows the status
records of every project (`/implement` runs and the scheduled maintenance commands). The page reads
the `projects` collection live, so it is published once and then left alone.

$ARGUMENTS

## Profile

Load the `project-profile` skill and follow its "Loading the profile" section. If it reports an
error, show the message verbatim and stop; never substitute a value of your own for a missing key.
Skill names: the toolkit's skills carry a plugin prefix (`devflow:project-profile`,
`devflow:pr-steward`, `stack-python:stack-python`). Use whichever form the skill list shows.

The board URL comes from the profile key `status.board_url` when set, else from the environment
variable `DEVFLOW_BOARD_URL`. The scripts named below sit next to the project-profile skill's
scripts (see its "Find the toolkit scripts" step); call them from there.

## `/board` (no argument)

1. If a board URL is already set, say so and print it. Stop unless the user asked for a new board.
2. Build the page: `build_board.py --title 'Devflow Board' --out <a file in your scratchpad directory, or /tmp>/board.html`.
3. Publish that file with the `Artifact` tool and `capabilities: {db: {}}` (no other capability, so
   viewers never see a consent dialog). Give it the icon `board`.
4. Print the artifact URL. Tell the owner to store it once as the environment variable
   `DEVFLOW_BOARD_URL` (it is not a secret), or to set `status.board_url` in a project's profile to
   override it for that project. Do not store it anywhere yourself.

The page has no buttons that write. To change the page later, run `/board` again with the same
file path and the stored URL so the URL stays the same.

## `/board prune`

Needs a board URL (see Profile); without one, stop and say so.

1. List the `projects` collection of that artifact with `ArtifactData` `list` (follow pages until
   none are left) and save the documents as a JSON list of `{"id", "data"}`.
2. Run `board_stale.py FILE`. It prints one document id per line for every record the board hides
   (no update for more than 7 days, or finished earlier), never one with `needs_you: true`.
3. If it prints nothing, say "Nothing to prune" and stop.
4. Show each id with its `updated_at`, then ask exactly one question: delete these n records? yes
   or no.
5. On yes, delete them with one `ArtifactData` `batch` of `delete` operations, one per id. On no,
   delete nothing.

Nothing else is ever deleted: not a record that is not on that list, not the page, not a record
because it looks old.
