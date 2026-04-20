/**
 * Preflight checks for the onboarding wizard (onboarding-wizard R6).
 *
 * Validates every collected value against reality BEFORE any file write.
 * Each check reports which field (if any) it tied to so T-009 can offer
 * re-entry of that single field instead of restarting the whole sequence.
 *
 * Every check is dependency-injectable so tests can cover the orchestrator
 * without hitting Discord or the backend, and so T-010 (secret logging
 * audit) can verify no check output leaks tokens.
 */

import { execFile } from "node:child_process";
import { dirname } from "node:path";
import { fileURLToPath } from "node:url";

import type { BotEnvKey, BotEnvShape } from "./returningUser";

export type PreflightFieldRef = BotEnvKey | "env" | "backend";

export interface CheckResult {
  id: string;
  label: string;
  passed: boolean;
  /** Which field (if any) the user should re-enter on failure. "env" /
   *  "backend" mean the failure is not tied to a user-supplied field. */
  field: PreflightFieldRef;
  errorMessage?: string;
  remediation?: string;
}

export interface PreflightDeps {
  nodeVersion?: () => string;
  hasLibsodium?: () => Promise<boolean>;
  hasFfmpeg?: () => Promise<boolean>;
  hasOpus?: () => Promise<boolean>;
  fetchImpl?: typeof fetch;
}

const MIN_NODE_MAJOR = 18;

/**
 * Run all preflight checks in dependency order. Short-circuits none — all
 * failures are returned so the user can see the full list at once.
 */
export async function runPreflight(
  values: BotEnvShape,
  deps: PreflightDeps = {},
): Promise<CheckResult[]> {
  const results: CheckResult[] = [];
  results.push(checkNodeVersion(deps.nodeVersion));
  results.push(await checkLibsodium(deps.hasLibsodium));
  results.push(await checkFfmpeg(deps.hasFfmpeg));
  results.push(await checkOpus(deps.hasOpus));

  const token = values.DISCORD_TOKEN;
  const appId = values.DISCORD_APPLICATION_ID;
  const guildId = values.ALLOWED_GUILD_ID;
  const channelId = values.ALLOWED_CHANNEL_ID;
  const userId = values.ALLOWED_USER_ID;
  const fetchFn = deps.fetchImpl ?? fetch;

  const tokenCheck = await checkDiscordToken(token, fetchFn);
  results.push(tokenCheck);

  if (tokenCheck.passed) {
    results.push(await checkAppIdMatches(token, appId, fetchFn));
    const guildCheck = await checkGuildReachable(token, guildId, fetchFn);
    results.push(guildCheck);
    if (guildCheck.passed) {
      results.push(
        await checkChannelUsable(token, guildId, channelId, fetchFn),
      );
      results.push(await checkUserInGuild(token, guildId, userId, fetchFn));
      results.push(await checkVoicePermissions(token, guildId, fetchFn));
    }
  }

  results.push(
    await checkBackendReachable(
      values.MUSIC_DL_BASE_URL,
      values.MUSIC_DL_BOT_TOKEN,
      fetchFn,
    ),
  );

  return results;
}

// ----------------------------------------------------------------------
// Environment checks
// ----------------------------------------------------------------------

function checkNodeVersion(provider?: () => string): CheckResult {
  const version = (provider ?? (() => process.version))();
  const m = /^v(\d+)\./.exec(version);
  const major = m ? Number(m[1]) : 0;
  const passed = major >= MIN_NODE_MAJOR;
  return {
    id: "node-version",
    label: `Node.js runtime ≥ ${MIN_NODE_MAJOR}`,
    field: "env",
    passed,
    errorMessage: passed ? undefined : `Found ${version}`,
    remediation: passed
      ? undefined
      : `Install Node.js ${MIN_NODE_MAJOR}+ (e.g. via nvm, fnm, or asdf).`,
  };
}

async function checkLibsodium(
  provider?: () => Promise<boolean>,
): Promise<CheckResult> {
  const ok = await (provider ?? defaultLibsodiumCheck)();
  return {
    id: "libsodium",
    label: "Voice encryption (libsodium-wrappers)",
    field: "env",
    passed: ok,
    remediation: ok
      ? undefined
      : "Reinstall dependencies: `bun install` inside apps/discord-bot.",
  };
}

async function defaultLibsodiumCheck(): Promise<boolean> {
  try {
    const mod: unknown = await import("libsodium-wrappers");
    const anyMod = mod as { ready?: Promise<unknown>; default?: unknown };
    if (anyMod.ready instanceof Promise) {
      await anyMod.ready;
    }
    return true;
  } catch {
    return false;
  }
}

async function checkFfmpeg(
  provider?: () => Promise<boolean>,
): Promise<CheckResult> {
  const ok = await (provider ?? defaultFfmpegCheck)();
  return {
    id: "ffmpeg",
    label: "ffmpeg available on PATH",
    field: "env",
    passed: ok,
    remediation: ok
      ? undefined
      : "Install ffmpeg (`brew install ffmpeg`, `apt install ffmpeg`, etc.) and ensure it is on PATH.",
  };
}

function defaultFfmpegCheck(): Promise<boolean> {
  return new Promise((resolve) => {
    // execFile with a hard-coded binary name + fixed arg list — no shell
    // interpolation, no user input. Safe by construction.
    execFile("ffmpeg", ["-version"], { timeout: 5000 }, (err) => {
      resolve(err === null);
    });
  });
}

async function checkOpus(
  provider?: () => Promise<boolean>,
): Promise<CheckResult> {
  const ok = await (provider ?? defaultOpusCheck)();
  return {
    id: "opus",
    label: "Opus binding (@discordjs/opus) loadable",
    field: "env",
    passed: ok,
    remediation: ok
      ? undefined
      : "Reinstall: `bun install` inside apps/discord-bot (this also rebuilds the native opus binding).",
  };
}

async function defaultOpusCheck(): Promise<boolean> {
  // The bot starts under `node` (package.json `start`: node --import tsx).
  // The wizard itself runs under `bun`, whose NAPI ABI can differ from the
  // prebuilt binary fetched during install (e.g. bun v137 vs Node v25 v141).
  // Checking opus in-process under bun gives a false negative in that case.
  // Shell out to `node` so the check reflects the actual bot runtime.
  const botRoot = dirname(dirname(dirname(fileURLToPath(import.meta.url))));
  return new Promise((resolve) => {
    execFile(
      "node",
      [
        "-e",
        "const m = require('@discordjs/opus'); new m.OpusEncoder(48000, 2);",
      ],
      { cwd: botRoot, timeout: 5000 },
      (err) => resolve(err === null),
    );
  });
}

// ----------------------------------------------------------------------
// Discord checks (via REST)
// ----------------------------------------------------------------------

const DISCORD_API = "https://discord.com/api/v10";

async function discordGet(
  path: string,
  token: string,
  fetchFn: typeof fetch,
): Promise<Response | Error> {
  try {
    return await fetchFn(`${DISCORD_API}${path}`, {
      method: "GET",
      headers: {
        Authorization: `Bot ${token}`,
        "User-Agent": "music-dl-wizard/1.0",
      },
    });
  } catch (err) {
    return err instanceof Error ? err : new Error(String(err));
  }
}

async function checkDiscordToken(
  token: string,
  fetchFn: typeof fetch,
): Promise<CheckResult> {
  const res = await discordGet("/users/@me", token, fetchFn);
  if (res instanceof Error) {
    return {
      id: "discord-token",
      label: "Discord bot token resolves to a valid identity",
      field: "DISCORD_TOKEN",
      passed: false,
      errorMessage: "network error contacting Discord",
      remediation:
        "Check your internet connection and that discord.com is reachable, then retry.",
    };
  }
  if (res.status === 401 || res.status === 403) {
    return {
      id: "discord-token",
      label: "Discord bot token resolves to a valid identity",
      field: "DISCORD_TOKEN",
      passed: false,
      errorMessage: "token rejected",
      remediation:
        "Reset the bot token at https://discord.com/developers/applications → Bot → Reset Token.",
    };
  }
  if (!res.ok) {
    return {
      id: "discord-token",
      label: "Discord bot token resolves to a valid identity",
      field: "DISCORD_TOKEN",
      passed: false,
      errorMessage: `Discord returned HTTP ${res.status}`,
      remediation: "Retry in a moment; if Discord is degraded, wait and retry.",
    };
  }
  return {
    id: "discord-token",
    label: "Discord bot token resolves to a valid identity",
    field: "DISCORD_TOKEN",
    passed: true,
  };
}

async function checkAppIdMatches(
  token: string,
  appId: string,
  fetchFn: typeof fetch,
): Promise<CheckResult> {
  const res = await discordGet("/oauth2/applications/@me", token, fetchFn);
  const label = "Application id matches the bot token";
  if (res instanceof Error || !res.ok) {
    return {
      id: "app-id-match",
      label,
      field: "DISCORD_APPLICATION_ID",
      passed: false,
      errorMessage: "unable to resolve application for this token",
      remediation:
        "Ensure the APPLICATION ID belongs to the same app as the bot token.",
    };
  }
  const body = (await res.json().catch(() => ({}))) as { id?: string };
  if (body.id !== appId) {
    return {
      id: "app-id-match",
      label,
      field: "DISCORD_APPLICATION_ID",
      passed: false,
      errorMessage: "application id does not match the token's application",
      remediation:
        "Copy the Application ID from the same Developer Portal app as the bot token.",
    };
  }
  return {
    id: "app-id-match",
    label,
    field: "DISCORD_APPLICATION_ID",
    passed: true,
  };
}

async function checkGuildReachable(
  token: string,
  guildId: string,
  fetchFn: typeof fetch,
): Promise<CheckResult> {
  const label = "Bot is a member of the allowed guild";
  const res = await discordGet(`/guilds/${guildId}`, token, fetchFn);
  if (res instanceof Error) {
    return {
      id: "guild-reachable",
      label,
      field: "ALLOWED_GUILD_ID",
      passed: false,
      errorMessage: "network error",
      remediation: "Retry after verifying your internet connection.",
    };
  }
  if (res.status === 404 || res.status === 403) {
    return {
      id: "guild-reachable",
      label,
      field: "ALLOWED_GUILD_ID",
      passed: false,
      errorMessage: "bot is not a member of that guild",
      remediation:
        "Invite the bot to the guild using the OAuth2 URL from the Developer Portal, or correct the guild id.",
    };
  }
  if (!res.ok) {
    return {
      id: "guild-reachable",
      label,
      field: "ALLOWED_GUILD_ID",
      passed: false,
      errorMessage: `Discord returned HTTP ${res.status}`,
      remediation: "Wait a moment and retry.",
    };
  }
  return {
    id: "guild-reachable",
    label,
    field: "ALLOWED_GUILD_ID",
    passed: true,
  };
}

async function checkChannelUsable(
  token: string,
  guildId: string,
  channelId: string,
  fetchFn: typeof fetch,
): Promise<CheckResult> {
  const label = "Allowed channel is a text channel in the guild and sendable";
  const res = await discordGet(`/channels/${channelId}`, token, fetchFn);
  if (res instanceof Error || !res.ok) {
    return {
      id: "channel-usable",
      label,
      field: "ALLOWED_CHANNEL_ID",
      passed: false,
      errorMessage: "channel not found or bot cannot view it",
      remediation:
        "Ensure the channel id is correct and the bot has View Channel permission.",
    };
  }
  const body = (await res.json().catch(() => ({}))) as {
    type?: number;
    guild_id?: string;
  };
  // Text-type channel types: GUILD_TEXT=0, GUILD_ANNOUNCEMENT=5.
  const textTypes = new Set([0, 5]);
  if (body.type === undefined || !textTypes.has(body.type)) {
    return {
      id: "channel-usable",
      label,
      field: "ALLOWED_CHANNEL_ID",
      passed: false,
      errorMessage: "channel is not a text channel",
      remediation: "Pick a text channel (right-click → Copy Channel ID).",
    };
  }
  if (body.guild_id !== guildId) {
    return {
      id: "channel-usable",
      label,
      field: "ALLOWED_CHANNEL_ID",
      passed: false,
      errorMessage: "channel is in a different guild",
      remediation: "Use a channel that belongs to the allowed guild.",
    };
  }
  return {
    id: "channel-usable",
    label,
    field: "ALLOWED_CHANNEL_ID",
    passed: true,
  };
}

async function checkUserInGuild(
  token: string,
  guildId: string,
  userId: string,
  fetchFn: typeof fetch,
): Promise<CheckResult> {
  const label = "Allowed user is a member of the guild";
  const res = await discordGet(
    `/guilds/${guildId}/members/${userId}`,
    token,
    fetchFn,
  );
  if (res instanceof Error || res.status === 404) {
    return {
      id: "user-in-guild",
      label,
      field: "ALLOWED_USER_ID",
      passed: false,
      errorMessage: "user is not a member of the allowed guild",
      remediation:
        "Join the guild with the user account whose id you supplied, or correct the user id.",
    };
  }
  if (!res.ok) {
    return {
      id: "user-in-guild",
      label,
      field: "ALLOWED_USER_ID",
      passed: false,
      errorMessage: `Discord returned HTTP ${res.status}`,
      remediation: "Retry after a short wait.",
    };
  }
  return { id: "user-in-guild", label, field: "ALLOWED_USER_ID", passed: true };
}

/** Connect (1 << 20) + Speak (1 << 21) and Administrator (1 << 3). */
const CONNECT_BIT = 1n << 20n;
const SPEAK_BIT = 1n << 21n;
const ADMIN_BIT = 1n << 3n;

async function checkVoicePermissions(
  token: string,
  guildId: string,
  fetchFn: typeof fetch,
): Promise<CheckResult> {
  const label = "Bot has Connect + Speak voice permissions in the guild";
  const res = await discordGet(`/guilds/${guildId}/roles`, token, fetchFn);
  if (res instanceof Error || !res.ok) {
    return {
      id: "voice-perms",
      label,
      field: "ALLOWED_GUILD_ID",
      passed: false,
      errorMessage: "could not read guild roles",
      remediation:
        "Re-invite the bot with the Connect and Speak permissions selected on the OAuth2 URL.",
    };
  }
  const roles = (await res.json().catch(() => [])) as Array<{
    permissions?: string;
  }>;
  let combined = 0n;
  for (const r of roles) {
    if (r.permissions) {
      try {
        combined |= BigInt(r.permissions);
      } catch {
        // skip malformed
      }
    }
  }
  const hasAdmin = (combined & ADMIN_BIT) !== 0n;
  const hasConnect = hasAdmin || (combined & CONNECT_BIT) !== 0n;
  const hasSpeak = hasAdmin || (combined & SPEAK_BIT) !== 0n;
  if (!hasConnect || !hasSpeak) {
    return {
      id: "voice-perms",
      label,
      field: "ALLOWED_GUILD_ID",
      passed: false,
      errorMessage: hasConnect
        ? "bot role lacks Speak"
        : hasSpeak
          ? "bot role lacks Connect"
          : "bot role lacks Connect and Speak",
      remediation:
        "Edit the bot role in the guild and enable Connect + Speak, or re-invite with those permissions.",
    };
  }
  return {
    id: "voice-perms",
    label,
    field: "ALLOWED_GUILD_ID",
    passed: true,
  };
}

// ----------------------------------------------------------------------
// Backend reachability
// ----------------------------------------------------------------------

async function checkBackendReachable(
  baseUrl: string,
  botToken: string,
  fetchFn: typeof fetch,
): Promise<CheckResult> {
  const label = "music-dl backend reachable + shared token accepted";
  try {
    // A bearer-authenticated probe against a bot route. An empty query
    // body is expected to yield 400 — that is PROOF the token was
    // accepted. 401/403 means the backend has not picked up the shared
    // token yet.
    const res = await fetchFn(
      new URL("/api/bot/play/resolve", baseUrl).toString(),
      {
        method: "POST",
        headers: {
          Authorization: `Bearer ${botToken}`,
          "Content-Type": "application/json",
        },
        body: JSON.stringify({ query: "" }),
      },
    );
    if (res.status === 401 || res.status === 403) {
      return {
        id: "backend-reachable",
        label,
        field: "backend",
        passed: false,
        errorMessage:
          "backend rejected the shared token (has it started with this config?)",
        remediation:
          "Restart the music-dl backend so it picks up the new shared token, then retry.",
      };
    }
    if (res.status >= 500) {
      return {
        id: "backend-reachable",
        label,
        field: "backend",
        passed: false,
        errorMessage: `backend returned HTTP ${res.status}`,
        remediation: "Check the backend logs for errors, then retry.",
      };
    }
    return { id: "backend-reachable", label, field: "backend", passed: true };
  } catch {
    return {
      id: "backend-reachable",
      label,
      field: "backend",
      passed: false,
      errorMessage: "backend unreachable",
      remediation: `Start the music-dl backend (\`music-dl gui\`), then retry. Base URL: ${baseUrl}`,
    };
  }
}

// ----------------------------------------------------------------------
// Summary helpers
// ----------------------------------------------------------------------

export function failedChecks(results: CheckResult[]): CheckResult[] {
  return results.filter((r) => !r.passed);
}

export function firstFailedFieldRef(
  results: CheckResult[],
): PreflightFieldRef | null {
  const first = failedChecks(results)[0];
  return first ? first.field : null;
}
