/**
 * Masked-line reader for the token prompt (R3 AC2).
 *
 * When stdin is a TTY we flip it to raw mode and consume keystrokes
 * silently — nothing echoes back to the terminal, not even a bullet
 * character (the simplest no-leak strategy). When stdin is not a TTY
 * (tests, piped input), we delegate to the shared line reader so we do
 * not compete with it for data — two readers attached to the same stream
 * split incoming chunks and shift every collected field.
 *
 * On Ctrl+C or EOF we return null. The caller translates that into a
 * PromptCancelError so the wizard exits non-zero rather than persisting
 * an empty value.
 */

import type { LineReader, LineReaderHandle } from "./returningUser";

export interface MaskedReaderOptions {
  /**
   * Output stream the masked reader uses for its trailing newline. MUST be
   * the same stream the rest of the wizard writes to — otherwise a
   * test-harness / wrapper process captures a broken transcript.
   */
  outputStream?: NodeJS.WritableStream;
}

export function makeMaskedLineReader(
  input: NodeJS.ReadableStream,
  sharedReader: LineReaderHandle,
  opts: MaskedReaderOptions = {},
): LineReader {
  const tty = input as NodeJS.ReadStream;
  const outputStream = opts.outputStream ?? process.stdout;

  if (!tty.isTTY) {
    // Non-TTY (tests, pipes, scripts): reuse the shared reader so the
    // single listener on stdin remains authoritative for buffering.
    return sharedReader.read;
  }

  return () =>
    new Promise<string | null>((resolve) => {
      // Hand stdin off to this reader exclusively while it runs.
      sharedReader.pause();
      let buffer = "";
      let raw: boolean;
      try {
        tty.setRawMode(true);
        raw = true;
      } catch {
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
        // Hand stdin back to the shared reader.
        sharedReader.resume();
        resolve(value);
      };

      const onData = (chunk: string) => {
        for (const ch of chunk) {
          if (ch === "\n" || ch === "\r") {
            outputStream.write("\n");
            return finalize(buffer);
          }
          if (ch === "\u0003") {
            // Ctrl+C — cancel
            outputStream.write("\n");
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
