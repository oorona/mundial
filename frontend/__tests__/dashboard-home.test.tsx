/**
 * Tests for the Dashboard Home page (/app/page.tsx).
 *
 * The most critical concern is card filtering by permission level:
 *
 *   - Cards with isAdminOnly=true are only shown when user.is_admin === true
 *   - Cards are filtered through hasAccess(card.level) from usePermissions()
 *   - Plugin nav items are merged into the card list
 *   - trackCardClick() is fired when a card is clicked
 *   - When getGuilds() fails, the page does not crash
 *
 * Permission-level to card mapping (from app/page.tsx):
 *   DEVELOPER (6, isAdminOnly): ai-analytics, system-config, database,
 *                               instrumentation, llm-configs
 *   OWNER     (5):              permissions, card-visibility
 *   ADMIN     (4):              bot-settings, audit-logs
 *   AUTHORIZED(3):              bot-health, event_logging
 *   USER      (2):              account-settings
 *   PUBLIC_DATA(1):             command-reference
 *   PUBLIC    (0):              bot-overview
 */
import React from 'react'
import { describe, it, expect, vi, beforeEach } from 'vitest'
import { render, screen, waitFor, act, fireEvent } from '@testing-library/react'
import { PermissionLevel } from '../lib/permissions'

// ── Shared static mocks ───────────────────────────────────────────────────────

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
  useTranslation: () => ({
    t: (k: string, a?: any) => {
      // Return recognisable card title strings so assertions can key off them
      const overrides: Record<string, string> = {
        'dashboard.cardAiAnalyticsTitle':   'AI Analytics',
        'dashboard.cardSystemConfigTitle':  'System Config',
        'dashboard.cardDatabaseTitle':      'Database',
        'dashboard.cardInstrumentationTitle': 'Instrumentation',
        'dashboard.cardLlmConfigsTitle':    'LLM Configs',
        'dashboard.cardPermissionsTitle':   'Permissions',
        'dashboard.cardCardVisibilityTitle': 'Card Visibility',
        'dashboard.cardBotSettingsTitle':   'Bot Settings',
        'dashboard.cardAccountSettingsTitle': 'Account Settings',
        'dashboard.cardCommandRefTitle':    'Command Reference',
        'dashboard.cardBotOverviewTitle':   'Bot Overview',
        'dashboard.cardBotHealthTitle':     'Bot Health',
        'dashboard.cardAuditLogsTitle':     'Audit Logs',
        'dashboard.cardPluginDesc':         'Plugin feature',
        'eventLogging.title':               'Event Logging',
        'eventLogging.description':         'Log guild events',
      }
      if (overrides[k]) return overrides[k]
      return a ? `${k}:${JSON.stringify(a)}` : k
    },
    language: 'en',
  }),
  LanguageProvider: ({ children }: { children: React.ReactNode }) => children,
}))

// ── Helpers ───────────────────────────────────────────────────────────────────

/** Builds a guild object that looks like an active guild (bot added). */
function makeGuild(id = 'guild-1', name = 'Test Guild') {
  return { id, name, bot_not_added: false, permission_level: 'owner' }
}

/** Returns a usePermissions mock for a given level. */
function makePermissionsMock(level: PermissionLevel) {
  return {
    usePermissions: () => ({
      permissionLevel: level,
      hasAccess: (required: PermissionLevel) => level >= required,
      loading: false,
      error: null,
      guild: makeGuild(),
    }),
  }
}

/** Returns a useAuth mock for a given user profile. */
function makeAuthMock(user: any) {
  return {
    useAuth: () => ({
      user,
      loading: false,
    }),
  }
}

/** A user object for a platform admin. */
const ADMIN_USER = {
  user_id: '1',
  username: 'admin',
  is_admin: true,
  preferences: { language: 'en' },
}

/** A user object for a guild owner (non-platform-admin). */
const OWNER_USER = {
  user_id: '2',
  username: 'owner',
  is_admin: false,
  preferences: { language: 'en' },
}

/** A user object for a regular member. */
const MEMBER_USER = {
  user_id: '3',
  username: 'member',
  is_admin: false,
  preferences: { language: 'en' },
}

// ── Test suites ───────────────────────────────────────────────────────────────

describe('DashboardHome — admin card visibility', () => {
  beforeEach(() => {
    vi.resetModules()
  })

  it('platform admin (is_admin: true) sees all DEVELOPER-level cards', async () => {
    vi.doMock('@/lib/auth-context', () => makeAuthMock(ADMIN_USER))
    // Platform admin → DEVELOPER level (6) from usePermissions
    vi.doMock('@/lib/hooks/use-permissions', () => makePermissionsMock(PermissionLevel.DEVELOPER))
    vi.doMock('@/app/plugins', () => ({
      usePlugins: () => ({ plugins: [], routes: [], navItems: [] }),
    }))
    vi.doMock('@/app/api-client', () => ({
      apiClient: {
        getGuilds: vi.fn().mockResolvedValue([makeGuild()]),
        trackCardClick: vi.fn().mockResolvedValue(undefined),
      },
    }))

    const { default: HomePage } = await import('../app/page')
    await act(async () => { render(<HomePage />) })

    await waitFor(() => {
      expect(screen.getByText('Database')).toBeDefined()
      expect(screen.getByText('LLM Configs')).toBeDefined()
      expect(screen.getByText('AI Analytics')).toBeDefined()
      expect(screen.getByText('System Config')).toBeDefined()
    })
  })

  it('non-admin user does NOT see DEVELOPER-level cards (isAdminOnly: true)', async () => {
    vi.doMock('@/lib/auth-context', () => makeAuthMock(OWNER_USER))
    // Guild owner has OWNER level (5) but is_admin: false
    vi.doMock('@/lib/hooks/use-permissions', () => makePermissionsMock(PermissionLevel.OWNER))
    vi.doMock('@/app/plugins', () => ({
      usePlugins: () => ({ plugins: [], routes: [], navItems: [] }),
    }))
    vi.doMock('@/app/api-client', () => ({
      apiClient: {
        getGuilds: vi.fn().mockResolvedValue([makeGuild()]),
        trackCardClick: vi.fn().mockResolvedValue(undefined),
      },
    }))

    const { default: HomePage } = await import('../app/page')
    await act(async () => { render(<HomePage />) })

    await waitFor(() => {
      // isAdminOnly cards must not appear for non-admin user
      expect(screen.queryByText('Database')).toBeNull()
      expect(screen.queryByText('LLM Configs')).toBeNull()
      expect(screen.queryByText('AI Analytics')).toBeNull()
      expect(screen.queryByText('System Config')).toBeNull()
    })
  })
})

describe('DashboardHome — owner card visibility', () => {
  beforeEach(() => {
    vi.resetModules()
  })

  it('owner user sees OWNER-level cards (Card Visibility, Permissions)', async () => {
    vi.doMock('@/lib/auth-context', () => makeAuthMock(OWNER_USER))
    vi.doMock('@/lib/hooks/use-permissions', () => makePermissionsMock(PermissionLevel.OWNER))
    vi.doMock('@/app/plugins', () => ({
      usePlugins: () => ({ plugins: [], routes: [], navItems: [] }),
    }))
    vi.doMock('@/app/api-client', () => ({
      apiClient: {
        getGuilds: vi.fn().mockResolvedValue([makeGuild()]),
        trackCardClick: vi.fn().mockResolvedValue(undefined),
      },
    }))

    const { default: HomePage } = await import('../app/page')
    await act(async () => { render(<HomePage />) })

    await waitFor(() => {
      expect(screen.getByText('Card Visibility')).toBeDefined()
      expect(screen.getByText('Permissions')).toBeDefined()
    })
  })

  it('non-owner ADMINISTRATOR user does NOT see OWNER-level cards', async () => {
    vi.doMock('@/lib/auth-context', () => makeAuthMock(MEMBER_USER))
    // Administrator level (4) — below OWNER (5)
    vi.doMock('@/lib/hooks/use-permissions', () => makePermissionsMock(PermissionLevel.ADMINISTRATOR))
    vi.doMock('@/app/plugins', () => ({
      usePlugins: () => ({ plugins: [], routes: [], navItems: [] }),
    }))
    vi.doMock('@/app/api-client', () => ({
      apiClient: {
        getGuilds: vi.fn().mockResolvedValue([makeGuild()]),
        trackCardClick: vi.fn().mockResolvedValue(undefined),
      },
    }))

    const { default: HomePage } = await import('../app/page')
    await act(async () => { render(<HomePage />) })

    await waitFor(() => {
      expect(screen.queryByText('Card Visibility')).toBeNull()
      expect(screen.queryByText('Permissions')).toBeNull()
    })
  })
})

describe('DashboardHome — card click tracking', () => {
  beforeEach(() => {
    vi.resetModules()
  })

  it('calls trackCardClick() when a card is clicked', async () => {
    const trackCardClick = vi.fn().mockResolvedValue(undefined)
    const pushMock = vi.fn()

    vi.doMock('next/navigation', () => ({
      useRouter: () => ({ push: pushMock }),
      usePathname: () => '/',
      useSearchParams: () => new URLSearchParams(),
      useParams: () => ({}),
    }))
    vi.doMock('@/lib/auth-context', () => makeAuthMock(OWNER_USER))
    vi.doMock('@/lib/hooks/use-permissions', () => makePermissionsMock(PermissionLevel.OWNER))
    vi.doMock('@/app/plugins', () => ({
      usePlugins: () => ({ plugins: [], routes: [], navItems: [] }),
    }))
    vi.doMock('@/app/api-client', () => ({
      apiClient: {
        getGuilds: vi.fn().mockResolvedValue([makeGuild()]),
        trackCardClick,
      },
    }))

    const { default: HomePage } = await import('../app/page')
    await act(async () => { render(<HomePage />) })

    // Wait for a known card to appear, then click it
    await waitFor(() => {
      expect(screen.getByText('Card Visibility')).toBeDefined()
    })

    await act(async () => {
      fireEvent.click(screen.getByText('Card Visibility'))
    })

    await waitFor(() => {
      expect(trackCardClick).toHaveBeenCalled()
      // The first argument should be the card id
      expect(trackCardClick.mock.calls[0][0]).toBe('card-visibility')
    })
  })
})

describe('DashboardHome — plugin cards', () => {
  beforeEach(() => {
    vi.resetModules()
  })

  it('merges plugin nav items into the card list', async () => {
    vi.doMock('@/lib/auth-context', () => makeAuthMock(OWNER_USER))
    vi.doMock('@/lib/hooks/use-permissions', () => makePermissionsMock(PermissionLevel.OWNER))
    vi.doMock('@/app/plugins', () => ({
      usePlugins: () => ({
        plugins: [],
        routes: [],
        navItems: [
          {
            id: 'test-plugin',
            name: 'My Test Plugin',
            href: '/dashboard/[guildId]/test-plugin',
            level: PermissionLevel.USER,
            icon: null,
            adminOnly: false,
          },
        ],
      }),
    }))
    vi.doMock('@/app/api-client', () => ({
      apiClient: {
        getGuilds: vi.fn().mockResolvedValue([makeGuild()]),
        trackCardClick: vi.fn().mockResolvedValue(undefined),
      },
    }))

    const { default: HomePage } = await import('../app/page')
    await act(async () => { render(<HomePage />) })

    await waitFor(() => {
      expect(screen.getByText('My Test Plugin')).toBeDefined()
    })
  })
})

describe('DashboardHome — getGuilds() failure', () => {
  beforeEach(() => {
    vi.resetModules()
  })

  it('does not crash when getGuilds() rejects', async () => {
    vi.doMock('@/lib/auth-context', () => makeAuthMock(ADMIN_USER))
    vi.doMock('@/lib/hooks/use-permissions', () => makePermissionsMock(PermissionLevel.DEVELOPER))
    vi.doMock('@/app/plugins', () => ({
      usePlugins: () => ({ plugins: [], routes: [], navItems: [] }),
    }))
    vi.doMock('@/app/api-client', () => ({
      apiClient: {
        getGuilds: vi.fn().mockRejectedValue(new Error('Network error')),
        trackCardClick: vi.fn().mockResolvedValue(undefined),
      },
    }))

    const { default: HomePage } = await import('../app/page')

    await expect(
      act(async () => { render(<HomePage />) })
    ).resolves.not.toThrow()

    // Page must not be stuck in loading state forever
    await waitFor(() => {
      expect(screen.queryByText('common.loadingDashboard')).toBeNull()
    }, { timeout: 3000 })
  })
})

describe('DashboardHome — no guilds available', () => {
  beforeEach(() => {
    vi.resetModules()
  })

  it('redirects to /welcome when all guilds have bot_not_added = true', async () => {
    const pushMock = vi.fn()

    vi.doMock('next/navigation', () => ({
      useRouter: () => ({ push: pushMock }),
      usePathname: () => '/',
      useSearchParams: () => new URLSearchParams(),
      useParams: () => ({}),
    }))
    vi.doMock('@/lib/auth-context', () => makeAuthMock(OWNER_USER))
    vi.doMock('@/lib/hooks/use-permissions', () => makePermissionsMock(PermissionLevel.PUBLIC))
    vi.doMock('@/app/plugins', () => ({
      usePlugins: () => ({ plugins: [], routes: [], navItems: [] }),
    }))
    vi.doMock('@/app/api-client', () => ({
      apiClient: {
        getGuilds: vi.fn().mockResolvedValue([
          { id: 'guild-1', name: 'Unavailable', bot_not_added: true },
        ]),
        trackCardClick: vi.fn().mockResolvedValue(undefined),
      },
    }))

    const { default: HomePage } = await import('../app/page')
    await act(async () => { render(<HomePage />) })

    await waitFor(() => {
      expect(pushMock).toHaveBeenCalledWith('/welcome')
    })
  })
})
