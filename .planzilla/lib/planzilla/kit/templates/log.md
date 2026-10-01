# N02 log

## brief · YYYY-MM-DD
plan: BRIEFED

## try 1 · YYYY-MM-DD
exec: DONE · tests: 12 passed
- <what changed>
- <a choice the brief didn't settle>
check: PASS 1/1
verify: FAIL C1
- C1 path:line - problem - expected

## try 2 · YYYY-MM-DD
exec: DONE · tests: 13 passed
- <how the finding was fixed>
check: PASS 1/1
verify: PASS

<!--
Format rules (FORMAT §7; this file shows the shape, never copy it)
- L: log/<id>.md, created by the CLI with `# <id> log`. S/M: entries under `## Log`, with headings
  `### <id> <key> · <date>`.
- Written only by the CLI: agents call `planzilla log <plan> <id> <kind> <text> [-b BULLET]...`; `check` and
  `resume` add their own lines. Append only; nobody edits an entry by hand.
- Heading keys: `brief`, `try <n>`, `replan <r>`, added by the CLI when the key changes.
- Kinds: exec (DONE · tests line, or BLOCKED · reason), check, verify (PASS or FAIL C2,C4, one bullet per
  finding with its criterion id), plan (BRIEFED, REPLANNED[ +N18], ASK D7), human, resume, note.
- Read by the planner on a replan of this node, by the next executor only through `planzilla brief` (the
  findings), and by humans; never by verifiers.
-->
