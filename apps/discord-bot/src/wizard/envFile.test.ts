/**
 * R5 acceptance tests — env file write.
 */

import { afterEach, beforeEach, describe, expect, it } from "bun:test";
import { mkdtemp, readFile, rm, stat, writeFile } from "node:fs/promises";
import { tmpdir } from "node:os";
import { dirname, join } from "node:path";

import { serializeEnvFile, writeEnvFile } from "./envFile";
import type { BotEnvShape } from "./returningUser";

const VALUES: BotEnvShape = {
  DISCORD_TOKEN: "bot-token-xyz",
  DISCORD_APPLICATION_ID: "1234567890",
  ALLOWED_GUILD_ID: "guild-1",
  ALLOWED_CHANNEL_ID: "channel-1",
  ALLOWED_USER_ID: "user-1",
  MUSIC_DL_BASE_URL: "http://127.0.0.1:8765",
  MUSIC_DL_BOT_TOKEN: "shared-token",
};

let work: string;
let envPath: string;

beforeEach(async () => {
  work = await mkdtemp(join(tmpdir(), "wizard-env-"));
  envPath = join(work, "nested", "discord-bot.env");
});

afterEach(async () => {
  await rm(work, { recursive: true, force: true });
});

describe("wizard R5 — env file serialization", () => {
  it("AC1: all 7 keys are present", () => {
    const text = serializeEnvFile(VALUES);
    for (const key of Object.keys(VALUES)) {
      expect(text).toContain(`${key}=`);
    }
  });

  it("quotes values so whitespace survives round-trip", () => {
    const text = serializeEnvFile({
      ...VALUES,
      DISCORD_APPLICATION_ID: "spaces in value",
    });
    expect(text).toContain('DISCORD_APPLICATION_ID="spaces in value"');
  });

  it("escapes embedded double quotes and backslashes", () => {
    const text = serializeEnvFile({
      ...VALUES,
      ALLOWED_GUILD_ID: 'weird"\\value',
    });
    expect(text).toContain('ALLOWED_GUILD_ID="weird\\"\\\\value"');
  });
});

describe("wizard R5 — env file atomic write", () => {
  it("AC3 + AC4: writes at 0600 + parent created + no tempfile leaks", async () => {
    await writeEnvFile(VALUES, { path: envPath });
    const s = await stat(envPath);
    expect(s.mode & 0o777).toBe(0o600);
    const { readdir } = await import("node:fs/promises");
    const leftovers = (await readdir(dirname(envPath))).filter((n) =>
      n.includes(".tmp-"),
    );
    expect(leftovers).toEqual([]);
  });

  it("AC2: base URL default is local-loopback and user-overridable", () => {
    // The default is enforced by prompts.ts (T-004). Here we just
    // round-trip whatever the user supplied verbatim.
    const body = serializeEnvFile({
      ...VALUES,
      MUSIC_DL_BASE_URL: "http://example.local:9999",
    });
    expect(body).toContain('MUSIC_DL_BASE_URL="http://example.local:9999"');
  });

  it("heals permissions on a pre-existing loose file", async () => {
    const { mkdir } = await import("node:fs/promises");
    await mkdir(dirname(envPath), { recursive: true });
    await writeFile(envPath, "old-contents\n", { mode: 0o644 });
    await writeEnvFile(VALUES, { path: envPath });
    const s = await stat(envPath);
    expect(s.mode & 0o777).toBe(0o600);
    const body = await readFile(envPath, "utf8");
    expect(body).toContain("DISCORD_TOKEN=");
  });

  it("overwrites an existing env file on a second write", async () => {
    await writeEnvFile(VALUES, { path: envPath });
    await writeEnvFile(
      { ...VALUES, DISCORD_APPLICATION_ID: "NEW-APP-ID" },
      { path: envPath },
    );
    const body = await readFile(envPath, "utf8");
    expect(body).toContain('DISCORD_APPLICATION_ID="NEW-APP-ID"');
    expect(body).not.toContain("1234567890");
  });
});
