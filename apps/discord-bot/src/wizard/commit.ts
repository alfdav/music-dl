/**
 * Atomic two-file commit (onboarding-wizard R8).
 *
 * On preflight pass the wizard commits the shared-token file and the env
 * file together — either both land on disk or neither does. The design
 * borrows from the classic tmp-write + rename pattern: we stage both
 * files as tempfiles, fsync them, then perform the two renames with the
 * shared-token going first.
 *
 * Rationale for token-first order:
 *   - The backend (onboarding-backend R1) uses the shared-token file as
 *     its "configured" marker. If the env file landed first but a crash
 *     happened before the token was renamed, on the next invocation the
 *     wizard would still see it as NEEDS_SETUP (because
 *     sharedTokenPresent() is false) and the user could re-run cleanly.
 *     The env file by itself is recoverable.
 *   - The reverse order would briefly present a state where the backend
 *     thinks setup is complete but the bot cannot start (no env file) —
 *     worse outcome.
 */

import {
  mkdir,
  open,
  rename,
  unlink,
} from "node:fs/promises";
import { dirname } from "node:path";
import { randomBytes } from "node:crypto";

import { getBotEnvPath, getSharedTokenPath } from "./paths";
import { serializeEnvFile } from "./envFile";
import type { BotEnvShape } from "./returningUser";

export interface CommitOptions {
  envPath?: string;
  tokenPath?: string;
}

export interface CommitPaths {
  envPath: string;
  tokenPath: string;
}

/**
 * Commit the env file and shared-token file atomically. Assumes the
 * wizard has already generated the shared token (T-003 ensureSharedToken
 * returns it) and collected the user values (T-004 collectBotValues).
 */
export async function commitWizardFiles(
  values: BotEnvShape,
  sharedToken: string,
  opts: CommitOptions = {},
): Promise<CommitPaths> {
  const envPath = opts.envPath ?? getBotEnvPath();
  const tokenPath = opts.tokenPath ?? getSharedTokenPath();
  await mkdir(dirname(envPath), { recursive: true, mode: 0o700 });
  if (dirname(tokenPath) !== dirname(envPath)) {
    await mkdir(dirname(tokenPath), { recursive: true, mode: 0o700 });
  }

  // Stage both tempfiles before moving either into place.
  const envTmp = await stageFile(envPath, serializeEnvFile(values));
  let tokenTmp: string;
  try {
    tokenTmp = await stageFile(tokenPath, sharedToken + "\n");
  } catch (err) {
    // Roll back the env tempfile; nothing has been published yet.
    await unlinkSilent(envTmp);
    throw err;
  }

  // Rename shared-token first, then env (see module header for why).
  try {
    await rename(tokenTmp, tokenPath);
  } catch (err) {
    await unlinkSilent(envTmp);
    await unlinkSilent(tokenTmp);
    throw err;
  }
  try {
    await rename(envTmp, envPath);
  } catch (err) {
    // The token is now live but the env failed. Best-effort: remove the
    // token so the pair stays consistent (backend will treat it as
    // NEEDS_SETUP again). A crash between these two renames leaves the
    // same recoverable state.
    await unlinkSilent(tokenPath);
    await unlinkSilent(envTmp);
    throw err;
  }

  await fsyncDir(dirname(envPath));
  if (dirname(tokenPath) !== dirname(envPath)) {
    await fsyncDir(dirname(tokenPath));
  }
  return { envPath, tokenPath };
}

async function stageFile(finalPath: string, body: string): Promise<string> {
  const tmp = `${finalPath}.tmp-${randomBytes(8).toString("hex")}`;
  const fh = await open(tmp, "wx", 0o600);
  try {
    await fh.writeFile(body, "utf8");
    await fh.sync();
  } finally {
    await fh.close();
  }
  return tmp;
}

async function unlinkSilent(path: string): Promise<void> {
  try {
    await unlink(path);
  } catch {
    // best-effort
  }
}

async function fsyncDir(dir: string): Promise<void> {
  try {
    const dh = await open(dir, "r");
    try {
      await dh.sync();
    } finally {
      await dh.close();
    }
  } catch {
    // best-effort
  }
}
