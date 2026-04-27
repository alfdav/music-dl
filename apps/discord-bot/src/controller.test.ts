import { describe, expect, mock, test } from "bun:test";

import type { BotConfig } from "./config";
import { buildControllerPanel, handleControllerInteraction } from "./controller";
import type { MusicDlClient } from "./musicDlClient";
import { QueueState } from "./queue";
import type { Playback, VoiceManager } from "./player";
import type { CommandDeps } from "./commands";

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

function makeDeps(overrides: Partial<CommandDeps> = {}): CommandDeps {
  const client: Partial<MusicDlClient> = {
    playlists: mock(async () => [
      { id: "pl1", name: "Sunday Reset", num_tracks: 2 },
    ]),
    playlistItems: mock(async () => [
      {
        id: "tidal:1",
        title: "Track One",
        artist: "Artist One",
        source_type: "tidal" as const,
        local: false,
        duration: 100,
      },
      {
        id: "tidal:2",
        title: "Track Two",
        artist: "Artist Two",
        source_type: "tidal" as const,
        local: false,
        duration: 120,
      },
    ]),
  };
  const playback: Partial<Playback> = {
    playCurrent: mock(async () => null),
    pause: mock(() => true),
    resume: mock(() => true),
    skip: mock(async () => null),
    stop: mock(() => {}),
  };
  const voice: Partial<VoiceManager> = {};

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

function makeSelectInteraction(value = "pl1") {
  const calls: unknown[] = [];
  return {
    guildId: "g-ok",
    channelId: "c-ok",
    user: { id: "u-ok" },
    isButton: () => false,
    isStringSelectMenu: () => true,
    isModalSubmit: () => false,
    customId: "djai:playlist",
    values: [value],
    deferUpdate: mock(async () => calls.push("deferUpdate")),
    followUp: mock(async (payload: unknown) => calls.push(payload)),
    _calls: calls,
  };
}

describe("DJAI controller panel", () => {
  test("panel exposes human playback controls", () => {
    const deps = makeDeps();
    const panel = buildControllerPanel(deps);

    expect(panel.content).toContain("DJAI");
    expect(panel.content).toContain("Repeat: all");
    const json = JSON.stringify(panel.components.map((row) => row.toJSON()));
    expect(json).toContain("Search");
    expect(json).toContain("Playlists");
    expect(json).toContain("Play/Pause");
  });

  test("playlist selection queues playlist and defaults repeat to all", async () => {
    const deps = makeDeps();
    deps.queue.setRepeat("off");

    const handled = await handleControllerInteraction(
      makeSelectInteraction() as never,
      deps,
    );

    expect(handled).toBe(true);
    expect(deps.queue.length).toBe(2);
    expect(deps.queue.getRepeat()).toBe("all");
    expect((deps.playback.playCurrent as ReturnType<typeof mock>).mock.calls.length).toBe(1);
  });

  test("unauthorized control click is rejected", async () => {
    const deps = makeDeps();
    const interaction = makeSelectInteraction();
    interaction.user.id = "intruder";

    const handled = await handleControllerInteraction(interaction as never, deps);

    expect(handled).toBe(true);
    expect(deps.queue.length).toBe(0);
    expect((interaction.followUp as ReturnType<typeof mock>).mock.calls.length).toBe(1);
  });
});
