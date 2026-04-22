/**
 * Bot runtime entrypoint — loads the wizard-written env file from its
 * canonical location, then hands off to the actual bot startup.
 *
 * Previously the `start` and `dev` scripts used `node --env-file=.env`,
 * which reads `.env` in the current working directory. That diverged
 * from the path the onboarding wizard writes to (see wizard/paths.ts:
 * `getBotEnvPath()` → `$MUSIC_DL_CONFIG_DIR/discord-bot.env` with
 * `$XDG_CONFIG_HOME/music-dl/discord-bot.env` and `~/.config/music-dl/
 * discord-bot.env` as fallbacks, plus a `$MUSIC_DL_BOT_ENV_PATH`
 * override). The wizard would write to the canonical path and the bot
 * would read from cwd — silently diverging state. Same failure mode as
 * the shared-token gap, closed the same way: a single authoritative
 * path, consulted by both writer and reader.
 */

import { existsSync } from "node:fs";

import { getBotEnvPath } from "./wizard/paths";

const envPath = getBotEnvPath();
if (existsSync(envPath)) {
  // process.loadEnvFile (Node 20.12+) mirrors what `--env-file=` does
  // internally. Non-existent files would throw ENOENT, so gate on
  // existsSync: a missing file means either first-run or a misplaced
  // config, both of which parseConfig() will surface with a clear
  // "Missing required configuration" message listing the exact keys.
  process.loadEnvFile(envPath);
}

await import("./index");
