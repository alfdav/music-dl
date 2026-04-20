/**
 * Voice lifecycle + audio playback pipeline (R5, R6).
 *
 * VoiceManager owns the Discord voice connection and AudioPlayer lifecycle.
 * Playback composes VoiceManager + QueueState + MusicDlClient to turn queued
 * items into audio streams. Media is only ever fetched through MusicDlClient
 * — the bot never touches the filesystem directly and never talks to remote
 * music services directly (R5-AC6, R5-AC7).
 */

import {
  joinVoiceChannel,
  getVoiceConnection,
  VoiceConnectionStatus,
  AudioPlayerStatus,
  entersState,
  createAudioPlayer,
  createAudioResource,
  type VoiceConnection,
  type AudioPlayer,
  type AudioResource,
} from "@discordjs/voice";
import type { VoiceBasedChannel, TextBasedChannel } from "discord.js";
import type { MusicDlClient } from "./musicDlClient";
import type { QueueState, QueueItem } from "./queue";

export interface VoiceManagerOptions {
  maxReconnectRetries?: number;
  reconnectTimeoutMs?: number;
}

const DEFAULT_MAX_RETRIES = 3;
const DEFAULT_RECONNECT_TIMEOUT_MS = 5_000;

export class VoiceManager {
  private connection: VoiceConnection | null = null;
  private player: AudioPlayer;
  private textChannel: TextBasedChannel | null = null;
  private maxRetries: number;
  private reconnectTimeoutMs: number;

  constructor(options: VoiceManagerOptions = {}) {
    this.maxRetries = options.maxReconnectRetries ?? DEFAULT_MAX_RETRIES;
    this.reconnectTimeoutMs = options.reconnectTimeoutMs ?? DEFAULT_RECONNECT_TIMEOUT_MS;
    this.player = createAudioPlayer();
  }

  getPlayer(): AudioPlayer {
    return this.player;
  }

  getTextChannel(): TextBasedChannel | null {
    return this.textChannel;
  }

  isConnected(): boolean {
    return (
      this.connection !== null &&
      this.connection.state.status !== VoiceConnectionStatus.Destroyed
    );
  }

  /** Join a voice channel (R6). Destroys existing connection first. */
  async join(
    voiceChannel: VoiceBasedChannel,
    textChannel: TextBasedChannel,
  ): Promise<VoiceConnection> {
    // R6: at most one voice channel at a time. Also handles "ghost"
    // sessions where a previous bot process died mid-join: Discord
    // holds the voice session for ~60s, so a fresh process must
    // actively clean it up before joining.
    this.destroyConnection();
    const ghost = getVoiceConnection(voiceChannel.guild.id);
    if (ghost) {
      try { ghost.destroy(); } catch { /* already gone */ }
    }

    this.textChannel = textChannel;

    const connection = joinVoiceChannel({
      channelId: voiceChannel.id,
      guildId: voiceChannel.guild.id,
      adapterCreator: voiceChannel.guild.voiceAdapterCreator,
      debug: true,
    });

    this.connection = connection;
    connection.subscribe(this.player);
    this.attachDisconnectHandler(connection);

    // Diagnostic: log every voice connection state transition so we can
    // see where the handshake stalls (Signalling → Connecting → Ready).
    connection.on("stateChange" as any, (oldState: any, newState: any) => {
      console.error(
        `[voice] state: ${oldState.status} → ${newState.status}`,
      );
    });
    connection.on("error" as any, (err: Error) => {
      console.error("[voice] connection error:", err);
    });
    connection.on("debug" as any, (msg: string) => {
      console.error("[voice:debug]", msg);
    });

    try {
      // Bumped from 10s to 30s: cold native-opus init on first join can
      // take longer than the default entersState window, especially when
      // Bun has to load sodium-native for the first time.
      await entersState(connection, VoiceConnectionStatus.Ready, 30_000);
    } catch (error) {
      // Connection never reached Ready — destroy so we don't leak a
      // half-open session that blocks future /summon attempts.
      try { connection.destroy(); } catch { /* already gone */ }
      this.connection = null;
      throw error;
    }
    return connection;
  }

  /** Leave voice and stop playback (R6). */
  leave(guildId?: string): void {
    this.player.stop(true);
    this.destroyConnection();
    // Also destroy any guild-level connection we don't have cached, so
    // /leave reliably detaches ghost sessions from a prior process.
    if (guildId) {
      const other = getVoiceConnection(guildId);
      if (other) {
        try { other.destroy(); } catch { /* already gone */ }
      }
    }
    this.textChannel = null;
  }

  /** Bounded reconnect on unexpected disconnect (R6). */
  private attachDisconnectHandler(connection: VoiceConnection): void {
    connection.on("stateChange" as any, async (_: any, newState: any) => {
      if (newState.status !== VoiceConnectionStatus.Disconnected) return;

      let retries = 0;
      while (retries < this.maxRetries) {
        retries++;
        try {
          await entersState(connection, VoiceConnectionStatus.Connecting, this.reconnectTimeoutMs);
          await entersState(connection, VoiceConnectionStatus.Ready, this.reconnectTimeoutMs);
          return;
        } catch {
          // retry
        }
      }

      // R6: all retries exhausted — report in text channel
      this.destroyConnection();
      if (this.textChannel && "send" in this.textChannel) {
        try {
          await this.textChannel.send(
            `Lost voice connection and couldn't reconnect after ${this.maxRetries} attempts. Use /summon to reconnect.`,
          );
        } catch {
          // nothing more to do
        }
      }
    });
  }

  private destroyConnection(): void {
    if (this.connection) {
      try {
        this.connection.destroy();
      } catch {
        // already destroyed
      }
      this.connection = null;
    }
  }
}

// ---------------------------------------------------------------------------
// Audio playback pipeline (R5)
// ---------------------------------------------------------------------------

export interface PlaybackOptions {
  logger?: {
    error: (...args: unknown[]) => void;
  };
}

/**
 * Wires QueueState + MusicDlClient to the VoiceManager's AudioPlayer.
 *
 * Playback listens for the player's transition to Idle (= track end) and
 * advances the queue per its current repeat mode. A `stopping` flag lets
 * us distinguish a user-initiated stop (from /leave) from a natural end.
 */
export class Playback {
  private currentResource: AudioResource | null = null;
  private currentVolume = 1.0;
  private stopping = false;
  private readonly logger: { error: (...args: unknown[]) => void };

  constructor(
    private readonly voice: VoiceManager,
    private readonly queue: QueueState,
    private readonly client: MusicDlClient,
    options: PlaybackOptions = {},
  ) {
    this.logger = options.logger ?? { error: (...a) => console.error(...a) };

    const player = this.voice.getPlayer();
    // R5-AC3: on track end, advance the queue per repeat mode.
    player.on(AudioPlayerStatus.Idle, (oldState, _newState) => {
      if (oldState.status === AudioPlayerStatus.Idle) return; // not a transition
      void this.handleTrackEnd();
    });
    // R5-AC5: track failure → log + advance.
    player.on("error", (error) => {
      this.logger.error("audio player error:", (error as Error).message);
      void this.handleTrackEnd();
    });
  }

  /** Current queue item, or null if nothing queued. */
  current(): QueueItem | null {
    return this.queue.current();
  }

  /** Start playing the queue's current item. Returns metadata on success. */
  async playCurrent(): Promise<QueueItem | null> {
    const item = this.queue.current();
    if (!item) {
      this.stopInternal();
      return null;
    }

    // R5-AC1: fetch playable source URL from backend.
    // R5-AC6/AC7: always through MusicDlClient, never direct.
    const playable = await this.client.playable(item.id);
    const absoluteUrl = this.client.absolutize(playable.url);

    const resource = createAudioResource(absoluteUrl, {
      inlineVolume: true,
      inputType: undefined,
    });
    resource.volume?.setVolume(this.currentVolume);

    this.currentResource = resource;
    this.stopping = false;
    this.voice.getPlayer().play(resource); // R5-AC2
    return item;
  }

  /** Pause playback. Returns true if a pause actually took effect. */
  pause(): boolean {
    return this.voice.getPlayer().pause();
  }

  /** Resume paused playback. */
  resume(): boolean {
    return this.voice.getPlayer().unpause();
  }

  /** Skip to the next queue item per current repeat mode. */
  async skip(): Promise<QueueItem | null> {
    const next = this.queue.advance();
    if (!next) {
      this.stopInternal();
      return null;
    }
    return this.playCurrent();
  }

  /**
   * Stop playback and clear queue state.
   * Called on /leave — disables auto-advance for this stop.
   */
  stop(): void {
    this.queue.clear();
    this.stopInternal();
  }

  /**
   * Set playback volume (0.0 – 2.0). Applied to current and future resources.
   * Values are clamped to the supported range.
   */
  setVolume(fraction: number): number {
    const clamped = Math.max(0, Math.min(2, fraction));
    this.currentVolume = clamped;
    this.currentResource?.volume?.setVolume(clamped);
    return clamped;
  }

  getVolume(): number {
    return this.currentVolume;
  }

  private stopInternal(): void {
    this.stopping = true;
    this.currentResource = null;
    try {
      this.voice.getPlayer().stop(true);
    } catch {
      // player may already be idle
    }
  }

  /**
   * Handle an Idle transition (track end or player error).
   *
   * Retries up to MAX_ADVANCE_CHAIN consecutive failures before giving up,
   * so a single bad item can't stall the queue but a persistently failing
   * source (or repeat-one of a broken item) can't trap us in infinite retry.
   */
  private async handleTrackEnd(): Promise<void> {
    if (this.stopping) {
      // User-initiated stop — don't auto-advance. Re-arm for next play.
      this.stopping = false;
      return;
    }

    const MAX_ADVANCE_CHAIN = 5;
    for (let attempt = 0; attempt < MAX_ADVANCE_CHAIN; attempt++) {
      // R5-AC3: auto-advance per repeat mode.
      const next = this.queue.advance();
      if (!next) {
        // R5-AC4: queue exhausted (repeat off, last item) — stop cleanly.
        this.currentResource = null;
        return;
      }

      try {
        await this.playCurrent();
        return;
      } catch (error) {
        // R5-AC5: playback-start failure → log, try the next item.
        this.logger.error(
          "failed to start next item, advancing:",
          (error as Error).message,
        );
      }
    }

    this.logger.error(
      `gave up after ${MAX_ADVANCE_CHAIN} consecutive failures`,
    );
    this.currentResource = null;
  }
}
