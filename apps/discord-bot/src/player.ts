/**
 * Voice lifecycle manager (R6).
 *
 * Manages joining/leaving voice channels, bounded reconnect retries,
 * and enforces one-voice-channel-per-guild constraint.
 */

import {
  joinVoiceChannel,
  VoiceConnectionStatus,
  entersState,
  createAudioPlayer,
  type VoiceConnection,
  type AudioPlayer,
} from "@discordjs/voice";
import type { VoiceBasedChannel, TextBasedChannel } from "discord.js";

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
    // R6: at most one voice channel at a time
    if (this.connection) {
      this.destroyConnection();
    }

    this.textChannel = textChannel;

    const connection = joinVoiceChannel({
      channelId: voiceChannel.id,
      guildId: voiceChannel.guild.id,
      adapterCreator: voiceChannel.guild.voiceAdapterCreator,
    });

    this.connection = connection;
    connection.subscribe(this.player);
    this.attachDisconnectHandler(connection);

    await entersState(connection, VoiceConnectionStatus.Ready, 10_000);
    return connection;
  }

  /** Leave voice and stop playback (R6). */
  leave(): void {
    this.player.stop(true);
    this.destroyConnection();
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
      if (this.textChannel) {
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
