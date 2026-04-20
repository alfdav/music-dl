/**
 * Masked-line reader for the token prompt (R3 AC2).
 *
 * When stdin is a TTY we flip it to raw mode and consume keystrokes
 * silently — nothing echoes back to the terminal, not even a bullet
 * character (the simplest no-leak strategy). When stdin is not a TTY
 * (tests, piped input), we fall back to a regular line read — there is
 * no echo to suppress.
 */

import type { LineReader } from "./returningUser";
import { makeLineReader } from "./returningUser";

export function makeMaskedLineReader(
  input: NodeJS.ReadableStream,
): LineReader {
  const tty = input as NodeJS.ReadStream;
  if (!tty.isTTY) {
    return makeLineReader(input);
  }

  return () =>
    new Promise<string | null>((resolve) => {
      let buffer = "";
      let raw: boolean;
      try {
        tty.setRawMode(true);
        raw = true;
      } catch {
        // Platform does not support raw mode — fall back to a normal read.
        raw = false;
      }
      tty.resume();
      tty.setEncoding("utf8");

      const finalize = (value: string | null) => {
        tty.off("data", onData);
        tty.off("end", onEnd);
        if (raw) {
          try {
            tty.setRawMode(false);
          } catch {
            // best-effort
          }
        }
        resolve(value);
      };

      const onData = (chunk: string) => {
        for (const ch of chunk) {
          if (ch === "\n" || ch === "\r") {
            // Echo the newline so the next prompt lands on a fresh line,
            // but never echo the typed characters themselves.
            process.stdout.write("\n");
            return finalize(buffer);
          }
          if (ch === "\u0003") {
            // Ctrl+C — cancel
            process.stdout.write("\n");
            return finalize(null);
          }
          if (ch === "\u0008" || ch === "\u007f") {
            buffer = buffer.slice(0, -1);
            continue;
          }
          buffer += ch;
        }
      };

      const onEnd = () => finalize(buffer.length > 0 ? buffer : null);

      tty.on("data", onData);
      tty.once("end", onEnd);
    });
}
