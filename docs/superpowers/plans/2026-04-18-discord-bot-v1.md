# Discord Bot V1 Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Build a private, local-first Discord music bot that uses `music-dl` as the only source-resolution and media-access layer.

**Architecture:** Keep `music-dl` responsible for resolving play inputs, Tidal access, local-vs-remote decisions, and bot-consumable playable sources. Add a thin Bun-based Discord bot that only handles slash commands, queue state, Discord voice lifecycle, and playback transport. Avoid reusing `muse` runtime code; use it only as a behavioral reference.

**Tech Stack:** Python 3.12+, FastAPI, pytest, Bun, TypeScript, `discord.js`, `@discordjs/voice`

---

## Planned File Structure

### Backend (`music-dl`)

- Create: `tidaldl-py/tidal_dl/gui/api/bot.py`
  Purpose: bot-facing endpoints for resolve, playable source, download trigger, and download polling.
- Create: `tidaldl-py/tidal_dl/helper/local_playlist_resolver.py`
  Purpose: find and parse local `.m3u` / `.m3u8` playlist files by name without mixing filesystem logic into HTTP routes.
- Modify: `tidaldl-py/tidal_dl/gui/api/__init__.py`
  Purpose: register the new `/api/bot` router.
- Modify: `tidaldl-py/tidal_dl/gui/security.py`
  Purpose: add dedicated bearer-token validation and short-lived bot stream token helpers.
- Modify: `tidaldl-py/tidal_dl/gui/api/playback.py`
  Purpose: reuse or extract stream-building helpers so `/api/bot/playable` can hand the bot a short-lived local or Tidal-backed playable URL.
- Test: `tidaldl-py/tests/test_bot_api.py`
  Purpose: API coverage for bearer auth, input resolution, playable source responses, and download status.
- Test: `tidaldl-py/tests/test_local_playlist_resolver.py`
  Purpose: local playlist name lookup and playlist file parsing coverage.

### Discord bot (`apps/discord-bot`)

- Create: `apps/discord-bot/package.json`
  Purpose: Bun-managed app manifest and scripts.
- Create: `apps/discord-bot/tsconfig.json`
  Purpose: TypeScript compiler settings.
- Create: `apps/discord-bot/.env.example`
  Purpose: document required Discord and backend environment variables.
- Create: `apps/discord-bot/src/config.ts`
  Purpose: environment parsing and startup validation.
- Test: `apps/discord-bot/src/config.test.ts`
  Purpose: startup configuration validation coverage.
- Create: `apps/discord-bot/src/musicDlClient.ts`
  Purpose: typed HTTP client for the bot-facing `music-dl` API.
- Create: `apps/discord-bot/src/queue.ts`
  Purpose: queue state, repeat modes, and now-playing state transitions.
- Create: `apps/discord-bot/src/player.ts`
  Purpose: Discord voice lifecycle, audio resource creation, reconnect handling, and queue advancement.
- Create: `apps/discord-bot/src/commands.ts`
  Purpose: slash-command definitions and command dispatch.
- Create: `apps/discord-bot/src/index.ts`
  Purpose: app entrypoint, client bootstrap, interaction wiring, and command registration.
- Test: `apps/discord-bot/src/queue.test.ts`
  Purpose: queue and repeat-state transitions.
- Test: `apps/discord-bot/src/commands.test.ts`
  Purpose: command allowlist and visible picker behavior.
- Create: `apps/discord-bot/README.md`
  Purpose: local bot setup and run instructions.

### Docs

- Modify: `README.md`
  Purpose: mention the private Discord bot feature as local-first / experimental and point contributors to the new docs.

## Implementation Notes

- Do not add a second persistence layer for the bot in `v1`.
- Do not let the bot read `/Volumes/Music` or any library path directly.
- Do not let the bot receive raw Tidal credentials.
- Keep `/play` read-only.
- Keep `/download` explicit.
- Use Bun, not npm.
- Avoid pytest `monkeypatch`; use `unittest.mock.patch` or explicit test doubles.

### Task 1: Add backend bot auth and router skeleton

**Files:**
- Create: `tidaldl-py/tidal_dl/gui/api/bot.py`
- Modify: `tidaldl-py/tidal_dl/gui/api/__init__.py`
- Modify: `tidaldl-py/tidal_dl/gui/security.py`
- Test: `tidaldl-py/tests/test_bot_api.py`

- [ ] **Step 1: Write the failing auth test**

```python
from fastapi.testclient import TestClient


def test_bot_route_rejects_missing_bearer_token(client: TestClient):
    response = client.post("/api/bot/play/resolve", headers={"host": "localhost:8765"}, json={"query": "test"})
    assert response.status_code == 401
```

- [ ] **Step 2: Run the test to verify it fails**

Run: `cd tidaldl-py && uv run pytest tests/test_bot_api.py::test_bot_route_rejects_missing_bearer_token -v`

Expected: FAIL because `/api/bot/play/resolve` does not exist yet.

- [ ] **Step 3: Write the minimal router and auth helper**

```python
# tidaldl-py/tidal_dl/gui/api/bot.py
from fastapi import APIRouter, Header, HTTPException

from tidal_dl.gui.security import validate_bot_bearer

router = APIRouter(prefix="/bot")


def require_bot_auth(authorization: str | None = Header(default=None)) -> None:
    if not validate_bot_bearer(authorization):
        raise HTTPException(status_code=401, detail="Unauthorized bot client")


@router.post("/play/resolve")
def resolve_placeholder(_: None = Depends(require_bot_auth)) -> dict:
    return {"items": []}
```

```python
# tidaldl-py/tidal_dl/gui/security.py
def validate_bot_bearer(header_value: str | None) -> bool:
    token = os.getenv("MUSIC_DL_BOT_TOKEN", "").strip()
    if not token or not header_value:
        return False
    scheme, _, supplied = header_value.partition(" ")
    return scheme.lower() == "bearer" and secrets.compare_digest(supplied.strip(), token)
```

- [ ] **Step 4: Register the router**

```python
# tidaldl-py/tidal_dl/gui/api/__init__.py
from tidal_dl.gui.api.bot import router as bot_router

api_router.include_router(bot_router, tags=["bot"])
```

- [ ] **Step 5: Run the focused test to verify it passes**

Run: `cd tidaldl-py && MUSIC_DL_BOT_TOKEN=test-token uv run pytest tests/test_bot_api.py::test_bot_route_rejects_missing_bearer_token -v`

Expected: PASS

- [ ] **Step 6: Add the happy-path auth test and make it pass**

```python
def test_bot_route_accepts_valid_bearer_token(client: TestClient):
    response = client.post(
        "/api/bot/play/resolve",
        headers={
            "host": "localhost:8765",
            "authorization": "Bearer test-token",
        },
        json={"query": "test"},
    )
    assert response.status_code == 200
```

Run: `cd tidaldl-py && MUSIC_DL_BOT_TOKEN=test-token uv run pytest tests/test_bot_api.py -v`

Expected: PASS

- [ ] **Step 7: Commit**

```bash
git add tidaldl-py/tidal_dl/gui/api/bot.py \
        tidaldl-py/tidal_dl/gui/api/__init__.py \
        tidaldl-py/tidal_dl/gui/security.py \
        tidaldl-py/tests/test_bot_api.py
git commit -m "feat(bot): add backend auth scaffold"
```

### Task 2: Implement local playlist resolution in the backend

**Files:**
- Create: `tidaldl-py/tidal_dl/helper/local_playlist_resolver.py`
- Test: `tidaldl-py/tests/test_local_playlist_resolver.py`

- [ ] **Step 1: Write the failing local playlist resolver test**

```python
from pathlib import Path

from tidal_dl.helper.local_playlist_resolver import resolve_playlist_name


def test_resolve_playlist_name_prefers_casefolded_exact_match(tmp_path: Path):
    playlist_dir = tmp_path / "Playlists"
    playlist_dir.mkdir()
    (playlist_dir / "Night Drive.m3u8").write_text("#EXTM3U\nsong.flac\n", encoding="utf-8")

    match = resolve_playlist_name("night drive", [playlist_dir])

    assert match is not None
    assert match.name == "Night Drive.m3u8"
```

- [ ] **Step 2: Run the test to verify it fails**

Run: `cd tidaldl-py && uv run pytest tests/test_local_playlist_resolver.py::test_resolve_playlist_name_prefers_casefolded_exact_match -v`

Expected: FAIL because the module does not exist yet.

- [ ] **Step 3: Write the minimal resolver**

```python
from pathlib import Path


def resolve_playlist_name(name: str, roots: list[Path]) -> Path | None:
    wanted = name.strip().casefold()
    if not wanted:
        return None

    for root in roots:
        if not root.exists():
            continue
        for candidate in root.rglob("*"):
            if candidate.suffix.lower() not in {".m3u", ".m3u8"}:
                continue
            if candidate.stem.casefold() == wanted:
                return candidate
    return None
```

- [ ] **Step 4: Add parsing coverage and make it pass**

```python
def test_parse_playlist_file_skips_comments_and_blank_lines(tmp_path: Path):
    playlist = tmp_path / "set.m3u8"
    playlist.write_text("#EXTM3U\n\ntrack-a.flac\n# comment\ntrack-b.flac\n", encoding="utf-8")

    paths = parse_playlist_file(playlist)

    assert paths == ["track-a.flac", "track-b.flac"]
```

Run: `cd tidaldl-py && uv run pytest tests/test_local_playlist_resolver.py -v`

Expected: PASS

- [ ] **Step 5: Commit**

```bash
git add tidaldl-py/tidal_dl/helper/local_playlist_resolver.py \
        tidaldl-py/tests/test_local_playlist_resolver.py
git commit -m "feat(bot): add local playlist resolver"
```

### Task 3: Implement bot resolve and playable endpoints

**Files:**
- Modify: `tidaldl-py/tidal_dl/gui/api/bot.py`
- Modify: `tidaldl-py/tidal_dl/gui/security.py`
- Modify: `tidaldl-py/tidal_dl/gui/api/playback.py`
- Modify: `tidaldl-py/tidal_dl/gui/api/downloads.py`
- Modify: `tidaldl-py/tidal_dl/gui/api/playlists.py`
- Modify: `tidaldl-py/tidal_dl/gui/api/search.py`
- Test: `tidaldl-py/tests/test_bot_api.py`

- [ ] **Step 1: Write the failing resolve-by-text test**

```python
from unittest.mock import patch


def test_bot_resolve_returns_five_text_choices(client):
    fake_tracks = [{"id": 1, "name": "Song A"}, {"id": 2, "name": "Song B"}, {"id": 3, "name": "Song C"},
                   {"id": 4, "name": "Song D"}, {"id": 5, "name": "Song E"}, {"id": 6, "name": "Song F"}]

    with patch("tidal_dl.gui.api.bot.resolve_text_query", return_value=fake_tracks):
        response = client.post(
            "/api/bot/play/resolve",
            headers={"host": "localhost:8765", "authorization": "Bearer test-token"},
            json={"query": "song"},
        )

    assert response.status_code == 200
    assert len(response.json()["choices"]) == 5
```

- [ ] **Step 2: Run the test to verify it fails**

Run: `cd tidaldl-py && MUSIC_DL_BOT_TOKEN=test-token uv run pytest tests/test_bot_api.py::test_bot_resolve_returns_five_text_choices -v`

Expected: FAIL because the route still returns the placeholder payload.

- [ ] **Step 3: Implement resolve request parsing**

```python
class ResolveRequest(BaseModel):
    query: str


@router.post("/play/resolve")
def resolve_play_request(payload: ResolveRequest, _: None = Depends(require_bot_auth)) -> dict:
    query = payload.query.strip()
    if not query:
        raise HTTPException(status_code=400, detail="Query is required")

    if looks_like_tidal_playlist(query):
        return {"kind": "playlist", "items": resolve_tidal_playlist(query)}
    if looks_like_tidal_track(query):
        return {"kind": "track", "items": [resolve_tidal_track(query)]}
    if looks_like_local_playlist_name(query):
        return {"kind": "playlist", "items": resolve_local_playlist(query)}

    return {"kind": "choices", "choices": resolve_text_query(query)[:5]}
```

- [ ] **Step 4: Write the failing playable-source test**

```python
from unittest.mock import patch


def test_bot_playable_returns_short_lived_stream_url(client):
    with patch("tidal_dl.gui.api.bot.build_playable_source", return_value={"url": "http://localhost:8765/api/playback/bot-stream/abc", "kind": "local"}):
        response = client.post(
            "/api/bot/playable",
            headers={"host": "localhost:8765", "authorization": "Bearer test-token"},
            json={"item_id": "track:123"},
        )

    assert response.status_code == 200
    assert response.json()["url"].startswith("http://localhost:8765/api/playback/")
```

- [ ] **Step 5: Implement short-lived playback handles**

```python
# tidaldl-py/tidal_dl/gui/security.py
def sign_bot_stream_token(payload: dict[str, str], ttl_seconds: int = 120) -> str:
    ...


def verify_bot_stream_token(token: str) -> dict[str, str] | None:
    ...
```

```python
# tidaldl-py/tidal_dl/gui/api/playback.py
@router.get("/bot-stream/{token}")
def serve_bot_stream(token: str):
    payload = verify_bot_stream_token(token)
    if payload is None:
        raise HTTPException(status_code=403, detail="Invalid or expired stream token")
    if payload["kind"] == "local":
        return _serve_validated_local_file(payload["path"])
    return _proxy_tidal_track(int(payload["track_id"]))
```

- [ ] **Step 6: Reuse backend download state**

Expose a bot-safe status reader in `bot.py` by delegating to existing download state instead of adding a second job model.

```python
@router.get("/downloads/{track_id}")
def bot_download_status(track_id: int, _: None = Depends(require_bot_auth)) -> dict:
    return get_download_status(track_id)
```

- [ ] **Step 7: Run backend tests**

Run: `cd tidaldl-py && MUSIC_DL_BOT_TOKEN=test-token uv run pytest tests/test_bot_api.py tests/test_local_playlist_resolver.py -v`

Expected: PASS

- [ ] **Step 8: Run broader regression tests around existing API behavior**

Run: `cd tidaldl-py && MUSIC_DL_BOT_TOKEN=test-token uv run pytest tests/test_gui_api.py tests/test_downloads.py tests/test_gui_security.py -v`

Expected: PASS

- [ ] **Step 9: Commit**

```bash
git add tidaldl-py/tidal_dl/gui/api/bot.py \
        tidaldl-py/tidal_dl/gui/security.py \
        tidaldl-py/tidal_dl/gui/api/playback.py \
        tidaldl-py/tidal_dl/gui/api/downloads.py \
        tidaldl-py/tidal_dl/gui/api/playlists.py \
        tidaldl-py/tidal_dl/gui/api/search.py \
        tidaldl-py/tests/test_bot_api.py \
        tidaldl-py/tests/test_local_playlist_resolver.py
git commit -m "feat(bot): add resolve and playable APIs"
```

### Task 4: Scaffold the Bun Discord bot app

**Files:**
- Create: `apps/discord-bot/package.json`
- Create: `apps/discord-bot/tsconfig.json`
- Create: `apps/discord-bot/.env.example`
- Create: `apps/discord-bot/src/config.ts`
- Test: `apps/discord-bot/src/config.test.ts`
- Create: `apps/discord-bot/src/musicDlClient.ts`

- [ ] **Step 1: Write the failing config validation test**

```ts
import { expect, test } from "bun:test";
import { parseConfig } from "./config";

test("parseConfig requires bot and backend ids", () => {
  expect(() =>
    parseConfig({
      DISCORD_TOKEN: "x",
      MUSIC_DL_BASE_URL: "http://127.0.0.1:8765",
    }),
  ).toThrow("ALLOWED_GUILD_ID");
});
```

- [ ] **Step 2: Run the test to verify it fails**

Run: `cd apps/discord-bot && bun test src/config.test.ts`

Expected: FAIL because the app scaffold does not exist yet.

- [ ] **Step 3: Create the Bun manifest and config parser**

```json
{
  "name": "@music-dl/discord-bot",
  "private": true,
  "type": "module",
  "scripts": {
    "dev": "bun --watch src/index.ts",
    "start": "bun src/index.ts",
    "test": "bun test",
    "typecheck": "bunx tsc --noEmit"
  },
  "dependencies": {
    "@discordjs/voice": "^0.18.0",
    "discord.js": "^14.21.0"
  },
  "devDependencies": {
    "typescript": "^5.9.0"
  }
}
```

```ts
export function parseConfig(env: Record<string, string | undefined>) {
  const required = [
    "DISCORD_TOKEN",
    "DISCORD_APPLICATION_ID",
    "ALLOWED_GUILD_ID",
    "ALLOWED_CHANNEL_ID",
    "ALLOWED_USER_ID",
    "MUSIC_DL_BASE_URL",
    "MUSIC_DL_BOT_TOKEN",
  ] as const;

  for (const key of required) {
    if (!env[key]?.trim()) throw new Error(`${key} is required`);
  }
}
```

- [ ] **Step 4: Add a typed backend client and test it**

```ts
export class MusicDlClient {
  constructor(private readonly baseUrl: string, private readonly token: string) {}

  async resolve(query: string) {
    const response = await fetch(`${this.baseUrl}/api/bot/play/resolve`, {
      method: "POST",
      headers: {
        "content-type": "application/json",
        authorization: `Bearer ${this.token}`,
      },
      body: JSON.stringify({ query }),
    });
    if (!response.ok) throw new Error(`resolve failed: ${response.status}`);
    return response.json();
  }
}
```

- [ ] **Step 5: Install dependencies and run tests**

Run: `cd apps/discord-bot && bun install && bun test && bun run typecheck`

Expected: PASS

- [ ] **Step 6: Commit**

```bash
git add apps/discord-bot/package.json \
        apps/discord-bot/tsconfig.json \
        apps/discord-bot/.env.example \
        apps/discord-bot/src/config.ts \
        apps/discord-bot/src/config.test.ts \
        apps/discord-bot/src/musicDlClient.ts \
git commit -m "feat(bot): scaffold bun discord app"
```

### Task 5: Implement queue, commands, and Discord playback

**Files:**
- Create: `apps/discord-bot/src/queue.ts`
- Create: `apps/discord-bot/src/player.ts`
- Create: `apps/discord-bot/src/commands.ts`
- Create: `apps/discord-bot/src/index.ts`
- Test: `apps/discord-bot/src/queue.test.ts`
- Test: `apps/discord-bot/src/commands.test.ts`

- [ ] **Step 1: Write the failing queue repeat-mode test**

```ts
import { expect, test } from "bun:test";
import { QueueState } from "./queue";

test("repeat all wraps to the first item", () => {
  const queue = new QueueState();
  queue.setItems([{ id: "a" }, { id: "b" }]);
  queue.setRepeat("all");
  queue.advance();
  queue.advance();
  expect(queue.current()?.id).toBe("a");
});
```

- [ ] **Step 2: Run the test to verify it fails**

Run: `cd apps/discord-bot && bun test src/queue.test.ts`

Expected: FAIL because `QueueState` does not exist yet.

- [ ] **Step 3: Implement the minimal queue state**

```ts
export type RepeatMode = "off" | "one" | "all";

export class QueueState {
  private items: Array<{ id: string }> = [];
  private index = 0;
  private repeat: RepeatMode = "all";

  setItems(items: Array<{ id: string }>) {
    this.items = items;
    this.index = 0;
  }

  setRepeat(mode: RepeatMode) {
    this.repeat = mode;
  }

  current() {
    return this.items[this.index] ?? null;
  }

  advance() {
    if (this.repeat === "one") return this.current();
    if (this.index + 1 < this.items.length) this.index += 1;
    else if (this.repeat === "all" && this.items.length > 0) this.index = 0;
    else this.index = this.items.length;
    return this.current();
  }
}
```

- [ ] **Step 4: Add command authorization and visible picker tests**

```ts
test("rejects command outside the allowed channel", async () => {
  const result = ensureAuthorized({
    guildId: "1",
    channelId: "wrong",
    userId: "3",
  }, config);

  expect(result.ok).toBeFalse();
});
```

```ts
test("play text query returns five visible choices", async () => {
  const musicDl = { resolve: async () => ({ kind: "choices", choices: Array.from({ length: 5 }, (_, i) => ({ id: `${i}` })) }) };
  const result = await handlePlayQuery("night drive", musicDl);
  expect(result.kind).toBe("choices");
  expect(result.choices).toHaveLength(5);
});
```

- [ ] **Step 5: Implement command handlers**

Required handlers:

- `/summon`
- `/leave`
- `/play`
- `/pause`
- `/resume`
- `/skip`
- `/queue`
- `/nowplaying`
- `/volume`
- `/repeat`
- `/download`

Use one command registry file rather than one file per command in `v1`.

```ts
export async function handleInteraction(interaction: ChatInputCommandInteraction, deps: Deps) {
  if (!ensureAuthorized(interaction, deps.config).ok) {
    await interaction.reply({ content: "Unauthorized context", ephemeral: true });
    return;
  }

  switch (interaction.commandName) {
    case "play":
      return handlePlay(interaction, deps);
    case "download":
      return handleDownload(interaction, deps);
    // ...
  }
}
```

- [ ] **Step 6: Implement player lifecycle**

Requirements:

- join the caller's voice channel on `/summon`
- fetch playable URLs from `music-dl`
- create Discord audio resources from those URLs
- advance queue on track end
- retry reconnect on voice disconnect
- never resolve sources without going through `music-dl`

```ts
player.on(AudioPlayerStatus.Idle, async () => {
  const next = queue.advance();
  if (!next) return;
  await playQueueItem(next);
});
```

- [ ] **Step 7: Run bot tests and typecheck**

Run: `cd apps/discord-bot && bun test && bun run typecheck`

Expected: PASS

- [ ] **Step 8: Commit**

```bash
git add apps/discord-bot/src/queue.ts \
        apps/discord-bot/src/player.ts \
        apps/discord-bot/src/commands.ts \
        apps/discord-bot/src/index.ts \
        apps/discord-bot/src/queue.test.ts \
        apps/discord-bot/src/commands.test.ts
git commit -m "feat(bot): add discord playback runtime"
```

### Task 6: Document the feature and run end-to-end verification

**Files:**
- Create: `apps/discord-bot/README.md`
- Modify: `README.md`

- [ ] **Step 1: Document local setup**

Include:

- required Discord application setup
- required environment variables
- how to run `music-dl`
- how to run the bot locally with Bun
- current `v1` limitations

- [ ] **Step 2: Update top-level README**

Add a short section linking to the Discord bot docs and clearly label the feature as local-first / in-progress.

- [ ] **Step 3: Verify backend tests**

Run: `cd tidaldl-py && MUSIC_DL_BOT_TOKEN=test-token uv run pytest tests/test_bot_api.py tests/test_local_playlist_resolver.py tests/test_gui_api.py tests/test_downloads.py tests/test_gui_security.py -v`

Expected: PASS

- [ ] **Step 4: Verify bot tests**

Run: `cd apps/discord-bot && bun test && bun run typecheck`

Expected: PASS

- [ ] **Step 5: Run local manual smoke test**

1. Start `music-dl` locally.
2. Start the bot with the allowlisted Discord ids.
3. Run `/summon`.
4. Run `/play` with a free-text query and confirm the 5-choice picker appears in the allowed text channel.
5. Play one local track.
6. Play one Tidal-only track without downloading it.
7. Play one Tidal playlist URL.
8. Run `/pause`, `/resume`, `/skip`, `/volume`, `/repeat`, `/queue`, `/nowplaying`, `/download`.
9. Disconnect and reconnect voice once to verify bounded recovery.

- [ ] **Step 6: Commit**

```bash
git add apps/discord-bot/README.md README.md
git commit -m "docs(bot): add discord setup guide"
```

## Completion Criteria

The feature is ready for the next execution phase when all of the following are true:

- backend exposes authenticated `/api/bot` endpoints
- bot can resolve free-text, Tidal URLs, and local playlist names through `music-dl`
- bot can play both local-backed and remote Tidal-backed items without direct disk access
- `/play` remains read-only
- `/download` remains explicit
- command access is restricted to the allowed guild, channel, and user
- backend and bot automated tests pass
- local manual smoke test passes
