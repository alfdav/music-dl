import { describe, expect, test, beforeEach, afterEach } from "bun:test";
import { MusicDlClient, MusicDlError } from "./musicDlClient";

const BASE = "http://127.0.0.1:8765";
const TOKEN = "test-bot-secret";

let originalFetch: typeof fetch;

beforeEach(() => {
  originalFetch = globalThis.fetch;
});

afterEach(() => {
  globalThis.fetch = originalFetch;
});

function mockFetch(handler: (req: { url: string; init?: RequestInit }) => Response | Promise<Response>) {
  globalThis.fetch = (async (url: any, init?: RequestInit) => {
    return handler({ url: typeof url === "string" ? url : url.toString(), init });
  }) as unknown as typeof fetch;
}

describe("MusicDlClient", () => {
  test("resolve sends bearer token and correct body", async () => {
    let capturedAuth = "";
    let capturedBody = "";
    let capturedUrl = "";
    mockFetch(({ url, init }) => {
      capturedUrl = url;
      capturedAuth = (init?.headers as any).authorization;
      capturedBody = init?.body as string;
      return new Response(JSON.stringify({ kind: "choices", choices: [] }), { status: 200 });
    });

    const client = new MusicDlClient(BASE, TOKEN);
    await client.resolve("night drive");

    expect(capturedUrl).toBe(`${BASE}/api/bot/play/resolve`);
    expect(capturedAuth).toBe(`Bearer ${TOKEN}`);
    expect(JSON.parse(capturedBody)).toEqual({ query: "night drive" });
  });

  test("playable returns typed source", async () => {
    mockFetch(() =>
      new Response(
        JSON.stringify({
          url: "/api/playback/bot-stream/abc",
          content_type: "audio/flac",
          title: "Song",
          artist: "Artist",
          duration: 180,
        }),
        { status: 200 },
      ),
    );
    const client = new MusicDlClient(BASE, TOKEN);
    const src = await client.playable("tidal:12345");
    expect(src.url).toContain("bot-stream");
    expect(src.duration).toBe(180);
  });

  test("triggerDownload returns job", async () => {
    mockFetch(() =>
      new Response(JSON.stringify({ job_id: "12345", status: "queued" }), { status: 200 }),
    );
    const client = new MusicDlClient(BASE, TOKEN);
    const job = await client.triggerDownload("tidal:12345");
    expect(job.job_id).toBe("12345");
    expect(job.status).toBe("queued");
  });

  test("downloadStatus sends GET with job id in path", async () => {
    let capturedUrl = "";
    mockFetch(({ url }) => {
      capturedUrl = url;
      return new Response(
        JSON.stringify({
          job_id: "12345",
          status: "in_progress",
          progress: 50,
          title: "X",
          artist: "Y",
          started_at: 0,
          finished_at: null,
        }),
        { status: 200 },
      );
    });
    const client = new MusicDlClient(BASE, TOKEN);
    await client.downloadStatus("12345");
    expect(capturedUrl).toBe(`${BASE}/api/bot/downloads/12345`);
  });

  test("backend unreachable raises MusicDlError with code 'unreachable'", async () => {
    globalThis.fetch = (async () => {
      throw new Error("ECONNREFUSED");
    }) as unknown as typeof fetch;
    const client = new MusicDlClient(BASE, TOKEN);
    await expect(client.resolve("x")).rejects.toBeInstanceOf(MusicDlError);
    try {
      await client.resolve("x");
    } catch (e) {
      expect((e as MusicDlError).code).toBe("unreachable");
    }
  });

  test("parse failure raises MusicDlError with code 'parse'", async () => {
    mockFetch(() => new Response("not json", { status: 200 }));
    const client = new MusicDlClient(BASE, TOKEN);
    try {
      await client.resolve("x");
      expect(true).toBe(false);
    } catch (e) {
      expect((e as MusicDlError).code).toBe("parse");
    }
  });

  test("401 raises MusicDlError with code 'auth'", async () => {
    mockFetch(() => new Response("{}", { status: 401 }));
    const client = new MusicDlClient(BASE, TOKEN);
    try {
      await client.resolve("x");
      expect(true).toBe(false);
    } catch (e) {
      expect((e as MusicDlError).code).toBe("auth");
    }
  });

  test("500 raises MusicDlError with code 'backend'", async () => {
    mockFetch(() => new Response("{}", { status: 500 }));
    const client = new MusicDlClient(BASE, TOKEN);
    try {
      await client.resolve("x");
      expect(true).toBe(false);
    } catch (e) {
      expect((e as MusicDlError).code).toBe("backend");
    }
  });

  test("F-011: resolve rejects response missing 'kind'", async () => {
    mockFetch(() => new Response(JSON.stringify({}), { status: 200 }));
    const client = new MusicDlClient(BASE, TOKEN);
    try {
      await client.resolve("x");
      expect(true).toBe(false);
    } catch (e) {
      expect(e).toBeInstanceOf(MusicDlError);
      expect((e as MusicDlError).code).toBe("parse");
    }
  });

  test("F-011: resolve rejects choices response without choices array", async () => {
    mockFetch(() => new Response(JSON.stringify({ kind: "choices" }), { status: 200 }));
    const client = new MusicDlClient(BASE, TOKEN);
    try {
      await client.resolve("x");
      expect(true).toBe(false);
    } catch (e) {
      expect((e as MusicDlError).code).toBe("parse");
    }
  });

  test("F-011: playable rejects response missing required fields", async () => {
    mockFetch(() =>
      new Response(JSON.stringify({ url: "/x" }), { status: 200 }),
    );
    const client = new MusicDlClient(BASE, TOKEN);
    try {
      await client.playable("tidal:1");
      expect(true).toBe(false);
    } catch (e) {
      expect((e as MusicDlError).code).toBe("parse");
      expect((e as MusicDlError).message).toContain("title");
    }
  });

  test("F-011: download rejects response without job_id", async () => {
    mockFetch(() => new Response(JSON.stringify({ status: "queued" }), { status: 200 }));
    const client = new MusicDlClient(BASE, TOKEN);
    try {
      await client.triggerDownload("tidal:1");
      expect(true).toBe(false);
    } catch (e) {
      expect((e as MusicDlError).code).toBe("parse");
    }
  });

  test("absolutize handles relative and absolute URLs", () => {
    const client = new MusicDlClient(BASE, TOKEN);
    expect(client.absolutize("/api/playback/bot-stream/abc")).toBe(
      `${BASE}/api/playback/bot-stream/abc`,
    );
    expect(client.absolutize("https://other.example/path")).toBe(
      "https://other.example/path",
    );
  });
});
