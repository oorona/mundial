/**
 * Tests for the Bot Settings page (/app/dashboard/[guildId]/settings/page.tsx).
 *
 * Guards against:
 *   - Schema and settings not fetched on mount
 *   - Incorrect field type rendering (boolean → checkbox, text → text input, etc.)
 *   - Permission gate not enforced (non-owners must see read-only form)
 *   - Save action not calling updateGuildSettings with correct payload
 *   - API errors swallowed silently (both on load and on save)
 *   - Loading state not shown while data is in flight
 */
import React from 'react'
import { describe, it, expect, vi, beforeEach } from 'vitest'
import { render, screen, waitFor, act, fireEvent } from '@testing-library/react'

// ── Shared static mocks ───────────────────────────────────────────────────────

vi.mock('next/navigation', () => ({
    useRouter:       () => ({ push: vi.fn() }),
    usePathname:     () => '/dashboard/123456789/settings',
    useSearchParams: () => new URLSearchParams(),
    useParams:       () => ({ guildId: '123456789' }),
}))

vi.mock('@tanstack/react-query', () => ({
    useQuery:            () => ({ data: null, isLoading: false, error: null }),
    QueryClient:         class {},
    QueryClientProvider: ({ children }: { children: React.ReactNode }) => children,
}))

vi.mock('@/lib/i18n', () => ({
    useTranslation: () => ({
        t: (k: string, a?: any) => (a ? `${k}:${JSON.stringify(a)}` : k),
        language: 'en',
    }),
    LanguageProvider: ({ children }: { children: React.ReactNode }) => children,
}))

vi.mock('@/lib/components/with-permission', () => ({
    withPermission: (Component: React.ComponentType<any>) =>
        function MockedWithPermission(props: any) {
            return <Component {...props} />
        },
}))

// ── Sample data ───────────────────────────────────────────────────────────────

const SAMPLE_SCHEMA = {
    id:    'test_cog',
    label: 'Test Settings',
    fields: [
        { key: 'enabled',    type: 'boolean',        label: 'Enable',     default: false },
        { key: 'prefix',     type: 'text',           label: 'Prefix',     default: '!'   },
        { key: 'limit',      type: 'number',         label: 'Max Items',  default: 10    },
        { key: 'channel_id', type: 'channel_select', label: 'Channel',    default: null  },
        { key: 'role_id',    type: 'role_select',    label: 'Role',       default: null  },
    ],
}

const SAMPLE_SETTINGS = {
    guild_id:   '123456789',
    settings:   { enabled: true, prefix: '!', limit: 10, channel_id: null, role_id: null },
    can_modify_level_3: false,
    updated_at: '2026-01-01T00:00:00Z',
}

const SAMPLE_CHANNELS = [
    { id: '111', name: 'general', type: 0 },
    { id: '222', name: 'announcements', type: 0 },
    { id: '333', name: 'voice-channel', type: 2 },   // type 2 — should be filtered out
]

const SAMPLE_ROLES = [
    { id: '444', name: 'Admin',     color: 0xff0000 },
    { id: '555', name: 'Moderator', color: 0x00ff00 },
    { id: '666', name: '@everyone', color: 0 },       // should be filtered out
]

// ── Helpers ───────────────────────────────────────────────────────────────────

function makeApiMock(overrides: Record<string, any> = {}) {
    return {
        getSettingsSchema:  vi.fn().mockResolvedValue({ schemas: [SAMPLE_SCHEMA] }),
        getGuildSettings:   vi.fn().mockResolvedValue(SAMPLE_SETTINGS),
        getGuild:           vi.fn().mockResolvedValue({ id: '123456789', permission_level: 'owner' }),
        getGuildChannels:   vi.fn().mockResolvedValue(SAMPLE_CHANNELS),
        getGuildRoles:      vi.fn().mockResolvedValue(SAMPLE_ROLES),
        updateGuildSettings: vi.fn().mockResolvedValue(SAMPLE_SETTINGS),
        ...overrides,
    }
}

// ── describe: data loading ────────────────────────────────────────────────────

describe('BotSettingsPage — data loading', () => {
    beforeEach(() => {
        vi.resetModules()
    })

    it('calls getSettingsSchema() on mount', async () => {
        const api = makeApiMock()
        vi.doMock('@/lib/auth-context', () => ({
            useAuth: () => ({ user: { user_id: '1', is_admin: false }, loading: false }),
        }))
        vi.doMock('@/app/api-client', () => ({ apiClient: api }))

        const { default: SettingsPage } = await import('../app/dashboard/[guildId]/settings/page')
        await act(async () => { render(<SettingsPage />) })

        await waitFor(() => {
            expect(api.getSettingsSchema).toHaveBeenCalledOnce()
        })
    })

    it('calls getGuildSettings() on mount', async () => {
        const api = makeApiMock()
        vi.doMock('@/lib/auth-context', () => ({
            useAuth: () => ({ user: { user_id: '1', is_admin: false }, loading: false }),
        }))
        vi.doMock('@/app/api-client', () => ({ apiClient: api }))

        const { default: SettingsPage } = await import('../app/dashboard/[guildId]/settings/page')
        await act(async () => { render(<SettingsPage />) })

        await waitFor(() => {
            expect(api.getGuildSettings).toHaveBeenCalledOnce()
        })
    })

    it('schema with boolean field renders an input[type=checkbox]', async () => {
        vi.doMock('@/lib/auth-context', () => ({
            useAuth: () => ({ user: { user_id: '1', is_admin: false }, loading: false }),
        }))
        vi.doMock('@/app/api-client', () => ({ apiClient: makeApiMock() }))

        const { default: SettingsPage } = await import('../app/dashboard/[guildId]/settings/page')
        await act(async () => { render(<SettingsPage />) })

        await waitFor(() => {
            // BooleanField renders <input type="checkbox" id={field.key}>
            const checkbox = document.getElementById('enabled') as HTMLInputElement | null
            expect(checkbox).not.toBeNull()
            expect(checkbox!.type).toBe('checkbox')
        })
    })

    it('schema with text field renders an input[type=text]', async () => {
        vi.doMock('@/lib/auth-context', () => ({
            useAuth: () => ({ user: { user_id: '1', is_admin: false }, loading: false }),
        }))
        vi.doMock('@/app/api-client', () => ({ apiClient: makeApiMock() }))

        const { default: SettingsPage } = await import('../app/dashboard/[guildId]/settings/page')
        await act(async () => { render(<SettingsPage />) })

        await waitFor(() => {
            // TextField with type 'text' renders <input type="text">
            const inputs = document.querySelectorAll('input[type="text"]')
            expect(inputs.length).toBeGreaterThan(0)
            // The prefix label is visible
            expect(screen.getByText('Prefix')).toBeDefined()
        })
    })

    it('schema with number field renders an input[type=number]', async () => {
        vi.doMock('@/lib/auth-context', () => ({
            useAuth: () => ({ user: { user_id: '1', is_admin: false }, loading: false }),
        }))
        vi.doMock('@/app/api-client', () => ({ apiClient: makeApiMock() }))

        const { default: SettingsPage } = await import('../app/dashboard/[guildId]/settings/page')
        await act(async () => { render(<SettingsPage />) })

        await waitFor(() => {
            // TextField dispatches input[type=number] when field.type === 'number'
            const inputs = document.querySelectorAll('input[type="number"]')
            expect(inputs.length).toBeGreaterThan(0)
            expect(screen.getByText('Max Items')).toBeDefined()
        })
    })

    it('schema with channel_select field renders a <select> with channel options', async () => {
        vi.doMock('@/lib/auth-context', () => ({
            useAuth: () => ({ user: { user_id: '1', is_admin: false }, loading: false }),
        }))
        vi.doMock('@/app/api-client', () => ({ apiClient: makeApiMock() }))

        const { default: SettingsPage } = await import('../app/dashboard/[guildId]/settings/page')
        await act(async () => { render(<SettingsPage />) })

        await waitFor(() => {
            // ChannelSelectField placeholder — i18n key (the t() mock returns the key)
            expect(screen.getByText('common.selectChannel')).toBeDefined()
            // Only type-0 channels are loaded; type-2 must be absent
            expect(screen.getByText('#general')).toBeDefined()
            expect(screen.getByText('#announcements')).toBeDefined()
            expect(screen.queryByText('#voice-channel')).toBeNull()
        })
    })

    it('schema with role_select field renders a <select> with role options', async () => {
        vi.doMock('@/lib/auth-context', () => ({
            useAuth: () => ({ user: { user_id: '1', is_admin: false }, loading: false }),
        }))
        vi.doMock('@/app/api-client', () => ({ apiClient: makeApiMock() }))

        const { default: SettingsPage } = await import('../app/dashboard/[guildId]/settings/page')
        await act(async () => { render(<SettingsPage />) })

        await waitFor(() => {
            // RoleSelectField placeholder — i18n key (the t() mock returns the key)
            expect(screen.getByText('common.selectRole')).toBeDefined()
            // @everyone is filtered; named roles must appear
            expect(screen.getByText('@Admin')).toBeDefined()
            expect(screen.getByText('@Moderator')).toBeDefined()
            expect(screen.queryByText('@everyone')).toBeNull()
        })
    })

    it('shows a loading indicator while data is being fetched', async () => {
        // Use a never-resolving promise so the component stays in the loading state
        const neverResolve = new Promise<never>(() => { /* intentionally never resolves */ })

        vi.doMock('@/lib/auth-context', () => ({
            useAuth: () => ({ user: { user_id: '1', is_admin: false }, loading: false }),
        }))
        vi.doMock('@/app/api-client', () => ({
            apiClient: {
                getSettingsSchema:   vi.fn().mockReturnValue(neverResolve),
                getGuildSettings:    vi.fn().mockReturnValue(neverResolve),
                getGuild:            vi.fn().mockReturnValue(neverResolve),
                getGuildChannels:    vi.fn().mockReturnValue(neverResolve),
                getGuildRoles:       vi.fn().mockReturnValue(neverResolve),
                updateGuildSettings: vi.fn(),
            },
        }))

        const { default: SettingsPage } = await import('../app/dashboard/[guildId]/settings/page')
        await act(async () => { render(<SettingsPage />) })

        // The loading text is rendered while all promises are pending
        expect(screen.getByText('guildSettings.loading')).toBeDefined()
    })
})

// ── describe: permissions ─────────────────────────────────────────────────────

describe('BotSettingsPage — permissions', () => {
    beforeEach(() => {
        vi.resetModules()
    })

    it('owner user — form fields are enabled (editable)', async () => {
        vi.doMock('@/lib/auth-context', () => ({
            useAuth: () => ({ user: { user_id: '1', is_admin: false }, loading: false }),
        }))
        vi.doMock('@/app/api-client', () => ({
            apiClient: makeApiMock({
                getGuild: vi.fn().mockResolvedValue({ id: '123456789', permission_level: 'owner' }),
            }),
        }))

        const { default: SettingsPage } = await import('../app/dashboard/[guildId]/settings/page')
        await act(async () => { render(<SettingsPage />) })

        await waitFor(() => {
            // When canModify is true, the checkbox for 'enabled' must not be disabled
            const checkbox = document.getElementById('enabled') as HTMLInputElement | null
            expect(checkbox).not.toBeNull()
            expect(checkbox!.disabled).toBe(false)
        })
    })

    it('non-admin (USER level, not owner or admin) — form fields are disabled', async () => {
        vi.doMock('@/lib/auth-context', () => ({
            useAuth: () => ({ user: { user_id: '1', is_admin: false }, loading: false }),
        }))
        vi.doMock('@/app/api-client', () => ({
            apiClient: makeApiMock({
                getGuild: vi.fn().mockResolvedValue({ id: '123456789', permission_level: 'user' }),
                getGuildSettings: vi.fn().mockResolvedValue({
                    ...SAMPLE_SETTINGS,
                    can_modify_level_3: false,
                }),
            }),
        }))

        const { default: SettingsPage } = await import('../app/dashboard/[guildId]/settings/page')
        await act(async () => { render(<SettingsPage />) })

        await waitFor(() => {
            // isReadOnly === true → all inputs get disabled={true}
            const checkbox = document.getElementById('enabled') as HTMLInputElement | null
            expect(checkbox).not.toBeNull()
            expect(checkbox!.disabled).toBe(true)
        })
    })

    it('non-admin — read-only banner is shown', async () => {
        vi.doMock('@/lib/auth-context', () => ({
            useAuth: () => ({ user: { user_id: '1', is_admin: false }, loading: false }),
        }))
        vi.doMock('@/app/api-client', () => ({
            apiClient: makeApiMock({
                getGuild: vi.fn().mockResolvedValue({ id: '123456789', permission_level: 'user' }),
                getGuildSettings: vi.fn().mockResolvedValue({
                    ...SAMPLE_SETTINGS,
                    can_modify_level_3: false,
                }),
            }),
        }))

        const { default: SettingsPage } = await import('../app/dashboard/[guildId]/settings/page')
        await act(async () => { render(<SettingsPage />) })

        await waitFor(() => {
            expect(screen.getByText(/guildSettings.readOnlyBanner/i)).toBeDefined()
        })
    })

    it('calls getGuild() to determine owner status', async () => {
        const api = makeApiMock()
        vi.doMock('@/lib/auth-context', () => ({
            useAuth: () => ({ user: { user_id: '1', is_admin: false }, loading: false }),
        }))
        vi.doMock('@/app/api-client', () => ({ apiClient: api }))

        const { default: SettingsPage } = await import('../app/dashboard/[guildId]/settings/page')
        await act(async () => { render(<SettingsPage />) })

        await waitFor(() => {
            expect(api.getGuild).toHaveBeenCalledOnce()
        })
    })
})

// ── describe: save action ─────────────────────────────────────────────────────

describe('BotSettingsPage — save action', () => {
    beforeEach(() => {
        vi.resetModules()
    })

    it('calls updateGuildSettings() with correct guild_id and current settings on save', async () => {
        const api = makeApiMock()
        vi.doMock('@/lib/auth-context', () => ({
            useAuth: () => ({ user: { user_id: '1', is_admin: false }, loading: false }),
        }))
        vi.doMock('@/app/api-client', () => ({ apiClient: api }))

        const { default: SettingsPage } = await import('../app/dashboard/[guildId]/settings/page')
        await act(async () => { render(<SettingsPage />) })

        // Wait for schema to render, then the Save button appears
        await waitFor(() => screen.getByText('guildSettings.saveButton'))

        await act(async () => {
            fireEvent.click(screen.getByText('guildSettings.saveButton'))
        })

        await waitFor(() => {
            expect(api.updateGuildSettings).toHaveBeenCalledOnce()
            const [calledGuildId, payload] = api.updateGuildSettings.mock.calls[0]
            expect(calledGuildId).toBe('123456789')
            // payload must be the flat settings dict — NOT wrapped in { settings: ... }
            expect(payload).not.toHaveProperty('settings')
            expect(payload).toMatchObject({ enabled: true, prefix: '!', limit: 10 })
        })
    })

    it('shows success message after a successful save', async () => {
        vi.doMock('@/lib/auth-context', () => ({
            useAuth: () => ({ user: { user_id: '1', is_admin: false }, loading: false }),
        }))
        vi.doMock('@/app/api-client', () => ({ apiClient: makeApiMock() }))

        const { default: SettingsPage } = await import('../app/dashboard/[guildId]/settings/page')
        await act(async () => { render(<SettingsPage />) })

        await waitFor(() => screen.getByText('guildSettings.saveButton'))

        await act(async () => {
            fireEvent.click(screen.getByText('guildSettings.saveButton'))
        })

        await waitFor(() => {
            expect(screen.getByText('guildSettings.savedSuccess')).toBeDefined()
        })
    })

    it('shows error message when updateGuildSettings() rejects — error is not swallowed', async () => {
        vi.doMock('@/lib/auth-context', () => ({
            useAuth: () => ({ user: { user_id: '1', is_admin: false }, loading: false }),
        }))
        vi.doMock('@/app/api-client', () => ({
            apiClient: makeApiMock({
                updateGuildSettings: vi.fn().mockRejectedValue(new Error('Server error')),
            }),
        }))

        const { default: SettingsPage } = await import('../app/dashboard/[guildId]/settings/page')
        await act(async () => { render(<SettingsPage />) })

        await waitFor(() => screen.getByText('guildSettings.saveButton'))

        await act(async () => {
            fireEvent.click(screen.getByText('guildSettings.saveButton'))
        })

        await waitFor(() => {
            expect(screen.getByText('guildSettings.saveError')).toBeDefined()
        })
    })
})

// ── describe: error states ────────────────────────────────────────────────────

describe('BotSettingsPage — error states', () => {
    beforeEach(() => {
        vi.resetModules()
    })

    it('getSettingsSchema() fails — does not crash, shows empty/error state instead of hanging', async () => {
        vi.doMock('@/lib/auth-context', () => ({
            useAuth: () => ({ user: { user_id: '1', is_admin: false }, loading: false }),
        }))
        vi.doMock('@/app/api-client', () => ({
            apiClient: makeApiMock({
                getSettingsSchema: vi.fn().mockRejectedValue(new Error('Schema unavailable')),
            }),
        }))

        const { default: SettingsPage } = await import('../app/dashboard/[guildId]/settings/page')

        // Must not throw during render
        await act(async () => { render(<SettingsPage />) })

        // Page must exit the loading state (no infinite spinner)
        await waitFor(() => {
            expect(screen.queryByText('guildSettings.loading')).toBeNull()
        })
    })

    it('getSettingsSchema() fails — shows error message', async () => {
        vi.doMock('@/lib/auth-context', () => ({
            useAuth: () => ({ user: { user_id: '1', is_admin: false }, loading: false }),
        }))
        vi.doMock('@/app/api-client', () => ({
            apiClient: makeApiMock({
                getSettingsSchema: vi.fn().mockRejectedValue(new Error('Schema unavailable')),
            }),
        }))

        const { default: SettingsPage } = await import('../app/dashboard/[guildId]/settings/page')
        await act(async () => { render(<SettingsPage />) })

        await waitFor(() => {
            // The catch block sets message: { type: 'error', text: 'Failed to load settings.' }
            expect(screen.getByText('guildSettings.loadError')).toBeDefined()
        })
    })

    it('getGuildSettings() fails — does not crash, shows error instead of hanging', async () => {
        vi.doMock('@/lib/auth-context', () => ({
            useAuth: () => ({ user: { user_id: '1', is_admin: false }, loading: false }),
        }))
        vi.doMock('@/app/api-client', () => ({
            apiClient: makeApiMock({
                getGuildSettings: vi.fn().mockRejectedValue(new Error('DB error')),
            }),
        }))

        const { default: SettingsPage } = await import('../app/dashboard/[guildId]/settings/page')
        await act(async () => { render(<SettingsPage />) })

        // Must exit loading state
        await waitFor(() => {
            expect(screen.queryByText('guildSettings.loading')).toBeNull()
        })

        // Error message must be surfaced
        expect(screen.getByText('guildSettings.loadError')).toBeDefined()
    })

    it('no schemas returned — shows "No configurable settings available" placeholder', async () => {
        vi.doMock('@/lib/auth-context', () => ({
            useAuth: () => ({ user: { user_id: '1', is_admin: false }, loading: false }),
        }))
        vi.doMock('@/app/api-client', () => ({
            apiClient: makeApiMock({
                getSettingsSchema: vi.fn().mockResolvedValue({ schemas: [] }),
            }),
        }))

        const { default: SettingsPage } = await import('../app/dashboard/[guildId]/settings/page')
        await act(async () => { render(<SettingsPage />) })

        await waitFor(() => {
            expect(screen.getByText('guildSettings.noSchemas')).toBeDefined()
        })
    })
})
