/**
 * R3 acceptance tests — five-prompt sequence + masking + defaults.
 */

import { describe, expect, it } from "bun:test";
import { Readable, Writable } from "node:stream";

import {
  PromptCancelError,
  collectBotValues,
  USER_SUPPLIED_FIELDS,
} from "./prompts";
import type { BotEnvShape } from "./returningUser";
import { makeLineReader } from "./returningUser";

class Capture extends Writable {
  chunks: string[] = [];
  _write(c: Buffer, _e: BufferEncoding, cb: () => void) {
    this.chunks.push(c.toString("utf8"));
    cb();
  }
  get text() {
    return this.chunks.join("");
  }
}

function ioFor(answers: string[]) {
  const stdin = Readable.from([answers.map((a) => a + "\n").join("")]);
  return {
    stdin,
    stdout: new Capture(),
    stderr: new Capture(),
    readLine: makeLineReader(stdin).read,
  };
}

describe("wizard R3 — prompt sequence", () => {
  it("AC1 + AC2 + AC3: prompts in correct order with breadcrumbs; token branch uses masked reader", async () => {
    // Two different reader streams — one for masked (token only), one
    // for the remaining plaintext fields. If collectBotValues uses the
    // wrong reader for a field the value comes back swapped.
    const maskedStdin = Readable.from(["my-bot-token\n"]);
    const plainStdin = Readable.from(
      [
        "app-id-value",
        "guild-id-value",
        "channel-id-value",
        "user-id-value",
        "", // accept default MUSIC_DL_BASE_URL
      ]
        .map((v) => v + "\n")
        .join(""),
    );
    const stdout = new Capture();
    const stderr = new Capture();
    const result = await collectBotValues(
      { stdin: plainStdin, stdout, stderr },
      {
        mode: "fresh",
        readLine: makeLineReader(plainStdin).read,
        readMaskedLine: makeLineReader(maskedStdin).read,
      },
    );

    expect(result.fields.DISCORD_TOKEN).toBe("my-bot-token");
    expect(result.fields.DISCORD_APPLICATION_ID).toBe("app-id-value");
    expect(result.fields.ALLOWED_GUILD_ID).toBe("guild-id-value");
    expect(result.fields.ALLOWED_CHANNEL_ID).toBe("channel-id-value");
    expect(result.fields.ALLOWED_USER_ID).toBe("user-id-value");
    expect(result.fields.MUSIC_DL_BASE_URL).toBe("http://127.0.0.1:8765");

    // All five user-supplied fields produced breadcrumbs.
    for (const field of USER_SUPPLIED_FIELDS) {
      expect(stdout.text).toContain(field.breadcrumb);
    }

    // The token prompt must not include the typed value in stdout — we
    // never echo the value (mask at the read layer, not the display
    // layer). The stdout contains the prompt label but not the token.
    expect(stdout.text).not.toContain("my-bot-token");
  });

  it("AC4: reconfigure shows existing values as defaults; Enter accepts", async () => {
    const defaults: BotEnvShape = {
      DISCORD_TOKEN: "existing-token-value",
      DISCORD_APPLICATION_ID: "existing-app",
      ALLOWED_GUILD_ID: "existing-guild",
      ALLOWED_CHANNEL_ID: "existing-channel",
      ALLOWED_USER_ID: "existing-user",
      MUSIC_DL_BASE_URL: "http://10.0.0.1:9000",
      MUSIC_DL_BOT_TOKEN: "shared-token-noop",
    };
    const { stdin, stdout, stderr, readLine } = ioFor(["", "", "", "", "", ""]);
    const result = await collectBotValues(
      { stdin, stdout, stderr },
      { mode: "reconfigure", defaults, readLine, readMaskedLine: readLine },
    );

    expect(result.fields.DISCORD_TOKEN).toBe("existing-token-value");
    expect(result.fields.DISCORD_APPLICATION_ID).toBe("existing-app");
    expect(result.fields.MUSIC_DL_BASE_URL).toBe("http://10.0.0.1:9000");

    // Token default must NOT be echoed verbatim — masked display form.
    expect(stdout.text).not.toContain("existing-token-value");
    // Non-secret defaults are shown verbatim.
    expect(stdout.text).toContain("existing-app");
  });

  it("AC5: empty required field with no default re-prompts", async () => {
    const { stdin, stdout, stderr, readLine } = ioFor([
      "", // empty token — re-prompt
      "valid-token",
      "app",
      "guild",
      "channel",
      "user",
      "", // default URL
    ]);
    const result = await collectBotValues(
      { stdin, stdout, stderr },
      { mode: "fresh", readLine, readMaskedLine: readLine },
    );
    expect(result.fields.DISCORD_TOKEN).toBe("valid-token");
    expect(stderr.text).toContain("Discord bot token is required");
  });

  it("regression: shared stdin + single reader does NOT shift field values across piped input", async () => {
    // Reproduces the Codex P1 finding: with a single shared reader
    // (masked reader delegates to the shared reader on non-TTY), feeding
    // six lines on one stdin must land each value in its own field.
    const stdin = Readable.from(
      [
        "token-LINE-1",
        "app-LINE-2",
        "guild-LINE-3",
        "channel-LINE-4",
        "user-LINE-5",
        "", // default URL
      ]
        .map((v) => v + "\n")
        .join(""),
    );
    const stdout = new Capture();
    const stderr = new Capture();
    const sharedReader = makeLineReader(stdin).read;
    const result = await collectBotValues(
      { stdin, stdout, stderr },
      {
        mode: "fresh",
        readLine: sharedReader,
        readMaskedLine: sharedReader, // non-TTY case — must share
      },
    );
    expect(result.fields.DISCORD_TOKEN).toBe("token-LINE-1");
    expect(result.fields.DISCORD_APPLICATION_ID).toBe("app-LINE-2");
    expect(result.fields.ALLOWED_GUILD_ID).toBe("guild-LINE-3");
    expect(result.fields.ALLOWED_CHANNEL_ID).toBe("channel-LINE-4");
    expect(result.fields.ALLOWED_USER_ID).toBe("user-LINE-5");
  });

  it("regression: EOF on a required field raises PromptCancelError", async () => {
    // No data — stream ends immediately. Required token field must
    // cancel rather than silently persist an empty value.
    const stdin = Readable.from([""]);
    const stdout = new Capture();
    const stderr = new Capture();
    const sharedReader = makeLineReader(stdin).read;

    let error: unknown;
    try {
      await collectBotValues(
        { stdin, stdout, stderr },
        {
          mode: "fresh",
          readLine: sharedReader,
          readMaskedLine: sharedReader,
        },
      );
    } catch (err) {
      error = err;
    }
    expect(error).toBeInstanceOf(PromptCancelError);
  });

  it("allows overriding MUSIC_DL_BASE_URL with a custom value", async () => {
    const { stdin, stdout, stderr, readLine } = ioFor([
      "tkn",
      "app",
      "guild",
      "channel",
      "user",
      "http://192.168.1.50:9999",
    ]);
    const result = await collectBotValues(
      { stdin, stdout, stderr },
      { mode: "fresh", readLine, readMaskedLine: readLine },
    );
    expect(result.fields.MUSIC_DL_BASE_URL).toBe("http://192.168.1.50:9999");
  });
});
