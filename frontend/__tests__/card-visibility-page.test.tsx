/**
 * Tests for the Card Visibility page (/app/dashboard/[guildId]/card-visibility/page.tsx).
 *
 * Guards against:
 *   - getCardVisibility() not called on mount (visibility silently skipped)
 *   - Cards not rendered with toggle switches
 *   - Visible card in API response showing toggle as off (state not applied)
 *   - Hidden card in API response showing toggle as on (state not applied)
 *   - Crash on undefined card in API response instead of falling back to default
 *   - updateCardVisibility() not called or called with wrong guildId on save
 *   - API failure on load crashing the page instead of showing error/empty state
 *   - Success message absent after a successful save
 */
import React from 'react'
import { describe, it, expect, vi, beforeEach } from 'vitest'
import { render, screen, waitFor, act, fireEvent } from '@testing-library/react'

// ── Shared mocks ──────────────────────────────────────────────────────────────

vi.mock('@/lib/i18n', () => ({
    useTranslation: () => ({
        t: (k: string, a?: any) => a ? `${k}:${JSON.stringify(a)}` : k,
        language: 'en',
    }),
    LanguageProvider: ({ children }: { children: React.ReactNode }) => children,
}))

vi.mock('next/navigation', () => ({
    useRouter:       () => ({ push: vi.fn() }),
    usePathname:     () => '/dashboard/123456789/card-visibility',
    useSearchParams: () => new URLSearchParams(),
    useParams:       () => ({ guildId: '123456789' }),
}))

vi.mock('@tanstack/react-query', () => ({
    useQuery:            () => ({ data: null, isLoading: false, error: null }),
    QueryClient:         class {},
    QueryClientProvider: ({ children }: { children: React.ReactNode }) => children,
}))

vi.mock('@/lib/permissions', () => ({
    PermissionLevel: {
        PUBLIC: 0, PUBLIC_DATA: 1, USER: 2, AUTHORIZED: 3,
        ADMINISTRATOR: 4, OWNER: 5, DEVELOPER: 6,
    },
}))

vi.mock('@/lib/components/with-permission', () => ({
    withPermission: (Component: React.ComponentType<any>) => Component,
}))

// ── Helpers ───────────────────────────────────────────────────────────────────

// IDs the page actually renders: ALL_BUILTIN filtered to BELOW owner level —
// permissions (OWNER) and audit-logs (DEVELOPER) are not toggleable.
const ALL_CARD_IDS = [
    'bot-overview',
    'command-reference',
    'bot-health',
    'bot-settings',
    'worldcup',
    'fixtures',
    'predictions',
    'leaderboard',
]

// A representative API response where all cards explicitly visible
const ALL_VISIBLE: Record<string, boolean> = Object.fromEntries(ALL_CARD_IDS.map(id => [id, true]))

// A representative API response where all cards explicitly hidden
const ALL_HIDDEN: Record<string, boolean> = Object.fromEntries(ALL_CARD_IDS.map(id => [id, false]))

// ── Test suites ───────────────────────────────────────────────────────────────

describe('CardVisibilityPage — data loading', () => {
    beforeEach(() => {
        vi.resetModules()
    })

    it('calls getCardVisibility() with the correct guildId on mount', async () => {
        const getCardVisibility = vi.fn().mockResolvedValue(ALL_VISIBLE)

        vi.doMock('@/lib/auth-context', () => ({
            useAuth: () => ({ user: { user_id: '1', is_admin: false }, loading: false }),
        }))
        vi.doMock('@/app/api-client', () => ({
            apiClient: {
                getCardVisibility,
                updateCardVisibility: vi.fn().mockResolvedValue({}),
            },
        }))

        const { default: CardVisibilityPage } = await import('../app/dashboard/[guildId]/card-visibility/page')
        await act(async () => { render(<CardVisibilityPage />) })

        await waitFor(() => {
            expect(getCardVisibility).toHaveBeenCalledOnce()
            expect(getCardVisibility).toHaveBeenCalledWith('123456789')
        })
    })

    it('renders all configurable cards with toggle buttons after loading', async () => {
        vi.doMock('@/lib/auth-context', () => ({
            useAuth: () => ({ user: { user_id: '1', is_admin: false }, loading: false }),
        }))
        vi.doMock('@/app/api-client', () => ({
            apiClient: {
                getCardVisibility: vi.fn().mockResolvedValue(ALL_VISIBLE),
                updateCardVisibility: vi.fn().mockResolvedValue({}),
            },
        }))

        const { default: CardVisibilityPage } = await import('../app/dashboard/[guildId]/card-visibility/page')
        await act(async () => { render(<CardVisibilityPage />) })

        await waitFor(() => {
            // The page title should be present
            expect(screen.getByText('cardVisibility.title')).toBeDefined()
            // All toggle buttons rendered — one per card
            const toggles = screen.getAllByRole('button', { name: /—/ })
            expect(toggles.length).toBe(ALL_CARD_IDS.length)
        })
    })
})

describe('CardVisibilityPage — toggle state from API', () => {
    beforeEach(() => {
        vi.resetModules()
    })

    it('marks a card as enabled when API returns true for that card', async () => {
        vi.doMock('@/lib/auth-context', () => ({
            useAuth: () => ({ user: { user_id: '1', is_admin: false }, loading: false }),
        }))
        vi.doMock('@/app/api-client', () => ({
            apiClient: {
                // bot-health explicitly visible
                getCardVisibility: vi.fn().mockResolvedValue({ 'bot-health': true }),
                updateCardVisibility: vi.fn().mockResolvedValue({}),
            },
        }))

        const { default: CardVisibilityPage } = await import('../app/dashboard/[guildId]/card-visibility/page')
        await act(async () => { render(<CardVisibilityPage />) })

        await waitFor(() => {
            // The enabled label should appear alongside the bot-health card
            const toggleBtn = screen.getByRole('button', {
                name: /dashboard\.cardBotHealthTitle.*cardVisibility\.enabled/,
            })
            expect(toggleBtn).toBeDefined()
            // Toggle button has bg-primary class when enabled
            expect(toggleBtn.className).toContain('bg-primary')
        })
    })

    it('marks a card as disabled when API returns false for that card', async () => {
        vi.doMock('@/lib/auth-context', () => ({
            useAuth: () => ({ user: { user_id: '1', is_admin: false }, loading: false }),
        }))
        vi.doMock('@/app/api-client', () => ({
            apiClient: {
                // bot-settings explicitly hidden (default is true, so API override matters)
                getCardVisibility: vi.fn().mockResolvedValue({ 'bot-settings': false }),
                updateCardVisibility: vi.fn().mockResolvedValue({}),
            },
        }))

        const { default: CardVisibilityPage } = await import('../app/dashboard/[guildId]/card-visibility/page')
        await act(async () => { render(<CardVisibilityPage />) })

        await waitFor(() => {
            const toggleBtn = screen.getByRole('button', {
                name: /dashboard\.cardBotSettingsTitle.*cardVisibility\.disabled/,
            })
            expect(toggleBtn).toBeDefined()
            // Toggle button uses bg-muted class when disabled
            expect(toggleBtn.className).toContain('bg-muted')
        })
    })

    it('falls back to defaultVisible when a card is missing from the API response — no crash', async () => {
        vi.doMock('@/lib/auth-context', () => ({
            useAuth: () => ({ user: { user_id: '1', is_admin: false }, loading: false }),
        }))
        vi.doMock('@/app/api-client', () => ({
            apiClient: {
                // Return an empty object — no card IDs at all
                getCardVisibility: vi.fn().mockResolvedValue({}),
                updateCardVisibility: vi.fn().mockResolvedValue({}),
            },
        }))

        const { default: CardVisibilityPage } = await import('../app/dashboard/[guildId]/card-visibility/page')

        // Should not throw
        await act(async () => { render(<CardVisibilityPage />) })

        await waitFor(() => {
            // All cards still rendered using defaults
            const toggles = screen.getAllByRole('button', { name: /—/ })
            expect(toggles.length).toBe(ALL_CARD_IDS.length)
        })
    })
})

describe('CardVisibilityPage — save', () => {
    beforeEach(() => {
        vi.resetModules()
    })

    it('calls updateCardVisibility() with the correct guildId and current visibility when save button clicked', async () => {
        const updateCardVisibility = vi.fn().mockResolvedValue({})

        vi.doMock('@/lib/auth-context', () => ({
            useAuth: () => ({ user: { user_id: '1', is_admin: false }, loading: false }),
        }))
        vi.doMock('@/app/api-client', () => ({
            apiClient: {
                getCardVisibility: vi.fn().mockResolvedValue(ALL_VISIBLE),
                updateCardVisibility,
            },
        }))

        const { default: CardVisibilityPage } = await import('../app/dashboard/[guildId]/card-visibility/page')
        await act(async () => { render(<CardVisibilityPage />) })

        await waitFor(() => {
            expect(screen.getByText('cardVisibility.saveButton')).toBeDefined()
        })

        await act(async () => {
            fireEvent.click(screen.getByText('cardVisibility.saveButton'))
        })

        await waitFor(() => {
            expect(updateCardVisibility).toHaveBeenCalledOnce()
            const [guildId, visibility] = updateCardVisibility.mock.calls[0]
            expect(guildId).toBe('123456789')
            expect(typeof visibility).toBe('object')
            // Visibility should contain card IDs as keys
            expect(Object.keys(visibility)).toEqual(expect.arrayContaining(ALL_CARD_IDS))
        })
    })

    it('shows success message after a successful save', async () => {
        vi.doMock('@/lib/auth-context', () => ({
            useAuth: () => ({ user: { user_id: '1', is_admin: false }, loading: false }),
        }))
        vi.doMock('@/app/api-client', () => ({
            apiClient: {
                getCardVisibility: vi.fn().mockResolvedValue(ALL_VISIBLE),
                updateCardVisibility: vi.fn().mockResolvedValue({}),
            },
        }))

        const { default: CardVisibilityPage } = await import('../app/dashboard/[guildId]/card-visibility/page')
        await act(async () => { render(<CardVisibilityPage />) })

        await waitFor(() => {
            expect(screen.getByText('cardVisibility.saveButton')).toBeDefined()
        })

        await act(async () => {
            fireEvent.click(screen.getByText('cardVisibility.saveButton'))
        })

        await waitFor(() => {
            expect(screen.getByText('cardVisibility.savedSuccess')).toBeDefined()
        })
    })
})

describe('CardVisibilityPage — API failure on load', () => {
    beforeEach(() => {
        vi.resetModules()
    })

    it('does not crash and shows error or empty state when getCardVisibility() fails with a non-404 error', async () => {
        const apiError = new Error('API error') as any
        apiError.response = { status: 500 }

        vi.doMock('@/lib/auth-context', () => ({
            useAuth: () => ({ user: { user_id: '1', is_admin: false }, loading: false }),
        }))
        vi.doMock('@/app/api-client', () => ({
            apiClient: {
                getCardVisibility: vi.fn().mockRejectedValue(apiError),
                updateCardVisibility: vi.fn().mockResolvedValue({}),
            },
        }))

        const { default: CardVisibilityPage } = await import('../app/dashboard/[guildId]/card-visibility/page')

        // Must not throw
        await act(async () => { render(<CardVisibilityPage />) })

        await waitFor(() => {
            // Either an error message is shown or the page renders default state without crashing
            const errorMsg = screen.queryByText('cardVisibility.loadingError')
            const title = screen.queryByText('cardVisibility.title')
            // One of the two must be present — page must have exited loading state
            expect(errorMsg !== null || title !== null).toBe(true)
        })
    })

    it('does not show error message when getCardVisibility() fails with 404 — uses defaults silently', async () => {
        const notFoundError = new Error('Not Found') as any
        notFoundError.response = { status: 404 }

        vi.doMock('@/lib/auth-context', () => ({
            useAuth: () => ({ user: { user_id: '1', is_admin: false }, loading: false }),
        }))
        vi.doMock('@/app/api-client', () => ({
            apiClient: {
                getCardVisibility: vi.fn().mockRejectedValue(notFoundError),
                updateCardVisibility: vi.fn().mockResolvedValue({}),
            },
        }))

        const { default: CardVisibilityPage } = await import('../app/dashboard/[guildId]/card-visibility/page')
        await act(async () => { render(<CardVisibilityPage />) })

        await waitFor(() => {
            // No error message for 404 — silently falls back to defaults
            expect(screen.queryByText('cardVisibility.loadingError')).toBeNull()
            // All cards still rendered using defaults
            const toggles = screen.getAllByRole('button', { name: /—/ })
            expect(toggles.length).toBe(ALL_CARD_IDS.length)
        })
    })
})
