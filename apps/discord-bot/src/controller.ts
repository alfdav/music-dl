import {
  ActionRowBuilder,
  ButtonBuilder,
  ButtonStyle,
  ChannelType,
  MessageFlags,
  ModalBuilder,
  StringSelectMenuBuilder,
  TextInputBuilder,
  TextInputStyle,
  type ButtonInteraction,
  type ChatInputCommandInteraction,
  type Client,
  type Interaction,
  type Message,
  type ModalSubmitInteraction,
  type StringSelectMenuInteraction,
} from "discord.js";
import { mkdir, readFile, writeFile } from "node:fs/promises";
import { dirname, join } from "node:path";

import { ensureAuthorized } from "./auth";
import type { CommandDeps } from "./commands";
import type { ResolvedItem } from "./musicDlClient";
import { getConfigDir } from "./wizard/paths";

const ID = {
  search: "djai:search",
  playPause: "djai:playpause",
  skip: "djai:skip",
  stop: "djai:stop",
  playlists: "djai:playlists",
  queue: "djai:queue",
  repeat: "djai:repeat",
  playlistSelect: "djai:playlist",
  searchModal: "djai:search-modal",
  searchQuery: "query",
  searchResult: "djai:search-result",
} as const;

const pendingSearchChoices = new Map<string, ResolvedItem[]>();

type PanelPayload = {
  content: string;
  components: ActionRowBuilder<ButtonBuilder>[];
};

export function buildControllerPanel(deps: CommandDeps): PanelPayload {
  const current = deps.queue.current();
  const nowPlaying = current
    ? `Now: ${current.title ?? current.id}${current.artist ? ` - ${current.artist}` : ""}`
    : "Now: nothing playing";
  const content = [
    "**DJAI remote**",
    nowPlaying,
    `Queue: ${deps.queue.length}`,
    `Repeat: ${deps.queue.getRepeat()}`,
  ].join("\n");

  const row1 = new ActionRowBuilder<ButtonBuilder>().addComponents(
    new ButtonBuilder().setCustomId(ID.search).setLabel("Search").setEmoji("🔎").setStyle(ButtonStyle.Primary),
    new ButtonBuilder().setCustomId(ID.playPause).setLabel("Play/Pause").setEmoji("⏯️").setStyle(ButtonStyle.Secondary),
    new ButtonBuilder().setCustomId(ID.skip).setLabel("Skip").setEmoji("⏭️").setStyle(ButtonStyle.Secondary),
    new ButtonBuilder().setCustomId(ID.stop).setLabel("Stop").setEmoji("⏹️").setStyle(ButtonStyle.Danger),
  );
  const row2 = new ActionRowBuilder<ButtonBuilder>().addComponents(
    new ButtonBuilder().setCustomId(ID.playlists).setLabel("Playlists").setEmoji("🎛️").setStyle(ButtonStyle.Primary),
    new ButtonBuilder().setCustomId(ID.queue).setLabel("Queue").setEmoji("📜").setStyle(ButtonStyle.Secondary),
    new ButtonBuilder().setCustomId(ID.repeat).setLabel("Repeat").setEmoji("🔁").setStyle(ButtonStyle.Secondary),
  );
  return { content, components: [row1, row2] };
}

export async function handleControllerInteraction(
  interaction: Interaction,
  deps: CommandDeps,
): Promise<boolean> {
  if (
    !interaction.isButton() &&
    !interaction.isStringSelectMenu() &&
    !interaction.isModalSubmit()
  ) {
    return false;
  }

  const customId = interaction.customId;
  if (!customId.startsWith("djai:")) return false;

  const authz = ensureAuthorized(interaction, deps.config);
  if (!authz.ok) {
    await replyPrivate(interaction, "You are not allowed to control DJAI.");
    return true;
  }

  if (interaction.isButton()) {
    await handleButton(interaction, deps);
    return true;
  }
  if (interaction.isStringSelectMenu()) {
    await handleSelect(interaction, deps);
    return true;
  }
  await handleModal(interaction, deps);
  return true;
}

async function handleButton(
  interaction: ButtonInteraction,
  deps: CommandDeps,
): Promise<void> {
  switch (interaction.customId) {
    case ID.search:
      await interaction.showModal(buildSearchModal());
      return;
    case ID.playlists:
      await showPlaylistPicker(interaction, deps);
      return;
    case ID.playPause:
      await interaction.deferUpdate();
      if (!deps.playback.pause()) deps.playback.resume();
      await refreshPanel(interaction, deps);
      return;
    case ID.skip:
      await interaction.deferUpdate();
      await deps.playback.skip();
      await refreshPanel(interaction, deps);
      return;
    case ID.stop:
      await interaction.deferUpdate();
      deps.playback.stop();
      await refreshPanel(interaction, deps);
      return;
    case ID.queue:
      await replyPrivate(interaction, formatQueue(deps));
      return;
    case ID.repeat:
      await interaction.deferUpdate();
      deps.queue.setRepeat(nextRepeat(deps.queue.getRepeat()));
      await refreshPanel(interaction, deps);
      return;
  }
}

async function handleSelect(
  interaction: StringSelectMenuInteraction,
  deps: CommandDeps,
): Promise<void> {
  if (interaction.customId === ID.playlistSelect) {
    await interaction.deferUpdate();
    const playlistId = interaction.values[0];
    const items = await deps.client.playlistItems(playlistId);
    deps.queue.setRepeat("all");
    await queueItemsAndMaybeStart(deps, items);
    await refreshPanel(interaction, deps);
    await interaction.followUp({
      content: `Queued playlist in repeat mode: ${items.length} tracks.`,
      flags: MessageFlags.Ephemeral,
    });
    return;
  }

  if (interaction.customId.startsWith(`${ID.searchResult}:`)) {
    await interaction.deferUpdate();
    const key = interaction.customId.slice(ID.searchResult.length + 1);
    const idx = Number(interaction.values[0]);
    const choice = pendingSearchChoices.get(key)?.[idx];
    pendingSearchChoices.delete(key);
    if (!choice) {
      await interaction.followUp({ content: "Selection expired.", flags: MessageFlags.Ephemeral });
      return;
    }
    await queueItemsAndMaybeStart(deps, [choice]);
    await refreshPanel(interaction, deps);
    await interaction.followUp({
      content: `Queued: **${choice.title}** - ${choice.artist}`,
      flags: MessageFlags.Ephemeral,
    });
  }
}

async function handleModal(
  interaction: ModalSubmitInteraction,
  deps: CommandDeps,
): Promise<void> {
  if (interaction.customId !== ID.searchModal) return;

  const query = interaction.fields.getTextInputValue(ID.searchQuery).trim();
  if (!query) {
    await replyPrivate(interaction, "Search cannot be empty.");
    return;
  }

  await interaction.deferReply({ flags: MessageFlags.Ephemeral });
  const result = await deps.client.resolve(query);
  if (result.kind === "choices") {
    const choices = result.choices.slice(0, 5);
    if (choices.length === 0) {
      await interaction.editReply("No results found.");
      return;
    }
    if (choices.length > 1) {
      const key = interaction.id;
      pendingSearchChoices.set(key, choices);
      await interaction.editReply(buildSearchResults(key, choices));
      return;
    }
    await queueItemsAndMaybeStart(deps, [choices[0]]);
    await refreshPanel(interaction, deps);
    await interaction.editReply(`Queued: **${choices[0].title}** - ${choices[0].artist}`);
    return;
  }

  if (result.kind === "playlist") deps.queue.setRepeat("all");
  await queueItemsAndMaybeStart(deps, result.items);
  await refreshPanel(interaction, deps);
  await interaction.editReply(
    result.kind === "playlist"
      ? `Queued playlist in repeat mode: ${result.items.length} tracks.`
      : `Queued: **${result.items[0]?.title ?? query}**`,
  );
}

export async function queueItemsAndMaybeStart(
  deps: CommandDeps,
  items: ResolvedItem[],
): Promise<void> {
  if (items.length === 0) return;
  const wasEmpty = deps.queue.length === 0;
  deps.queue.append(items as unknown as Parameters<typeof deps.queue.append>[0]);
  if (wasEmpty) await deps.playback.playCurrent();
}

function buildSearchModal(): ModalBuilder {
  return new ModalBuilder()
    .setCustomId(ID.searchModal)
    .setTitle("What do you want to hear?")
    .addComponents(
      new ActionRowBuilder<TextInputBuilder>().addComponents(
        new TextInputBuilder()
          .setCustomId(ID.searchQuery)
          .setLabel("Song, artist, playlist, or URL")
          .setStyle(TextInputStyle.Short)
          .setRequired(true),
      ),
    );
}

async function showPlaylistPicker(
  interaction: ButtonInteraction,
  deps: CommandDeps,
): Promise<void> {
  await interaction.deferReply({ flags: MessageFlags.Ephemeral });
  const playlists = (await deps.client.playlists()).slice(0, 25);
  if (playlists.length === 0) {
    await interaction.editReply("No Tidal playlists found.");
    return;
  }
  const row = new ActionRowBuilder<StringSelectMenuBuilder>().addComponents(
    new StringSelectMenuBuilder()
      .setCustomId(ID.playlistSelect)
      .setPlaceholder("Pick playlist to play on repeat")
      .addOptions(
        playlists.map((playlist) => ({
          label: truncate(playlist.name || "Untitled playlist", 100),
          description: `${playlist.num_tracks} tracks - repeats by default`,
          value: playlist.id,
        })),
      ),
  );
  await interaction.editReply({
    content: "Pick playlist. DJAI will repeat it by default.",
    components: [row],
  });
}

function buildSearchResults(key: string, choices: ResolvedItem[]) {
  const row = new ActionRowBuilder<StringSelectMenuBuilder>().addComponents(
    new StringSelectMenuBuilder()
      .setCustomId(`${ID.searchResult}:${key}`)
      .setPlaceholder("Pick track")
      .addOptions(
        choices.map((choice, i) => ({
          label: truncate(choice.title, 100),
          description: truncate(choice.artist || "Unknown artist", 100),
          value: String(i),
        })),
      ),
  );
  return {
    content: "Pick one:",
    components: [row],
  };
}

async function refreshPanel(
  interaction: ButtonInteraction | StringSelectMenuInteraction | ModalSubmitInteraction,
  deps: CommandDeps,
): Promise<void> {
  if (interaction.message?.editable) {
    await interaction.message.edit(buildControllerPanel(deps));
  }
}

function formatQueue(deps: CommandDeps): string {
  const items = deps.queue.contents();
  if (items.length === 0) return "Queue is empty.";
  return items
    .map((item, i) => `${i + 1}. ${item.title ?? item.id}${item.artist ? ` - ${item.artist}` : ""}`)
    .join("\n")
    .slice(0, 1900);
}

function nextRepeat(mode: "off" | "one" | "all"): "off" | "one" | "all" {
  if (mode === "all") return "one";
  if (mode === "one") return "off";
  return "all";
}

async function replyPrivate(
  interaction: ButtonInteraction | StringSelectMenuInteraction | ModalSubmitInteraction,
  content: string,
): Promise<void> {
  const payload = { content, flags: MessageFlags.Ephemeral as const };
  if (interaction.deferred || interaction.replied) {
    await interaction.followUp(payload);
  } else if ("reply" in interaction && typeof interaction.reply === "function") {
    await interaction.reply(payload);
  } else {
    await interaction.followUp(payload);
  }
}

function truncate(value: string, max: number): string {
  return value.length > max ? value.slice(0, max - 1) : value;
}

interface PanelState {
  channelId: string;
  messageId: string;
}

export function panelStatePath(env: NodeJS.ProcessEnv = process.env): string {
  return join(getConfigDir(env), "discord-bot-panel.json");
}

export async function postOrUpdateControllerPanel(
  client: Client,
  deps: CommandDeps,
  path = panelStatePath(),
): Promise<void> {
  const channel = await client.channels.fetch(deps.config.allowedChannelId);
  if (!channel || channel.type === ChannelType.DM || !("send" in channel)) return;

  const payload = buildControllerPanel(deps);
  const state = await readPanelState(path);
  if (state?.channelId === deps.config.allowedChannelId && "messages" in channel) {
    const previous = await channel.messages.fetch(state.messageId).catch(() => null);
    if (previous) {
      await previous.edit(payload);
      return;
    }
  }

  const sent = (await channel.send(payload)) as Message;
  await writePanelState(path, {
    channelId: deps.config.allowedChannelId,
    messageId: sent.id,
  });
}

async function readPanelState(path: string): Promise<PanelState | null> {
  try {
    const parsed = JSON.parse(await readFile(path, "utf8")) as PanelState;
    if (parsed.channelId && parsed.messageId) return parsed;
  } catch {
    // missing or invalid state means post a fresh panel
  }
  return null;
}

async function writePanelState(path: string, state: PanelState): Promise<void> {
  await mkdir(dirname(path), { recursive: true, mode: 0o700 });
  await writeFile(path, JSON.stringify(state, null, 2) + "\n", { mode: 0o600 });
}
