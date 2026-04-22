import { describe, expect, test, beforeEach } from "bun:test";
import { QueueState } from "./queue";

function item(id: string) {
  return { id, title: `Track ${id}` };
}

describe("QueueState", () => {
  let q: QueueState;

  beforeEach(() => {
    q = new QueueState();
  });

  // R3: Items can be appended to the queue
  test("append adds items", () => {
    q.append([item("a"), item("b")]);
    expect(q.contents()).toEqual([item("a"), item("b")]);
    expect(q.length).toBe(2);
  });

  // R3: Queue tracks a current item index
  test("current tracks index after append", () => {
    expect(q.current()).toBeNull();
    q.append([item("a")]);
    expect(q.current()).toEqual(item("a"));
  });

  // R3: Repeat off — advance moves to next, stops when exhausted
  test("repeat off exhausts", () => {
    q.setRepeat("off");
    q.append([item("a"), item("b")]);
    expect(q.current()?.id).toBe("a");
    expect(q.advance()?.id).toBe("b");
    expect(q.advance()).toBeNull();
    expect(q.advance()).toBeNull(); // stays exhausted
  });

  // R3: Repeat one — replays current item indefinitely
  test("repeat one replays", () => {
    q.setRepeat("one");
    q.append([item("a"), item("b")]);
    expect(q.advance()?.id).toBe("a");
    expect(q.advance()?.id).toBe("a");
    expect(q.advance()?.id).toBe("a");
  });

  // R3: Repeat all — wraps to first item after last
  test("repeat all wraps", () => {
    q.append([item("a"), item("b")]);
    expect(q.current()?.id).toBe("a");
    expect(q.advance()?.id).toBe("b");
    expect(q.advance()?.id).toBe("a"); // wrapped
  });

  // R3: Default repeat mode is all
  test("default repeat mode is all", () => {
    expect(q.getRepeat()).toBe("all");
  });

  // R3: Queue can be cleared
  test("clear empties queue", () => {
    q.append([item("a"), item("b")]);
    q.clear();
    expect(q.length).toBe(0);
    expect(q.current()).toBeNull();
    expect(q.contents()).toEqual([]);
  });

  // R3: Queue can report current contents and current item
  test("contents returns snapshot", () => {
    q.append([item("a")]);
    const snap = q.contents();
    q.append([item("b")]);
    expect(snap).toEqual([item("a")]);
    expect(q.contents()).toEqual([item("a"), item("b")]);
  });

  // Edge cases
  test("advance on empty returns null", () => {
    expect(q.advance()).toBeNull();
  });

  test("single item repeat all loops", () => {
    q.append([item("a")]);
    expect(q.advance()?.id).toBe("a");
    expect(q.advance()?.id).toBe("a");
  });
});
