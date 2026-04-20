---
created: 2026-04-20
last_edited: 2026-04-20
---
# Loop Log — onboarding build site

### Iteration 1 — 2026-04-20
- T-001: wizard entry points + header — DONE. Files: apps/discord-bot/src/wizard/{index,cli,index.test}.ts, apps/discord-bot/package.json. Build P, Tests P 2/2. Next: T-002, T-003 (tier 1, parallel).

### Iteration 2 — 2026-04-20
- T-002 + T-003 tier-1 packet — DONE. Subagent dispatch unreliable (reports tool_uses=0 despite narrative; no commits landed on first attempts). Fell back to inline. Files: apps/discord-bot/src/wizard/{paths,returningUser,returningUser.test,sharedToken,sharedToken.test}.ts + index.ts/cli.ts integration. Build P, Tests P 21/21. Next: T-004 (fresh/reconfigure prompt sequence), T-005 (backend config detection).

### Iteration 3 — 2026-04-20
- Tier-1 Codex gate (peer review). Cycle 1 findings: P1 stub exit=0 on fresh/reconfigure (misreads as success), P2 reuse path preserves bad file mode. Fixed: exit=75 stub, chmod-heal to 0600 on reuse. Cycle 2 findings: P1 ignore MUSIC_DL_CONFIG_DIR (diverges from backend), P2 cli.ts shebang points at node (cannot run .ts), P3 no parent-dir fsync after rename. All three fixed: paths.ts honors MUSIC_DL_CONFIG_DIR, shebang → bun, fsyncDir(parent) post-rename. 26/26 wizard tests pass.

### Iteration 4 — 2026-04-20
- T-004 + T-005 tier-2 packet — DONE. T-004: prompts.ts (5 ordered fields + breadcrumbs + reconfigure defaults + token masked display), maskedInput.ts (TTY raw-mode, no-echo), prompts.test.ts (4 cases covering AC1-5 + base-URL override). T-005: bot_onboarding.py (OnboardingState + detect_state with configured > dismissed > needs-setup precedence), test_bot_onboarding.py (8 cases AC1-AC3 + edges). 30/30 wizard tests, 8/8 backend tests. Next tier: T-006 preflight (blocks T-008), T-007 TTY prompt (blocks T-011).
