/**
 * Onboarding wizard — T-001 scaffolding (onboarding-wizard R1).
 *
 * Future tasks fill in:
 *   T-002 returning-user detection    T-003 shared-token generation
 *   T-004 prompt sequence             T-006 preflight checks
 *   T-008 env file write              T-009 retry-single-field
 *   T-010 logging safety              T-012 atomic two-file commit
 */

export const WIZARD_HEADER = "music-dl Discord bot setup";

export interface WizardIO {
  stdout: NodeJS.WritableStream;
  stderr: NodeJS.WritableStream;
  stdin: NodeJS.ReadableStream;
}

const defaultIO = (): WizardIO => ({
  stdout: process.stdout,
  stderr: process.stderr,
  stdin: process.stdin,
});

/**
 * Entry point. Returns an exit code (0 = success, non-zero = failure/cancel).
 * Argv-less invocation is required so the backend (onboarding-backend R4) can
 * spawn this as a child process with inherited stdio.
 */
export async function runWizard(io: WizardIO = defaultIO()): Promise<number> {
  io.stdout.write(`${WIZARD_HEADER}\n`);
  io.stdout.write("Not yet implemented.\n");
  return 0;
}
