/**
 * Startup configuration validation (R1).
 * Reads required environment variables and fails fast with clear messages.
 */

export interface BotConfig {
  discordToken: string;
  discordApplicationId: string;
  allowedGuildId: string;
  allowedChannelId: string;
  allowedUserId: string;
  musicDlBaseUrl: string;
  musicDlBotToken: string;
}

const REQUIRED_VARS = [
  ["DISCORD_TOKEN", "discordToken"],
  ["DISCORD_APPLICATION_ID", "discordApplicationId"],
  ["ALLOWED_GUILD_ID", "allowedGuildId"],
  ["ALLOWED_CHANNEL_ID", "allowedChannelId"],
  ["ALLOWED_USER_ID", "allowedUserId"],
  ["MUSIC_DL_BASE_URL", "musicDlBaseUrl"],
  ["MUSIC_DL_BOT_TOKEN", "musicDlBotToken"],
] as const;

/**
 * Parse and validate all required configuration from environment variables.
 * Throws with a clear message naming every missing/empty variable.
 */
export function parseConfig(
  env: Record<string, string | undefined> = process.env,
): BotConfig {
  const missing: string[] = [];
  const values: Record<string, string> = {};

  for (const [envKey, configKey] of REQUIRED_VARS) {
    const raw = env[envKey];
    const trimmed = raw?.trim();

    if (!trimmed) {
      missing.push(envKey);
    } else {
      values[configKey] = trimmed;
    }
  }

  if (missing.length > 0) {
    throw new Error(
      `Missing required configuration: ${missing.join(", ")}. ` +
        `Set these environment variables before starting the bot.`,
    );
  }

  return values as unknown as BotConfig;
}
