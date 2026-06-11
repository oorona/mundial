/**
 * Tests for the Event Logging page (/app/dashboard/[guildId]/event_logging/page.tsx).
 *
 * Guards against:
 *   - apiClient.get() not called on mount or called with wrong URL
 *   - enabled: true status not displayed
 *   - enabled: false status not displayed
 *   - Channel info not rendered when channel is set
 *   - Crash when API returns an error
 *   - Crash on network failure
 *   - Event list items (message_delete, message_edit, member_join, member_leave) not rendered
 *
 * NOTE: This page uses apiClient.get() (not raw fetch). global.fetch is not mocked here.
 */
import React from 'react'
import { describe, it, expect, vi, beforeEach } from 'vitest'
import { render, screen, waitFor, act } from '@testing-library/react'

// ── Shared mocks ──────────────────────────────────────────────────────────────

vi.mock('next/navigation', () => ({
  useRouter: () => ({ push: vi.fn() }),
  usePathname: () => '/dashboard/123456789/event_logging',
  useSearchParams: () => new URLSearchParams(),
  useParams: () => ({ guildId: '123456789' }),
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

vi.mock('@/lib/components/with-permission', () => ({
  withPermission: (Component: React.ComponentType<any>) => Component,
}))

vi.mock('@/lib/permissions', () => ({
  PermissionLevel: { AUTHORIZED: 2 },
}))

vi.mock('lucide-react', () => ({
  FileText:     () => null,
  CheckCircle:  () => null,
  XCircle:      () => null,
  AlertCircle:  () => null,
  Hash:         () => null,
  Settings:     () => null,
}))

vi.mock('next/link', () => ({
  default: ({ children, href }: { children: React.ReactNode; href: string }) =>
    React.createElement('a', { href }, children),
}))

// ── Helpers ───────────────────────────────────────────────────────────────────

/** Props the page component expects. */
const PAGE_PROPS = { params: { guildId: '123456789' } }

/** Fully-configured settings fixture. */
const SETTINGS_ENABLED: Record<string, any> = {
  logging_enabled:        true,
  logging_channel_id:     '987654321',
  logging_ignored_events: [],
}

/** Disabled, no channel. */
const SETTINGS_DISABLED: Record<string, any> = {
  logging_enabled:        false,
  logging_channel_id:     null,
  logging_ignored_events: ['on_message_delete', 'on_message_edit', 'on_member_join', 'on_member_remove'],
}

// ── Test suites ───────────────────────────────────────────────────────────────

describe('EventLoggingPage — API call', () => {
  beforeEach(() => {
    vi.resetModules()
  })

  it('calls apiClient.get() with a URL containing the correct guildId on mount', async () => {
    const get = vi.fn().mockResolvedValue(SETTINGS_ENABLED)

    vi.doMock('@/app/api-client', () => ({
      apiClient: { get },
    }))

    const { default: Page } = await import('../app/dashboard/[guildId]/event_logging/page')
    await act(async () => { render(<Page {...PAGE_PROPS} />) })

    await waitFor(() => {
      expect(get).toHaveBeenCalledOnce()
      const calledUrl: string = get.mock.calls[0][0]
      expect(calledUrl).toContain('123456789')
    })
  })
})

describe('EventLoggingPage — status display', () => {
  beforeEach(() => {
    vi.resetModules()
  })

  it('shows active status when logging_enabled is true', async () => {
    vi.doMock('@/app/api-client', () => ({
      apiClient: { get: vi.fn().mockResolvedValue(SETTINGS_ENABLED) },
    }))

    const { default: Page } = await import('../app/dashboard/[guildId]/event_logging/page')
    await act(async () => { render(<Page {...PAGE_PROPS} />) })

    await waitFor(() => {
      expect(screen.getByText('eventLogging.statusActive')).toBeDefined()
    })
  })

  it('shows inactive status when logging_enabled is false', async () => {
    vi.doMock('@/app/api-client', () => ({
      apiClient: { get: vi.fn().mockResolvedValue(SETTINGS_DISABLED) },
    }))

    const { default: Page } = await import('../app/dashboard/[guildId]/event_logging/page')
    await act(async () => { render(<Page {...PAGE_PROPS} />) })

    await waitFor(() => {
      expect(screen.getByText('eventLogging.statusInactive')).toBeDefined()
    })
  })

  it('renders the channel_id when a logging channel is set', async () => {
    vi.doMock('@/app/api-client', () => ({
      apiClient: { get: vi.fn().mockResolvedValue(SETTINGS_ENABLED) },
    }))

    const { default: Page } = await import('../app/dashboard/[guildId]/event_logging/page')
    await act(async () => { render(<Page {...PAGE_PROPS} />) })

    await waitFor(() => {
      expect(screen.getByText('987654321')).toBeDefined()
    })
  })
})

describe('EventLoggingPage — error handling', () => {
  beforeEach(() => {
    vi.resetModules()
  })

  it('shows error state and does not crash when API returns a rejection', async () => {
    vi.doMock('@/app/api-client', () => ({
      apiClient: {
        get: vi.fn().mockRejectedValue({ status: 404, message: 'Not Found' }),
      },
    }))

    const { default: Page } = await import('../app/dashboard/[guildId]/event_logging/page')
    await act(async () => { render(<Page {...PAGE_PROPS} />) })

    await waitFor(() => {
      // The catch block sets error to t('eventLogging.loadError'); since our t()
      // returns the key, we assert on the key string.
      expect(screen.getByText('eventLogging.loadError')).toBeDefined()
    })
  })

  it('shows error state and does not crash on network error', async () => {
    vi.doMock('@/app/api-client', () => ({
      apiClient: {
        get: vi.fn().mockRejectedValue(new Error('Network failure')),
      },
    }))

    const { default: Page } = await import('../app/dashboard/[guildId]/event_logging/page')
    await act(async () => { render(<Page {...PAGE_PROPS} />) })

    await waitFor(() => {
      expect(screen.getByText('eventLogging.loadError')).toBeDefined()
    })
  })
})

describe('EventLoggingPage — events list', () => {
  beforeEach(() => {
    vi.resetModules()
  })

  it('renders all four monitored event labels', async () => {
    vi.doMock('@/app/api-client', () => ({
      // No ignored events — all four events are active
      apiClient: { get: vi.fn().mockResolvedValue(SETTINGS_ENABLED) },
    }))

    const { default: Page } = await import('../app/dashboard/[guildId]/event_logging/page')
    await act(async () => { render(<Page {...PAGE_PROPS} />) })

    await waitFor(() => {
      // Each event renders t(ev.labelKey); our t() mock returns the key itself
      expect(screen.getByText('eventLogging.events.messageDelete')).toBeDefined()
      expect(screen.getByText('eventLogging.events.messageEdit')).toBeDefined()
      expect(screen.getByText('eventLogging.events.memberJoin')).toBeDefined()
      expect(screen.getByText('eventLogging.events.memberLeave')).toBeDefined()
    })
  })
})
