/**
 * Returning-user detection and Keep/Reconfigure/Cancel prompt
 * (onboarding-wizard R2).
 *
 * Consumed by runWizard() before any prompt sequence. Exports the
 * EntryDecision shape the prompt sequence (T-004) and the two-file
 * commit (T-012) consume.
 */

import { readFile, stat } from "node:fs/promises";

import { getBotEnvPath, getSharedTokenPath } from "./paths";

export const BOT_ENV_KEYS = [
  "DISCORD_TOKEN",
  "DISCORD_APPLICATION_ID",
  "ALLOWED_GUILD_ID",
  "ALLOWED_CHANNEL_ID",
  "ALLOWED_USER_ID",
  "MUSIC_DL_BASE_URL",
  "MUSIC_DL_BOT_TOKEN",
] as const;

export type BotEnvKey = (typeof BOT_ENV_KEYS)[number];
export type BotEnvShape = Record<BotEnvKey, string>;

export type EntryDecision =
  | { mode: "fresh" }
  | { mode: "reconfigure"; defaults: BotEnvShape }
  | { mode: "keep" }
  | { mode: "cancel" };

export interface PromptIO {
  stdout: NodeJS.WritableStream;
  stderr: NodeJS.WritableStream;
  stdin: NodeJS.ReadableStream;
}

export interface DetectOptions {
  envPath?: string;
  tokenPath?: string;
}

/**
 * Load-and-parse the bot env file when it is both present and contains all
 * seven required keys. Returns null if any key is missing/blank or file is
 * absent.
 */
export async function loadBotEnv(
  envPath: string = getBotEnvPath(),
): Promise<BotEnvShape | null> {
  let raw: string;
  try {
    raw = await readFile(envPath, "utf8");
  } catch (err: unknown) {
    if (isNotFound(err)) return null;
    throw err;
  }
  const parsed = parseDotenv(raw);
  const out: Partial<BotEnvShape> = {};
  for (const key of BOT_ENV_KEYS) {
    const v = parsed[key]?.trim();
    if (!v) return null;
    out[key] = v;
  }
  return out as BotEnvShape;
}

/**
 * Returns true when the token file exists and its content is non-empty after trim.
 */
export async function sharedTokenPresent(
  tokenPath: string = getSharedTokenPath(),
): Promise<boolean> {
  try {
    const s = await stat(tokenPath);
    if (!s.isFile() || s.size === 0) return false;
    const body = (await readFile(tokenPath, "utf8")).trim();
    return body.length > 0;
  } catch (err: unknown) {
    if (isNotFound(err)) return false;
    throw err;
  }
}

/**
 * Full R2 flow: detect valid config, prompt Keep/Reconfigure/Cancel, return
 * a decision the caller uses to drive the rest of the wizard. When no valid
 * config exists, returns {mode: "fresh"} with no prompt.
 */
export async function resolveEntryDecision(
  io: PromptIO,
  opts: DetectOptions & { readLine?: LineReader } = {},
): Promise<EntryDecision> {
  const envPath = opts.envPath ?? getBotEnvPath();
  const tokenPath = opts.tokenPath ?? getSharedTokenPath();

  const [env, hasToken] = await Promise.all([
    loadBotEnv(envPath),
    sharedTokenPresent(tokenPath),
  ]);

  if (!env || !hasToken) return { mode: "fresh" };

  const readLine = opts.readLine ?? makeLineReader(io.stdin).read;
  const choice = await promptKeepReconfigureCancel(io, readLine);
  if (choice === "keep") return { mode: "keep" };
  if (choice === "reconfigure") return { mode: "reconfigure", defaults: env };
  return { mode: "cancel" };
}

type KeepReconfigureCancel = "keep" | "reconfigure" | "cancel";

export type LineReader = () => Promise<string | null>;

async function promptKeepReconfigureCancel(
  io: PromptIO,
  readLine: LineReader,
): Promise<KeepReconfigureCancel> {
  io.stdout.write(
    "Existing configuration detected. [K]eep / [R]econfigure / [C]ancel? ",
  );

  for (let attempt = 0; attempt < 3; attempt++) {
    const answer = await readLine();
    if (answer === null) return "cancel"; // EOF → safe default
    const parsed = classify(answer);
    if (parsed !== null) return parsed;
    io.stderr.write(
      `Please answer K (keep), R (reconfigure), or C (cancel).\n`,
    );
  }
  // Three invalid inputs → cancel (safe default; no changes).
  return "cancel";
}

function classify(input: string): KeepReconfigureCancel | null {
  const v = input.trim().toLowerCase();
  if (v === "" || v === "k" || v === "keep") return "keep";
  if (v === "r" || v === "reconfigure") return "reconfigure";
  if (v === "c" || v === "cancel") return "cancel";
  return null;
}

export interface LineReaderHandle {
  read: LineReader;
  pause: () => void;
  resume: () => void;
}

/**
 * Build a reusable line reader over a Readable stream. Accumulates data and
 * hands out one line per call. Returns null on EOF. Avoids readline's
 * single-shot behavior and its quirks with in-memory test streams.
 *
 * Returns a handle that exposes pause()/resume() so a masked reader can
 * temporarily take over stdin without dropping data into the shared buffer
 * (and, critically, without duplicating consumption across competing
 * readers — that was a deterministic bug when two listeners ran side by
 * side on the same stdin).
 */
export function makeLineReader(input: NodeJS.ReadableStream): LineReaderHandle {
  let buffer = "";
  let ended = false;
  let attached = false;
  const pending: Array<() => void> = [];

  input.setEncoding?.("utf8");

  const onData = (chunk: string | Buffer): void => {
    buffer += typeof chunk === "string" ? chunk : chunk.toString("utf8");
    drain();
  };
  const onEnd = (): void => {
    ended = true;
    drain();
  };

  const attach = (): void => {
    if (attached) return;
    input.on("data", onData);
    input.on("end", onEnd);
    attached = true;
  };
  const detach = (): void => {
    if (!attached) return;
    input.off("data", onData);
    input.off("end", onEnd);
    attached = false;
  };

  attach();

  function drain(): void {
    while (pending.length > 0 && (buffer.includes("\n") || ended)) {
      const waiter = pending.shift();
      waiter?.();
    }
  }

  const read: LineReader = () =>
    new Promise<string | null>((resolve) => {
      const tryRead = () => {
        const nl = buffer.indexOf("\n");
        if (nl >= 0) {
          const line = buffer.slice(0, nl).replace(/\r$/, "");
          buffer = buffer.slice(nl + 1);
          resolve(line);
          return true;
        }
        if (ended) {
          if (buffer.length > 0) {
            const line = buffer;
            buffer = "";
            resolve(line);
          } else {
            resolve(null);
          }
          return true;
        }
        return false;
      };
      if (!tryRead()) pending.push(tryRead);
    });

  return { read, pause: detach, resume: attach };
}

/**
 * Minimal dotenv parser — KEY=VALUE per line. Tolerates # comments and
 * surrounding double/single quotes on the value. Does not support escape
 * sequences or multi-line values (not needed for the seven keys we write).
 */
function parseDotenv(raw: string): Record<string, string> {
  const out: Record<string, string> = {};
  for (const rawLine of raw.split(/\r?\n/)) {
    const line = rawLine.trim();
    if (!line || line.startsWith("#")) continue;
    const eq = line.indexOf("=");
    if (eq < 0) continue;
    const key = line.slice(0, eq).trim();
    let value = line.slice(eq + 1).trim();
    if (
      (value.startsWith('"') && value.endsWith('"')) ||
      (value.startsWith("'") && value.endsWith("'"))
    ) {
      value = value.slice(1, -1);
    }
    if (key) out[key] = value;
  }
  return out;
}

function isNotFound(err: unknown): boolean {
  return (
    typeof err === "object" &&
    err !== null &&
    "code" in err &&
    (err as { code: string }).code === "ENOENT"
  );
}
