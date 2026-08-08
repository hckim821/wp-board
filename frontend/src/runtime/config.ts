/**
 * Runtime configuration.
 *
 * INTEGRATION.md §5: the API base URL and auth token are supplied at **runtime** — via
 * `configure()` before mount, or per-instance props. `import.meta.env` is never read at
 * module scope here, because Vite inlines it at build time and the dev value would be
 * frozen into the federated bundle the host downloads.
 *
 * `hostDefaults` is the only module-scope state in the package. It holds configuration
 * the host sets once, never per-board state, and every instance can override it, so two
 * concurrently mounted boards can point at different backends.
 */
export interface WpRuntimeConfig {
  /** e.g. `https://intranet.example.com/wp` — the `/api/v1/...` paths are appended. */
  apiBaseUrl: string
  /** Extra headers merged into every request (tenant id, trace id, …). */
  headers: Record<string, string>
  /** Called per request; return `null` to send no Authorization header. */
  getAuthToken: (() => string | null | Promise<string | null>) | null
  requestTimeoutMs: number
  withCredentials: boolean
}

const BUILTIN_DEFAULTS: WpRuntimeConfig = {
  apiBaseUrl: '',
  headers: {},
  getAuthToken: null,
  requestTimeoutMs: 30_000,
  withCredentials: false,
}

let hostDefaults: Partial<WpRuntimeConfig> = {}

/** Host-side setup. Call once before mounting the exposed component. */
export function configure(config: Partial<WpRuntimeConfig>): void {
  hostDefaults = { ...hostDefaults, ...config }
}

/** Test/teardown helper — drops anything a previous `configure()` set. */
export function resetConfiguration(): void {
  hostDefaults = {}
}

export function resolveConfig(overrides: Partial<WpRuntimeConfig> = {}): WpRuntimeConfig {
  const merged = { ...BUILTIN_DEFAULTS, ...hostDefaults }
  for (const [key, value] of Object.entries(overrides)) {
    if (value !== undefined) {
      ;(merged as Record<string, unknown>)[key] = value
    }
  }
  merged.headers = { ...(hostDefaults.headers ?? {}), ...(overrides.headers ?? {}) }
  return merged
}
