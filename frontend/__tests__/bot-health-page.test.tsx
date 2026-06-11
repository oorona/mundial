/**
 * Tests for the Bot Health page (/app/dashboard/bot-health/page.tsx).
 *
 * Guards against:
 *   - Healthy API response not surfaced to status cards
 *   - Degraded state not displayed when health check returns non-ok
 *   - Page hanging on loading state when healthCheck() fails
 *   - Refresh button absent or not wired to healthCheck()
 *   - Crash when auth context reports permission denied / no user
 */
import React from 'react'
import { describe, it, expect, vi, beforeEach, afterEach } from 'vitest'
import { render, screen, waitFor, act, fireEvent } from '@testing-library/react'

// ── Shared mocks ──────────────────────────────────────────────────────────────

vi.mock('@/lib/i18n', () => ({
    useTranslation: () => ({
        t: (k: string, args?: any) => args ? `${k}:${JSON.stringify(args)}` : k,
        language: 'en',
        setLanguage: vi.fn(),
    }),
    LanguageProvider: ({ children }: { children: React.ReactNode }) => children,
}))

vi.mock('next/navigation', () => ({
    useRouter:       () => ({ push: vi.fn() }),
    usePathname:     () => '/dashboard/bot-health',
    useSearchParams: () => new URLSearchParams(),
    useParams:       () => ({ guildId: '123456789' }),
}))

vi.mock('@tanstack/react-query', () => ({
    useQuery:            () => ({ data: null, isLoading: false, error: null }),
    QueryClient:         class {},
    QueryClientProvider: ({ children }: { children: React.ReactNode }) => children,
}))

// withPermission just renders its wrapped component in tests
vi.mock('@/lib/components/with-permission', () => ({
    withPermission: (Component: React.ComponentType<any>) =>
        function WrappedComponent(props: any) {
            return <Component {...props} />
        },
}))

vi.mock('@/lib/permissions', () => ({
    PermissionLevel: { AUTHORIZED: 1, ADMIN: 2 },
}))

// ── Test suites ───────────────────────────────────────────────────────────────

describe('BotHealthPage — healthy state', () => {
    beforeEach(() => {
        vi.resetModules()
    })

    it('shows Operational status for backend, database, and discord when all healthy', async () => {
        vi.doMock('@/lib/auth-context', () => ({
            useAuth: () => ({ user: { user_id: '1', is_admin: true }, loading: false }),
        }))

        vi.doMock('@/app/api-client', () => ({
            apiClient: {
                healthCheck: vi.fn().mockResolvedValue({ status: 'ok' }),
            },
        }))

        const { default: BotHealthPage } = await import('../app/dashboard/bot-health/page')
        render(<BotHealthPage />)

        await waitFor(() => {
            const operationalCells = screen.getAllByText('botHealth.statusOperational')
            expect(operationalCells.length).toBe(3)
        })
    })
})

describe('BotHealthPage — degraded state', () => {
    beforeEach(() => {
        vi.resetModules()
    })

    it('shows Degraded status for backend when health check returns non-ok status', async () => {
        vi.doMock('@/lib/auth-context', () => ({
            useAuth: () => ({ user: { user_id: '1', is_admin: true }, loading: false }),
        }))

        vi.doMock('@/app/api-client', () => ({
            apiClient: {
                healthCheck: vi.fn().mockResolvedValue({ status: 'degraded' }),
            },
        }))

        const { default: BotHealthPage } = await import('../app/dashboard/bot-health/page')
        render(<BotHealthPage />)

        await waitFor(() => {
            expect(screen.getByText('botHealth.statusDegraded')).toBeDefined()
        })
    })
})

describe('BotHealthPage — error / failure state', () => {
    beforeEach(() => {
        vi.resetModules()
    })

    it('does not hang on loading and shows non-healthy state when healthCheck() throws', async () => {
        vi.doMock('@/lib/auth-context', () => ({
            useAuth: () => ({ user: { user_id: '1', is_admin: true }, loading: false }),
        }))

        vi.doMock('@/app/api-client', () => ({
            apiClient: {
                healthCheck: vi.fn().mockRejectedValue(new Error('Network error')),
            },
        }))

        const { default: BotHealthPage } = await import('../app/dashboard/bot-health/page')
        render(<BotHealthPage />)

        // The page's catch leaves status at 'unknown' which renders "Issues Detected"
        // and sets loadingData false, so the loading spinner must not be present
        await waitFor(() => {
            expect(screen.queryByText('botHealth.loading')).toBeNull()
        })

        // At least one status card should show Issues Detected
        await waitFor(() => {
            const issueCards = screen.getAllByText('botHealth.statusIssues')
            expect(issueCards.length).toBeGreaterThan(0)
        })
    })
})

describe('BotHealthPage — refresh button', () => {
    beforeEach(() => {
        vi.resetModules()
    })

    it('refresh button is present and calls healthCheck() again when clicked', async () => {
        const healthCheck = vi.fn().mockResolvedValue({ status: 'ok' })

        vi.doMock('@/lib/auth-context', () => ({
            useAuth: () => ({ user: { user_id: '1', is_admin: true }, loading: false }),
        }))

        vi.doMock('@/app/api-client', () => ({
            apiClient: { healthCheck },
        }))

        const { default: BotHealthPage } = await import('../app/dashboard/bot-health/page')
        render(<BotHealthPage />)

        // Wait for initial load to complete so the refresh button is rendered
        await waitFor(() => {
            expect(screen.getByTitle('botHealth.refreshTitle')).toBeDefined()
        })

        const callCountBefore = healthCheck.mock.calls.length

        fireEvent.click(screen.getByTitle('botHealth.refreshTitle'))

        await waitFor(() => {
            expect(healthCheck.mock.calls.length).toBeGreaterThan(callCountBefore)
        })
    })
})

describe('BotHealthPage — unauthorized user', () => {
    beforeEach(() => {
        vi.resetModules()
    })

    it('does not crash when user is null (permission denied / unauthenticated)', async () => {
        vi.doMock('@/lib/auth-context', () => ({
            useAuth: () => ({ user: null, loading: false }),
        }))

        vi.doMock('@/app/api-client', () => ({
            apiClient: {
                healthCheck: vi.fn().mockResolvedValue({ status: 'ok' }),
            },
        }))

        const { default: BotHealthPage } = await import('../app/dashboard/bot-health/page')

        // Should not throw
        render(<BotHealthPage />)

        // The page skips fetchData when user is null — loading state is never
        // cleared and no crash should occur. The spinner text may or may not
        // appear depending on how authLoading/loadingData interact, but the
        // render must complete without throwing.
        expect(true).toBe(true)
    })
})
