import { describe, expect, test } from "bun:test";
import { parseConfig } from "./config";

const VALID_ENV = {
  DISCORD_TOKEN: "test-token-abc",
  DISCORD_APPLICATION_ID: "123456789",
  ALLOWED_GUILD_ID: "guild-001",
  ALLOWED_CHANNEL_ID: "chan-001",
  ALLOWED_USER_ID: "user-001",
  MUSIC_DL_BASE_URL: "http://127.0.0.1:8765",
  MUSIC_DL_BOT_TOKEN: "backend-secret",
};

describe("parseConfig", () => {
  test("returns config when all variables present", () => {
    const config = parseConfig(VALID_ENV);
    expect(config.discordToken).toBe("test-token-abc");
    expect(config.discordApplicationId).toBe("123456789");
    expect(config.allowedGuildId).toBe("guild-001");
    expect(config.allowedChannelId).toBe("chan-001");
    expect(config.allowedUserId).toBe("user-001");
    expect(config.musicDlBaseUrl).toBe("http://127.0.0.1:8765");
    expect(config.musicDlBotToken).toBe("backend-secret");
  });

  test("fails without DISCORD_TOKEN", () => {
    const env = { ...VALID_ENV, DISCORD_TOKEN: undefined };
    expect(() => parseConfig(env)).toThrow("DISCORD_TOKEN");
  });

  test("fails without DISCORD_APPLICATION_ID", () => {
    const env = { ...VALID_ENV, DISCORD_APPLICATION_ID: undefined };
    expect(() => parseConfig(env)).toThrow("DISCORD_APPLICATION_ID");
  });

  test("fails without ALLOWED_GUILD_ID", () => {
    const env = { ...VALID_ENV, ALLOWED_GUILD_ID: undefined };
    expect(() => parseConfig(env)).toThrow("ALLOWED_GUILD_ID");
  });

  test("fails without ALLOWED_CHANNEL_ID", () => {
    const env = { ...VALID_ENV, ALLOWED_CHANNEL_ID: undefined };
    expect(() => parseConfig(env)).toThrow("ALLOWED_CHANNEL_ID");
  });

  test("fails without ALLOWED_USER_ID", () => {
    const env = { ...VALID_ENV, ALLOWED_USER_ID: undefined };
    expect(() => parseConfig(env)).toThrow("ALLOWED_USER_ID");
  });

  test("fails without MUSIC_DL_BASE_URL", () => {
    const env = { ...VALID_ENV, MUSIC_DL_BASE_URL: undefined };
    expect(() => parseConfig(env)).toThrow("MUSIC_DL_BASE_URL");
  });

  test("fails without MUSIC_DL_BOT_TOKEN", () => {
    const env = { ...VALID_ENV, MUSIC_DL_BOT_TOKEN: undefined };
    expect(() => parseConfig(env)).toThrow("MUSIC_DL_BOT_TOKEN");
  });

  test("treats whitespace-only values as missing", () => {
    const env = { ...VALID_ENV, DISCORD_TOKEN: "   " };
    expect(() => parseConfig(env)).toThrow("DISCORD_TOKEN");
  });

  test("error message names all missing values", () => {
    expect(() => parseConfig({})).toThrow(
      "Missing required configuration: DISCORD_TOKEN, DISCORD_APPLICATION_ID, ALLOWED_GUILD_ID, ALLOWED_CHANNEL_ID, ALLOWED_USER_ID, MUSIC_DL_BASE_URL, MUSIC_DL_BOT_TOKEN",
    );
  });
});
