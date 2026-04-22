/**
 * Canonical filesystem paths shared by the wizard and the backend's
 * first-run detection (onboarding-backend R1 reads these same paths).
 *
 * Override via env vars for testability — tests should never touch the
 * real user config directory.
 */

import { homedir } from "node:os";
import { join } from "node:path";

function configDir(env: NodeJS.ProcessEnv = process.env): string {
  // Match the backend's path_config_base() precedence exactly so the
  // wizard and the backend always read/write the same files. Docker and
  // custom-config deployments rely on MUSIC_DL_CONFIG_DIR winning over XDG.
  const custom = env.MUSIC_DL_CONFIG_DIR?.trim();
  if (custom) return custom;
  const xdg = env.XDG_CONFIG_HOME?.trim();
  const base = xdg || join(env.HOME || homedir(), ".config");
  return join(base, "music-dl");
}

export function getBotEnvPath(env: NodeJS.ProcessEnv = process.env): string {
  const override = env.MUSIC_DL_BOT_ENV_PATH?.trim();
  return override || join(configDir(env), "discord-bot.env");
}

export function getSharedTokenPath(
  env: NodeJS.ProcessEnv = process.env,
): string {
  const override = env.MUSIC_DL_BOT_TOKEN_PATH?.trim();
  return override || join(configDir(env), "bot-shared-token");
}

export function getConfigDir(env: NodeJS.ProcessEnv = process.env): string {
  return configDir(env);
}
