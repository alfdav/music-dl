/**
 * Tests for the picker message builder (R8).
 *
 * The build step is pure; runPicker's collector is exercised live at
 * integration time (T-017) since discord.js's message-component runtime
 * is not easily unit-mockable.
 */

import { describe, expect, test } from "bun:test";
import { ButtonStyle } from "discord.js";
import { buildPickerMessage } from "./picker";
import type { ResolvedItem } from "./musicDlClient";

function item(id: string, title: string, artist: string, local = false): ResolvedItem {
  return { id, title, artist, source_type: "tidal", local, duration: 200 };
}

describe("buildPickerMessage", () => {
  test("renders a numbered list of every choice", () => {
    const payload = buildPickerMessage([
      item("a", "Alpha", "X"),
      item("b", "Beta", "Y"),
      item("c", "Gamma", "Z"),
    ]);
    expect(payload.content).toContain("1. **Alpha** — X");
    expect(payload.content).toContain("2. **Beta** — Y");
    expect(payload.content).toContain("3. **Gamma** — Z");
  });

  test("caps at 5 visible choices even when more are supplied", () => {
    const payload = buildPickerMessage([
      item("1", "One", "A"),
      item("2", "Two", "A"),
      item("3", "Three", "A"),
      item("4", "Four", "A"),
      item("5", "Five", "A"),
      item("6", "Six", "A"),
      item("7", "Seven", "A"),
    ]);
    expect(payload.content).toContain("5. **Five**");
    expect(payload.content).not.toContain("6. **Six**");
    const row = payload.components[0].toJSON() as { components: unknown[] };
    expect(row.components.length).toBe(5);
  });

  test("emits one primary button per choice with pick:<idx> custom id", () => {
    const payload = buildPickerMessage([
      item("a", "Alpha", "X"),
      item("b", "Beta", "Y"),
    ]);
    const row = payload.components[0].toJSON() as {
      components: Array<{ custom_id: string; label: string; style: ButtonStyle }>;
    };
    expect(row.components.length).toBe(2);
    expect(row.components[0].custom_id).toBe("pick:0");
    expect(row.components[1].custom_id).toBe("pick:1");
    expect(row.components[0].label).toBe("1");
    expect(row.components[0].style).toBe(ButtonStyle.Primary);
  });

  test("marks local items with (local)", () => {
    const payload = buildPickerMessage([
      item("a", "Alpha", "X", true),
      item("b", "Beta", "Y", false),
    ]);
    expect(payload.content).toMatch(/Alpha.*_\(local\)_/);
    expect(payload.content).not.toMatch(/Beta.*_\(local\)_/);
  });
});
