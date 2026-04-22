/**
 * paths.ts — precedence matches backend's path_config_base().
 */

import { describe, expect, it } from "bun:test";
import { join } from "node:path";

import { getBotEnvPath, getConfigDir, getSharedTokenPath } from "./paths";

describe("wizard paths — precedence", () => {
  it("MUSIC_DL_CONFIG_DIR wins over XDG_CONFIG_HOME and HOME", () => {
    const env = {
      MUSIC_DL_CONFIG_DIR: "/srv/music-dl-config",
      XDG_CONFIG_HOME: "/home/user/.config-xdg",
      HOME: "/home/user",
    };
    expect(getConfigDir(env)).toBe("/srv/music-dl-config");
    expect(getBotEnvPath(env)).toBe(
      join("/srv/music-dl-config", "discord-bot.env"),
    );
    expect(getSharedTokenPath(env)).toBe(
      join("/srv/music-dl-config", "bot-shared-token"),
    );
  });

  it("XDG_CONFIG_HOME used when MUSIC_DL_CONFIG_DIR absent", () => {
    const env = {
      XDG_CONFIG_HOME: "/home/user/.config-xdg",
      HOME: "/home/user",
    };
    expect(getConfigDir(env)).toBe(join("/home/user/.config-xdg", "music-dl"));
  });

  it("HOME/.config/music-dl is the fallback", () => {
    const env = { HOME: "/home/user" };
    expect(getConfigDir(env)).toBe(join("/home/user/.config", "music-dl"));
  });

  it("explicit env-var overrides take full precedence", () => {
    const env = {
      MUSIC_DL_CONFIG_DIR: "/srv/music-dl-config",
      MUSIC_DL_BOT_ENV_PATH: "/tmp/custom.env",
      MUSIC_DL_BOT_TOKEN_PATH: "/tmp/custom.token",
    };
    expect(getBotEnvPath(env)).toBe("/tmp/custom.env");
    expect(getSharedTokenPath(env)).toBe("/tmp/custom.token");
  });
});
