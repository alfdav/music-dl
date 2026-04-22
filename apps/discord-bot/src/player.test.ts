/**
 * Tests for Playback (R5) — the audio pipeline that ties QueueState to the
 * AudioPlayer via MusicDlClient. Voice connection and resource creation are
 * mocked; these tests cover the decision logic, not discord.js internals.
 */

import { beforeEach, describe, expect, test, mock, spyOn } from "bun:test";
import { EventEmitter } from "node:events";
import { AudioPlayerStatus } from "@discordjs/voice";
import * as voiceModule from "@discordjs/voice";

import { Playback, VoiceManager } from "./player";
import { QueueState } from "./queue";
import type { MusicDlClient, PlayableSource } from "./musicDlClient";

class MockPlayer extends EventEmitter {
  played: unknown[] = [];
  stopped = 0;
  paused = false;
  play(resource: unknown) {
    this.played.push(resource);
  }
  stop(_force?: boolean) {
    this.stopped++;
    return true;
  }
  pause(_interpolateSilence?: boolean) {
    this.paused = true;
    return true;
  }
  unpause() {
    this.paused = false;
    return true;
  }
  // Emit a fake track-end event so we can drive handleTrackEnd from tests.
  emitTrackEnd() {
    this.emit(
      AudioPlayerStatus.Idle,
      { status: AudioPlayerStatus.Playing },
      { status: AudioPlayerStatus.Idle },
    );
  }
  emitError(err: Error) {
    this.emit("error", err);
  }
}

function makeVoice(player: MockPlayer): VoiceManager {
  const vm = Object.create(VoiceManager.prototype) as VoiceManager;
  (vm as unknown as { player: MockPlayer }).player = player;
  (vm as unknown as { textChannel: null }).textChannel = null;
  return vm;
}

function makeClient(overrides: Partial<MusicDlClient> = {}): MusicDlClient {
  const defaults: Partial<MusicDlClient> = {
    playable: mock(async (id: string): Promise<PlayableSource> => ({
      url: `/api/bot/bot-stream/tok-${id}`,
      content_type: "audio/flac",
      title: `T ${id}`,
      artist: "A",
      duration: 180,
    })),
    absolutize: (rel: string) =>
      rel.startsWith("http") ? rel : `http://backend${rel}`,
  };
  return Object.assign(
    Object.create(null),
    defaults,
    overrides,
  ) as unknown as MusicDlClient;
}

describe("Playback", () => {
  let player: MockPlayer;
  let voice: VoiceManager;
  let queue: QueueState;
  let client: MusicDlClient;
  let playback: Playback;
  let createResourceSpy: ReturnType<typeof spyOn>;

  beforeEach(() => {
    player = new MockPlayer();
    voice = makeVoice(player);
    queue = new QueueState();
    client = makeClient();
    // Stub createAudioResource so we don't need a real stream.
    createResourceSpy = spyOn(voiceModule, "createAudioResource").mockImplementation(
      (url: unknown) => ({
        volume: { setVolume: () => {} },
        _url: url,
      }) as unknown as ReturnType<typeof voiceModule.createAudioResource>,
    );
    playback = new Playback(voice, queue, client, {
      logger: { error: () => {} },
    });
  });

  // R5-AC1: backend playable URL fetched before playback
  test("playCurrent fetches playable URL from backend before playing", async () => {
    queue.append([{ id: "item-1" }]);
    const item = await playback.playCurrent();
    expect(item?.id).toBe("item-1");
    expect((client.playable as ReturnType<typeof mock>).mock.calls).toEqual([
      ["item-1"],
    ]);
    expect(createResourceSpy).toHaveBeenCalledWith(
      "http://backend/api/bot/bot-stream/tok-item-1",
      expect.objectContaining({ inlineVolume: true }),
    );
    expect(player.played.length).toBe(1);
  });

  // R5-AC2: audio plays through active voice connection
  test("playCurrent calls player.play with the created resource", async () => {
    queue.append([{ id: "x" }]);
    await playback.playCurrent();
    expect(player.played.length).toBe(1);
    expect((player.played[0] as { _url: string })._url).toBe(
      "http://backend/api/bot/bot-stream/tok-x",
    );
  });

  // R5-AC3: track end advances queue per repeat mode
  test("track end advances to next item (repeat all)", async () => {
    queue.append([{ id: "a" }, { id: "b" }]);
    await playback.playCurrent();
    player.played = [];

    player.emitTrackEnd();
    // Drain microtasks so the async handler completes
    await new Promise((r) => setTimeout(r, 0));

    expect(queue.current()?.id).toBe("b");
    expect(player.played.length).toBe(1);
  });

  // R5-AC3 + R3-AC4: repeat one replays current
  test("track end replays current item in repeat one", async () => {
    queue.setRepeat("one");
    queue.append([{ id: "only" }]);
    await playback.playCurrent();
    player.played = [];
    (client.playable as ReturnType<typeof mock>).mock.calls.length = 0;

    player.emitTrackEnd();
    await new Promise((r) => setTimeout(r, 0));

    expect(queue.current()?.id).toBe("only");
    expect(player.played.length).toBe(1);
  });

  // R5-AC4: queue exhausted -> stop cleanly, no further play
  test("queue exhausted stops cleanly", async () => {
    queue.setRepeat("off");
    queue.append([{ id: "a" }]);
    await playback.playCurrent();
    player.played = [];

    player.emitTrackEnd(); // advance → null
    await new Promise((r) => setTimeout(r, 0));

    expect(queue.current()).toBeNull();
    expect(player.played.length).toBe(0);
  });

  // R5-AC5: track failure logs + advances
  test("player error advances to next item", async () => {
    const logs: string[] = [];
    // Replace the beforeEach Playback with a logger-capturing one on a
    // fresh player to avoid double-subscribed handlers on the same emitter.
    player.removeAllListeners();
    playback = new Playback(voice, queue, client, {
      logger: { error: (...a) => logs.push(a.map(String).join(" ")) },
    });
    queue.append([{ id: "a" }, { id: "b" }]);
    await playback.playCurrent();
    player.played = [];

    player.emitError(new Error("decoder blew up"));
    await new Promise((r) => setTimeout(r, 0));

    expect(logs.some((l) => l.includes("decoder blew up"))).toBe(true);
    expect(queue.current()?.id).toBe("b");
    expect(player.played.length).toBe(1);
  });

  test("intentional stop does not auto-advance", async () => {
    queue.setRepeat("all");
    queue.append([{ id: "a" }, { id: "b" }]);
    await playback.playCurrent();
    player.played = [];

    playback.stop();
    // stop() calls player.stop(true); emulate the resulting Idle event.
    player.emitTrackEnd();
    await new Promise((r) => setTimeout(r, 0));

    expect(player.played.length).toBe(0);
    expect(queue.current()).toBeNull(); // cleared
  });

  test("skip advances and plays next item", async () => {
    queue.append([{ id: "a" }, { id: "b" }]);
    await playback.playCurrent();
    player.played = [];

    const played = await playback.skip();
    expect(played?.id).toBe("b");
    expect(player.played.length).toBe(1);
  });

  test("skip on last item with repeat off stops", async () => {
    queue.setRepeat("off");
    queue.append([{ id: "a" }]);
    await playback.playCurrent();
    player.played = [];

    const played = await playback.skip();
    expect(played).toBeNull();
    expect(player.played.length).toBe(0);
  });

  test("pause delegates to player.pause", () => {
    playback.pause();
    expect(player.paused).toBe(true);
  });

  test("resume delegates to player.unpause", () => {
    playback.pause();
    playback.resume();
    expect(player.paused).toBe(false);
  });

  test("setVolume clamps to [0, 2]", () => {
    expect(playback.setVolume(3)).toBe(2);
    expect(playback.setVolume(-1)).toBe(0);
    expect(playback.setVolume(0.7)).toBe(0.7);
    expect(playback.getVolume()).toBe(0.7);
  });

  test("setVolume applies to current resource when present", async () => {
    const setVol = mock(() => {});
    createResourceSpy.mockImplementationOnce(
      () => ({ volume: { setVolume: setVol } }) as unknown as ReturnType<typeof voiceModule.createAudioResource>,
    );
    queue.append([{ id: "a" }]);
    await playback.playCurrent();
    playback.setVolume(0.5);
    expect(setVol).toHaveBeenCalledWith(0.5);
  });

  // R5-AC5: multiple consecutive failures eventually give up (no infinite loop)
  test("gives up after consecutive start failures", async () => {
    const failing = makeClient({
      playable: mock(async () => {
        throw new Error("backend down");
      }) as unknown as MusicDlClient["playable"],
    });
    const logs: string[] = [];
    player.removeAllListeners();
    playback = new Playback(voice, queue, failing, {
      logger: { error: (...a) => logs.push(a.map(String).join(" ")) },
    });
    queue.setRepeat("all");
    queue.append([{ id: "a" }, { id: "b" }, { id: "c" }]);

    // First playCurrent throws synchronously (no Idle event to drive loop).
    await expect(playback.playCurrent()).rejects.toThrow("backend down");

    // Simulate an Idle event arriving from a previously-playing item.
    player.emitTrackEnd();
    await new Promise((r) => setTimeout(r, 10));

    expect(logs.some((l) => l.includes("gave up"))).toBe(true);
  });
});
