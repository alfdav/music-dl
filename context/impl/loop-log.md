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
- T-004 + T-005 tier-2 packet — DONE. T-004: prompts.ts + maskedInput.ts + 4 tests (AC1-5 + base-URL). T-005: bot_onboarding.py + 8 tests. 30/30 wizard, 8/8 backend.

### Iteration 5 — 2026-04-20
- Tier-2 Codex gate cycle 1. P1 two readers on same stdin duplicate consumption. P2 null → "" instead of cancel. P3 masked writes to process.stdout not injected stdout. Fixed all: makeLineReader → LineReaderHandle with pause/resume; masked reader shares handle on non-TTY + pauses shared on TTY; PromptCancelError propagates through runWizard → exitCode 130. 32/32.

### Iteration 6 — 2026-04-20
- Tier-2 Codex cycle 2. P2 only finding: Ctrl+D (\u0004) in raw mode hangs prompt. Fixed. 32/32.

### Iteration 7 — 2026-04-20
- T-006 preflight + T-007 backend TTY prompt. T-006: preflight.ts (10 checks DI-injectable) + 15 tests covering every R6 AC + secret-leak regression. T-007: bot_first_run.py (should_prompt, classify_answer, ask_user, decide_startup_action) + 28 tests (R2 AC1-4, R3 AC1-4, Y/n/never mapping). 47/47 wizard, 36/36 backend.

### Iteration 8 — 2026-04-20
- Tier 4 packet T-008/009/010/012 + T-011. T-008 envFile.ts atomic 0600 + 7 tests. T-012 commit.ts two-file atomic with token-first rename + rollback + 3 tests. T-009 retry-single-field loop in runWizard + 3 integration tests. T-010 integration.test.ts full-pipeline no-secret-leak + generic-phrasing (token-rejected). T-011 write_dismissal_flag. 65/65 wizard tests.

### Iteration 9 — 2026-04-20
- Tier 5 T-013 + T-014. dispatch_wizard (bun → node --import tsx fallback, inherited stdio, never aborts server), run_first_run_flow (R4+R5 orchestrator), --setup-bot Typer flag wired into gui command. 16 new backend tests. 44/44 backend. All 14 tasks DONE.

### Iteration 10 — 2026-04-20 (kit revision)
- User feedback: `music-dl gui` terminal-hijack prompt alienates normal users. Revised cavekit-onboarding-backend.md: collapsed R2/R3/R4/R5 → R2 (non-blocking hint) + R3 (force flag is ONLY wizard-launch path). Deleted bot_onboarding.DISMISSED + dismissal_flag_path. Rewrote bot_first_run.py: deleted should_prompt / classify_answer / ask_user / decide_startup_action / write_dismissal_flag / run_first_run_flow; added print_setup_hint + run_setup_force. cli.py gui: --setup-bot → run_setup_force; else → print_setup_hint. Tests rewritten with a regression test asserting the deleted interactive symbols stay deleted. Backend code ~200 → ~100 lines; tests 44 → 17. Coverage matrix updated (58/58 post-revision). 65/65 wizard, 17/17 backend.
