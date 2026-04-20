/**
 * R1 acceptance tests — header + invocability.
 *
 * Note: isolation. These tests point the wizard at a guaranteed-absent
 * config directory so the "fresh" path is exercised deterministically
 * regardless of the user's real ~/.config/music-dl state.
 */

import { afterEach, beforeEach, describe, expect, it } from "bun:test";
import { spawnSync } from "node:child_process";
import { mkdtemp, rm } from "node:fs/promises";
import { tmpdir } from "node:os";
import { Readable, Writable } from "node:stream";
import { resolve, join } from "node:path";

import { WIZARD_HEADER, runWizard } from "./index";

const CLI_PATH = resolve(__dirname, "./cli.ts");

class Capture extends Writable {
  chunks: string[] = [];
  _write(chunk: Buffer, _enc: BufferEncoding, cb: () => void): void {
    this.chunks.push(chunk.toString("utf8"));
    cb();
  }
  get text(): string {
    return this.chunks.join("");
  }
}

let work: string;
let envOverrides: NodeJS.ProcessEnv;

beforeEach(async () => {
  work = await mkdtemp(join(tmpdir(), "wizard-r1-"));
  envOverrides = {
    MUSIC_DL_BOT_ENV_PATH: join(work, "discord-bot.env"),
    MUSIC_DL_BOT_TOKEN_PATH: join(work, "bot-shared-token"),
  };
  Object.assign(process.env, envOverrides);
});

afterEach(async () => {
  for (const key of Object.keys(envOverrides)) {
    delete process.env[key];
  }
  await rm(work, { recursive: true, force: true });
});

describe("wizard R1 — entry points and header", () => {
  it("AC3: prints the header line on start", async () => {
    const stdout = new Capture();
    const stderr = new Capture();
    // Feed enough blank answers so the prompt sequence reaches EOF
    // quickly; the test only cares that the header prints. Required
    // fields reject blanks and re-prompt up to 10 times per field,
    // after which they fall back to "" and the wizard returns 75.
    const blankAnswers = "\n".repeat(120);
    const stdin = Readable.from([blankAnswers]);
    const result = await runWizard({ stdout, stderr, stdin });
    expect(result.exitCode).toBe(75);
    expect(stdout.text.split("\n")[0]).toBe(WIZARD_HEADER);
  });

  it("AC1 + AC2: CLI is invokable with no arguments and prints header", () => {
    const result = spawnSync("bun", [CLI_PATH], {
      cwd: resolve(__dirname, "../.."),
      encoding: "utf8",
      env: { ...process.env, ...envOverrides },
    });
    expect(result.stdout.split("\n")[0]).toBe(WIZARD_HEADER);
    // AC1 + AC2 care that invocation works and produces the header. The
    // exit code reflects current build state (75 on fresh while T-004
    // pending); both values are acceptable per R1 (not an exit-code spec).
    expect(result.status).not.toBeNull();
    expect([0, 75]).toContain(result.status as number);
  });
});
