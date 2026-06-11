/**
 * Tests for the AI Analytics page (/app/dashboard/ai-analytics/page.tsx).
 *
 * Guards against:
 *   - getLLMStats() not called on mount
 *   - Total requests not rendered from provider data
 *   - Provider table rows missing
 *   - Recent logs table not rendered
 *   - Crash on empty stats (no logs, no providers)
 *   - Crash when total_cost is null/undefined
 *   - Crash on API failure (must show error state, not hang)
 */
import React from 'react'
import { describe, it, expect, vi, beforeEach } from 'vitest'
import { render, screen, waitFor, act } from '@testing-library/react'

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
  total_requests: 42,
  total_tokens: 15000,
  total_cost: 0.45,
  by_provider: [
    { provider: 'openai', requests: 30, cost: 0.30 },
    { provider: 'gemini', requests: 12, cost: 0.15 },
  ],
  recent_logs: [
    {
      id: 'log-1',
      timestamp: '2026-01-01T00:00:00Z',
      user_id: '111',
      provider: 'openai',
      model: 'gpt-4',
      tokens: 500,
      type: 'completion',
      latency_ms: 1200,
    },
  ],
}

// ── Helpers ───────────────────────────────────────────────────────────────────

function makeAuthMock(isAdmin = true) {
  return {
    useAuth: () => ({
      user: { user_id: '1', username: 'testuser', is_admin: isAdmin },
      loading: false,
    }),
  }
}

function makePermissionsMock(level = 6) {
  return {
    usePermissions: () => ({
      permissionLevel: level,
      hasAccess: () => true,
      loading: false,
      error: null,
      guild: null,
    }),
  }
}

// withPermission wraps the inner component; mock it to render children directly
// so that we test the real page logic without auth guard interference.
function makeWithPermissionMock() {
  return {
    withPermission: (Component: React.ComponentType<any>) =>
      function MockedWithPermission(props: any) {
        return <Component {...props} />
      },
  }
}

// ── Test suite ────────────────────────────────────────────────────────────────

describe('AIAnalyticsPage', () => {
  beforeEach(() => {
    vi.resetModules()
  })

  it('calls getLLMStats() on mount', async () => {
    const getLLMStats = vi.fn().mockResolvedValue(SAMPLE_STATS)

    vi.doMock('@/lib/auth-context', () => makeAuthMock())
    vi.doMock('@/lib/hooks/use-permissions', () => makePermissionsMock())
    vi.doMock('@/lib/components/with-permission', () => makeWithPermissionMock())
    vi.doMock('@/app/api-client', () => ({ apiClient: { getLLMStats } }))

    const { default: Page } = await import('../app/dashboard/ai-analytics/page')
    await act(async () => { render(<Page />) })

    await waitFor(() => {
      expect(getLLMStats).toHaveBeenCalledOnce()
    })
  })

  it('renders total requests computed from by_provider', async () => {
    vi.doMock('@/lib/auth-context', () => makeAuthMock())
    vi.doMock('@/lib/hooks/use-permissions', () => makePermissionsMock())
    vi.doMock('@/lib/components/with-permission', () => makeWithPermissionMock())
    vi.doMock('@/app/api-client', () => ({
      apiClient: { getLLMStats: vi.fn().mockResolvedValue(SAMPLE_STATS) },
    }))

    const { default: Page } = await import('../app/dashboard/ai-analytics/page')
    await act(async () => { render(<Page />) })

    // total requests = 30 + 12 = 42
    await waitFor(() => {
      expect(screen.getByText('42')).toBeDefined()
    })
  })

  it('renders provider names in the provider table', async () => {
    vi.doMock('@/lib/auth-context', () => makeAuthMock())
    vi.doMock('@/lib/hooks/use-permissions', () => makePermissionsMock())
    vi.doMock('@/lib/components/with-permission', () => makeWithPermissionMock())
    vi.doMock('@/app/api-client', () => ({
      apiClient: { getLLMStats: vi.fn().mockResolvedValue(SAMPLE_STATS) },
    }))

    const { default: Page } = await import('../app/dashboard/ai-analytics/page')
    await act(async () => { render(<Page />) })

    await waitFor(() => {
      expect(screen.getAllByText('openai').length).toBeGreaterThan(0)
      expect(screen.getAllByText('gemini').length).toBeGreaterThan(0)
    })
  })

  it('renders the recent logs table with at least one row', async () => {
    vi.doMock('@/lib/auth-context', () => makeAuthMock())
    vi.doMock('@/lib/hooks/use-permissions', () => makePermissionsMock())
    vi.doMock('@/lib/components/with-permission', () => makeWithPermissionMock())
    vi.doMock('@/app/api-client', () => ({
      apiClient: { getLLMStats: vi.fn().mockResolvedValue(SAMPLE_STATS) },
    }))

    const { default: Page } = await import('../app/dashboard/ai-analytics/page')
    await act(async () => { render(<Page />) })

    await waitFor(() => {
      // user_id from the log entry
      expect(screen.getByText('111')).toBeDefined()
    })
  })

  it('does not crash when stats has empty logs and empty providers', async () => {
    const emptyStats = {
      total_tokens: 0,
      total_cost: 0,
      by_provider: [],
      recent_logs: [],
    }

    vi.doMock('@/lib/auth-context', () => makeAuthMock())
    vi.doMock('@/lib/hooks/use-permissions', () => makePermissionsMock())
    vi.doMock('@/lib/components/with-permission', () => makeWithPermissionMock())
    vi.doMock('@/app/api-client', () => ({
      apiClient: { getLLMStats: vi.fn().mockResolvedValue(emptyStats) },
    }))

    const { default: Page } = await import('../app/dashboard/ai-analytics/page')

    await expect(
      act(async () => { render(<Page />) })
    ).resolves.not.toThrow()

    // total requests should be 0 (sum of empty array) — multiple '0' elements may exist
    await waitFor(() => {
      expect(screen.getAllByText('0').length).toBeGreaterThan(0)
    })
  })

  it('does not crash when total_cost is null or undefined', async () => {
    const statsNoCost = {
      total_tokens: 100,
      total_cost: null as any,
      by_provider: [{ provider: 'openai', requests: 5, cost: 0 }],
      recent_logs: [],
    }

    vi.doMock('@/lib/auth-context', () => makeAuthMock())
    vi.doMock('@/lib/hooks/use-permissions', () => makePermissionsMock())
    vi.doMock('@/lib/components/with-permission', () => makeWithPermissionMock())
    vi.doMock('@/app/api-client', () => ({
      apiClient: { getLLMStats: vi.fn().mockResolvedValue(statsNoCost) },
    }))

    const { default: Page } = await import('../app/dashboard/ai-analytics/page')

    // The page calls total_cost.toFixed(4) — if cost is null this crashes.
    // This test verifies a formatting guard exists or that the value is handled.
    let thrown = false
    try {
      await act(async () => { render(<Page />) })
      // wait for state to settle
      await waitFor(() => {
        // page rendered at all
        expect(screen.queryByText('aiAnalytics.loading')).toBeNull()
      })
    } catch {
      thrown = true
    }
    // Test documents the crash behavior: we expect no unhandled crash from the
    // render pipeline itself (React error boundaries / caught errors are acceptable)
    expect(thrown).toBe(false)
  })

  it('shows error state and does not crash on API failure', async () => {
    vi.doMock('@/lib/auth-context', () => makeAuthMock())
    vi.doMock('@/lib/hooks/use-permissions', () => makePermissionsMock())
    vi.doMock('@/lib/components/with-permission', () => makeWithPermissionMock())
    vi.doMock('@/app/api-client', () => ({
      apiClient: {
        getLLMStats: vi.fn().mockRejectedValue(new Error('Network error')),
      },
    }))

    const { default: Page } = await import('../app/dashboard/ai-analytics/page')
    await act(async () => { render(<Page />) })

    await waitFor(() => {
      // The page sets an error string that includes "developer permissions"
      expect(screen.getByText(/aiAnalytics.loadError/i)).toBeDefined()
    })
  })
})
