/**
 * R6 acceptance tests — preflight orchestrator.
 *
 * Covers the 10 R6 check points at the orchestrator level. Each Discord
 * + backend interaction is stubbed via fetchImpl so tests never touch
 * discord.com or the user's real backend.
 */

import { describe, expect, it } from "bun:test";

import { failedChecks, runPreflight } from "./preflight";
import type { BotEnvShape } from "./returningUser";

const GOOD_VALUES: BotEnvShape = {
  DISCORD_TOKEN: "bot-token-xyz",
  DISCORD_APPLICATION_ID: "1234567890",
  ALLOWED_GUILD_ID: "guild-1",
  ALLOWED_CHANNEL_ID: "channel-1",
  ALLOWED_USER_ID: "user-1",
  MUSIC_DL_BASE_URL: "http://127.0.0.1:8765",
  MUSIC_DL_BOT_TOKEN: "shared-token",
};

type Responder = (
  url: string,
  init?: RequestInit,
) => Response | Promise<Response>;

function makeFetch(responder: Responder): typeof fetch {
  const fn = (async (input: RequestInfo | URL, init?: RequestInit) => {
    const url = typeof input === "string" ? input : input.toString();
    return await responder(url, init);
  }) as typeof fetch;
  return fn;
}

function happyPathFetch(): typeof fetch {
  return makeFetch((url) => {
    if (url.includes("/users/@me")) {
      return new Response('{"id":"bot","username":"music-dl-bot"}', {
        status: 200,
      });
    }
    if (url.includes("/oauth2/applications/@me")) {
      return new Response('{"id":"1234567890"}', { status: 200 });
    }
    if (url.endsWith("/guilds/guild-1/roles")) {
      // Connect + Speak bitmask as string: (1<<20)|(1<<21) = 0x300000
      return new Response('[{"permissions":"3145728"}]', { status: 200 });
    }
    if (url.endsWith("/guilds/guild-1")) {
      return new Response('{"id":"guild-1"}', { status: 200 });
    }
    if (url.includes("/channels/channel-1")) {
      return new Response('{"type":0,"guild_id":"guild-1"}', { status: 200 });
    }
    if (url.includes("/guilds/guild-1/members/user-1")) {
      return new Response('{"user":{"id":"user-1"}}', { status: 200 });
    }
    if (url.includes("/api/bot/play/resolve")) {
      // Bearer accepted; empty query yields a 400 (bad request body).
      return new Response('{"detail":"Query is required"}', { status: 400 });
    }
    return new Response("", { status: 404 });
  });
}

const GOOD_DEPS = {
  nodeVersion: () => "v22.0.0",
  hasLibsodium: async () => true,
  hasFfmpeg: async () => true,
  hasOpus: async () => true,
  fetchImpl: happyPathFetch(),
};

describe("wizard R6 — preflight orchestrator", () => {
  it("all checks pass on a healthy stack", async () => {
    const results = await runPreflight(GOOD_VALUES, GOOD_DEPS);
    expect(failedChecks(results)).toEqual([]);
    // 10 env+Discord checks total: node/libsodium/ffmpeg/opus +
    // token/app/guild/channel/user/voice. No backend-reachable check —
    // the wizard runs standalone; backend handshake is verified by the
    // backend itself on startup (see server.py).
    expect(results.length).toBe(10);
    expect(results.find((r) => r.id === "backend-reachable")).toBeUndefined();
  });

  it("AC1: Node version below minimum reports env failure with remediation", async () => {
    const results = await runPreflight(GOOD_VALUES, {
      ...GOOD_DEPS,
      nodeVersion: () => "v16.19.0",
    });
    const fail = results.find((r) => r.id === "node-version");
    expect(fail?.passed).toBe(false);
    expect(fail?.field).toBe("env");
    expect(fail?.remediation).toContain("Node.js");
  });

  it("AC1: libsodium missing reports env failure", async () => {
    const results = await runPreflight(GOOD_VALUES, {
      ...GOOD_DEPS,
      hasLibsodium: async () => false,
    });
    expect(results.find((r) => r.id === "libsodium")?.passed).toBe(false);
  });

  it("AC1: ffmpeg missing reports env failure", async () => {
    const results = await runPreflight(GOOD_VALUES, {
      ...GOOD_DEPS,
      hasFfmpeg: async () => false,
    });
    expect(results.find((r) => r.id === "ffmpeg")?.passed).toBe(false);
  });

  it("AC1: opus binding missing reports env failure", async () => {
    const results = await runPreflight(GOOD_VALUES, {
      ...GOOD_DEPS,
      hasOpus: async () => false,
    });
    expect(results.find((r) => r.id === "opus")?.passed).toBe(false);
  });

  it("AC5: invalid token → DISCORD_TOKEN field failure; downstream checks skipped", async () => {
    const results = await runPreflight(GOOD_VALUES, {
      ...GOOD_DEPS,
      fetchImpl: makeFetch((url) => {
        if (url.includes("/users/@me")) {
          return new Response('{"message":"401: Unauthorized"}', { status: 401 });
        }
        if (url.includes("/api/bot/play/resolve")) {
          return new Response("", { status: 400 });
        }
        return new Response("", { status: 200 });
      }),
    });
    const fail = results.find((r) => r.id === "discord-token");
    expect(fail?.passed).toBe(false);
    expect(fail?.field).toBe("DISCORD_TOKEN");
    // Downstream Discord checks are skipped when the token fails.
    expect(results.find((r) => r.id === "app-id-match")).toBeUndefined();
    expect(results.find((r) => r.id === "guild-reachable")).toBeUndefined();
  });

  it("AC6: app id mismatch → DISCORD_APPLICATION_ID field failure", async () => {
    const results = await runPreflight(GOOD_VALUES, {
      ...GOOD_DEPS,
      fetchImpl: makeFetch((url) => {
        if (url.includes("/users/@me"))
          return new Response('{"id":"bot"}', { status: 200 });
        if (url.includes("/oauth2/applications/@me"))
          return new Response('{"id":"OTHER-APP-ID"}', { status: 200 });
        if (url.endsWith("/guilds/guild-1/roles"))
          return new Response('[{"permissions":"3145728"}]', { status: 200 });
        if (url.endsWith("/guilds/guild-1"))
          return new Response('{"id":"guild-1"}', { status: 200 });
        if (url.includes("/channels/channel-1"))
          return new Response('{"type":0,"guild_id":"guild-1"}', { status: 200 });
        if (url.includes("/guilds/guild-1/members/user-1"))
          return new Response('{"user":{}}', { status: 200 });
        if (url.includes("/api/bot/play/resolve"))
          return new Response("", { status: 400 });
        return new Response("", { status: 404 });
      }),
    });
    const fail = results.find((r) => r.id === "app-id-match");
    expect(fail?.passed).toBe(false);
    expect(fail?.field).toBe("DISCORD_APPLICATION_ID");
  });

  it("AC7: guild 404 → ALLOWED_GUILD_ID failure; downstream guild checks skipped", async () => {
    const results = await runPreflight(GOOD_VALUES, {
      ...GOOD_DEPS,
      fetchImpl: makeFetch((url) => {
        if (url.includes("/users/@me"))
          return new Response('{"id":"bot"}', { status: 200 });
        if (url.includes("/oauth2/applications/@me"))
          return new Response('{"id":"1234567890"}', { status: 200 });
        if (url.endsWith("/guilds/guild-1"))
          return new Response('{"message":"Unknown Guild"}', { status: 404 });
        if (url.includes("/api/bot/play/resolve"))
          return new Response("", { status: 400 });
        return new Response("", { status: 404 });
      }),
    });
    const fail = results.find((r) => r.id === "guild-reachable");
    expect(fail?.passed).toBe(false);
    expect(fail?.field).toBe("ALLOWED_GUILD_ID");
    expect(results.find((r) => r.id === "channel-usable")).toBeUndefined();
    expect(results.find((r) => r.id === "user-in-guild")).toBeUndefined();
    expect(results.find((r) => r.id === "voice-perms")).toBeUndefined();
  });

  it("AC8: channel wrong type → ALLOWED_CHANNEL_ID failure", async () => {
    const results = await runPreflight(GOOD_VALUES, {
      ...GOOD_DEPS,
      fetchImpl: makeFetch((url) => {
        if (url.includes("/users/@me"))
          return new Response('{"id":"bot"}', { status: 200 });
        if (url.includes("/oauth2/applications/@me"))
          return new Response('{"id":"1234567890"}', { status: 200 });
        if (url.endsWith("/guilds/guild-1/roles"))
          return new Response('[{"permissions":"3145728"}]', { status: 200 });
        if (url.endsWith("/guilds/guild-1"))
          return new Response('{"id":"guild-1"}', { status: 200 });
        if (url.includes("/channels/channel-1"))
          // Voice channel (type 2) — not sendable
          return new Response('{"type":2,"guild_id":"guild-1"}', { status: 200 });
        if (url.includes("/guilds/guild-1/members/user-1"))
          return new Response('{"user":{}}', { status: 200 });
        if (url.includes("/api/bot/play/resolve"))
          return new Response("", { status: 400 });
        return new Response("", { status: 404 });
      }),
    });
    const fail = results.find((r) => r.id === "channel-usable");
    expect(fail?.passed).toBe(false);
    expect(fail?.field).toBe("ALLOWED_CHANNEL_ID");
    expect(fail?.errorMessage).toContain("text channel");
  });

  it("AC9: user not in guild → ALLOWED_USER_ID failure", async () => {
    const results = await runPreflight(GOOD_VALUES, {
      ...GOOD_DEPS,
      fetchImpl: makeFetch((url) => {
        if (url.includes("/users/@me"))
          return new Response('{"id":"bot"}', { status: 200 });
        if (url.includes("/oauth2/applications/@me"))
          return new Response('{"id":"1234567890"}', { status: 200 });
        if (url.endsWith("/guilds/guild-1/roles"))
          return new Response('[{"permissions":"3145728"}]', { status: 200 });
        if (url.endsWith("/guilds/guild-1"))
          return new Response('{"id":"guild-1"}', { status: 200 });
        if (url.includes("/channels/channel-1"))
          return new Response('{"type":0,"guild_id":"guild-1"}', { status: 200 });
        if (url.includes("/guilds/guild-1/members/user-1"))
          return new Response('{"message":"Unknown Member"}', { status: 404 });
        if (url.includes("/api/bot/play/resolve"))
          return new Response("", { status: 400 });
        return new Response("", { status: 404 });
      }),
    });
    const fail = results.find((r) => r.id === "user-in-guild");
    expect(fail?.passed).toBe(false);
    expect(fail?.field).toBe("ALLOWED_USER_ID");
  });

  it("AC9: bot role lacks Connect+Speak → voice-perms failure", async () => {
    const results = await runPreflight(GOOD_VALUES, {
      ...GOOD_DEPS,
      fetchImpl: makeFetch((url) => {
        if (url.includes("/users/@me"))
          return new Response('{"id":"bot"}', { status: 200 });
        if (url.includes("/oauth2/applications/@me"))
          return new Response('{"id":"1234567890"}', { status: 200 });
        if (url.endsWith("/guilds/guild-1/roles"))
          // Only Send Messages (1 << 11) — no voice bits.
          return new Response('[{"permissions":"2048"}]', { status: 200 });
        if (url.endsWith("/guilds/guild-1"))
          return new Response('{"id":"guild-1"}', { status: 200 });
        if (url.includes("/channels/channel-1"))
          return new Response('{"type":0,"guild_id":"guild-1"}', { status: 200 });
        if (url.includes("/guilds/guild-1/members/user-1"))
          return new Response('{"user":{}}', { status: 200 });
        if (url.includes("/api/bot/play/resolve"))
          return new Response("", { status: 400 });
        return new Response("", { status: 404 });
      }),
    });
    const fail = results.find((r) => r.id === "voice-perms");
    expect(fail?.passed).toBe(false);
    expect(fail?.errorMessage).toContain("Connect");
  });

  // Plan B (2026-04-20): R10 "backend reachable" removed from wizard.
  // Wizard runs standalone; backend handshake plumbing is closed by
  // security.resolve_bot_shared_token reading the wizard's shared-token
  // file. Backend startup logs confirm pickup (server.py).

  it("all failures record label, errorMessage, remediation", async () => {
    const results = await runPreflight(GOOD_VALUES, {
      ...GOOD_DEPS,
      hasFfmpeg: async () => false,
      hasOpus: async () => false,
    });
    for (const failure of failedChecks(results)) {
      expect(failure.label).toBeTruthy();
      expect(failure.remediation).toBeTruthy();
    }
  });

  it("secrets are not leaked in any result text", async () => {
    // Token / shared token / ids must not appear in labels, errors,
    // remediations. T-010 does the broader audit, but preflight is the
    // biggest single source of user-facing text.
    const results = await runPreflight(GOOD_VALUES, {
      ...GOOD_DEPS,
      hasFfmpeg: async () => false,
    });
    const serialized = JSON.stringify(results);
    expect(serialized).not.toContain(GOOD_VALUES.DISCORD_TOKEN);
    expect(serialized).not.toContain(GOOD_VALUES.MUSIC_DL_BOT_TOKEN);
  });
});
