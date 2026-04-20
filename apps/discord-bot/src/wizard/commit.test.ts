/**
 * R8 acceptance tests — atomic two-file commit.
 */

import { afterEach, beforeEach, describe, expect, it } from "bun:test";
import { mkdtemp, readFile, rm, stat } from "node:fs/promises";
import { tmpdir } from "node:os";
import { join } from "node:path";

import { commitWizardFiles } from "./commit";
import type { BotEnvShape } from "./returningUser";

const VALUES: BotEnvShape = {
  DISCORD_TOKEN: "bot-token-xyz",
  DISCORD_APPLICATION_ID: "app-1",
  ALLOWED_GUILD_ID: "guild-1",
  ALLOWED_CHANNEL_ID: "channel-1",
  ALLOWED_USER_ID: "user-1",
  MUSIC_DL_BASE_URL: "http://127.0.0.1:8765",
  MUSIC_DL_BOT_TOKEN: "shared-token-SHOULD-MATCH-FILE",
};

let work: string;
let envPath: string;
let tokenPath: string;

beforeEach(async () => {
  work = await mkdtemp(join(tmpdir(), "wizard-commit-"));
  envPath = join(work, "discord-bot.env");
  tokenPath = join(work, "bot-shared-token");
});

afterEach(async () => {
  await rm(work, { recursive: true, force: true });
});

describe("wizard R8 — atomic two-file commit", () => {
  it("AC1: both files land; both at 0600", async () => {
    await commitWizardFiles(VALUES, "shared-token-SHOULD-MATCH-FILE", {
      envPath,
      tokenPath,
    });
    const envStat = await stat(envPath);
    const tokenStat = await stat(tokenPath);
    expect(envStat.mode & 0o777).toBe(0o600);
    expect(tokenStat.mode & 0o777).toBe(0o600);

    const envBody = await readFile(envPath, "utf8");
    const tokenBody = (await readFile(tokenPath, "utf8")).trim();
    expect(envBody).toContain('DISCORD_TOKEN="bot-token-xyz"');
    expect(tokenBody).toBe("shared-token-SHOULD-MATCH-FILE");
  });

  it("AC1: no tempfile siblings remain after success", async () => {
    await commitWizardFiles(VALUES, "tok", { envPath, tokenPath });
    const { readdir } = await import("node:fs/promises");
    const siblings = await readdir(work);
    expect(siblings.filter((n) => n.includes(".tmp-"))).toEqual([]);
  });

  it("overwrite: second commit replaces both files atomically", async () => {
    await commitWizardFiles(VALUES, "token-A", { envPath, tokenPath });
    await commitWizardFiles(
      { ...VALUES, DISCORD_APPLICATION_ID: "app-2" },
      "token-B",
      { envPath, tokenPath },
    );
    const envBody = await readFile(envPath, "utf8");
    const tokenBody = (await readFile(tokenPath, "utf8")).trim();
    expect(envBody).toContain('DISCORD_APPLICATION_ID="app-2"');
    expect(tokenBody).toBe("token-B");
  });
});
