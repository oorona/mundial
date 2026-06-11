// Discord Activity (Embedded App SDK) auth helper.
//
// An Activity page uses `@discord/embedded-app-sdk` to obtain an OAuth `code`
// and the instance's `guildId`, then calls `authenticateActivity(code, guildId)`
// here. We exchange them at the framework's POST /auth/activity handshake (which
// re-verifies guild membership with the bot token) and store the returned
// short-lived activity token so subsequent `apiClient` calls send it as the
// Bearer credential read by the backend's `get_activity_user` dependency.
//
// The Activity iframe is served from the discordsays proxy origin, so its
// localStorage is isolated from the dashboard session — storing the activity
// token under the same key the apiClient reads is safe and keeps API calls
// authenticated with zero extra wiring.
import { DiscordSDK } from '@discord/embedded-app-sdk';
import { apiClient, setAuthToken } from '@/app/api-client';

export interface ActivitySession {
    token: string;
    user_id: string;
    username: string;
    guild_id: string;
    /** Discord client locale (e.g. "es-ES", "en-US"), best-effort. */
    locale?: string;
}

export async function authenticateActivity(code: string, guildId: string): Promise<ActivitySession> {
    const session: ActivitySession = await apiClient.activityAuth(code, guildId);
    if (session?.token) {
        // In-memory first — Discord Activity localStorage is unreliable/partitioned,
        // so this is what actually keeps the token available for apiClient calls.
        setAuthToken(session.token);
    }
    if (typeof window !== 'undefined' && session?.token) {
        // Best-effort persistence (may be a no-op under partitioned storage).
        try {
            localStorage.setItem('access_token', session.token);
            if (session.guild_id) localStorage.setItem('activity_guild_id', String(session.guild_id));
        } catch { /* partitioned/blocked storage — in-memory token above is the source of truth */ }
    }
    return session;
}

export function getActivityToken(): string | null {
    return typeof window !== 'undefined' ? localStorage.getItem('access_token') : null;
}

/** Guild id captured by the most recent successful activity handshake (hub), or null. */
export function getActivityGuildId(): string | null {
    return typeof window !== 'undefined' ? localStorage.getItem('activity_guild_id') : null;
}

/**
 * Full Discord Activity handshake: initialise the Embedded App SDK, obtain an OAuth
 * `code` + the instance `guildId`, and mint a framework activity session.
 *
 * Returns the session, or `null` when not running inside Discord (or the handshake
 * fails) so callers can fall back to public, read-only behaviour. Requires
 * `NEXT_PUBLIC_DISCORD_CLIENT_ID` to be set at build time.
 */
export async function initActivity(): Promise<ActivitySession | null> {
    try {
        const clientId = process.env.NEXT_PUBLIC_DISCORD_CLIENT_ID;
        if (!clientId) return null;
        const sdk = new DiscordSDK(clientId);
        await sdk.ready();
        const { code } = await sdk.commands.authorize({
            client_id: clientId,
            response_type: 'code',
            state: '',
            prompt: 'none',
            scope: ['identify'],
        });
        const session = await authenticateActivity(code, String(sdk.guildId));
        // Best-effort: read the user's Discord client locale so the activity can
        // render in their language (e.g. Spanish) without any dashboard login.
        try {
            const loc = await sdk.commands.userSettingsGetLocale();
            if (loc?.locale) session.locale = loc.locale;
        } catch { /* command unavailable — fall back to browser language */ }
        return session;
    } catch {
        return null;
    }
}
