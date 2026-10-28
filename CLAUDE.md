@AGENTS.md

## Claude Code notes

- `AGENTS.md` is the single source of truth (shared with Codex). Edit project guidance there, not here.
- `api/app.py` is huge: grep for the route/function and read the slice, don't read the whole file.
- Keep `AGENTS.md`, this file and `memory/MEMORY.md` in sync (rules in AGENTS.md, section "Keeping AGENTS.md, CLAUDE.md and MEMORY.md in sync").

## Skills: always-on setup (Claude Code)

Activate once at session start (don't re-invoke every turn; levels persist):

1. `/caveman ultra`: terse prose. Normal prose for code, commits, PRs, security warnings, destructive-action confirmations.
2. `/ponytail:ponytail ultra`: minimal-code ladder (see Working style in AGENTS.md).
3. `/graphify`: graph-first for codebase questions (rules in AGENTS.md). If `graphify` CLI or `graphify-out/graph.json` is missing, say so and use grep; don't run a full semantic build (costs tokens) without asking.
4. `/typesafe:typesafe-ai`: invoke when a task involves semantic judgment; read live docs first. Not for verdict/ratio/auth/billing logic.

### Council for complex tasks

Complex = architecture changes, multi-file or risky edits, security/billing/verdict logic, hard debugging. Trivial edits skip it.

- Use `/codex-claude-council:codex-claude-council` via `council_join`, continuing Codex session `01a0f3c4-b893-73b3-813d-a11d2dc8aa44` (`codex_session_id`), with `workspace` set to this repo's absolute path.
- If Codex hits its session limit, fall back to `/llm-council`.
- Council is advisory: verify its claims against the code before acting.

## Session ritual (Claude Code)

Start: read `docs/HANDOVER.md` and `docs/CONSTRAINTS.md` (they are on branch `docs/readme-accuracy` until PR #88 merges; the "Defend What You Ship" rules are in AGENTS.md); check `git status` and the open PRs before assuming state; activate the skills above.

During: plan first for non-trivial work, small commits, show real command output, ask before removing or disabling anything the user did not ask to change.

End: update `docs/HANDOVER.md` (5-line handoff, newest on top), list unverified assumptions, then run the sync check from AGENTS.md (AGENTS.md / CLAUDE.md / MEMORY.md) and correct or delete stale memory entries. Tell the user what changed in these files.
