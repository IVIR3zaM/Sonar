# Planzilla config (FORMAT §8). A missing key takes its default; a plan's header wins over this file.
# Keys with an empty default are commented out: uncomment and fill them.
# verify: <one shell command: the full check for the repo>
# verify_fast: <command executors run before replying; default: verify>
commit: per-node
push: none
retention: keep
# visual_recipe: <one line: how to start the app and which URL to open>
models: planner=opus, exec=sonnet, verify=sonnet
providers: claude
harness: claude-code
# preauthorized: <action agents may take without asking>; <another action>
always_review: no
# commit_trailer: <text; \n separates lines>

# Format rules (delete these lines if you like)
# - Lines are blank, `#` comments or `key: value` with a key above; any other line, an unknown key or a
#   repeated key is a parse error naming this file and line.
# - commit: per-node or none. push: per-node or none. retention: keep, prune-logs, delete or branch-only.
#   always_review: yes or no. models: any subset of planner=, exec=, verify=;
#   models use [<route>::]<name>[@<effort>]. opus/sonnet/haiku are portable intent; exact IDs, effort and
#   route qualifiers are independent pins. `copilot::claude-sonnet-5@high` pins delivery, ID and effort.
#   Bare claude/codex/copilot selects an evidenced CLI default.
# - providers: a comma-separated subset of claude, codex, copilot, with no repeats; an allowed delivery
#   list, not proof of login, model availability or quota. Model tokens must fit the effective providers.
#   harness: claude-code, codex, copilot records the configured client; actual callable tools govern dispatch.
# - plan providers/models override repository defaults; optional plan harnesses restricts actual coordinator
#   and every role delivery before defaults, aliases or auth probes. Intersect permissions, never widen.
#   Omitted plan harnesses preserves legacy permissions. harnesses is a plan header, not a config key.
#   Configured/actual mismatch needs capability reconciliation, not automatic config rewriting.
# - Engineering rules belong in AGENTS.md/CLAUDE.md, not here. Executors and verifiers never read this file.
