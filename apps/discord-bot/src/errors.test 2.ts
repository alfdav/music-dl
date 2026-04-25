import { describe, expect, test } from "bun:test";
import { ErrorKind, userMessage, classifyError, safeErrorReply } from "./errors";

describe("userMessage", () => {
  test("resolution failure is user-friendly", () => {
    const msg = userMessage(ErrorKind.ResolutionFailed);
    expect(msg).toContain("find");
    expect(msg).not.toContain("http");
  });

  test("backend unavailable is clear", () => {
    const msg = userMessage(ErrorKind.BackendUnavailable);
    expect(msg).toContain("backend");
    expect(msg).toContain("unavailable");
  });

  test("voice failure is clear", () => {
    const msg = userMessage(ErrorKind.VoiceConnectionFailed);
    expect(msg).toContain("voice channel");
  });

  test("no message exposes internal details", () => {
    for (const kind of Object.values(ErrorKind)) {
      const msg = userMessage(kind as ErrorKind);
      expect(msg).not.toMatch(/https?:\/\//);
      expect(msg).not.toMatch(/Bearer/i);
      expect(msg).not.toMatch(/at \w+\.\w+ \(/);
    }
  });
});

describe("classifyError", () => {
  test("ECONNREFUSED → BackendUnavailable", () => {
    expect(classifyError(new Error("ECONNREFUSED 127.0.0.1"))).toBe(ErrorKind.BackendUnavailable);
  });

  test("voice error → VoiceConnectionFailed", () => {
    expect(classifyError(new Error("Voice connection destroyed"))).toBe(ErrorKind.VoiceConnectionFailed);
  });

  test("not found → ResolutionFailed", () => {
    expect(classifyError(new Error("Track not found"))).toBe(ErrorKind.ResolutionFailed);
  });

  test("unknown → Unknown", () => {
    expect(classifyError(new Error("cosmic ray"))).toBe(ErrorKind.Unknown);
  });

  test("non-Error → Unknown", () => {
    expect(classifyError("string")).toBe(ErrorKind.Unknown);
    expect(classifyError(null)).toBe(ErrorKind.Unknown);
  });
});

describe("safeErrorReply", () => {
  test("ECONNREFUSED returns safe message", () => {
    const reply = safeErrorReply(new Error("ECONNREFUSED"));
    expect(reply).toContain("backend");
    expect(reply).not.toContain("ECONNREFUSED");
  });

  test("never exposes internals", () => {
    const reply = safeErrorReply(
      new Error("http://secret:8000/api Bearer token stack at Object.fn"),
    );
    expect(reply).not.toContain("http");
    expect(reply).not.toContain("Bearer");
    expect(reply).not.toContain("stack");
  });
});
