## Planzilla

This repo plans its work with Planzilla. Plans live in `.plan/`.

- Never read or edit plan state by hand. Use only the CLI `.planzilla/plz`; `.planzilla/plz --help` lists the commands.
- To plan a task, follow the skill `plz-new-plan`: `.agents/skills/plz-new-plan/SKILL.md`.
- To run a plan, follow the skill `plz-run-plan`: `.agents/skills/plz-run-plan/SKILL.md`.
- The same skills are in `.claude/skills/`.
- Subagents follow the role prompt for their job:
  - `.planzilla/roles/planner.md`
  - `.planzilla/roles/executor.md`
  - `.planzilla/roles/verifier.md`
  - `.planzilla/roles/visual.md`
- `.planzilla/` is vendored. Never edit it; upgrade by re-running `planzilla install`.
