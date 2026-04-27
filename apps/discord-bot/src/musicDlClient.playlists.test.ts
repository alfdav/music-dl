import { describe, expect, test } from "bun:test";

import { MusicDlClient } from "./musicDlClient";

const BASE = "http://music-dl.test";

function mockFetch(handler: (url: string, init?: RequestInit) => Response) {
  globalThis.fetch = (async (url: string | URL | Request, init?: RequestInit) =>
    handler(String(url), init)) as typeof fetch;
}

describe("MusicDlClient playlist UX helpers", () => {
  test("lists Tidal playlists with bearer auth", async () => {
    let auth = "";
    mockFetch((_url, init) => {
      auth = String(init?.headers instanceof Headers ? init.headers.get("authorization") : (init?.headers as Record<string, string>)?.authorization);
      return new Response(JSON.stringify({
        playlists: [{ id: "p1", name: "Sunday Reset", num_tracks: 18 }],
      }));
    });

    const client = new MusicDlClient(BASE, "secret");
    const playlists = await client.playlists();

    expect(auth).toBe("Bearer secret");
    expect(playlists).toEqual([{ id: "p1", name: "Sunday Reset", num_tracks: 18 }]);
  });

  test("maps playlist tracks to bot queue items", async () => {
    mockFetch(() =>
      new Response(JSON.stringify({
        tracks: [
          { id: 123, name: "Song A", artist: "Artist A", duration: 90, is_local: false },
        ],
      })),
    );

    const client = new MusicDlClient(BASE, "secret");
    const items = await client.playlistItems("p1");

    expect(items).toEqual([
      {
        id: "tidal:123",
        title: "Song A",
        artist: "Artist A",
        source_type: "tidal",
        local: false,
        duration: 90,
      },
    ]);
  });

  test("uses local item id when playlist track has a local path", async () => {
    mockFetch(() =>
      new Response(JSON.stringify({
        tracks: [
          {
            id: 123,
            name: "Song A",
            artist: "Artist A",
            duration: 90,
            is_local: true,
            local_path: "/music/Song A.flac",
          },
        ],
      })),
    );

    const client = new MusicDlClient(BASE, "secret");
    const items = await client.playlistItems("p1");

    expect(items[0]).toMatchObject({
      id: "local:L211c2ljL1NvbmcgQS5mbGFj",
      source_type: "local",
      local: true,
    });
  });
});
