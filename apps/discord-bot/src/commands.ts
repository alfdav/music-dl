/**
 * Slash command registration + dispatch (R4).
 *
 * Exactly 11 commands are defined. Each handler runs ensureAuthorized
 * before doing any work, and /play never triggers a download.
 */

import {
  SlashCommandBuilder,
  type ChatInputCommandInteraction,
  type GuildMember,
} from "discord.js";

import type { BotConfig } from "./config";
import type { MusicDlClient, ResolveResult, ResolvedItem } from "./musicDlClient";
import { MusicDlError } from "./musicDlClient";
// re-exported to make MusicDlError available within this module
import type { QueueState, RepeatMode } from "./queue";
import type { VoiceManager, Playback } from "./player";
import { ensureAuthorized } from "./auth";
import { classifyError, ErrorKind, userMessage } from "./errors";

export interface CommandDeps {
  config: BotConfig;
  client: MusicDlClient;
  queue: QueueState;
  voice: VoiceManager;
  playback: Playback;
  logger?: { error: (...args: unknown[]) => void };
}

const REPEAT_CHOICES: ReadonlyArray<{ name: string; value: RepeatMode }> = [
  { name: "off", value: "off" },
  { name: "one", value: "one" },
  { name: "all", value: "all" },
];

/** Definitions for exactly 11 slash commands (R4-AC13). */
export function buildCommands() {
  return [
    new SlashCommandBuilder()
      .setName("summon")
      .setDescription("Join your current voice channel"),
    new SlashCommandBuilder()
      .setName("leave")
      .setDescription("Disconnect and clear playback state"),
    new SlashCommandBuilder()
      .setName("play")
      .setDescription("Resolve and queue a track, playlist, or search result")
      .addStringOption((o) =>
        o.setName("query").setDescription("URL, playlist name, or search text").setRequired(true),
      ),
    new SlashCommandBuilder()
      .setName("pause")
      .setDescription("Pause the current track"),
    new SlashCommandBuilder()
      .setName("resume")
      .setDescription("Resume paused playback"),
    new SlashCommandBuilder()
      .setName("skip")
      .setDescription("Skip to the next queued item"),
    new SlashCommandBuilder()
      .setName("queue")
      .setDescription("Show the current queue"),
    new SlashCommandBuilder()
      .setName("nowplaying")
      .setDescription("Show what is currently playing"),
    new SlashCommandBuilder()
      .setName("volume")
      .setDescription("Set playback volume (0 – 200%)")
      .addIntegerOption((o) =>
        o
          .setName("level")
          .setDescription("Volume level (0 – 200)")
          .setMinValue(0)
          .setMaxValue(200)
          .setRequired(true),
      ),
    new SlashCommandBuilder()
      .setName("repeat")
      .setDescription("Set repeat mode")
      .addStringOption((o) =>
        o
          .setName("mode")
          .setDescription("off | one | all")
          .setRequired(true)
          .addChoices(...REPEAT_CHOICES),
      ),
    new SlashCommandBuilder()
      .setName("download")
      .setDescription("Resolve and explicitly download")
      .addStringOption((o) =>
        o.setName("query").setDescription("URL, playlist name, or search text").setRequired(true),
      ),
  ];
}

/** Names of all commands this bot registers. Exported for test inspection. */
export const COMMAND_NAMES = [
  "summon",
  "leave",
  "play",
  "pause",
  "resume",
  "skip",
  "queue",
  "nowplaying",
  "volume",
  "repeat",
  "download",
] as const;

/**
 * Dispatcher. Called from the interactionCreate handler.
 * Every command enforces the authorization gate before doing anything.
 */
export async function handleInteraction(
  interaction: ChatInputCommandInteraction,
  deps: CommandDeps,
): Promise<void> {
  // R4-AC12: auth gate before every command.
  const authz = ensureAuthorized(interaction, deps.config);
  if (!authz.ok) {
    await safeReply(interaction, { content: authz.message, ephemeral: true });
    return;
  }

  const name = interaction.commandName;
  try {
    switch (name) {
      case "summon":
        return await handleSummon(interaction, deps);
      case "leave":
        return await handleLeave(interaction, deps);
      case "play":
        return await handlePlay(interaction, deps);
      case "pause":
        return await handlePause(interaction, deps);
      case "resume":
        return await handleResume(interaction, deps);
      case "skip":
        return await handleSkip(interaction, deps);
      case "queue":
        return await handleQueue(interaction, deps);
      case "nowplaying":
        return await handleNowPlaying(interaction, deps);
      case "volume":
        return await handleVolume(interaction, deps);
      case "repeat":
        return await handleRepeat(interaction, deps);
      case "download":
        return await handleDownload(interaction, deps);
      default:
        await safeReply(interaction, {
          content: `Unknown command: ${name}`,
          ephemeral: true,
        });
    }
  } catch (error) {
    deps.logger?.error(`command '${name}' failed:`, (error as Error).message);
    await safeReply(interaction, {
      content: userMessage(classifyError(error)),
      ephemeral: true,
    });
  }
}

// ---------------------------------------------------------------------------
// Individual command handlers
// ---------------------------------------------------------------------------

async function handleSummon(
  interaction: ChatInputCommandInteraction,
  deps: CommandDeps,
): Promise<void> {
  const member = interaction.member as GuildMember | null;
  const voiceChannel = member?.voice?.channel ?? null;
  if (!voiceChannel) {
    await safeReply(interaction, {
      content: "Join a voice channel first, then call /summon.",
      ephemeral: true,
    });
    return;
  }
  const textChannel = interaction.channel;
  if (!textChannel) {
    await safeReply(interaction, {
      content: "I can only join when called from a text channel.",
      ephemeral: true,
    });
    return;
  }
  try {
    await deps.voice.join(voiceChannel, textChannel);
    await safeReply(interaction, {
      content: `Joined **${voiceChannel.name}**.`,
    });
  } catch (error) {
    deps.logger?.error("summon failed:", (error as Error).message);
    await safeReply(interaction, {
      content: userMessage(ErrorKind.VoiceConnectionFailed),
      ephemeral: true,
    });
  }
}

async function handleLeave(
  interaction: ChatInputCommandInteraction,
  deps: CommandDeps,
): Promise<void> {
  deps.playback.stop();
  deps.voice.leave();
  await safeReply(interaction, { content: "Left the voice channel." });
}

async function handlePlay(
  interaction: ChatInputCommandInteraction,
  deps: CommandDeps,
): Promise<void> {
  const query = interaction.options.getString("query", true).trim();
  if (!query) {
    await safeReply(interaction, {
      content: "Query cannot be empty.",
      ephemeral: true,
    });
    return;
  }

  // Resolution can take a moment; acknowledge the interaction.
  await interaction.deferReply();

  let result: ResolveResult;
  try {
    result = await deps.client.resolve(query);
  } catch (error) {
    const kind =
      error instanceof MusicDlError && error.code === "unreachable"
        ? ErrorKind.BackendUnavailable
        : ErrorKind.ResolutionFailed;
    await safeEdit(interaction, userMessage(kind));
    return;
  }

  if (result.kind === "choices") {
    // R4-AC3: free-text shows up to 5 visible choices. T-016 adds selection;
    // for now, render the list and direct the user to the picker (coming).
    const choices = result.choices.slice(0, 5);
    if (choices.length === 0) {
      await safeEdit(interaction, "No results found.");
      return;
    }
    if (choices.length === 1) {
      // R8-AC4: single result queues directly without selection.
      await queueAndMaybeStart(interaction, deps, choices, "Queued");
      return;
    }
    const body = formatChoices(choices);
    await safeEdit(interaction, `Found ${choices.length} matches:\n${body}`);
    return;
  }

  // R4-AC3: direct track/playlist queue immediately; NEVER downloads.
  const items = result.items;
  if (items.length === 0) {
    await safeEdit(interaction, "No playable items in that resolution.");
    return;
  }
  const label = result.kind === "playlist" ? "Queued playlist" : "Queued";
  await queueAndMaybeStart(interaction, deps, items, label);
}

async function handlePause(
  interaction: ChatInputCommandInteraction,
  deps: CommandDeps,
): Promise<void> {
  const paused = deps.playback.pause();
  await safeReply(interaction, {
    content: paused ? "Paused." : "Nothing is currently playing.",
  });
}

async function handleResume(
  interaction: ChatInputCommandInteraction,
  deps: CommandDeps,
): Promise<void> {
  const resumed = deps.playback.resume();
  await safeReply(interaction, {
    content: resumed ? "Resumed." : "Nothing to resume.",
  });
}

async function handleSkip(
  interaction: ChatInputCommandInteraction,
  deps: CommandDeps,
): Promise<void> {
  const next = await deps.playback.skip();
  if (!next) {
    await safeReply(interaction, { content: "Queue is empty." });
    return;
  }
  await safeReply(interaction, {
    content: `Skipped → now playing **${next.title ?? next.id}**.`,
  });
}

async function handleQueue(
  interaction: ChatInputCommandInteraction,
  deps: CommandDeps,
): Promise<void> {
  const contents = deps.queue.contents();
  const currentPos = deps.queue.currentIndex();
  if (contents.length === 0) {
    await safeReply(interaction, { content: "Queue is empty." });
    return;
  }
  // Marker is tied to position, not id — duplicates in the queue must not
  // all render as ▶. (Codex-F-T2-003)
  const lines = contents.map((item, i) => {
    const mark = i === currentPos ? "▶" : " ";
    const title = (item as { title?: string }).title ?? item.id;
    const artist = (item as { artist?: string }).artist ?? "";
    return `${mark} ${i + 1}. ${title}${artist ? ` — ${artist}` : ""}`;
  });
  // Discord content cap is 2000 chars; trim conservatively.
  const body = lines.join("\n").slice(0, 1900);
  await safeReply(interaction, { content: "```\n" + body + "\n```" });
}

async function handleNowPlaying(
  interaction: ChatInputCommandInteraction,
  deps: CommandDeps,
): Promise<void> {
  const item = deps.queue.current() as
    | (ResolvedItem & { [k: string]: unknown })
    | null;
  if (!item) {
    await safeReply(interaction, { content: "Nothing playing." });
    return;
  }
  const title = item.title ?? String(item.id);
  const artist = item.artist ?? "Unknown artist";
  const duration = formatDuration(
    typeof item.duration === "number" ? item.duration : undefined,
  );
  await safeReply(interaction, {
    content: `**${title}** — ${artist}${duration ? ` · ${duration}` : ""}`,
  });
}

async function handleVolume(
  interaction: ChatInputCommandInteraction,
  deps: CommandDeps,
): Promise<void> {
  const level = interaction.options.getInteger("level", true);
  // 0–200 percent maps to 0.0–2.0 gain.
  const applied = deps.playback.setVolume(level / 100);
  await safeReply(interaction, {
    content: `Volume set to ${Math.round(applied * 100)}%.`,
  });
}

async function handleRepeat(
  interaction: ChatInputCommandInteraction,
  deps: CommandDeps,
): Promise<void> {
  const mode = interaction.options.getString("mode", true) as RepeatMode;
  deps.queue.setRepeat(mode);
  await safeReply(interaction, { content: `Repeat mode: **${mode}**.` });
}

async function handleDownload(
  interaction: ChatInputCommandInteraction,
  deps: CommandDeps,
): Promise<void> {
  const query = interaction.options.getString("query", true).trim();
  if (!query) {
    await safeReply(interaction, {
      content: "Query cannot be empty.",
      ephemeral: true,
    });
    return;
  }
  await interaction.deferReply();

  let result: ResolveResult;
  try {
    result = await deps.client.resolve(query);
  } catch (error) {
    const kind =
      error instanceof MusicDlError && error.code === "unreachable"
        ? ErrorKind.BackendUnavailable
        : ErrorKind.ResolutionFailed;
    await safeEdit(interaction, userMessage(kind));
    return;
  }

  // Codex-F-T2-002: do not silently pick choices[0] or items[0] when the
  // resolve result is ambiguous or multi-item — the user would get a
  // download they didn't ask for. Require disambiguation for free-text
  // with multiple matches; iterate every track for a playlist.
  let targets: ResolvedItem[];
  if (result.kind === "choices") {
    if (result.choices.length === 0) {
      await safeEdit(interaction, "No downloadable items found.");
      return;
    }
    if (result.choices.length > 1) {
      const body = formatChoices(result.choices.slice(0, 5));
      await safeEdit(
        interaction,
        `Multiple matches — narrow the query or paste a direct URL:\n${body}`,
      );
      return;
    }
    targets = [result.choices[0]];
  } else {
    if (result.items.length === 0) {
      await safeEdit(interaction, "No downloadable items found.");
      return;
    }
    targets = [...result.items];
  }

  const jobs: Array<{ title: string; jobId: string }> = [];
  let firstTriggerError: unknown = null;
  for (const item of targets) {
    try {
      const job = await deps.client.triggerDownload(item.id);
      jobs.push({ title: item.title, jobId: job.job_id });
    } catch (error) {
      deps.logger?.error(
        `download trigger failed for ${item.id}:`,
        (error as Error).message,
      );
      if (firstTriggerError === null) firstTriggerError = error;
    }
  }

  if (jobs.length === 0) {
    // Codex-F-T2-005: surface the real error class instead of hard-coding
    // BackendUnavailable. Auth failures and backend 4xx/5xx were being
    // routed to the wrong message.
    await safeEdit(
      interaction,
      firstTriggerError
        ? userMessage(classifyError(firstTriggerError))
        : userMessage(ErrorKind.Unknown),
    );
    return;
  }

  if (jobs.length === 1) {
    await safeEdit(
      interaction,
      `Download queued for **${jobs[0].title}** (job \`${jobs[0].jobId}\`).`,
    );
    void pollDownload(interaction, deps, jobs[0].jobId, jobs[0].title);
    return;
  }

  // Codex-F-T2-004: multi-item downloads share the single interaction reply,
  // so parallel polls racing to editReply would overwrite each other's status.
  // Poll all jobs and render one aggregated summary per tick.
  void pollBatch(interaction, deps, jobs);
}

// ---------------------------------------------------------------------------
// Helpers
// ---------------------------------------------------------------------------

async function queueAndMaybeStart(
  interaction: ChatInputCommandInteraction,
  deps: CommandDeps,
  items: ResolvedItem[],
  label: string,
): Promise<void> {
  const wasEmpty = deps.queue.length === 0;
  const insertedAt = deps.queue.length;
  deps.queue.append(items as unknown as Parameters<typeof deps.queue.append>[0]);

  // R4-AC3: never triggers a download on /play.
  if (wasEmpty) {
    try {
      await deps.playback.playCurrent();
    } catch (error) {
      // Codex-F-T2-001: if initial playback fails, roll back the append
      // so a later /play can re-trigger playCurrent. Otherwise the failed
      // item wedges the queue and playback stays silent forever.
      deps.logger?.error("play start failed:", (error as Error).message);
      for (let i = deps.queue.length - 1; i >= insertedAt; i--) {
        deps.queue.removeAt(i);
      }
      await safeEdit(interaction, userMessage(classifyError(error)));
      return;
    }
  }

  const headline = items.length === 1
    ? `${label}: **${items[0].title}** — ${items[0].artist}`
    : `${label}: ${items.length} items`;
  await safeEdit(interaction, headline);
}

function formatChoices(choices: ResolvedItem[]): string {
  return choices
    .map(
      (c, i) =>
        `${i + 1}. **${c.title}** — ${c.artist}${c.local ? " _(local)_" : ""}`,
    )
    .join("\n");
}

function formatDuration(seconds: number | undefined): string {
  if (!seconds || !Number.isFinite(seconds) || seconds <= 0) return "";
  const total = Math.floor(seconds);
  const m = Math.floor(total / 60);
  const s = total % 60;
  return `${m}:${s.toString().padStart(2, "0")}`;
}

const TERMINAL_STATUSES = new Set(["completed", "failed"]);
const POLL_INTERVAL_MS = 2_000;
const POLL_MAX_TICKS = 150; // ~5 minutes

async function pollDownload(
  interaction: ChatInputCommandInteraction,
  deps: CommandDeps,
  jobId: string,
  itemTitle: string,
): Promise<void> {
  for (let i = 0; i < POLL_MAX_TICKS; i++) {
    await new Promise((r) => setTimeout(r, POLL_INTERVAL_MS));
    try {
      const status = await deps.client.downloadStatus(jobId);
      if (TERMINAL_STATUSES.has(status.status)) {
        const summary =
          status.status === "completed"
            ? `Download of **${itemTitle}** completed.`
            : `Download of **${itemTitle}** failed.`;
        await safeEdit(interaction, summary);
        return;
      }
    } catch (error) {
      deps.logger?.error("poll error:", (error as Error).message);
      return;
    }
  }
  await safeEdit(interaction, `Download of **${itemTitle}** is still in progress (stopped polling).`);
}

/**
 * Poll a batch of download jobs and render a single aggregated status
 * message as state changes. Prevents concurrent editReply races
 * (Codex-F-T2-004) by funneling every render through the same reply.
 *
 * Each job has its own independent poll loop (Codex-F-T2-009) so a slow
 * or hung status request can't stall updates for the rest of the batch.
 */
async function pollBatch(
  interaction: ChatInputCommandInteraction,
  deps: CommandDeps,
  jobs: ReadonlyArray<{ title: string; jobId: string }>,
): Promise<void> {
  const statuses: string[] = jobs.map(() => "queued");

  const renderSummary = () => {
    const completed = statuses.filter((s) => s === "completed").length;
    const failed = statuses.filter((s) => s === "failed").length;
    const pending = statuses.length - completed - failed;
    const lines = jobs.map(
      (j, idx) => `• ${statuses[idx]}: ${j.title}`,
    );
    return (
      `Batch download (${jobs.length} tracks): ` +
      `${completed} done, ${failed} failed, ${pending} in flight\n` +
      lines.join("\n").slice(0, 1800)
    );
  };

  // Coalesce bursts of per-job renders into one edit per microtask so
  // we don't hammer Discord when several jobs terminate simultaneously.
  let renderScheduled = false;
  const scheduleRender = () => {
    if (renderScheduled) return;
    renderScheduled = true;
    queueMicrotask(() => {
      renderScheduled = false;
      void safeEdit(interaction, renderSummary());
    });
  };

  await safeEdit(interaction, renderSummary());

  await Promise.allSettled(
    jobs.map((job, slot) =>
      pollSingleJob(deps, job, slot, statuses, scheduleRender),
    ),
  );

  await safeEdit(interaction, renderSummary());
}

/**
 * Independent per-job poll loop. Updates `statuses[slot]` in place and
 * invokes `onChange` whenever the slot's value changes.
 *
 * F-T2-006/F-T2-008: distinguishes transient transport errors (kept
 * non-terminal, retried next tick) from permanent backend/auth/parse
 * errors (marked as terminal 'failed' so the user sees the failure).
 */
async function pollSingleJob(
  deps: CommandDeps,
  job: { title: string; jobId: string },
  slot: number,
  statuses: string[],
  onChange: () => void,
): Promise<void> {
  for (let tick = 0; tick < POLL_MAX_TICKS; tick++) {
    await new Promise((r) => setTimeout(r, POLL_INTERVAL_MS));
    if (TERMINAL_STATUSES.has(statuses[slot])) return;

    try {
      const s = await deps.client.downloadStatus(job.jobId);
      if (s.status !== statuses[slot]) {
        statuses[slot] = s.status;
        onChange();
      }
      if (TERMINAL_STATUSES.has(s.status)) return;
    } catch (error) {
      deps.logger?.error(
        `poll failed for ${job.jobId}:`,
        (error as Error).message,
      );
      // F-T2-008: only transport errors retry; permanent errors become
      // terminal so the user isn't left staring at "in flight" forever.
      if (isTransientPollError(error)) continue;
      statuses[slot] = "failed";
      onChange();
      return;
    }
  }
}

function isTransientPollError(error: unknown): boolean {
  if (error instanceof MusicDlError) {
    return error.code === "unreachable";
  }
  // Unknown error shapes default to transient — prefer retrying over
  // marking a running download as permanently failed on ambiguous signals.
  return true;
}

interface ReplyOptions {
  content: string;
  ephemeral?: boolean;
}

async function safeReply(
  interaction: ChatInputCommandInteraction,
  options: ReplyOptions,
): Promise<void> {
  try {
    if (interaction.deferred || interaction.replied) {
      await interaction.editReply({ content: options.content });
    } else {
      await interaction.reply({
        content: options.content,
        ephemeral: options.ephemeral ?? false,
      });
    }
  } catch {
    // nothing more we can do — interaction likely expired.
  }
}

async function safeEdit(
  interaction: ChatInputCommandInteraction,
  content: string,
): Promise<void> {
  try {
    await interaction.editReply({ content });
  } catch {
    // ignore
  }
}
