---
created: 2026-04-20
last_edited: 2026-04-20
---
# Implementation Tracking: onboarding-wizard

Build site: context/plans/build-site.md

| Task | Status | Notes |
|------|--------|-------|
| T-001 | DONE | Scaffolding + header. Files: apps/discord-bot/src/wizard/{index,cli,index.test}.ts + package.json wizard script. Build P, Tests P 2/2. AC1+AC2+AC3 verified. |
| T-002 | DONE | paths.ts + returningUser.ts + test (10 cases). AC1-AC5 verified. |
| T-003 | DONE | sharedToken.ts + test (8 cases). AC1-AC5 verified (CSPRNG 256-bit / 0600 / atomic / reuse / rotate). tier-1 cycle 2 added chmod-heal on reuse + fsync parent dir + MUSIC_DL_CONFIG_DIR precedence in paths.ts + cli.ts shebang fix. |
| T-004 | DONE | prompts.ts (5 ordered fields + breadcrumbs + default masking) + maskedInput.ts (TTY raw-mode reader, Ctrl+C + Ctrl+D handled) + 6 tests. AC1-AC5 verified. tier-2 cycles fixed shared-reader shift, cancel propagation (PromptCancelError), output-stream injection. |
| T-005 | DONE | bot_onboarding.py (OnboardingState + detect_state) + 8 tests. AC1-AC3 + precedence + env-override verified. |
| T-006 | DONE | preflight.ts (10 checks, DI) + preflight.test.ts (15 cases covering every AC + secret-leak regression). AC1-AC10 verified. |
| T-007 | DEPRECATED | Prior TTY prompt (should_prompt / classify_answer / ask_user / decide_startup_action + 28 tests) was DELETED in the 2026-04-20 kit revision — it hijacked `music-dl gui` with a terminal questionnaire and alienated normal users. Replacement: T-NEW-A (non-blocking print_setup_hint) in context/impl/impl-onboarding-backend.md. See onboarding-backend Coverage Matrix note in context/plans/build-site.md for the full rationale. |
| T-008 | DONE | envFile.ts (serializeEnvFile + writeEnvFile atomic 0600 + heal-mode + fsync-parent) + 7 tests. R5 AC1-AC7 verified. |
| T-009 | DONE | Retry-single-field loop in runWizard: field-identifiable → single-field re-prompt; field-unidentifiable → retry/abort. integration.test.ts covers AC1-AC3. |
| T-010 | DONE | integration.test.ts asserts DISCORD_TOKEN + shared-token never appear in stdout/stderr on happy path; preflight 401 body with echoed token reports "token rejected" not the body. R9 AC1-AC3 verified. |
| T-012 | DONE | commit.ts atomic two-file commit: stage both tmpfiles, rename shared-token first then env, rollback token on env-rename failure, fsync both parents. 3 dedicated tests + integration coverage. R8 AC1-AC4 verified. |
