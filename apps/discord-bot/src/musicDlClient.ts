/**
 * Typed HTTP client for the music-dl bot API (R7).
 *
 * All requests carry the bearer token. Network failures and response
 * parsing errors surface as clear error objects rather than uncaught
 * exceptions.
 */

export interface ResolvedItem {
  id: string;
  title: string;
  artist: string;
  source_type: "local" | "tidal";
  local: boolean;
  duration: number;
}

export type ResolveResult =
  | { kind: "choices"; choices: ResolvedItem[] }
  | { kind: "track"; items: ResolvedItem[] }
  | { kind: "playlist"; items: ResolvedItem[] };

export interface PlayableSource {
  url: string;
  content_type: string;
  title: string;
  artist: string;
  duration: number;
}

export interface DownloadJob {
  job_id: string;
  status: string;
}

export interface DownloadStatus {
  job_id: string;
  status: string;
  progress: number;
  title: string;
  artist: string;
  started_at: number;
  finished_at: number | null;
}

export class MusicDlError extends Error {
  constructor(
    public readonly code: "unreachable" | "parse" | "auth" | "backend",
    message: string,
    public readonly status?: number,
  ) {
    super(message);
    this.name = "MusicDlError";
  }
}

export interface MusicDlClientOptions {
  timeoutMs?: number;
}

const DEFAULT_TIMEOUT_MS = 30_000;

export class MusicDlClient {
  private readonly timeoutMs: number;

  constructor(
    private readonly baseUrl: string,
    private readonly token: string,
    options: MusicDlClientOptions = {},
  ) {
    this.timeoutMs = options.timeoutMs ?? DEFAULT_TIMEOUT_MS;
  }

  async resolve(query: string): Promise<ResolveResult> {
    return this.request<ResolveResult>("POST", "/api/bot/play/resolve", { query });
  }

  async playable(itemId: string): Promise<PlayableSource> {
    return this.request<PlayableSource>("POST", "/api/bot/playable", { item_id: itemId });
  }

  async triggerDownload(itemId: string): Promise<DownloadJob> {
    return this.request<DownloadJob>("POST", "/api/bot/download", { item_id: itemId });
  }

  async downloadStatus(jobId: string): Promise<DownloadStatus> {
    return this.request<DownloadStatus>("GET", `/api/bot/downloads/${encodeURIComponent(jobId)}`);
  }

  /** Resolve a relative stream URL returned by /playable to an absolute URL. */
  absolutize(relativeOrAbsolute: string): string {
    if (relativeOrAbsolute.startsWith("http")) return relativeOrAbsolute;
    return this.baseUrl.replace(/\/$/, "") + relativeOrAbsolute;
  }

  private async request<T>(
    method: "GET" | "POST",
    path: string,
    body?: unknown,
  ): Promise<T> {
    const url = this.baseUrl.replace(/\/$/, "") + path;
    const controller = new AbortController();
    const timer = setTimeout(() => controller.abort(), this.timeoutMs);

    let response: Response;
    try {
      response = await fetch(url, {
        method,
        headers: {
          authorization: `Bearer ${this.token}`,
          ...(body !== undefined ? { "content-type": "application/json" } : {}),
        },
        body: body !== undefined ? JSON.stringify(body) : undefined,
        signal: controller.signal,
      });
    } catch (error) {
      clearTimeout(timer);
      throw new MusicDlError(
        "unreachable",
        `Backend unreachable: ${(error as Error).message}`,
      );
    }
    clearTimeout(timer);

    if (response.status === 401) {
      throw new MusicDlError("auth", "Backend rejected bot credentials", 401);
    }
    if (!response.ok) {
      throw new MusicDlError(
        "backend",
        `Backend returned ${response.status}`,
        response.status,
      );
    }

    try {
      return (await response.json()) as T;
    } catch (error) {
      throw new MusicDlError(
        "parse",
        `Failed to parse backend response: ${(error as Error).message}`,
      );
    }
  }
}
