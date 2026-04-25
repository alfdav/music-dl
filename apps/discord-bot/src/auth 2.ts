/**
 * Authorization gate (R2).
 *
 * Every slash command is checked against the allowed guild, channel,
 * and user. All three must match — commands from unauthorized contexts
 * are rejected with an ephemeral private error.
 */

import type { BotConfig } from "./config";

export interface InteractionLike {
  guildId: string | null;
  channelId: string | null;
  user: { id: string };
}

export type AuthResult =
  | { ok: true }
  | { ok: false; reason: "wrong_guild" | "wrong_channel" | "wrong_user"; message: string };

/**
 * Check whether an interaction is authorized.
 *
 * Returns a discriminated result so callers can choose how to respond
 * (typically: ephemeral reply with `message`).
 */
export function ensureAuthorized(
  interaction: InteractionLike,
  config: BotConfig,
): AuthResult {
  if (interaction.guildId !== config.allowedGuildId) {
    return {
      ok: false,
      reason: "wrong_guild",
      message: "This bot is not authorized to operate in this server.",
    };
  }
  if (interaction.channelId !== config.allowedChannelId) {
    return {
      ok: false,
      reason: "wrong_channel",
      message: "Please use the designated channel for this bot.",
    };
  }
  if (interaction.user.id !== config.allowedUserId) {
    return {
      ok: false,
      reason: "wrong_user",
      message: "You are not authorized to use this bot.",
    };
  }
  return { ok: true };
}
