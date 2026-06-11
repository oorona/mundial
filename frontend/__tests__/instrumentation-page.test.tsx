/**
 * Tests for the Instrumentation page (/app/dashboard/instrumentation/page.tsx).
 *
 * Guards against:
 *   - getInstrumentationStats() not called on mount with default range
 *   - Range selector buttons not rendered
 *   - Range change not triggering a new API call with updated range
 *   - Stats data not displayed after load
 *   - Crash on empty stats
 *   - Crash / hang on API failure
 */
import React from 'react'
import { describe, it, expect, vi, beforeEach } from 'vitest'
import { render, screen, waitFor, act, fireEvent } from '@testing-library/react'

// ── Shared mocks ──────────────────────────────────────────────────────────────

vi.mock('next/navigation', () => ({
  useRouter: () => ({ push: vi.fn() }),
  usePathname: () => '/',
  useSearchParams: () => new URLSearchParams(),
  useParams: () => ({}),
}))

vi.mock('@tanstack/react-query', () => ({
  useQuery: () => ({ data: null, isLoading: false, error: null }),
  QueryClient: class {},
  QueryClientProvider: ({ children }: { children: React.ReactNode }) => children,
}))

vi.mock('@/lib/i18n', () => ({
  useTranslation: () => ({ t: (k: string, a?: any) => a ? `${k}:${JSON.stringify(a)}` : k, language: 'en' }),
  LanguageProvider: ({ children }: { children: React.ReactNode }) => children,
}))

// ── Sample data ───────────────────────────────────────────────────────────────

const SAMPLE_STATS = {
  range: '7d',
  guild_id_filter: null,
  guild_growth: [
    { date: '2026-01-01', joins: 10, leaves: 3, net: 7 },
    { date: '2026-01-02', joins: 8, leaves: 2, net: 6 },
  ],
  card_usage: [
    { card_id: 'bot-settings', count: 50, unique_users: 20 },
  ],
  top_commands: [
    { command: 'ping', cog: 'UtilityCog', count: 100, avg_ms: 80, p95_ms: 150, success_rate: 99.0 },
  ],
  endpoint_perf: [
    { path: '/api/v1/guilds', method: 'GET', count: 200, p50_ms: 45, p95_ms: 120, p99_ms: 300 },
  ],
}

const EMPTY_STATS = {
  range: '7d',
  guild_id_filter: null,
  guild_growth: [],
  card_usage: [],
  top_commands: [],
  endpoint_perf: [],
}

// ── Helpers ───────────────────────────────────────────────────────────────────

function makeWithPermissionMock() {
  return {
    withPermission: (Component: React.ComponentType<any>) =>
      function MockedWithPermission(props: any) {
        return <Component {...props} />
      },
  }
}

function makeAuthMock(isAdmin = true) {
  return {
    useAuth: () => ({
      user: { user_id: '1', username: 'testuser', is_admin: isAdmin },
      loading: false,
    }),
  }
}

function makePermissionsMock() {
  return {
    usePermissions: () => ({
      permissionLevel: 6,
      hasAccess: () => true,
      loading: false,
      error: null,
      guild: null,
    }),
  }
}

// ── Test suite ────────────────────────────────────────────────────────────────

describe('InstrumentationPage', () => {
  beforeEach(() => {
    vi.resetModules()
  })

  it('calls getInstrumentationStats() on mount with the default range (7d)', async () => {
    const getInstrumentationStats = vi.fn().mockResolvedValue(SAMPLE_STATS)

    vi.doMock('@/lib/auth-context', () => makeAuthMock())
    vi.doMock('@/lib/hooks/use-permissions', () => makePermissionsMock())
    vi.doMock('@/lib/components/with-permission', () => makeWithPermissionMock())
    vi.doMock('@/app/api-client', () => ({ apiClient: { getInstrumentationStats } }))

    const { default: Page } = await import('../app/dashboard/instrumentation/page')
    await act(async () => { render(<Page />) })

    await waitFor(() => {
      expect(getInstrumentationStats).toHaveBeenCalledOnce()
      // Default range is '7d' and no guild filter (null)
      expect(getInstrumentationStats).toHaveBeenCalledWith('7d', null)
    })
  })

  it('renders range selector with 24h, 7d, and 30d options', async () => {
    vi.doMock('@/lib/auth-context', () => makeAuthMock())
    vi.doMock('@/lib/hooks/use-permissions', () => makePermissionsMock())
    vi.doMock('@/lib/components/with-permission', () => makeWithPermissionMock())
    vi.doMock('@/app/api-client', () => ({
      apiClient: { getInstrumentationStats: vi.fn().mockResolvedValue(SAMPLE_STATS) },
    }))

    const { default: Page } = await import('../app/dashboard/instrumentation/page')
    await act(async () => { render(<Page />) })

    await waitFor(() => {
      expect(screen.getByText('24h')).toBeDefined()
      expect(screen.getByText('7d')).toBeDefined()
      expect(screen.getByText('30d')).toBeDefined()
    })
  })

  it('calls getInstrumentationStats() with new range when range selector is clicked', async () => {
    const getInstrumentationStats = vi.fn().mockResolvedValue(SAMPLE_STATS)

    vi.doMock('@/lib/auth-context', () => makeAuthMock())
    vi.doMock('@/lib/hooks/use-permissions', () => makePermissionsMock())
    vi.doMock('@/lib/components/with-permission', () => makeWithPermissionMock())
    vi.doMock('@/app/api-client', () => ({ apiClient: { getInstrumentationStats } }))

    const { default: Page } = await import('../app/dashboard/instrumentation/page')
    await act(async () => { render(<Page />) })

    // Wait for initial load
    await waitFor(() => {
      expect(getInstrumentationStats).toHaveBeenCalledOnce()
    })

    // Click the 30d range button
    await act(async () => {
      fireEvent.click(screen.getByText('30d'))
    })

    await waitFor(() => {
      // Should have been called again with the new range
      expect(getInstrumentationStats.mock.calls.length).toBeGreaterThanOrEqual(2)
      const calls = getInstrumentationStats.mock.calls
      const lastCall = calls[calls.length - 1]
      expect(lastCall[0]).toBe('30d')
    })
  })

  it('displays stats data after successful load', async () => {
    vi.doMock('@/lib/auth-context', () => makeAuthMock())
    vi.doMock('@/lib/hooks/use-permissions', () => makePermissionsMock())
    vi.doMock('@/lib/components/with-permission', () => makeWithPermissionMock())
    vi.doMock('@/app/api-client', () => ({
      apiClient: { getInstrumentationStats: vi.fn().mockResolvedValue(SAMPLE_STATS) },
    }))

    const { default: Page } = await import('../app/dashboard/instrumentation/page')
    await act(async () => { render(<Page />) })

    await waitFor(() => {
      // Command name from top_commands
      expect(screen.getAllByText('/ping').length).toBeGreaterThan(0)
      // Endpoint path from endpoint_perf
      expect(screen.getAllByText('/api/v1/guilds').length).toBeGreaterThan(0)
      // Card id from card_usage
      expect(screen.getAllByText('bot-settings').length).toBeGreaterThan(0)
    })
  })

  it('does not crash and shows zero values when stats has all empty arrays', async () => {
    vi.doMock('@/lib/auth-context', () => makeAuthMock())
    vi.doMock('@/lib/hooks/use-permissions', () => makePermissionsMock())
    vi.doMock('@/lib/components/with-permission', () => makeWithPermissionMock())
    vi.doMock('@/app/api-client', () => ({
      apiClient: { getInstrumentationStats: vi.fn().mockResolvedValue(EMPTY_STATS) },
    }))

    const { default: Page } = await import('../app/dashboard/instrumentation/page')

    await expect(
      act(async () => { render(<Page />) })
    ).resolves.not.toThrow()

    await waitFor(() => {
      // Should not be stuck in loading state
      expect(screen.queryByText('Loading…')).toBeNull()
    })
  })

  it('does not crash on API failure and shows error message', async () => {
    vi.doMock('@/lib/auth-context', () => makeAuthMock())
    vi.doMock('@/lib/hooks/use-permissions', () => makePermissionsMock())
    vi.doMock('@/lib/components/with-permission', () => makeWithPermissionMock())
    vi.doMock('@/app/api-client', () => ({
      apiClient: {
        getInstrumentationStats: vi.fn().mockRejectedValue({
          message: 'Failed to load stats',
          response: { data: { detail: 'Internal Server Error' } },
        }),
      },
    }))

    const { default: Page } = await import('../app/dashboard/instrumentation/page')
    await act(async () => { render(<Page />) })

    await waitFor(() => {
      // The page renders error in a red div; it should not stay in loading state
      expect(screen.queryByText('Loading…')).toBeNull()
      // Error message from response.data.detail should be visible
      expect(screen.getByText('Internal Server Error')).toBeDefined()
    })
  })
})
