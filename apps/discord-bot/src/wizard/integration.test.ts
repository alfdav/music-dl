/**
 * End-to-end wizard tests (onboarding-wizard R7 + R8 + R9).
 *
 * R9 is inherently a whole-pipeline property — "no token appears in any
 * byte of wizard output" — so this file runs the full runWizard() with
 * stubbed deps, captures stdout/stderr, and asserts the secrets never
 * surface.
 */

import { afterEach, beforeEach, describe, expect, it } from "bun:test";
import { mkdtemp, readFile, rm, writeFile, stat } from "node:fs/promises";
import { tmpdir } from "node:os";
import { Readable, Writable } from "node:stream";
import { join } from "node:path";

import { runWizard } from "./index";

const SECRET_DISCORD_TOKEN =
  "NTVWEWVfgweOwkLPs7j5gWdnG6FiEgHo6aZweqtBU4kSV3r6SbynPSVlZwUjKiGT";

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

let work: string;
let envPath: string;
let tokenPath: string;

beforeEach(async () => {
  work = await mkdtemp(join(tmpdir(), "wizard-int-"));
  envPath = join(work, "discord-bot.env");
  tokenPath = join(work, "bot-shared-token");
  process.env.MUSIC_DL_BOT_ENV_PATH = envPath;
  process.env.MUSIC_DL_BOT_TOKEN_PATH = tokenPath;
});

afterEach(async () => {
  delete process.env.MUSIC_DL_BOT_ENV_PATH;
  delete process.env.MUSIC_DL_BOT_TOKEN_PATH;
  await rm(work, { recursive: true, force: true });
});

function happyPreflight() {
  return {
    nodeVersion: () => "v22.0.0",
    hasLibsodium: async () => true,
    hasFfmpeg: async () => true,
    hasOpus: async () => true,
    fetchImpl: (async (input: RequestInfo | URL): Promise<Response> => {
      const url = typeof input === "string" ? input : input.toString();
      if (url.includes("/users/@me"))
        return new Response('{"id":"bot"}', { status: 200 });
      if (url.includes("/oauth2/applications/@me"))
        return new Response('{"id":"APP-1"}', { status: 200 });
      if (url.endsWith("/guilds/G1/roles"))
        return new Response('[{"permissions":"3145728"}]', { status: 200 });
      if (url.endsWith("/guilds/G1"))
        return new Response('{"id":"G1"}', { status: 200 });
      if (url.includes("/channels/C1"))
        return new Response('{"type":0,"guild_id":"G1"}', { status: 200 });
      if (url.includes("/guilds/G1/members/U1"))
        return new Response('{"user":{}}', { status: 200 });
      if (url.includes("/api/bot/play/resolve"))
        return new Response("", { status: 400 });
      return new Response("", { status: 404 });
    }) as typeof fetch,
  };
}

describe("wizard — end-to-end R8 success path", () => {
  it("happy path: fresh install persists env + token, exits 0, prints start command", async () => {
    const stdout = new Capture();
    const stderr = new Capture();
    const stdin = Readable.from(
      [
        SECRET_DISCORD_TOKEN,
        "APP-1",
        "G1",
        "C1",
        "U1",
        "", // default base URL
      ]
        .map((s) => s + "\n")
        .join(""),
    );
    const result = await runWizard(
      { stdin, stdout, stderr },
      { preflightDeps: happyPreflight() },
    );
    expect(result.exitCode).toBe(0);
    expect(stdout.text).toContain("Setup complete");
    expect(stdout.text).toContain("bun run start");

    const envBody = await readFile(envPath, "utf8");
    expect(envBody).toContain(`DISCORD_TOKEN="${SECRET_DISCORD_TOKEN}"`);
    const tokenStat = await stat(tokenPath);
    expect(tokenStat.mode & 0o777).toBe(0o600);
    const envStat = await stat(envPath);
    expect(envStat.mode & 0o777).toBe(0o600);
  });

  it("R9: Discord bot token never appears in stdout/stderr produced by the wizard", async () => {
    const stdout = new Capture();
    const stderr = new Capture();
    const stdin = Readable.from(
      [SECRET_DISCORD_TOKEN, "APP-1", "G1", "C1", "U1", ""]
        .map((s) => s + "\n")
        .join(""),
    );
    await runWizard(
      { stdin, stdout, stderr },
      { preflightDeps: happyPreflight() },
    );
    expect(stdout.text).not.toContain(SECRET_DISCORD_TOKEN);
    expect(stderr.text).not.toContain(SECRET_DISCORD_TOKEN);
  });

  it("R9: generated shared backend token never appears in output", async () => {
    const stdout = new Capture();
    const stderr = new Capture();
    const stdin = Readable.from(
      [SECRET_DISCORD_TOKEN, "APP-1", "G1", "C1", "U1", ""]
        .map((s) => s + "\n")
        .join(""),
    );
    await runWizard(
      { stdin, stdout, stderr },
      { preflightDeps: happyPreflight() },
    );
    // Read the shared token from disk and ensure it is NOT anywhere in
    // the wizard's captured streams.
    const sharedToken = (await readFile(tokenPath, "utf8")).trim();
    expect(sharedToken.length).toBeGreaterThanOrEqual(43);
    expect(stdout.text).not.toContain(sharedToken);
    expect(stderr.text).not.toContain(sharedToken);
  });

  it("R9: preflight error messages use generic phrasing when a secret could appear", async () => {
    // Stub Discord to reject the token with a body that includes the
    // full HTTP response. R9 AC3 requires generic phrasing — "token
    // rejected" not a full body dump.
    const deps = happyPreflight();
    deps.fetchImpl = (async (input: RequestInfo | URL): Promise<Response> => {
      const url = typeof input === "string" ? input : input.toString();
      if (url.includes("/users/@me")) {
        return new Response(
          JSON.stringify({
            raw_token_echo: SECRET_DISCORD_TOKEN,
            message: "401: unauthorized",
          }),
          { status: 401 },
        );
      }
      if (url.includes("/api/bot/play/resolve"))
        return new Response("", { status: 400 });
      return new Response("", { status: 404 });
    }) as typeof fetch;

    const stdout = new Capture();
    const stderr = new Capture();
    const stdin = Readable.from(
      [SECRET_DISCORD_TOKEN, "APP-1", "G1", "C1", "U1", "", "a\n"]
        .map((s) => s + "\n")
        .join(""),
    );
    await runWizard({ stdin, stdout, stderr }, { preflightDeps: deps });
    expect(stderr.text).toContain("token rejected");
    expect(stderr.text).not.toContain(SECRET_DISCORD_TOKEN);
    expect(stdout.text).not.toContain(SECRET_DISCORD_TOKEN);
  });
});

describe("wizard — R7 retry-single-field", () => {
  it("field-identifiable failure offers re-entry of just that field", async () => {
    // First guild-reachable fails (bad guild id), user re-enters, passes.
    let calls = 0;
    const deps = happyPreflight();
    const baseline = deps.fetchImpl;
    deps.fetchImpl = (async (input: RequestInfo | URL): Promise<Response> => {
      const url = typeof input === "string" ? input : input.toString();
      if (url.endsWith("/guilds/BAD-GUILD")) {
        calls++;
        return new Response('{"message":"Unknown Guild"}', { status: 404 });
      }
      return baseline(input);
    }) as typeof fetch;

    const stdout = new Capture();
    const stderr = new Capture();
    const stdin = Readable.from(
      [
        SECRET_DISCORD_TOKEN,
        "APP-1",
        "BAD-GUILD",
        "C1",
        "U1",
        "",
        "y", // retry [Y]
        "G1", // corrected guild id
      ]
        .map((s) => s + "\n")
        .join(""),
    );
    const result = await runWizard(
      { stdin, stdout, stderr },
      { preflightDeps: deps },
    );
    expect(calls).toBeGreaterThan(0);
    expect(result.exitCode).toBe(0);
    const envBody = await readFile(envPath, "utf8");
    expect(envBody).toContain('ALLOWED_GUILD_ID="G1"');
  });

  it("user abort at retry prompt → non-zero, no files written", async () => {
    const deps = happyPreflight();
    deps.fetchImpl = (async (input: RequestInfo | URL): Promise<Response> => {
      const url = typeof input === "string" ? input : input.toString();
      if (url.endsWith("/guilds/BAD"))
        return new Response('{"message":"Unknown Guild"}', { status: 404 });
      if (url.includes("/users/@me"))
        return new Response('{"id":"bot"}', { status: 200 });
      if (url.includes("/oauth2/applications/@me"))
        return new Response('{"id":"APP-1"}', { status: 200 });
      if (url.includes("/api/bot/play/resolve"))
        return new Response("", { status: 400 });
      return new Response("", { status: 404 });
    }) as typeof fetch;

    const stdout = new Capture();
    const stderr = new Capture();
    const stdin = Readable.from(
      [SECRET_DISCORD_TOKEN, "APP-1", "BAD", "C1", "U1", "", "a"]
        .map((s) => s + "\n")
        .join(""),
    );
    const result = await runWizard(
      { stdin, stdout, stderr },
      { preflightDeps: deps },
    );
    expect(result.exitCode).toBe(130);
    // No env file on disk.
    await expect(stat(envPath)).rejects.toThrow();
  });

  it("R7 AC2: field-unidentifiable failure prints remediation, offers retry/abort", async () => {
    // ffmpeg missing — no field tie. Abort path.
    const deps = happyPreflight();
    deps.hasFfmpeg = async () => false;

    const stdout = new Capture();
    const stderr = new Capture();
    const stdin = Readable.from(
      [SECRET_DISCORD_TOKEN, "APP-1", "G1", "C1", "U1", "", "a"]
        .map((s) => s + "\n")
        .join(""),
    );
    const result = await runWizard(
      { stdin, stdout, stderr },
      { preflightDeps: deps },
    );
    expect(result.exitCode).toBe(130);
    expect(stderr.text).toContain("Install ffmpeg");
  });

  it("R5 AC7: preflight fail on reconfigure leaves original env untouched", async () => {
    // Write a pre-existing env + token that constitute valid config.
    const original = [
      'DISCORD_TOKEN="original-token"',
      'DISCORD_APPLICATION_ID="original-app"',
      'ALLOWED_GUILD_ID="original-guild"',
      'ALLOWED_CHANNEL_ID="original-channel"',
      'ALLOWED_USER_ID="original-user"',
      'MUSIC_DL_BASE_URL="http://127.0.0.1:8765"',
      'MUSIC_DL_BOT_TOKEN="original-shared"',
    ].join("\n");
    await writeFile(envPath, original, { mode: 0o600 });
    await writeFile(tokenPath, "original-shared\n", { mode: 0o600 });

    const deps = happyPreflight();
    // Make the Discord token check fail for the new token
    deps.fetchImpl = (async (input: RequestInfo | URL): Promise<Response> => {
      const url = typeof input === "string" ? input : input.toString();
      if (url.includes("/users/@me"))
        return new Response("", { status: 401 });
      if (url.includes("/api/bot/play/resolve"))
        return new Response("", { status: 400 });
      return new Response("", { status: 404 });
    }) as typeof fetch;

    const stdout = new Capture();
    const stderr = new Capture();
    const stdin = Readable.from(
      // returning-user prompt gets "r" (reconfigure), then the 5 prompts,
      // then abort at retry.
      [
        "r",
        SECRET_DISCORD_TOKEN,
        "APP-1",
        "G1",
        "C1",
        "U1",
        "",
        "a",
      ]
        .map((s) => s + "\n")
        .join(""),
    );
    await runWizard(
      { stdin, stdout, stderr },
      { preflightDeps: deps },
    );

    const stillOriginal = await readFile(envPath, "utf8");
    expect(stillOriginal).toBe(original);
    const tokenContent = await readFile(tokenPath, "utf8");
    expect(tokenContent.trim()).toBe("original-shared");
  });
});
