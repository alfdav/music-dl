/**
 * Onboarding wizard (onboarding-wizard R1 entry + R2 returning-user + R3
 * prompts + R6 preflight + R7 retry-single-field + R8 atomic commit +
 * R9 logging safety).
 */

import { commitWizardFiles } from "./commit";
import { makeMaskedLineReader } from "./maskedInput";
import {
  PromptCancelError,
  collectBotValues,
  isUserSuppliedField,
  USER_SUPPLIED_FIELDS,
} from "./prompts";
import {
  runPreflight,
  type CheckResult,
  type PreflightDeps,
  type PreflightFieldRef,
} from "./preflight";
import { ensureSharedToken } from "./sharedToken";
import {
  BOT_ENV_KEYS,
  makeLineReader,
  resolveEntryDecision,
  type BotEnvKey,
  type BotEnvShape,
  type LineReader,
  type LineReaderHandle,
} from "./returningUser";

export const WIZARD_HEADER = "music-dl Discord bot setup";

export interface WizardIO {
  stdout: NodeJS.WritableStream;
  stderr: NodeJS.WritableStream;
  stdin: NodeJS.ReadableStream;
}

export interface WizardResult {
  exitCode: number;
}

export interface RunWizardOptions {
  preflightDeps?: PreflightDeps;
}

const defaultIO = (): WizardIO => ({
  stdout: process.stdout,
  stderr: process.stderr,
  stdin: process.stdin,
});

const MAX_RETRY_ROUNDS = 5;

/**
 * Entry point. Returns a WizardResult with an exit code (0 = success,
 * non-zero = failure/cancel).
 */
export async function runWizard(
  io: WizardIO = defaultIO(),
  opts: RunWizardOptions = {},
): Promise<WizardResult> {
  io.stdout.write(`${WIZARD_HEADER}\n`);

  // Single shared reader — see Codex tier-2 P1 finding.
  const lineReader = makeLineReader(io.stdin);
  const readLine = lineReader.read;
  const readMaskedLine = makeMaskedLineReader(io.stdin, lineReader, {
    outputStream: io.stdout,
  });

  const decision = await resolveEntryDecision(io, { readLine });

  if (decision.mode === "keep") {
    io.stdout.write("Keeping existing configuration.\n");
    return { exitCode: 0 };
  }
  if (decision.mode === "cancel") {
    io.stdout.write("Cancelled. No changes made.\n");
    return { exitCode: 130 };
  }

  try {
    return await runFreshOrReconfigure(io, {
      mode: decision.mode,
      defaults: decision.mode === "reconfigure" ? decision.defaults : undefined,
      readLine,
      readMaskedLine,
      preflightDeps: opts.preflightDeps,
      lineReader,
    });
  } catch (err) {
    if (err instanceof PromptCancelError) {
      io.stdout.write("\nCancelled. No changes made.\n");
      return { exitCode: 130 };
    }
    throw err;
  }
}

interface FreshOrReconfigureCtx {
  mode: "fresh" | "reconfigure";
  defaults?: BotEnvShape;
  readLine: LineReader;
  readMaskedLine: LineReader;
  preflightDeps?: PreflightDeps;
  lineReader: LineReaderHandle;
}

async function runFreshOrReconfigure(
  io: WizardIO,
  ctx: FreshOrReconfigureCtx,
): Promise<WizardResult> {
  // 1. Collect user-supplied values.
  const collected = await collectBotValues(io, {
    mode: ctx.mode,
    defaults: ctx.defaults,
    readLine: ctx.readLine,
    readMaskedLine: ctx.readMaskedLine,
  });

  // 2. Ensure a shared token exists (reuse on reconfigure).
  const sharedTokenResult = await ensureSharedToken();
  const values: BotEnvShape = {
    ...collected.fields,
    MUSIC_DL_BOT_TOKEN: sharedTokenResult.token,
  } as BotEnvShape;

  // 3. Preflight loop (R6 + R7).
  for (let round = 0; round < MAX_RETRY_ROUNDS; round++) {
    const results = await runPreflight(values, ctx.preflightDeps);
    const failures = results.filter((r) => !r.passed);

    if (failures.length === 0) break;

    reportPreflightResults(io, results);
    const action = await askRetryAction(
      io,
      ctx.readLine,
      failures,
    );
    if (action.type === "abort") {
      // R7 AC3: user abort → non-zero, no config written.
      io.stdout.write("\nCancelled. No changes made.\n");
      return { exitCode: 130 };
    }
    if (action.type === "retry-all") continue;
    // action.type === "retry-field"
    await promptSingleField(io, values, action.field, ctx);
  }

  // Last check — if we exhausted retries without a clean preflight:
  const finalResults = await runPreflight(values, ctx.preflightDeps);
  if (finalResults.some((r) => !r.passed)) {
    reportPreflightResults(io, finalResults);
    io.stdout.write(
      "\nPreflight still failing after retries. No configuration written.\n",
    );
    return { exitCode: 75 };
  }

  // 4. Atomic commit (R8 AC1).
  await commitWizardFiles(values, sharedTokenResult.token);

  // 5. Print the start command (R8 AC2) — do NOT auto-start (R8 AC3).
  io.stdout.write(
    "\nSetup complete. Start the bot with:\n" +
      "  cd apps/discord-bot && bun run start\n",
  );
  return { exitCode: 0 };
}

function reportPreflightResults(io: WizardIO, results: CheckResult[]): void {
  io.stdout.write("\nPreflight results:\n");
  for (const r of results) {
    const icon = r.passed ? "✓" : "✗";
    io.stdout.write(`  ${icon} ${r.label}\n`);
    if (!r.passed) {
      if (r.errorMessage) io.stderr.write(`    → ${r.errorMessage}\n`);
      if (r.remediation) io.stderr.write(`    → ${r.remediation}\n`);
    }
  }
}

type RetryAction =
  | { type: "retry-all" }
  | { type: "retry-field"; field: BotEnvKey }
  | { type: "abort" };

async function askRetryAction(
  io: WizardIO,
  readLine: LineReader,
  failures: CheckResult[],
): Promise<RetryAction> {
  // Pick the first failure that maps to a user-supplied field for the
  // single-field retry offer (R7 AC1). "env" / "backend" failures are
  // not field-identifiable — offer retry/abort only (R7 AC2).
  const fieldFailure = failures.find(
    (f): f is CheckResult & { field: BotEnvKey } =>
      isUserSuppliedField(f.field),
  );

  if (fieldFailure) {
    io.stdout.write(
      `\nRe-enter ${fieldFailure.field}? [Y]es / [A]bort: `,
    );
    const ans = (await readLine())?.trim().toLowerCase();
    if (ans === null || ans === undefined) return { type: "abort" };
    if (ans === "" || ans === "y" || ans === "yes") {
      return { type: "retry-field", field: fieldFailure.field };
    }
    return { type: "abort" };
  }

  // Field-unidentifiable failure (R7 AC2)
  io.stdout.write("\nRetry preflight? [Y]es / [A]bort: ");
  const ans = (await readLine())?.trim().toLowerCase();
  if (ans === null || ans === undefined) return { type: "abort" };
  if (ans === "" || ans === "y" || ans === "yes") return { type: "retry-all" };
  return { type: "abort" };
}

async function promptSingleField(
  io: WizardIO,
  values: BotEnvShape,
  field: BotEnvKey,
  ctx: FreshOrReconfigureCtx,
): Promise<void> {
  // Leverage collectBotValues by passing defaults for every OTHER field
  // (so only the one missing field gets re-prompted via required-field
  // re-prompt semantics) — but that would re-print every breadcrumb.
  // Simpler and clearer: inline a single prompt here.
  const fieldMeta = USER_SUPPLIED_FIELDS.find((f) => f.key === field);
  if (!fieldMeta) return;
  io.stdout.write(`\n${fieldMeta.breadcrumb}\n`);
  io.stdout.write(`${fieldMeta.label}: `);
  const raw =
    fieldMeta.masked
      ? await ctx.readMaskedLine()
      : await ctx.readLine();
  if (raw === null || raw.trim() === "") {
    throw new PromptCancelError(`No value for ${field}`);
  }
  values[field] = raw.trim();
  void BOT_ENV_KEYS;
}

export type { PreflightFieldRef };
