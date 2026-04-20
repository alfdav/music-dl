/**
 * Onboarding wizard (onboarding-wizard R1 entry + R2 returning-user).
 *
 * Future tasks fill in:
 *   T-004 prompt sequence             T-006 preflight checks
 *   T-008 env file write              T-009 retry-single-field
 *   T-010 logging safety              T-012 atomic two-file commit
 */

import { resolveEntryDecision } from "./returningUser";

export const WIZARD_HEADER = "music-dl Discord bot setup";

export interface WizardIO {
  stdout: NodeJS.WritableStream;
  stderr: NodeJS.WritableStream;
  stdin: NodeJS.ReadableStream;
}

export interface WizardResult {
  exitCode: number;
}

const defaultIO = (): WizardIO => ({
  stdout: process.stdout,
  stderr: process.stderr,
  stdin: process.stdin,
});

/**
 * Entry point. Returns a WizardResult with an exit code (0 = success,
 * non-zero = failure/cancel). Argv-less invocation is required so the
 * backend (onboarding-backend R4) can spawn this as a child process with
 * inherited stdio.
 */
export async function runWizard(
  io: WizardIO = defaultIO(),
): Promise<WizardResult> {
  io.stdout.write(`${WIZARD_HEADER}\n`);

  const decision = await resolveEntryDecision(io);

  if (decision.mode === "keep") {
    io.stdout.write("Keeping existing configuration.\n");
    return { exitCode: 0 };
  }
  if (decision.mode === "cancel") {
    io.stdout.write("Cancelled. No changes made.\n");
    return { exitCode: 130 };
  }

  // decision.mode === "fresh" or "reconfigure" — T-004 replaces this stub.
  io.stdout.write("Not yet implemented.\n");
  return { exitCode: 0 };
}
