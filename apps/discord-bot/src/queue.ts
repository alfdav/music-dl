/**
 * Runtime queue state machine (R3).
 *
 * Pure state — no Discord dependencies. Tracks items, current index,
 * and repeat mode that governs advance behaviour.
 */

export type RepeatMode = "off" | "one" | "all";

export interface QueueItem {
  id: string;
  title?: string;
  artist?: string;
  [key: string]: unknown;
}

export class QueueState {
  private items: QueueItem[] = [];
  private index = -1;
  private repeat: RepeatMode = "all"; // R3: default repeat mode is all

  /** Append items to the end of the queue. */
  append(newItems: QueueItem[]): void {
    const wasEmpty = this.items.length === 0;
    this.items.push(...newItems);
    if (wasEmpty && this.items.length > 0) {
      this.index = 0;
    }
  }

  /** Set the repeat mode. */
  setRepeat(mode: RepeatMode): void {
    this.repeat = mode;
  }

  /** Get current repeat mode. */
  getRepeat(): RepeatMode {
    return this.repeat;
  }

  /** Current item, or null if empty/exhausted. */
  current(): QueueItem | null {
    if (this.index < 0 || this.index >= this.items.length) return null;
    return this.items[this.index];
  }

  /** Current position in the queue, or -1 if empty/exhausted. */
  currentIndex(): number {
    if (this.index < 0 || this.index >= this.items.length) return -1;
    return this.index;
  }

  /** Drop the item at *position*. Adjusts the cursor so the relative order is preserved. */
  removeAt(position: number): QueueItem | null {
    if (position < 0 || position >= this.items.length) return null;
    const [removed] = this.items.splice(position, 1);
    if (this.items.length === 0) {
      this.index = -1;
    } else if (position < this.index) {
      this.index -= 1;
    } else if (position === this.index && this.index >= this.items.length) {
      this.index = this.items.length - 1;
    }
    return removed ?? null;
  }

  /**
   * Advance to next item per repeat mode.
   * Returns new current item or null when exhausted.
   */
  advance(): QueueItem | null {
    if (this.items.length === 0) return null;

    switch (this.repeat) {
      case "one":
        return this.items[this.index] ?? null;

      case "all":
        this.index = (this.index + 1) % this.items.length;
        return this.items[this.index];

      case "off":
      default:
        this.index += 1;
        if (this.index >= this.items.length) {
          this.index = this.items.length;
          return null;
        }
        return this.items[this.index];
    }
  }

  /** Clear all items and reset. */
  clear(): void {
    this.items = [];
    this.index = -1;
  }

  /** Snapshot of all queue contents. */
  contents(): readonly QueueItem[] {
    return [...this.items];
  }

  /** Number of items. */
  get length(): number {
    return this.items.length;
  }
}
