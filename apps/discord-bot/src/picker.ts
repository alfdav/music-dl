/**
 * Visible picker for free-text search results (R8).
 *
 * Renders up to 5 choices as numbered buttons in the text channel and
 * waits for the invoking user to click one. Single-result is auto-queued
 * before we ever get here (handled by handlePlay), so this module only
 * deals with the N>1 case.
 */

import {
  ActionRowBuilder,
  ButtonBuilder,
  ButtonStyle,
  ComponentType,
  type ChatInputCommandInteraction,
  type ButtonInteraction,
  type Message,
} from "discord.js";

import type { ResolvedItem } from "./musicDlClient";

export interface PickerOptions {
  timeoutMs?: number;
}

const DEFAULT_TIMEOUT_MS = 30_000;
const PICK_PREFIX = "pick";

/**
 * Build the message payload for the picker — the numbered body plus
 * a single ActionRow of N numbered buttons. Pure function, no I/O,
 * so it is testable without a Discord runtime.
 */
export function buildPickerMessage(choices: ResolvedItem[]) {
  const capped = choices.slice(0, 5);
  const lines = capped.map(
    (c, i) =>
      `${i + 1}. **${c.title}** — ${c.artist}${c.local ? " _(local)_" : ""}`,
  );
  const content = `Pick one (auto-cancels in 30s):\n${lines.join("\n")}`;

  const row = new ActionRowBuilder<ButtonBuilder>().addComponents(
    ...capped.map((_, i) =>
      new ButtonBuilder()
        .setCustomId(`${PICK_PREFIX}:${i}`)
        .setLabel(`${i + 1}`)
        .setStyle(ButtonStyle.Primary),
    ),
  );
  return { content, components: [row] };
}

/** Disabled-buttons payload used after selection or timeout. */
function buildDisabledMessage(
  choices: ResolvedItem[],
  headline: string,
  selectedIdx: number | null,
) {
  const capped = choices.slice(0, 5);
  const lines = capped.map((c, i) => {
    const mark = i === selectedIdx ? "✓" : "";
    return `${i + 1}. **${c.title}** — ${c.artist}${c.local ? " _(local)_" : ""}${mark ? `  ${mark}` : ""}`;
  });
  const row = new ActionRowBuilder<ButtonBuilder>().addComponents(
    ...capped.map((_, i) =>
      new ButtonBuilder()
        .setCustomId(`${PICK_PREFIX}:${i}`)
        .setLabel(`${i + 1}`)
        .setStyle(
          i === selectedIdx ? ButtonStyle.Success : ButtonStyle.Secondary,
        )
        .setDisabled(true),
    ),
  );
  return { content: `${headline}\n${lines.join("\n")}`, components: [row] };
}

export interface PickerResult {
  choice: ResolvedItem;
  index: number;
  buttonInteraction: ButtonInteraction;
}

/**
 * Present the picker and await the invoking user's click.
 *
 * Returns the selected choice on pick, or `null` on timeout / collector
 * failure. The reply message is edited to reflect either the selection
 * or the timeout — callers don't need to message the channel themselves.
 */
export async function runPicker(
  interaction: ChatInputCommandInteraction,
  choices: ResolvedItem[],
  options: PickerOptions = {},
): Promise<PickerResult | null> {
  const capped = choices.slice(0, 5);
  if (capped.length === 0) return null;

  const payload = buildPickerMessage(capped);
  // editReply returns the Message we can attach a component collector to.
  const message = (await interaction.editReply(payload)) as Message;

  const timeoutMs = options.timeoutMs ?? DEFAULT_TIMEOUT_MS;
  try {
    const clicked = await message.awaitMessageComponent({
      componentType: ComponentType.Button,
      time: timeoutMs,
      filter: (i) =>
        i.user.id === interaction.user.id &&
        typeof i.customId === "string" &&
        i.customId.startsWith(`${PICK_PREFIX}:`),
    });

    // F-T3-001: acknowledge the button click BEFORE editing the original
    // command reply. Editing via interaction.editReply doesn't satisfy
    // Discord's 3-second response budget for the click itself, so without
    // this the user sees "interaction failed" under API latency spikes.
    try {
      await clicked.deferUpdate();
    } catch {
      // already acknowledged / expired — continue anyway
    }

    const idx = parsePickIndex(clicked.customId, capped.length);
    if (idx === null) {
      await interaction.editReply(
        buildDisabledMessage(capped, "Invalid selection.", null),
      );
      return null;
    }

    const choice = capped[idx];
    await interaction.editReply(
      buildDisabledMessage(capped, `Queued: **${choice.title}** — ${choice.artist}`, idx),
    );
    return { choice, index: idx, buttonInteraction: clicked };
  } catch {
    // awaitMessageComponent rejects on timeout.
    await interaction.editReply(
      buildDisabledMessage(capped, "Selection timed out — nothing queued.", null),
    );
    return null;
  }
}

function parsePickIndex(customId: string, max: number): number | null {
  const parts = customId.split(":");
  if (parts.length !== 2 || parts[0] !== PICK_PREFIX) return null;
  const n = Number(parts[1]);
  if (!Number.isInteger(n) || n < 0 || n >= max) return null;
  return n;
}
