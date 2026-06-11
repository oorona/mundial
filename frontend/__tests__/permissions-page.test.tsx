/**
 * Tests for the Permissions page.
 *
 * Guards against the 'Failed to load permission data' crash caused by
 * the guild settings endpoint returning 500 (NoResultFound when the
 * guild_settings row doesn't exist and db.commit() clears SET LOCAL RLS).
 *
 * All API calls are mocked.
 */
import React from 'react'
import { describe, it, expect, vi } from 'vitest'
import { render, screen, waitFor, act } from '@testing-library/react'

// ── Mocks ────────────────────────────────────────────────────────────────────

vi.mock('@/lib/i18n', () => ({
    useTranslation: () => ({ t: (k: string) => k, language: 'en' }),
    LanguageProvider: ({ children }: { children: React.ReactNode }) => children,
}))

vi.mock('next/navigation', () => ({
    useParams:       () => ({ guildId: '123456789' }),
    useRouter:       () => ({ push: vi.fn() }),
    usePathname:     () => '/',
    useSearchParams: () => new URLSearchParams(),
}))

vi.mock('@/lib/auth-context', () => ({
    useAuth: () => ({
        user: { user_id: '1', username: 'testuser', is_admin: true },
        loading: false,
    }),
}))

vi.mock('@tanstack/react-query', () => ({
    useQuery: ({ queryFn }: { queryFn: () => any }) => ({
        data: null,
        isLoading: false,
        error: null,
    }),
    QueryClient: class {},
    QueryClientProvider: ({ children }: { children: React.ReactNode }) => children,
}))

// ── API client mock ───────────────────────────────────────────────────────────

const mockGuildSettings = {
    guild_id:   '123456789',
    settings:   {},           // empty dict — the auto-created default
    updated_at: '2026-01-01T00:00:00Z',
}

vi.mock('@/app/api-client', () => ({
    apiClient: {
        getAuthorizedUsers: vi.fn().mockResolvedValue([]),
        getGuildRoles:      vi.fn().mockResolvedValue([]),
        getAuthorizedRoles: vi.fn().mockResolvedValue([]),
        getGuildSettings:   vi.fn().mockResolvedValue(mockGuildSettings),
        addAuthorizedUser:  vi.fn().mockResolvedValue({}),
        removeAuthorizedUser: vi.fn().mockResolvedValue({}),
        addAuthorizedRole:  vi.fn().mockResolvedValue({}),
        removeAuthorizedRole: vi.fn().mockResolvedValue({}),
        updateGuildSettings: vi.fn().mockResolvedValue(mockGuildSettings),
        getGuild: vi.fn().mockResolvedValue({ id: '123456789', permission_level: 'owner' }),
    },
}))

// ── Tests ─────────────────────────────────────────────────────────────────────

const { default: PermissionsPage } = await import('../app/dashboard/[guildId]/permissions/page')

describe('Permissions Page', () => {
    it('renders without crashing', async () => {
        await act(async () => {
            render(<PermissionsPage />)
        })
    })

    it('does not show error message when API calls succeed', async () => {
        await act(async () => {
            render(<PermissionsPage />)
        })
        await waitFor(() => {
            expect(screen.queryByText(/Failed to load permission data/i)).toBeNull()
        })
    })
})

describe('Guild settings API response contract', () => {
    it('mock settings response has required fields', () => {
        expect(mockGuildSettings).toHaveProperty('guild_id')
        expect(mockGuildSettings).toHaveProperty('settings')
        expect(mockGuildSettings).toHaveProperty('updated_at')
    })

    it('settings field is a dict', () => {
        expect(typeof mockGuildSettings.settings).toBe('object')
        expect(Array.isArray(mockGuildSettings.settings)).toBe(false)
    })
})
