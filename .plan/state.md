# Sonar plan state
Milestone: M0 Skeleton
Replans: 0/2
## Tasks (M0)
- T1 [haiku] uv project, ruff/pytest config: todo
- T2 [sonnet] migration runner src/sonar/db.py: todo (deps T1)
- T3 [sonnet] create_app + templates: todo (deps T2)
- T4 [haiku] `uv run sonar` on 127.0.0.1: todo (deps T3)
- T5 [haiku] CLAUDE.md: todo (deps T4)
- T6 [haiku] ruff format/fix, suite green: todo (deps T4)
## Done
- setup: SPEC.md, samples/ gitignored, git init, .claude/agents/
## Decisions
- htmx via pinned CDN script tag (vendor later only if offline need)
- no real migration in M0; first table arrives in M1
## Notes
- .claude/agents/* load only at session start; this session used general-purpose agents told to follow them
## Open questions
- none
