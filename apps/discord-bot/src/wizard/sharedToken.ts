/**
 * Shared backend token generation + atomic 0600 write (onboarding-wizard R4).
 *
 * The token is read by the backend (onboarding-backend R1) and validated on
 * every bot-API request (bot-api R1). The user never types it or sees it.
 *
 * This module is pure library code — no stdout/stderr/log output, ever.
 * Secret-logging audit (T-010) depends on this module staying silent.
 */

import {
  open,
  mkdir,
  readFile,
  rename,
  stat,
  unlink,
} from "node:fs/promises";
import { dirname } from "node:path";
import { randomBytes } from "node:crypto";

import { getSharedTokenPath } from "./paths";

const TOKEN_BYTES = 32; // 256 bits of entropy (R4 AC1)

export interface EnsureOptions {
  rotate?: boolean;
  path?: string;
}

export interface EnsureResult {
  token: string;
  rotated: boolean;
}

/**
 * Ensures a shared token file exists. Returns the token content.
 *
 * - If the file exists and is non-empty and rotate is not requested → reuse.
 * - Otherwise generate 32 CSPRNG bytes (base64url) and write atomically at 0600.
 *
 * The parent directory is created with mode 0700 if missing. The write lands on
 * a sibling temp file which is fsynced and then renamed over the final path so
 * a crash mid-write cannot leave a partial file.
 */
export async function ensureSharedToken(
  opts: EnsureOptions = {},
): Promise<EnsureResult> {
  const final = opts.path ?? getSharedTokenPath();

  if (!opts.rotate) {
    const existing = await readExistingToken(final);
    if (existing !== null) return { token: existing, rotated: false };
  }

  const token = randomBytes(TOKEN_BYTES).toString("base64url");
  await writeTokenAtomic(final, token);
  return { token, rotated: true };
}

async function readExistingToken(path: string): Promise<string | null> {
  try {
    const content = (await readFile(path, "utf8")).trim();
    return content.length > 0 ? content : null;
  } catch (err: unknown) {
    if (isNotFound(err)) return null;
    throw err;
  }
}

async function writeTokenAtomic(final: string, token: string): Promise<void> {
  const dir = dirname(final);
  await mkdir(dir, { recursive: true, mode: 0o700 });

  const tmp = `${final}.tmp-${randomBytes(8).toString("hex")}`;
  let cleanup = true;
  try {
    const fh = await open(tmp, "wx", 0o600);
    try {
      await fh.writeFile(token + "\n", "utf8");
      await fh.sync();
    } finally {
      await fh.close();
    }
    await rename(tmp, final);
    cleanup = false;
  } finally {
    if (cleanup) {
      try {
        await unlink(tmp);
      } catch {
        // best-effort
      }
    }
  }
}

function isNotFound(err: unknown): boolean {
  return (
    typeof err === "object" &&
    err !== null &&
    "code" in err &&
    (err as { code: string }).code === "ENOENT"
  );
}

/**
 * Read an existing token's file mode, for tests and diagnostics.
 */
export async function tokenFileMode(path: string): Promise<number> {
  const s = await stat(path);
  return s.mode & 0o777;
}
