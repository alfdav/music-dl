/**
 * Five-prompt sequence for user-supplied values (onboarding-wizard R3).
 *
 * R3 AC ordering:
 *   1. Discord bot token         — masked input (no echo)
 *   2. Discord application id    — echoed
 *   3. Allowed guild id          — echoed
 *   4. Allowed text-channel id   — echoed
 *   5. Allowed user id           — echoed
 *
 * Each prompt prints a one-line breadcrumb above the input showing where
 * the user can find the value. Empty input on a required field with no
 * default re-prompts until the user enters something.
 */

import type { BotEnvKey, BotEnvShape, PromptIO } from "./returningUser";
import { BOT_ENV_KEYS, makeLineReader, type LineReader } from "./returningUser";

export interface PromptOptions {
  mode: "fresh" | "reconfigure";
  defaults?: BotEnvShape;
  readLine?: LineReader;
  readMaskedLine?: LineReader;
}

interface Field {
  key: BotEnvKey;
  label: string;
  breadcrumb: string;
  masked: boolean;
}

const USER_SUPPLIED_FIELDS: Field[] = [
  {
    key: "DISCORD_TOKEN",
    label: "Discord bot token",
    breadcrumb:
      "Find at https://discord.com/developers/applications → Your App → Bot → Reset Token",
    masked: true,
  },
  {
    key: "DISCORD_APPLICATION_ID",
    label: "Discord application id",
    breadcrumb:
      "Find at https://discord.com/developers/applications → Your App → General Information → Application ID",
    masked: false,
  },
  {
    key: "ALLOWED_GUILD_ID",
    label: "Allowed guild (server) id",
    breadcrumb:
      "Right-click the server icon in Discord (Developer Mode on) → Copy Server ID",
    masked: false,
  },
  {
    key: "ALLOWED_CHANNEL_ID",
    label: "Allowed text-channel id",
    breadcrumb:
      "Right-click the text channel in Discord (Developer Mode on) → Copy Channel ID",
    masked: false,
  },
  {
    key: "ALLOWED_USER_ID",
    label: "Allowed user id (yours)",
    breadcrumb:
      "Right-click your own profile in Discord (Developer Mode on) → Copy User ID",
    masked: false,
  },
];

export interface CollectedValues {
  // The five user-supplied fields, plus MUSIC_DL_BASE_URL (defaulted to
  // loopback unless overridden) and MUSIC_DL_BOT_TOKEN which T-012 writes
  // separately from the shared-token file.
  fields: Record<BotEnvKey, string>;
}

// Guard: the kit lists seven env keys total — five user-supplied + two
// wizard-supplied (MUSIC_DL_BASE_URL default + MUSIC_DL_BOT_TOKEN). If the
// kit's key list ever grows or shrinks, this assertion forces the prompt
// module to be re-read.
const EXPECTED_TOTAL_KEYS = 7;
if (BOT_ENV_KEYS.length !== EXPECTED_TOTAL_KEYS) {
  throw new Error(
    `prompts.ts expected ${EXPECTED_TOTAL_KEYS} bot env keys, found ${BOT_ENV_KEYS.length}`,
  );
}

/**
 * Run the prompt sequence. Returns the collected values. Does not write
 * any files — T-012 will commit them atomically.
 *
 * The caller supplies readLine and readMaskedLine for testability. In
 * production, runWizard() builds readers from process.stdin; in tests the
 * in-memory line reader is used for both and masking is verified via the
 * field descriptor (prompts.ts calls readMaskedLine for the token).
 */
export async function collectBotValues(
  io: PromptIO,
  opts: PromptOptions,
): Promise<CollectedValues> {
  const readLine = opts.readLine ?? makeLineReader(io.stdin);
  const readMaskedLine = opts.readMaskedLine ?? readLine;
  const defaults = opts.defaults ?? ({} as Partial<BotEnvShape>);

  const collected: Partial<Record<BotEnvKey, string>> = {};

  for (const field of USER_SUPPLIED_FIELDS) {
    const existing = opts.mode === "reconfigure" ? defaults[field.key] : undefined;
    collected[field.key] = await promptOne(
      io,
      field,
      existing,
      field.masked ? readMaskedLine : readLine,
    );
  }

  // MUSIC_DL_BASE_URL: defaulted to the backend's loopback bind address.
  // The user can override — not a secret, echoed normally.
  const baseUrlDefault =
    (opts.mode === "reconfigure" && defaults.MUSIC_DL_BASE_URL) ||
    "http://127.0.0.1:8765";
  io.stdout.write("\n");
  io.stdout.write(
    "Where does the music-dl backend listen? (press Enter to accept the default)\n",
  );
  collected.MUSIC_DL_BASE_URL = await promptOne(
    io,
    {
      key: "MUSIC_DL_BASE_URL",
      label: "music-dl backend base URL",
      breadcrumb: `Default: ${baseUrlDefault}`,
      masked: false,
    },
    baseUrlDefault,
    readLine,
  );

  // MUSIC_DL_BOT_TOKEN is filled by the caller from ensureSharedToken().
  // Leave it blank here; runWizard composes them before writing.
  collected.MUSIC_DL_BOT_TOKEN = defaults.MUSIC_DL_BOT_TOKEN ?? "";

  return { fields: collected as Record<BotEnvKey, string> };
}

async function promptOne(
  io: PromptIO,
  field: Field,
  defaultValue: string | undefined,
  readLine: LineReader,
): Promise<string> {
  io.stdout.write(`\n${field.breadcrumb}\n`);
  const defaultHint = defaultValue
    ? ` [${field.masked ? maskForDisplay(defaultValue) : defaultValue}]`
    : "";

  // Re-prompt until we have a non-empty value or the stream ends. An EOF
  // on a required field with no default propagates as empty string; the
  // caller handles that by treating the result as cancelled.
  for (let attempt = 0; attempt < 10; attempt++) {
    io.stdout.write(`${field.label}${defaultHint}: `);
    const raw = await readLine();
    if (raw === null) return defaultValue ?? "";
    const trimmed = raw.trim();
    if (trimmed !== "") return trimmed;
    if (defaultValue) return defaultValue;
    io.stderr.write(
      `${field.label} is required — please enter a value or press Ctrl+C to cancel.\n`,
    );
  }
  return defaultValue ?? "";
}

function maskForDisplay(value: string): string {
  if (value.length <= 4) return "***";
  return `${value.slice(0, 2)}…${value.slice(-2)}`;
}

export function isUserSuppliedField(key: string): boolean {
  return USER_SUPPLIED_FIELDS.some((f) => f.key === key);
}

export { USER_SUPPLIED_FIELDS };
