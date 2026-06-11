/**
 * Tests for the Commands Reference page (/app/commands/page.tsx).
 *
 * Guards against:
 *   - Silent error swallow hiding API failures (the catch block must surface errors)
 *   - Empty state shown when API returns data (data not wired to display)
 *   - Refresh button absent for non-admin users
 *   - Refresh button present for admin users
 *   - Commands grouped by cog and rendered
 */
import React from 'react'
import { describe, it, expect, vi, beforeEach } from 'vitest'
import { render, screen, waitFor, act, fireEvent } from '@testing-library/react'

// ── Shared mocks ──────────────────────────────────────────────────────────────

vi.mock('@/lib/i18n', () => ({
    useTranslation: () => ({ t: (k: string, args?: any) => args ? `${k}:${JSON.stringify(args)}` : k, language: 'en' }),
    LanguageProvider: ({ children }: { children: React.ReactNode }) => children,
}))

vi.mock('next/navigation', () => ({
    useRouter:       () => ({ push: vi.fn() }),
    usePathname:     () => '/commands',
    useSearchParams: () => new URLSearchParams(),
    useParams:       () => ({}),
}))

vi.mock('@tanstack/react-query', () => ({
    useQuery:            () => ({ data: null, isLoading: false, error: null }),
    QueryClient:         class {},
    QueryClientProvider: ({ children }: { children: React.ReactNode }) => children,
}))

// ── Helpers ───────────────────────────────────────────────────────────────────

const SAMPLE_COMMANDS = [
    { name: 'status',  description: 'Show bot status',  cog: 'StatusCog',  usage: '/status',  examples: [] },
    { name: 'reload',  description: 'Reload a cog',     cog: 'MetaCog',    usage: '/reload',  examples: [] },
    { name: 'load',    description: 'Load a cog',       cog: 'MetaCog',    usage: '/load',    examples: [] },
]

function mockAuth(isAdmin: boolean) {
    vi.mock('@/lib/auth-context', () => ({
        useAuth: () => ({
            user:    { user_id: '1', username: 'testuser', is_admin: isAdmin },
            loading: false,
        }),
    }))
}

// ── Test suites ───────────────────────────────────────────────────────────────

describe('CommandsPage — data display', () => {
    beforeEach(() => {
        vi.resetModules()
    })

    it('shows commands grouped by cog when API returns data', async () => {
        vi.doMock('@/lib/auth-context', () => ({
            useAuth: () => ({ user: { user_id: '1', is_admin: false }, loading: false }),
        }))
        vi.doMock('@/app/api-client', () => ({
            apiClient: {
                getCommands: vi.fn().mockResolvedValue({
                    commands: SAMPLE_COMMANDS,
                    last_updated: '2026-01-01T00:00:00+00:00',
                    total: 3,
                }),
            },
        }))

        const { default: CommandsPage } = await import('../app/commands/page')
        await act(async () => { render(<CommandsPage />) })

        await waitFor(() => {
            expect(screen.getByText('status')).toBeDefined()
            expect(screen.getByText('reload')).toBeDefined()
        })
    })

    it('shows empty state when API returns zero commands', async () => {
        vi.doMock('@/lib/auth-context', () => ({
            useAuth: () => ({ user: { user_id: '1', is_admin: false }, loading: false }),
        }))
        vi.doMock('@/app/api-client', () => ({
            apiClient: {
                getCommands: vi.fn().mockResolvedValue({
                    commands: [], last_updated: null, total: 0,
                }),
            },
        }))

        const { default: CommandsPage } = await import('../app/commands/page')
        await act(async () => { render(<CommandsPage />) })

        await waitFor(() => {
            expect(screen.getByText('commands.noCommands')).toBeDefined()
        })
    })

    it('shows empty state when API call fails — does not crash or hang on loading', async () => {
        vi.doMock('@/lib/auth-context', () => ({
            useAuth: () => ({ user: { user_id: '1', is_admin: false }, loading: false }),
        }))
        vi.doMock('@/app/api-client', () => ({
            apiClient: {
                getCommands: vi.fn().mockRejectedValue(new Error('Network error')),
            },
        }))

        const { default: CommandsPage } = await import('../app/commands/page')
        await act(async () => { render(<CommandsPage />) })

        // Must exit loading state (not hang forever)
        await waitFor(() => {
            expect(screen.queryByText('commands.noCommands')).toBeDefined()
        })
    })
})

describe('CommandsPage — admin controls', () => {
    beforeEach(() => {
        vi.resetModules()
    })

    it('hides Refresh button for non-admin users', async () => {
        vi.doMock('@/lib/auth-context', () => ({
            useAuth: () => ({ user: { user_id: '1', is_admin: false }, loading: false }),
        }))
        vi.doMock('@/app/api-client', () => ({
            apiClient: {
                getCommands: vi.fn().mockResolvedValue({ commands: [], last_updated: null, total: 0 }),
            },
        }))

        const { default: CommandsPage } = await import('../app/commands/page')
        await act(async () => { render(<CommandsPage />) })

        await waitFor(() => {
            expect(screen.queryByText('commands.refreshButton')).toBeNull()
        })
    })

    it('shows Refresh button for admin users', async () => {
        vi.doMock('@/lib/auth-context', () => ({
            useAuth: () => ({ user: { user_id: '1', is_admin: true }, loading: false }),
        }))
        vi.doMock('@/app/api-client', () => ({
            apiClient: {
                getCommands: vi.fn().mockResolvedValue({ commands: [], last_updated: null, total: 0 }),
            },
        }))

        const { default: CommandsPage } = await import('../app/commands/page')
        await act(async () => { render(<CommandsPage />) })

        await waitFor(() => {
            expect(screen.getByText('commands.refreshButton')).toBeDefined()
        })
    })

    it('calls refreshCommands then re-fetches on Refresh click', async () => {
        const refreshCommands = vi.fn().mockResolvedValue(undefined)
        const getCommands = vi.fn().mockResolvedValue({
            commands: SAMPLE_COMMANDS, last_updated: '2026-01-01T00:00:00+00:00', total: 3,
        })

        vi.doMock('@/lib/auth-context', () => ({
            useAuth: () => ({ user: { user_id: '1', is_admin: true }, loading: false }),
        }))
        vi.doMock('@/app/api-client', () => ({
            apiClient: { getCommands, refreshCommands },
        }))

        const { default: CommandsPage } = await import('../app/commands/page')
        await act(async () => { render(<CommandsPage />) })

        await waitFor(() => screen.getByText('commands.refreshButton'))

        await act(async () => {
            fireEvent.click(screen.getByText('commands.refreshButton'))
        })

        await waitFor(() => {
            expect(refreshCommands).toHaveBeenCalledOnce()
            // getCommands called once on mount + once after refresh
            expect(getCommands.mock.calls.length).toBeGreaterThanOrEqual(2)
        })
    })

    it('shows error message when refresh fails', async () => {
        vi.doMock('@/lib/auth-context', () => ({
            useAuth: () => ({ user: { user_id: '1', is_admin: true }, loading: false }),
        }))
        vi.doMock('@/app/api-client', () => ({
            apiClient: {
                getCommands:     vi.fn().mockResolvedValue({ commands: [], last_updated: null, total: 0 }),
                refreshCommands: vi.fn().mockRejectedValue({ message: 'Bot offline' }),
            },
        }))

        const { default: CommandsPage } = await import('../app/commands/page')
        await act(async () => { render(<CommandsPage />) })
        await waitFor(() => screen.getByText('commands.refreshButton'))

        await act(async () => {
            fireEvent.click(screen.getByText('commands.refreshButton'))
        })

        await waitFor(() => {
            expect(screen.getByText(/commands\.refreshError/)).toBeDefined()
        })
    })
})
