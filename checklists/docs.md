# Checklist: documentation

Treat every sentence that states a fact as a claim to check against the code. A project's own style
guide (in its must-read docs) adds to this list and wins where it is more specific.

## What counts as documentation

README files, `docs/`, contributor, security and support docs, the changelog, API and configuration
references, CLI help text, examples and sample projects, in-code documentation of public
interfaces, error messages that tell a user what to do, and the website.

**A website is in the repository** when any of these is: a static-site generator config
(`mkdocs.yml`, `docusaurus.config.*`, `astro.config.*`, `hugo.toml` or a `config.*` beside
`content/`, Jekyll `_config.yml`, `.vitepress/`, `book.toml`, `conf.py` for Sphinx), a `site/`,
`website/`, `www/` or `pages/` directory with HTML or a framework app, a `CNAME`, or a workflow that
deploys pages. Say which signal you found.

## Checks

1. **Accuracy**: every command, flag, option, default value, environment variable, configuration
   key, file path, version number, output sample and API signature matches the code at the reviewed
   commit. Quote the sentence and the code that contradicts it.
2. **Validity**: run the documented install, build, quick-start and test commands that are safe in
   the container; examples compile or run; relative links and anchors resolve; external links
   answer (say which you could not reach rather than calling them broken); images exist.
3. **Completeness**: every user-visible feature, CLI command, configuration key and environment
   variable is documented; setup prerequisites, upgrade and migration notes, troubleshooting for
   the errors users hit, how to report a vulnerability, how to contribute and run the tests; the
   changelog covers the user-visible changes since the last release.
4. **Consistency**: the same fact stated in two places agrees (README versus website versus help
   text); terms are used one way throughout; versions match the package metadata.
5. **Clarity**: each document says who it is for and what they can do after reading it; tasks
   come before background; steps are numbered, one action each, with what the reader should see;
   jargon is defined at first use; no ambiguous "it" or "this".
6. **Readability**: headings that say what is under them, short paragraphs, sentences a reader
   can follow at first pass, code in code blocks with the language marked. Raise readability only
   where it gets in the way of understanding, and give the rewrite, not just the complaint.
7. **Staleness**: references to removed features, old names, old screenshots, TODOs in published
   docs, dates and "coming soon" that have passed.
8. **Docs index (only when the profile has `docs.index`)**: run `tld ops docs-index check --profile .tld/toolkit.yaml`. Every error is a blocking finding (a doc the change adds, moves or deletes without its row, a broken link, an entry file over 60 lines); a warning is non-blocking. Report index errors; never fix the index, not even in `edit` mode: only the retirement phase, docs init and docs tidy edit it (C3, [../playbooks/policies/docs.md](../playbooks/policies/docs.md)).

## Website checks, when there is one

1. It builds with the documented command, without warnings about missing pages or broken links.
2. Navigation reaches every page; no orphan pages; no page that exists only in the repository docs
   and is missing from the site, or the other way round, unless that is intended.
3. Content duplicated from the repository docs has not drifted.
4. Basics a visitor relies on: page titles and descriptions, a working search if it advertises one,
   alt text on images, a heading order that makes sense, readable contrast in both themes if it has
   them.
5. Security, together with [security.md](security.md): third-party scripts are pinned or have integrity
   hashes, forms post where they say, deployment config in the repository sets sensible headers,
   no secrets or internal URLs in the built output.

## Output

One finding per problem, in the format the calling playbook asks for, with the quoted text, where it
is, and the corrected text or the missing section's outline as the fix. End with a short verdict on
documentation health and on the website, and what you could not check.
