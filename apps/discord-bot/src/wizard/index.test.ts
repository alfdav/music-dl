/**
 * R1 acceptance tests — header + invocability.
 */

import { describe, expect, it } from "bun:test";
import { spawnSync } from "node:child_process";
import { Readable, Writable } from "node:stream";
import { resolve } from "node:path";

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

describe("wizard R1 — entry points and header", () => {
  it("AC3: prints the header line on start", async () => {
    const stdout = new Capture();
    const stderr = new Capture();
    const exit = await runWizard({
      stdout,
      stderr,
      stdin: new Readable({ read() {} }),
    });
    expect(exit).toBe(0);
    expect(stdout.text.split("\n")[0]).toBe(WIZARD_HEADER);
  });

  it("AC1 + AC2: CLI is invokable with no arguments and prints header", () => {
    const result = spawnSync("bun", [CLI_PATH], {
      cwd: resolve(__dirname, "../.."),
      encoding: "utf8",
    });
    expect(result.status).toBe(0);
    expect(result.stdout.split("\n")[0]).toBe(WIZARD_HEADER);
  });
});
