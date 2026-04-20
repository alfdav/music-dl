---
created: 2026-04-20
last_edited: 2026-04-20
---
# Implementation Tracking: onboarding-wizard

Build site: context/plans/build-site.md

| Task | Status | Notes |
|------|--------|-------|
| T-001 | DONE | Scaffolding + header. Files: apps/discord-bot/src/wizard/{index,cli,index.test}.ts + package.json wizard script. Build P, Tests P 2/2. AC1+AC2+AC3 verified. |
| T-002 | DONE | paths.ts + returningUser.ts + test (10 cases). AC1-AC5 verified. Inline impl (subagent hallucinated tools). |
| T-003 | DONE | sharedToken.ts + test (8 cases). AC1-AC5 verified (CSPRNG 256-bit / 0600 / atomic / reuse / rotate). Inline impl. |
| T-004 | PENDING | Five-prompt masked sequence (R3) |
| T-006 | PENDING | Preflight checks (R6) |
| T-008 | PENDING | Env file write (R5) |
| T-009 | PENDING | Retry-single-field (R7) |
| T-010 | PENDING | Logging safety (R9) |
| T-012 | PENDING | Atomic two-file commit (R8) |
