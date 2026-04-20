---
created: 2026-04-20
last_edited: 2026-04-20
---
# Implementation Tracking: onboarding-backend

Build site: context/plans/build-site.md

Kit revised 2026-04-20 after normie-UX feedback: prior R2 (TTY prompt), R3 (Y/n/never), R4 (wizard dispatch as result of interactive answer), and R5 (force flag) collapsed to new R2 (non-blocking one-line hint) + R3 (force flag is the ONLY wizard-launch path from backend). Prior tasks T-007 / T-011 / T-013 are deprecated; their code + tests were deleted. Net backend code shrank from ~200 lines to ~100 and tests from 44 to 17.

| Task | Status | Notes |
|------|--------|-------|
| T-005 | DONE | bot_onboarding.py simplified — OnboardingState has 2 values (CONFIGURED / NEEDS_SETUP); DISMISSED + dismissal_flag_path removed. 6 tests covering AC1-AC2 + edges. |
| T-007 | DEPRECATED | Prior TTY prompt on startup — DELETED. Replaced by non-blocking print_setup_hint() per revised R2. Test suite for ask_user / decide_startup_action / classify_answer deleted. |
| T-011 | DEPRECATED | Prior Y/n/never handling — DELETED. No interactive prompt means no answer to handle. write_dismissal_flag deleted; there is no longer a "never" answer to record. |
| T-013 | PARTIAL-RETAINED | Wizard dispatch via subprocess retained in dispatch_wizard() but only invoked through T-014 (--setup-bot). No implicit launch. |
| T-014 | DONE | --setup-bot Typer flag → run_setup_force() → dispatch_wizard(). Blocks until exit, prints retry hint on non-zero, never aborts server startup (revised R3 AC6). 3 tests. |

Revised tasks (replacing old R2-R5):

| New Task | Status | Notes |
|----------|--------|-------|
| T-NEW-A | DONE | print_setup_hint() — one-line output on needs-setup + TTY; silent when configured or non-TTY. 4 tests (ACs 1-5 of revised R2). |
| T-NEW-B | DONE | run_setup_force() — explicit wizard launch on --setup-bot flag. 3 tests (dispatch + wizard-fail + runtime-missing). |
