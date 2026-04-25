import { describe, expect, test } from "bun:test";
import { ensureAuthorized } from "./auth";
import type { BotConfig } from "./config";

const CONFIG: BotConfig = {
  discordToken: "t",
  discordApplicationId: "app",
  allowedGuildId: "guild-ok",
  allowedChannelId: "chan-ok",
  allowedUserId: "user-ok",
  musicDlBaseUrl: "http://127.0.0.1:8765",
  musicDlBotToken: "secret",
};

function interaction(g: string | null, c: string | null, u: string) {
  return { guildId: g, channelId: c, user: { id: u } };
}

describe("ensureAuthorized", () => {
  test("passes when all three match", () => {
    const r = ensureAuthorized(interaction("guild-ok", "chan-ok", "user-ok"), CONFIG);
    expect(r.ok).toBe(true);
  });

  test("rejects wrong guild", () => {
    const r = ensureAuthorized(interaction("guild-bad", "chan-ok", "user-ok"), CONFIG);
    expect(r.ok).toBe(false);
    if (!r.ok) expect(r.reason).toBe("wrong_guild");
  });

  test("rejects wrong channel", () => {
    const r = ensureAuthorized(interaction("guild-ok", "chan-bad", "user-ok"), CONFIG);
    expect(r.ok).toBe(false);
    if (!r.ok) expect(r.reason).toBe("wrong_channel");
  });

  test("rejects wrong user", () => {
    const r = ensureAuthorized(interaction("guild-ok", "chan-ok", "user-bad"), CONFIG);
    expect(r.ok).toBe(false);
    if (!r.ok) expect(r.reason).toBe("wrong_user");
  });

  test("rejects null guild (DM)", () => {
    const r = ensureAuthorized(interaction(null, "chan-ok", "user-ok"), CONFIG);
    expect(r.ok).toBe(false);
  });

  test("rejects null channel", () => {
    const r = ensureAuthorized(interaction("guild-ok", null, "user-ok"), CONFIG);
    expect(r.ok).toBe(false);
  });

  test("rejection messages don't expose internals", () => {
    const r = ensureAuthorized(interaction("guild-bad", "chan-ok", "user-ok"), CONFIG);
    if (!r.ok) {
      expect(r.message).not.toContain("guild-ok");
      expect(r.message).not.toContain("guild-bad");
    }
  });
});
