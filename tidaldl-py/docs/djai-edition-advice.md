# Edition advice (Jev)

Advisory TypeSafe Jev classification on Clean Up. This is a **DJAI module**, not a Settings toggle.

AI suggestions can be wrong. Treat edition advice as advisory. Confirm paths yourself (Reveal in Finder) before Clean Up. music-dl never promises a suggestion is safe to delete.

DJAI modules that use AI can make mistakes. Verify important actions yourself before you confirm them. See [`djai-modules.md`](djai-modules.md).

Evidence for TypeSafe key and API facts: Techmarine verified note dated **2026-09-18** (`docs/plans/2026-09-18-typesafe-key-access-verified.md`). This guide does not add steps beyond that note.

## Where it lives

1. Open music-dl.
2. Open **DJAI**.
3. Use the **Edition advice (Jev)** card — enable the module there.

Do not look for an Edition advice switch in Settings. The boolean is stored with other settings for persistence only.

## What you need

- The DJAI module enabled (off = Clean Up behaves as it does today).
- Environment variable `TYPESAFE_API_KEY` set for the **music-dl process**.
- A scorer CLI compatible with `typesafe-music-edition` (`--a` / `--b` JSON). music-dl looks on `PATH` and well-known install locations. The card shows scorer status: **Ready**, **Missing binary**, or **n/a**.

music-dl does not log the API key.

## Get a TypeSafe Jev API key

TypeSafe Jev is **early access**.

### If you already have console access

TypeSafe Quick start (fetched 2026-09-18) names these URLs:

1. Log in at [console.typesafe.ai](https://console.typesafe.ai). The unauthenticated keys URL redirects to login. Login copy verified without an account: **Continue with Google**, or **Continue** / **Email me a code instead**.
2. After login, open the Settings → Keys URL from TypeSafe docs: [https://console.typesafe.ai/settings/keys](https://console.typesafe.ai/settings/keys).
3. Copy the key into `TYPESAFE_API_KEY` for the music-dl process.

We did **not** verify the authenticated keys page. This guide does not name post-login button labels.

Optional try-out: [TypeSafe Playground](https://console.typesafe.ai/playground).

### If you do not have console access

Ask TypeSafe about early access. Contact visible on the TypeSafe site: `hello@typesafe.ai`. See also their blog post on System One / Jev early access.

Do **not** click marketing **Join Waitlist** for an API key — that control currently opens TypeSafe **jobs**, not a key form. There is no working public waitlist form URL.

## TypeSafe API (verified)

The sidecar talks to TypeSafe. Verified request shape:

- `POST https://api.typesafe.ai/v1/systemone`
- `Authorization: Bearer <API_KEY>`
- Model alias in TypeSafe docs: `jev-latest` (a 2026-09-18 smoke returned `jev-1.13.0`)

You do not paste this URL into music-dl. Set `TYPESAFE_API_KEY` and keep the scorer CLI available.

## How to use it in music-dl

1. Enable **DJAI → Edition advice**.
2. Open **Clean Up**.
3. Open a duplicate group (expand the card).
4. Click **Score** or **Re-score**. The list does not score every row when it opens; chips stay `Edition: —` until cached.
5. Read the chip and per-extra relation + confidence. Copy never says “safe to delete”. True duplicates are labeled **candidate**.
6. Checkboxes: extras with status auto stay available to clean. After scores land, ≥0.95 `layout_twin_extra` or `true_duplicate_candidate` may auto-check. You can uncheck; Clean Up honors that.
7. Before you confirm: AI suggestions can be wrong. Treat edition advice as advisory. Confirm paths yourself (Reveal in Finder). music-dl never promises a suggestion is safe to delete.
8. Confirm Clean Up. Only checked extras are posted. The server still refuses `keep_both_editions` and `insufficient_evidence` (unclear). Unscored pairs are never auto-deleted via Jev.

Scorer missing or errors: chips show **n/a**. Clean Up still works.

## Related

- DJAI overview: [`djai-modules.md`](djai-modules.md)
- Verified research appendix: [`docs/plans/2026-09-18-typesafe-key-access-verified.md`](../../docs/plans/2026-09-18-typesafe-key-access-verified.md)
- TypeSafe Quick start: https://docs.typesafe.ai/introduction/quickstart.md
- TypeSafe Python SDK env note: https://docs.typesafe.ai/sdk/python.md
