---
created: 2026-04-20
last_edited: 2026-04-20
---
# Implementation Tracking: onboarding-backend

Build site: context/plans/build-site.md

| Task | Status | Notes |
|------|--------|-------|
| T-005 | DONE | bot_onboarding.py (OnboardingState + detect_state) + 8 tests. R1 AC1-AC3 + precedence + env-override verified. |
| T-007 | DONE | bot_first_run.py (should_prompt, classify_answer, ask_user, decide_startup_action) + 21 tests. R2 AC1-AC4 + R3 AC1-AC4 verified. |
| T-011 | DONE | write_dismissal_flag() + ask_user yes/no/never mapping + idempotency test. R3 AC1-AC4 verified. |
| T-013 | DONE | dispatch_wizard() + run_first_run_flow() integrated in cli.py gui command. R4 AC1-AC5 verified (inherited stdio via subprocess.run, blocks on exit, prints retry command on non-zero, NEVER aborts server startup). |
| T-014 | DONE | --setup-bot Typer flag on gui command + force path in run_first_run_flow. R5 AC1-AC4 verified (bypasses state, ignores dismissal, does NOT modify flag, prompts even when configured). |
