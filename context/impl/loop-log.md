---
created: 2026-04-20
last_edited: 2026-04-20
---
# Loop Log — onboarding build site

### Iteration 1 — 2026-04-20
- T-001: wizard entry points + header — DONE. Files: apps/discord-bot/src/wizard/{index,cli,index.test}.ts, apps/discord-bot/package.json. Build P, Tests P 2/2. Next: T-002, T-003 (tier 1, parallel).

### Iteration 2 — 2026-04-20
- T-002 + T-003 tier-1 packet — DONE. Subagent dispatch unreliable (reports tool_uses=0 despite narrative; no commits landed on first attempts). Fell back to inline. Files: apps/discord-bot/src/wizard/{paths,returningUser,returningUser.test,sharedToken,sharedToken.test}.ts + index.ts/cli.ts integration. Build P, Tests P 21/21. Next: T-004 (fresh/reconfigure prompt sequence), T-005 (backend config detection).
