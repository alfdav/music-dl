/**
 * Error reporting utilities (R9).
 * User-facing messages that never expose internal details.
 */

export enum ErrorKind {
  ResolutionFailed = "RESOLUTION_FAILED",
  BackendUnavailable = "BACKEND_UNAVAILABLE",
  VoiceConnectionFailed = "VOICE_CONNECTION_FAILED",
  Unknown = "UNKNOWN",
}

const USER_MESSAGES: Record<ErrorKind, string> = {
  [ErrorKind.ResolutionFailed]:
    "Could not find that track. Double-check the URL or search terms and try again.",
  [ErrorKind.BackendUnavailable]:
    "The music backend is currently unavailable. Try again in a moment.",
  [ErrorKind.VoiceConnectionFailed]:
    "Failed to connect to the voice channel. Make sure the bot has permission to join and speak.",
  [ErrorKind.Unknown]:
    "Something went wrong. Try again, and if it keeps happening, poke the admin.",
};

/** Get a safe user-facing error message for a given error kind. */
export function userMessage(kind: ErrorKind): string {
  return USER_MESSAGES[kind];
}

/** Classify a raw error into an ErrorKind. */
export function classifyError(error: unknown): ErrorKind {
  if (error instanceof Error) {
    const msg = error.message.toLowerCase();
    if (msg.includes("econnrefused") || msg.includes("fetch failed") || msg.includes("enotfound")) {
      return ErrorKind.BackendUnavailable;
    }
    if (msg.includes("timeout") || msg.includes("abort")) {
      return ErrorKind.BackendUnavailable;
    }
    if (msg.includes("voice") || msg.includes("udp") || msg.includes("opus")) {
      return ErrorKind.VoiceConnectionFailed;
    }
    if (msg.includes("not found") || msg.includes("404") || msg.includes("no results")) {
      return ErrorKind.ResolutionFailed;
    }
  }
  return ErrorKind.Unknown;
}

/** Build a safe reply string for Discord given a raw error. */
export function safeErrorReply(error: unknown): string {
  return userMessage(classifyError(error));
}
