/**
 * Bot environment-file generation (onboarding-wizard R5).
 *
 * Atomic 0600 write of the 7 user-facing env keys. T-012 orchestrates
 * the two-file commit (this file + shared-token); this module only
 * provides the write primitive.
 *
 * No stdout/stderr/log output here — T-010 audits the module for
 * secret leakage.
 */

import {
  chmod,
  mkdir,
  open,
  rename,
  stat,
  unlink,
} from "node:fs/promises";
import { dirname } from "node:path";
import { randomBytes } from "node:crypto";

import { BOT_ENV_KEYS, type BotEnvShape } from "./returningUser";
import { getBotEnvPath } from "./paths";

/** Format the 7 bot env keys as a dotenv body. Values are double-quoted
 *  to tolerate whitespace; embedded quotes/backslashes are escaped. */
export function serializeEnvFile(values: BotEnvShape): string {
  const lines: string[] = [
    "# music-dl Discord bot configuration.",
    "# Written by the onboarding wizard — do not edit unless you know what you are doing.",
  ];
  for (const key of BOT_ENV_KEYS) {
    lines.push(`${key}=${quote(values[key])}`);
  }
  return lines.join("\n") + "\n";
}

function quote(value: string): string {
  // Escape backslashes and double quotes; wrap in double quotes.
  const escaped = value.replace(/\\/g, "\\\\").replace(/"/g, '\\"');
  return `"${escaped}"`;
}

export interface WriteEnvFileOptions {
  path?: string;
  mode?: number;
}

/**
 * Atomically write the env file. Matches the sharedToken.ts pattern —
 * mkdir parent (0700), write temp (0600), fsync, rename, fsync parent.
 * Heals mode on a pre-existing file that has loose permissions.
 */
export async function writeEnvFile(
  values: BotEnvShape,
  opts: WriteEnvFileOptions = {},
): Promise<void> {
  const final = opts.path ?? getBotEnvPath();
  const mode = opts.mode ?? 0o600;
  const dir = dirname(final);
  await mkdir(dir, { recursive: true, mode: 0o700 });

  const body = serializeEnvFile(values);
  const tmp = `${final}.tmp-${randomBytes(8).toString("hex")}`;
  let cleanup = true;
  try {
    const fh = await open(tmp, "wx", mode);
    try {
      await fh.writeFile(body, "utf8");
      await fh.sync();
    } finally {
      await fh.close();
    }
    await rename(tmp, final);
    cleanup = false;

    // Heal mode on pre-existing loose files (the "wx" flag above only
    // applies to the temp file; rename preserves whatever mode the old
    // final had if the rename didn't clobber mode).
    const s = await stat(final);
    if ((s.mode & 0o777) !== mode) {
      await chmod(final, mode);
    }

    // Parent-dir fsync — matches sharedToken's durability contract.
    try {
      const dh = await open(dir, "r");
      try {
        await dh.sync();
      } finally {
        await dh.close();
      }
    } catch {
      // best-effort on platforms without directory fsync
    }
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
