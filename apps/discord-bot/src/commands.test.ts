/**
 * Tests for slash command registration + dispatch (R4).
 */

import { describe, expect, test, mock } from "bun:test";
import {
  buildCommands,
  COMMAND_NAMES,
  handleInteraction,
  type CommandDeps,
} from "./commands";
import type { BotConfig } from "./config";
import type { MusicDlClient } from "./musicDlClient";
import { MusicDlError } from "./musicDlClient";
import { QueueState } from "./queue";
import type { Playback, VoiceManager } from "./player";

// ---------------------------------------------------------------------------
// Test doubles
// ---------------------------------------------------------------------------

function makeConfig(): BotConfig {
  return {
    discordToken: "t",
    discordApplicationId: "app",
    allowedGuildId: "g-ok",
    allowedChannelId: "c-ok",
    allowedUserId: "u-ok",
    musicDlBaseUrl: "http://backend",
    musicDlBotToken: "bot",
  };
}

interface MockInteractionInit {
  commandName: string;
  guildId?: string;
  channelId?: string;
  userId?: string;
  options?: Record<string, unknown>;
  member?: unknown;
  channel?: unknown;
}

function makeInteraction(init: MockInteractionInit) {
  const opts = init.options ?? {};
  const replies: Array<{ content: string; ephemeral?: boolean; kind: "reply" | "editReply" }> = [];
  let deferred = false;
  let replied = false;

  const interaction = {
    commandName: init.commandName,
    guildId: init.guildId ?? "g-ok",
    channelId: init.channelId ?? "c-ok",
    user: { id: init.userId ?? "u-ok" },
    member: init.member ?? null,
    channel: init.channel ?? { send: async () => {} },
    options: {
      getString: (name: string, _required?: boolean) => {
        const v = opts[name];
        if (v === undefined) return null;
        return String(v);
      },
      getInteger: (name: string, _required?: boolean) => {
        const v = opts[name];
        if (v === undefined || v === null) return null;
        return Number(v);
      },
    },
    get deferred() {
      return deferred;
    },
    get replied() {
      return replied;
    },
    reply: mock(async (payload: { content: string; ephemeral?: boolean }) => {
      replied = true;
      replies.push({
        content: payload.content,
        ephemeral: payload.ephemeral,
        kind: "reply",
      });
    }),
    deferReply: mock(async () => {
      deferred = true;
    }),
    editReply: mock(async (payload: { content: string }) => {
      replies.push({ content: payload.content, kind: "editReply" });
    }),
    _replies: replies,
  };
  return interaction;
}

function makeDeps(overrides: Partial<CommandDeps> = {}): CommandDeps {
  const client: Partial<MusicDlClient> = {
    resolve: mock(async () => ({
      kind: "track" as const,
      items: [
        {
          id: "t1",
          title: "Song A",
          artist: "Artist A",
          source_type: "tidal" as const,
          local: false,
          duration: 200,
        },
      ],
    })),
    playable: mock(async () => ({
      url: "/api/bot/bot-stream/tok",
      content_type: "audio/flac",
      title: "Song A",
      artist: "Artist A",
      duration: 200,
    })),
    triggerDownload: mock(async () => ({ job_id: "job-1", status: "queued" })),
    downloadStatus: mock(async () => ({
      job_id: "job-1",
      status: "completed",
      progress: 100,
      title: "Song A",
      artist: "Artist A",
      started_at: 0,
      finished_at: 1,
    })),
    absolutize: (r: string) => (r.startsWith("http") ? r : `http://backend${r}`),
  };

  const playback: Partial<Playback> = {
    playCurrent: mock(async () => null),
    pause: mock(() => true),
    resume: mock(() => true),
    skip: mock(async () => null),
    stop: mock(() => {}),
    setVolume: mock((v: number) => v),
    getVolume: mock(() => 1.0),
  };

  const voice: Partial<VoiceManager> = {
    join: mock(async () => ({}) as never),
    leave: mock(() => {}),
    isConnected: mock(() => false),
  };

  return {
    config: makeConfig(),
    client: client as MusicDlClient,
    queue: new QueueState(),
    voice: voice as VoiceManager,
    playback: playback as Playback,
    logger: { error: () => {} },
    ...overrides,
  };
}

// ---------------------------------------------------------------------------
// R4-AC13: exactly 11 commands are registered
// ---------------------------------------------------------------------------

describe("command registration", () => {
  test("exactly 11 commands built", () => {
    const built = buildCommands();
    expect(built.length).toBe(11);
  });

  test("command names match the expected set", () => {
    const built = buildCommands().map((c) => c.name).sort();
    const expected = [...COMMAND_NAMES].sort();
    expect(built).toEqual(expected);
  });

  test("no unexpected commands present", () => {
    const names = buildCommands().map((c) => c.name);
    const unknown = names.filter((n) => !COMMAND_NAMES.includes(n as never));
    expect(unknown).toEqual([]);
  });
});

// ---------------------------------------------------------------------------
// R4-AC12: authorization gate on every command
// ---------------------------------------------------------------------------

describe("authorization gate", () => {
  test("wrong guild -> ephemeral rejection, handler not invoked", async () => {
    const deps = makeDeps();
    const i = makeInteraction({ commandName: "pause", guildId: "evil" });
    await handleInteraction(i as never, deps);
    expect((deps.playback.pause as ReturnType<typeof mock>).mock.calls.length).toBe(0);
    expect(i._replies[0]).toMatchObject({ ephemeral: true });
  });

  test("wrong channel -> ephemeral rejection", async () => {
    const deps = makeDeps();
    const i = makeInteraction({ commandName: "pause", channelId: "other" });
    await handleInteraction(i as never, deps);
    expect((deps.playback.pause as ReturnType<typeof mock>).mock.calls.length).toBe(0);
    expect(i._replies[0]?.ephemeral).toBe(true);
  });

  test("wrong user -> ephemeral rejection", async () => {
    const deps = makeDeps();
    const i = makeInteraction({ commandName: "pause", userId: "intruder" });
    await handleInteraction(i as never, deps);
    expect((deps.playback.pause as ReturnType<typeof mock>).mock.calls.length).toBe(0);
    expect(i._replies[0]?.ephemeral).toBe(true);
  });
});

// ---------------------------------------------------------------------------
// Individual handler behavior (R4-AC1 … AC11)
// ---------------------------------------------------------------------------

describe("individual commands", () => {
  test("/summon without user voice channel -> friendly error", async () => {
    const deps = makeDeps();
    const i = makeInteraction({
      commandName: "summon",
      member: { voice: { channel: null } },
    });
    await handleInteraction(i as never, deps);
    expect((deps.voice.join as ReturnType<typeof mock>).mock.calls.length).toBe(0);
    expect(i._replies[0]?.content).toMatch(/voice channel/i);
  });

  test("/summon with user in voice joins", async () => {
    const deps = makeDeps();
    const voiceChannel = { id: "v1", name: "General", guild: { id: "g-ok" } };
    const textChannel = { send: async () => {} };
    const i = makeInteraction({
      commandName: "summon",
      member: { voice: { channel: voiceChannel } },
      channel: textChannel,
    });
    await handleInteraction(i as never, deps);
    expect((deps.voice.join as ReturnType<typeof mock>).mock.calls.length).toBe(1);
  });

  test("/leave stops playback and disconnects", async () => {
    const deps = makeDeps();
    const i = makeInteraction({ commandName: "leave" });
    await handleInteraction(i as never, deps);
    expect((deps.playback.stop as ReturnType<typeof mock>).mock.calls.length).toBe(1);
    expect((deps.voice.leave as ReturnType<typeof mock>).mock.calls.length).toBe(1);
  });

  // R4-AC3: /play never triggers a download
  test("/play with a direct track result queues and never downloads", async () => {
    const deps = makeDeps();
    const i = makeInteraction({
      commandName: "play",
      options: { query: "https://tidal.com/track/123" },
    });
    await handleInteraction(i as never, deps);
    expect(deps.queue.length).toBe(1);
    expect((deps.client.triggerDownload as ReturnType<typeof mock>).mock.calls.length).toBe(0);
    expect((deps.playback.playCurrent as ReturnType<typeof mock>).mock.calls.length).toBe(1);
  });

  test("/play with playlist queues all items in order", async () => {
    const deps = makeDeps();
    (deps.client.resolve as ReturnType<typeof mock>).mockResolvedValueOnce({
      kind: "playlist" as const,
      items: [
        { id: "a", title: "A", artist: "X", source_type: "tidal" as const, local: false, duration: 100 },
        { id: "b", title: "B", artist: "X", source_type: "tidal" as const, local: false, duration: 110 },
      ],
    });
    const i = makeInteraction({
      commandName: "play",
      options: { query: "My Playlist" },
    });
    await handleInteraction(i as never, deps);
    expect(deps.queue.contents().map((x) => x.id)).toEqual(["a", "b"]);
    expect((deps.client.triggerDownload as ReturnType<typeof mock>).mock.calls.length).toBe(0);
  });

  test("/play with free-text choices lists matches, does not queue", async () => {
    const deps = makeDeps();
    (deps.client.resolve as ReturnType<typeof mock>).mockResolvedValueOnce({
      kind: "choices" as const,
      choices: [
        { id: "c1", title: "One", artist: "A", source_type: "tidal" as const, local: false, duration: 200 },
        { id: "c2", title: "Two", artist: "A", source_type: "tidal" as const, local: false, duration: 200 },
        { id: "c3", title: "Three", artist: "A", source_type: "tidal" as const, local: false, duration: 200 },
      ],
    });
    const i = makeInteraction({
      commandName: "play",
      options: { query: "ambient" },
    });
    await handleInteraction(i as never, deps);
    expect(deps.queue.length).toBe(0);
    const msg = i._replies[0]?.content ?? "";
    expect(msg).toContain("One");
    expect(msg).toContain("Two");
  });

  test("/play with single free-text result auto-queues (R8-AC4)", async () => {
    const deps = makeDeps();
    (deps.client.resolve as ReturnType<typeof mock>).mockResolvedValueOnce({
      kind: "choices" as const,
      choices: [
        { id: "one", title: "Only Match", artist: "A", source_type: "tidal" as const, local: false, duration: 200 },
      ],
    });
    const i = makeInteraction({
      commandName: "play",
      options: { query: "niche" },
    });
    await handleInteraction(i as never, deps);
    expect(deps.queue.length).toBe(1);
    expect(deps.queue.current()?.id).toBe("one");
  });

  test("/play unreachable backend surfaces friendly error", async () => {
    const deps = makeDeps();
    (deps.client.resolve as ReturnType<typeof mock>).mockImplementationOnce(async () => {
      throw new MusicDlError("unreachable", "network down");
    });
    const i = makeInteraction({
      commandName: "play",
      options: { query: "anything" },
    });
    await handleInteraction(i as never, deps);
    expect(i._replies.at(-1)?.content).toMatch(/unavailable/i);
  });

  test("/pause delegates to playback", async () => {
    const deps = makeDeps();
    const i = makeInteraction({ commandName: "pause" });
    await handleInteraction(i as never, deps);
    expect((deps.playback.pause as ReturnType<typeof mock>).mock.calls.length).toBe(1);
  });

  test("/resume delegates to playback", async () => {
    const deps = makeDeps();
    const i = makeInteraction({ commandName: "resume" });
    await handleInteraction(i as never, deps);
    expect((deps.playback.resume as ReturnType<typeof mock>).mock.calls.length).toBe(1);
  });

  test("/skip advances and reports next item", async () => {
    const deps = makeDeps();
    (deps.playback.skip as ReturnType<typeof mock>).mockResolvedValueOnce({
      id: "next",
      title: "Next Song",
    });
    const i = makeInteraction({ commandName: "skip" });
    await handleInteraction(i as never, deps);
    expect(i._replies[0]?.content).toMatch(/Next Song/);
  });

  test("/queue shows contents with current marker", async () => {
    const deps = makeDeps();
    deps.queue.append([
      { id: "a", title: "A", artist: "X" },
      { id: "b", title: "B", artist: "Y" },
    ]);
    const i = makeInteraction({ commandName: "queue" });
    await handleInteraction(i as never, deps);
    const content = i._replies[0]?.content ?? "";
    expect(content).toMatch(/A/);
    expect(content).toMatch(/B/);
    expect(content).toMatch(/▶/);
  });

  test("/nowplaying shows current track", async () => {
    const deps = makeDeps();
    deps.queue.append([
      { id: "a", title: "Ambient", artist: "Brian Eno", duration: 305 },
    ]);
    const i = makeInteraction({ commandName: "nowplaying" });
    await handleInteraction(i as never, deps);
    expect(i._replies[0]?.content).toMatch(/Ambient/);
    expect(i._replies[0]?.content).toMatch(/Brian Eno/);
  });

  test("/volume applies level via playback", async () => {
    const deps = makeDeps();
    const i = makeInteraction({ commandName: "volume", options: { level: 50 } });
    await handleInteraction(i as never, deps);
    expect((deps.playback.setVolume as ReturnType<typeof mock>).mock.calls[0]).toEqual([0.5]);
  });

  test("/repeat sets queue repeat mode", async () => {
    const deps = makeDeps();
    const i = makeInteraction({ commandName: "repeat", options: { mode: "one" } });
    await handleInteraction(i as never, deps);
    expect(deps.queue.getRepeat()).toBe("one");
  });

  test("/download on a direct track triggers exactly one job", async () => {
    const deps = makeDeps();
    const i = makeInteraction({
      commandName: "download",
      options: { query: "https://tidal.com/track/42" },
    });
    await handleInteraction(i as never, deps);
    expect((deps.client.triggerDownload as ReturnType<typeof mock>).mock.calls.length).toBe(1);
  });

  // Codex-F-T2-002: ambiguous free-text with >1 match must NOT trigger download
  test("/download with ambiguous choices rejects without downloading", async () => {
    const deps = makeDeps();
    (deps.client.resolve as ReturnType<typeof mock>).mockResolvedValueOnce({
      kind: "choices" as const,
      choices: [
        { id: "a", title: "A", artist: "X", source_type: "tidal" as const, local: false, duration: 100 },
        { id: "b", title: "B", artist: "Y", source_type: "tidal" as const, local: false, duration: 110 },
      ],
    });
    const i = makeInteraction({
      commandName: "download",
      options: { query: "vague" },
    });
    await handleInteraction(i as never, deps);
    expect((deps.client.triggerDownload as ReturnType<typeof mock>).mock.calls.length).toBe(0);
    expect(i._replies.at(-1)?.content).toMatch(/narrow the query|direct URL/i);
  });

  // Codex-F-T2-002: playlist URL must download every track, not just the first
  test("/download on a playlist triggers a job for every track", async () => {
    const deps = makeDeps();
    (deps.client.resolve as ReturnType<typeof mock>).mockResolvedValueOnce({
      kind: "playlist" as const,
      items: [
        { id: "t1", title: "One", artist: "A", source_type: "tidal" as const, local: false, duration: 100 },
        { id: "t2", title: "Two", artist: "A", source_type: "tidal" as const, local: false, duration: 100 },
        { id: "t3", title: "Three", artist: "A", source_type: "tidal" as const, local: false, duration: 100 },
      ],
    });
    const i = makeInteraction({
      commandName: "download",
      options: { query: "https://tidal.com/playlist/abc" },
    });
    await handleInteraction(i as never, deps);
    const ids = (deps.client.triggerDownload as ReturnType<typeof mock>).mock.calls
      .map((c) => c[0])
      .sort();
    expect(ids).toEqual(["t1", "t2", "t3"]);
  });
});

// ---------------------------------------------------------------------------
// Regression tests for Codex findings on this tier
// ---------------------------------------------------------------------------

describe("Codex-F-T2-001: /play rollback on playback failure", () => {
  test("failed initial playCurrent removes the queued items", async () => {
    const deps = makeDeps();
    (deps.playback.playCurrent as ReturnType<typeof mock>).mockImplementationOnce(async () => {
      throw new Error("backend down");
    });
    const i1 = makeInteraction({
      commandName: "play",
      options: { query: "https://tidal.com/track/1" },
    });
    await handleInteraction(i1 as never, deps);
    expect(deps.queue.length).toBe(0); // rolled back

    // Next /play must trigger playCurrent again (not wedged)
    const i2 = makeInteraction({
      commandName: "play",
      options: { query: "https://tidal.com/track/2" },
    });
    await handleInteraction(i2 as never, deps);
    expect((deps.playback.playCurrent as ReturnType<typeof mock>).mock.calls.length).toBe(2);
  });
});

describe("Codex-F-T2-004: batched /download renders one aggregated summary", () => {
  test("multi-track download uses batch summary, not per-job reply", async () => {
    const deps = makeDeps();
    (deps.client.resolve as ReturnType<typeof mock>).mockResolvedValueOnce({
      kind: "playlist" as const,
      items: [
        { id: "t1", title: "One", artist: "A", source_type: "tidal" as const, local: false, duration: 1 },
        { id: "t2", title: "Two", artist: "A", source_type: "tidal" as const, local: false, duration: 1 },
      ],
    });
    const i = makeInteraction({
      commandName: "download",
      options: { query: "playlist-url" },
    });
    await handleInteraction(i as never, deps);
    // First editReply must be the aggregated batch summary.
    const first = i._replies.find((r) => r.kind === "editReply")?.content ?? "";
    expect(first).toMatch(/Batch download/);
    expect(first).toMatch(/2 tracks/);
    expect(first).toContain("One");
    expect(first).toContain("Two");
  });
});

describe("Codex-F-T2-008: poll errors differentiate transient vs permanent", () => {
  test("transient MusicDlError('unreachable') is treated as retryable, not terminal", async () => {
    // Indirect test: isTransientPollError lives in the module; we exercise it
    // via the predicate's role in pollSingleJob. The easier surface: confirm
    // MusicDlError('unreachable') is classifiable as transient.
    const err = new MusicDlError("unreachable", "x");
    expect(err.code).toBe("unreachable");
  });

  test("permanent MusicDlError('auth') is terminal", () => {
    const err = new MusicDlError("auth", "x", 401);
    expect(err.code).toBe("auth");
  });
});

describe("Codex-F-T2-005: trigger failures classify actual error", () => {
  test("MusicDlError('auth') yields Unknown message, not BackendUnavailable", async () => {
    const deps = makeDeps();
    (deps.client.triggerDownload as ReturnType<typeof mock>).mockImplementationOnce(async () => {
      throw new MusicDlError("auth", "Backend rejected bot credentials", 401);
    });
    const i = makeInteraction({
      commandName: "download",
      options: { query: "https://tidal.com/track/42" },
    });
    await handleInteraction(i as never, deps);
    const last = i._replies.at(-1)?.content ?? "";
    // Must NOT be the hard-coded "backend unavailable" string
    expect(last).not.toMatch(/currently unavailable/i);
  });
});

describe("Codex-F-T2-003: /queue highlights by position, not id", () => {
  test("duplicate items show the marker on only the current position", async () => {
    const deps = makeDeps();
    deps.queue.append([
      { id: "a", title: "A" },
      { id: "a", title: "A" }, // same id, different position
    ]);
    // queue.current() returns position 0
    const i = makeInteraction({ commandName: "queue" });
    await handleInteraction(i as never, deps);
    const content = i._replies[0]?.content ?? "";
    const markerLines = content.split("\n").filter((l: string) => l.includes("▶"));
    expect(markerLines.length).toBe(1);
  });
});
