// Server-Sent Events client helper — the sanctioned framework streaming path
// for the browser. Plugins use `subscribeSSE` instead of constructing an
// `EventSource` directly; the validator permits it on any page (raw
// `EventSource` stays limited to public/activity pages).
//
// The API base is resolved exactly like `app/api-client.ts`: in the browser the
// path is relative (the Next.js proxy forwards /api/v1 to the backend), so an
// SSE stream route such as `/guilds/123/feed/stream` becomes
// `/api/v1/guilds/123/feed/stream`.

const API_BASE_URL =
    typeof window === 'undefined'
        ? process.env.INTERNAL_API_URL || 'http://backend:8000'
        : process.env.NEXT_PUBLIC_API_URL || '';

export interface SSEHandle {
    /** Close the underlying EventSource. */
    close: () => void;
    /** The live EventSource, for attaching named-event listeners if needed. */
    source: EventSource;
}

export interface SubscribeOptions {
    /** Named SSE events to listen for in addition to the default `message`. */
    events?: string[];
    /** Called on connection error. */
    onError?: (err: Event) => void;
}

/**
 * Subscribe to an SSE route. `onEvent` receives the parsed JSON payload (or the
 * raw string if it isn't JSON). Returns a handle whose `close()` ends the
 * stream — call it from a React effect cleanup.
 *
 *   useEffect(() => {
 *     const sub = subscribeSSE(`/guilds/${guildId}/feed/stream`, (e) => setItems(p => [e, ...p]));
 *     return () => sub.close();
 *   }, [guildId]);
 */
export function subscribeSSE(
    path: string,
    onEvent: (data: any) => void,
    options: SubscribeOptions = {},
): SSEHandle {
    const url = `${API_BASE_URL}/api/v1${path.startsWith('/') ? path : `/${path}`}`;
    const source = new EventSource(url, { withCredentials: true });

    const handler = (e: MessageEvent) => {
        if (!e.data) return; // ping/keep-alive
        try {
            onEvent(JSON.parse(e.data));
        } catch {
            onEvent(e.data);
        }
    };

    source.onmessage = handler;
    for (const name of options.events ?? []) {
        source.addEventListener(name, handler as EventListener);
    }
    if (options.onError) {
        source.onerror = options.onError;
    }

    return { close: () => source.close(), source };
}
