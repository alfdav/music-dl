/**
 * R2 acceptance tests — returning-user Keep/Reconfigure/Cancel.
 */

import { afterEach, beforeEach, describe, expect, it } from "bun:test";
import { mkdtemp, readFile, rm, writeFile, stat } from "node:fs/promises";
import { tmpdir } from "node:os";
import { join } from "node:path";
import { Readable, Writable } from "node:stream";

import {
  BOT_ENV_KEYS,
  loadBotEnv,
  resolveEntryDecision,
  sharedTokenPresent,
} from "./returningUser";

class Capture extends Writable {
  chunks: string[] = [];
  _write(c: Buffer, _e: BufferEncoding, cb: () => void) {
    this.chunks.push(c.toString("utf8"));
    cb();
  }
  get text() {
    return this.chunks.join("");
  }
}

function io(stdinText: string) {
  return {
    stdin: Readable.from([stdinText]),
    stdout: new Capture(),
    stderr: new Capture(),
  };
}

function goodEnv(): string {
  return BOT_ENV_KEYS.map((k) => `${k}=value-of-${k}`).join("\n") + "\n";
}

let work: string;
let envPath: string;
let tokenPath: string;

beforeEach(async () => {
  work = await mkdtemp(join(tmpdir(), "wizard-ru-"));
  envPath = join(work, "discord-bot.env");
  tokenPath = join(work, "bot-shared-token");
});

afterEach(async () => {
  await rm(work, { recursive: true, force: true });
});

describe("wizard R2 — returning-user path", () => {
  it("no env + no token → fresh (no prompt, no changes)", async () => {
    const { stdin, stdout, stderr } = io("");
    const decision = await resolveEntryDecision(
      { stdin, stdout, stderr },
      { envPath, tokenPath },
    );
    expect(decision).toEqual({ mode: "fresh" });
    expect(stdout.text).toBe("");
  });

  it("env missing one key → fresh", async () => {
    // Drop ALLOWED_GUILD_ID
    const content = BOT_ENV_KEYS.filter((k) => k !== "ALLOWED_GUILD_ID")
      .map((k) => `${k}=value`)
      .join("\n");
    await writeFile(envPath, content);
    await writeFile(tokenPath, "token123");
    const { stdin, stdout, stderr } = io("");
    const decision = await resolveEntryDecision(
      { stdin, stdout, stderr },
      { envPath, tokenPath },
    );
    expect(decision).toEqual({ mode: "fresh" });
  });

  it("env key present but empty → fresh", async () => {
    const content = BOT_ENV_KEYS.map((k) =>
      k === "MUSIC_DL_BASE_URL" ? `${k}=` : `${k}=v`,
    ).join("\n");
    await writeFile(envPath, content);
    await writeFile(tokenPath, "token");
    const { stdin, stdout, stderr } = io("");
    const d = await resolveEntryDecision(
      { stdin, stdout, stderr },
      { envPath, tokenPath },
    );
    expect(d).toEqual({ mode: "fresh" });
  });

  it("empty token file → fresh", async () => {
    await writeFile(envPath, goodEnv());
    await writeFile(tokenPath, "");
    const { stdin, stdout, stderr } = io("");
    const d = await resolveEntryDecision(
      { stdin, stdout, stderr },
      { envPath, tokenPath },
    );
    expect(d).toEqual({ mode: "fresh" });
  });

  it("AC1 + AC2: valid config + 'k' → keep (exits 0, no file changes)", async () => {
    await writeFile(envPath, goodEnv());
    await writeFile(tokenPath, "token");
    const envStatBefore = await stat(envPath);
    const tokenContentBefore = await readFile(tokenPath, "utf8");

    const { stdin, stdout, stderr } = io("k\n");
    const d = await resolveEntryDecision(
      { stdin, stdout, stderr },
      { envPath, tokenPath },
    );
    expect(d).toEqual({ mode: "keep" });
    expect(stdout.text).toContain("Existing configuration");

    const envStatAfter = await stat(envPath);
    const tokenContentAfter = await readFile(tokenPath, "utf8");
    expect(envStatAfter.mtimeMs).toBe(envStatBefore.mtimeMs);
    expect(tokenContentAfter).toBe(tokenContentBefore);
  });

  it("AC1 + AC3: valid config + 'r' → reconfigure with defaults", async () => {
    await writeFile(envPath, goodEnv());
    await writeFile(tokenPath, "token");
    const { stdin, stdout, stderr } = io("r\n");
    const d = await resolveEntryDecision(
      { stdin, stdout, stderr },
      { envPath, tokenPath },
    );
    expect(d.mode).toBe("reconfigure");
    if (d.mode === "reconfigure") {
      expect(d.defaults.DISCORD_TOKEN).toBe("value-of-DISCORD_TOKEN");
      expect(d.defaults.MUSIC_DL_BOT_TOKEN).toBe("value-of-MUSIC_DL_BOT_TOKEN");
    }
  });

  it("AC1 + AC4: valid config + 'c' → cancel", async () => {
    await writeFile(envPath, goodEnv());
    await writeFile(tokenPath, "token");
    const { stdin, stdout, stderr } = io("c\n");
    const d = await resolveEntryDecision(
      { stdin, stdout, stderr },
      { envPath, tokenPath },
    );
    expect(d).toEqual({ mode: "cancel" });
  });

  it("empty enter (default) maps to keep", async () => {
    await writeFile(envPath, goodEnv());
    await writeFile(tokenPath, "token");
    const { stdin, stdout, stderr } = io("\n");
    const d = await resolveEntryDecision(
      { stdin, stdout, stderr },
      { envPath, tokenPath },
    );
    expect(d).toEqual({ mode: "keep" });
  });

  it("3 invalid answers → cancel", async () => {
    await writeFile(envPath, goodEnv());
    await writeFile(tokenPath, "token");
    const { stdin, stdout, stderr } = io("foo\nbar\nbaz\n");
    const d = await resolveEntryDecision(
      { stdin, stdout, stderr },
      { envPath, tokenPath },
    );
    expect(d).toEqual({ mode: "cancel" });
    expect(stderr.text).toContain("K (keep)");
  });

  it("loadBotEnv tolerates comments + quoted values", async () => {
    const lines = [
      "# a comment",
      '  DISCORD_TOKEN = "quoted-token"  ',
      "DISCORD_APPLICATION_ID='app-id'",
      "ALLOWED_GUILD_ID=g",
      "ALLOWED_CHANNEL_ID=c",
      "ALLOWED_USER_ID=u",
      "MUSIC_DL_BASE_URL=http://127.0.0.1:8765",
      "MUSIC_DL_BOT_TOKEN=tkn",
    ].join("\n");
    await writeFile(envPath, lines);
    const env = await loadBotEnv(envPath);
    expect(env?.DISCORD_TOKEN).toBe("quoted-token");
    expect(env?.DISCORD_APPLICATION_ID).toBe("app-id");
  });

  it("sharedTokenPresent: whitespace-only file → false", async () => {
    await writeFile(tokenPath, "   \n\n");
    expect(await sharedTokenPresent(tokenPath)).toBe(false);
  });
});
