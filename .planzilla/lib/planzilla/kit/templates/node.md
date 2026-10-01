# N02 <short title>
Do: <2-4 sentences: what changes and why. No backstory, no history of earlier tries.>
Context: <the Decisions this node needs, restated in a line each; spec sections and `path:line` to read>
Read: <backticked paths the executor reads>
Write: `<path>`, `<dir>/**`
Test first: <the failing test's behavior, or `-`>
Done when:
- C1 [review] <falsifiable statement about the tree, naming the file or behavior>
- C2 [cmd] `<verify_fast command; tier S: the full verify command>`

<!--
Format rules (FORMAT §6; delete this comment in a real brief)
- L: nodes/<id>.md, first line `# <id> <title>`. S/M: a `## <id> <title>` section of the plan file.
- At most 40 lines with the heading (L1). Fields at column 0 in this order: Do, Context, Read, Write, Test first,
  Done when (last). Do and Done when required; exec nodes need Write; check and gate nodes have no Write.
- Write: backticked repo-relative paths joined by `, `; `*` within a segment, `**` a whole segment, trailing `/`.
- Self-contained: the executor reads only this brief (via `planzilla brief`); cite path:line, never paste code.
- Criteria `- C<n> [tag] text`, continuation lines indented 2+ spaces. Tags: cmd (starts with one backticked
  command), review, smoke (command and expected observation), visual (page/state and what must be seen), human
  (only when nothing else can check it). Each falsifiable; together they cover the whole Do (L4).
- The current brief only: a replan rewrites it clean; history lives in the log (L1). L-tier briefs, check nodes
  included, are written just in time, when the node is ready (L2); gate briefs come with the outline.
-->
