# TypeSafe / Jev access — verified facts only (2026-09-18)

Techmarine walked public docs + HTTP checks. Live API smoke succeeded with household key.
Do **not** invent steps beyond this file.

## Verified working (API)

- Endpoint: `POST https://api.typesafe.ai/v1/systemone`
- Auth: `Authorization: Bearer <API_KEY>`
- Model alias used in docs: `jev-latest` (live smoke returned `jev-1.13.0`)
- Env var name in TypeSafe docs/SDK: `TYPESAFE_API_KEY`
- Live smoke 2026-09-18: deluxe vs original pair → `keep_both_editions` @ confidence `1.0`

## Verified: where docs say to get a key

From https://docs.typesafe.ai/introduction/quickstart.md (fetched 2026-09-18):

1. Playground: https://console.typesafe.ai/playground
2. **Get your API key from the dashboard:** https://console.typesafe.ai/settings/keys
3. Call the API with Bearer token as above

From https://docs.typesafe.ai/sdk/python.md:

- Set `TYPESAFE_API_KEY` in your environment (create it [here](https://console.typesafe.ai/))

## Verified: console login wall (unauthenticated)

- `https://console.typesafe.ai/settings/keys` → **200** redirect to  
  `https://console.typesafe.ai/login?returnTo=%2Fsettings%2Fkeys`
- Login page copy (search/snippet + console HTML): **Continue with Google**, or **Continue** / **Email me a code instead**
- Terms: https://typesafe.ai/legal/terms — Privacy: https://typesafe.ai/legal/privacy-policy

**Not verified without login:** the exact button labels / screens after login to create or copy a key on `/settings/keys`. Docs name that URL; UI after auth was not clicked in this pass.

## Verified: public “waitlist” is broken / misleading

| Check | Result |
| --- | --- |
| `https://typesafe.ai/join-the-waitlist` | **404** |
| `https://typesafe.ai/waitlist` | **404** |
| Homepage control named **Join Waitlist** | `href` = `https://jobs.ashbyhq.com/typesafe-ai?...` → page title **TypeSafe AI Jobs**, h1 **Join us** (careers, not API waitlist) |

Blog https://typesafe.ai/blog/introducing-system-one-models-and-jev (2026-09-18):

- Jev in **early access**; “opening early access and bringing developers off the waitlist”
- Footer contact visible: `hello@typesafe.ai`
- Does **not** document a working public waitlist form URL

## Honest user-doc stance

1. Say TypeSafe Jev is **early access**.
2. Do **not** instruct users to click marketing **Join Waitlist** for an API key (it currently opens jobs).
3. Do **not** link `/join-the-waitlist` (404).
4. Instruct users with console access: log in at console → open **Settings → Keys** URL from docs → set `TYPESAFE_API_KEY` for music-dl.
5. For users **without** access: point to `hello@typesafe.ai` and TypeSafe docs/blog early-access language — **not** a fabricated signup wizard.
6. music-dl: enable Edition advice under **DJAI**; Score on Clean Up detail; never “safe to delete”.

## Sources

- https://docs.typesafe.ai/introduction/quickstart.md
- https://docs.typesafe.ai/sdk/python.md
- https://docs.typesafe.ai/api.md
- https://console.typesafe.ai/login (via keys redirect)
- https://typesafe.ai/ (Join Waitlist href)
- https://jobs.ashbyhq.com/typesafe-ai (Ashby jobs)
- https://typesafe.ai/blog/introducing-system-one-models-and-jev
