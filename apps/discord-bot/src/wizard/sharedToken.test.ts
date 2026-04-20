/**
 * R4 acceptance tests — CSPRNG + 0600 atomic write + reuse-unless-rotate.
 */

import { afterEach, beforeEach, describe, expect, it } from "bun:test";
import {
  chmod,
  mkdtemp,
  readFile,
  rm,
  stat,
  writeFile,
} from "node:fs/promises";
import { tmpdir } from "node:os";
import { dirname, join } from "node:path";

import { ensureSharedToken, tokenFileMode } from "./sharedToken";

let work: string;
let tokenPath: string;

beforeEach(async () => {
  work = await mkdtemp(join(tmpdir(), "wizard-token-"));
  tokenPath = join(work, "nested", "bot-shared-token");
});

afterEach(async () => {
  await rm(work, { recursive: true, force: true });
});

describe("wizard R4 — shared-token generation", () => {
  it("AC1 + AC2 + AC3: generates when absent; 0600 mode; parent dir created", async () => {
    const result = await ensureSharedToken({ path: tokenPath });
    expect(result.rotated).toBe(true);
    // base64url of 32 bytes = 43 chars (no padding)
    expect(result.token.length).toBeGreaterThanOrEqual(43);

    const mode = await tokenFileMode(tokenPath);
    expect(mode).toBe(0o600);

    const parentStat = await stat(dirname(tokenPath));
    expect(parentStat.isDirectory()).toBe(true);

    const onDisk = (await readFile(tokenPath, "utf8")).trim();
    expect(onDisk).toBe(result.token);
  });

  it("AC5: reuses existing non-empty token", async () => {
    const first = await ensureSharedToken({ path: tokenPath });
    expect(first.rotated).toBe(true);

    const second = await ensureSharedToken({ path: tokenPath });
    expect(second.rotated).toBe(false);
    expect(second.token).toBe(first.token);
  });

  it("AC5: rotate=true regenerates", async () => {
    const first = await ensureSharedToken({ path: tokenPath });
    const rotated = await ensureSharedToken({ path: tokenPath, rotate: true });
    expect(rotated.rotated).toBe(true);
    expect(rotated.token).not.toBe(first.token);
    expect(await tokenFileMode(tokenPath)).toBe(0o600);
  });

  it("empty file treated as absent", async () => {
    const { mkdir } = await import("node:fs/promises");
    await mkdir(dirname(tokenPath), { recursive: true });
    await writeFile(tokenPath, "", { mode: 0o600 });
    const result = await ensureSharedToken({ path: tokenPath });
    expect(result.rotated).toBe(true);
    expect(result.token.length).toBeGreaterThanOrEqual(43);
  });

  it("AC4: atomic — no .tmp sibling left on success", async () => {
    await ensureSharedToken({ path: tokenPath });
    const { readdir } = await import("node:fs/promises");
    const siblings = await readdir(dirname(tokenPath));
    const leftovers = siblings.filter((n) => n.includes(".tmp-"));
    expect(leftovers).toEqual([]);
  });

  it("AC1: two generations yield different tokens (entropy)", async () => {
    const a = await ensureSharedToken({ path: tokenPath });
    await rm(tokenPath);
    const b = await ensureSharedToken({ path: tokenPath });
    expect(a.token).not.toBe(b.token);
  });

  it("AC5 edge: whitespace-only file treated as empty → regenerated", async () => {
    const { mkdir } = await import("node:fs/promises");
    await mkdir(dirname(tokenPath), { recursive: true });
    await writeFile(tokenPath, "   \n", { mode: 0o600 });
    const result = await ensureSharedToken({ path: tokenPath });
    expect(result.rotated).toBe(true);
  });

  it("reuse works even when parent dir mode changed after creation", async () => {
    await ensureSharedToken({ path: tokenPath });
    // Simulate an already-existing config directory with permissive mode —
    // the reuse path must not crash on mkdir recursive.
    await chmod(dirname(tokenPath), 0o755);
    const again = await ensureSharedToken({ path: tokenPath });
    expect(again.rotated).toBe(false);
  });
});
