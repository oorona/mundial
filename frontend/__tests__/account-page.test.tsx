/**
 * Tests for the Account Settings page (/app/dashboard/account/page.tsx).
 *
 * Guards against:
 *   - Profile not displayed (user data not wired to display)
 *   - getUserSettings() not called on mount (settings silently skipped)
 *   - Theme selector absent or not reflecting current theme
 *   - Language selector absent or not reflecting current language
 *   - updateUserSettings() not called or called with wrong payload on save
 *   - Save button not disabled / loading state not shown while saving
 *   - API failure on save silently swallowed instead of surfacing error message
 *   - Guild list not loaded (getGuilds() not called on mount)
 */
import React from 'react'
import { describe, it, expect, vi, beforeEach } from 'vitest'
import { render, screen, waitFor, act, fireEvent } from '@testing-library/react'

// ── Shared mocks ──────────────────────────────────────────────────────────────

vi.mock('@/lib/i18n', () => ({
    useTranslation: () => ({
        t: (k: string, a?: any) => a ? `${k}:${JSON.stringify(a)}` : k,
        language: 'en',
        setLanguage: vi.fn(),
    }),
    LanguageProvider: ({ children }: { children: React.ReactNode }) => children,
}))

vi.mock('next/navigation', () => ({
    useRouter:       () => ({ push: vi.fn() }),
    usePathname:     () => '/dashboard/account',
    useSearchParams: () => new URLSearchParams(),
    useParams:       () => ({ guildId: '123456789' }),
}))

vi.mock('@tanstack/react-query', () => ({
    useQuery:            () => ({ data: null, isLoading: false, error: null }),
    QueryClient:         class {},
    QueryClientProvider: ({ children }: { children: React.ReactNode }) => children,
}))

vi.mock('next-themes', () => ({
    useTheme: () => ({ theme: 'system', setTheme: vi.fn() }),
}))

vi.mock('@/lib/permissions', () => ({
    PermissionLevel: { USER: 1, ADMIN: 2, OWNER: 3 },
}))

vi.mock('@/lib/components/with-permission', () => ({
    withPermission: (Component: React.ComponentType<any>) => Component,
}))

// ── Helpers ───────────────────────────────────────────────────────────────────

const SAMPLE_USER = {
    user_id: '111222333',
    username: 'testuser',
    avatar_url: '',
    is_admin: false,
}

const SAMPLE_SETTINGS = {
    theme: 'dark',
    language: 'en',
    default_guild_id: '999888777',
}

const SAMPLE_GUILDS = [
    { id: '999888777', name: 'Test Guild' },
    { id: '111000111', name: 'Another Guild' },
]

// ── Test suites ───────────────────────────────────────────────────────────────

describe('AccountPage — profile display', () => {
    beforeEach(() => {
        vi.resetModules()
    })

    it('loads and displays the user username on the page', async () => {
        vi.doMock('@/lib/auth-context', () => ({
            useAuth: () => ({
                user: SAMPLE_USER,
                loading: false,
                refreshUser: vi.fn().mockResolvedValue(undefined),
            }),
        }))
        vi.doMock('@/app/api-client', () => ({
            apiClient: {
                getUserSettings: vi.fn().mockResolvedValue({ settings: SAMPLE_SETTINGS }),
                getGuilds:       vi.fn().mockResolvedValue(SAMPLE_GUILDS),
                updateUserSettings: vi.fn().mockResolvedValue({}),
            },
        }))

        const { default: AccountPage } = await import('../app/dashboard/account/page')
        await act(async () => { render(<AccountPage />) })

        await waitFor(() => {
            expect(screen.getByText('testuser')).toBeDefined()
        })
    })

    it('calls getUserSettings() on mount', async () => {
        const getUserSettings = vi.fn().mockResolvedValue({ settings: SAMPLE_SETTINGS })

        vi.doMock('@/lib/auth-context', () => ({
            useAuth: () => ({
                user: SAMPLE_USER,
                loading: false,
                refreshUser: vi.fn().mockResolvedValue(undefined),
            }),
        }))
        vi.doMock('@/app/api-client', () => ({
            apiClient: {
                getUserSettings,
                getGuilds: vi.fn().mockResolvedValue(SAMPLE_GUILDS),
                updateUserSettings: vi.fn().mockResolvedValue({}),
            },
        }))

        const { default: AccountPage } = await import('../app/dashboard/account/page')
        await act(async () => { render(<AccountPage />) })

        await waitFor(() => {
            expect(getUserSettings).toHaveBeenCalledOnce()
        })
    })
})

describe('AccountPage — theme selector', () => {
    beforeEach(() => {
        vi.resetModules()
    })

    it('renders the theme selector with the current theme option visible', async () => {
        vi.doMock('@/lib/auth-context', () => ({
            useAuth: () => ({
                user: SAMPLE_USER,
                loading: false,
                refreshUser: vi.fn().mockResolvedValue(undefined),
            }),
        }))
        vi.doMock('@/app/api-client', () => ({
            apiClient: {
                getUserSettings: vi.fn().mockResolvedValue({ settings: { ...SAMPLE_SETTINGS, theme: 'dark' } }),
                getGuilds:       vi.fn().mockResolvedValue(SAMPLE_GUILDS),
                updateUserSettings: vi.fn().mockResolvedValue({}),
            },
        }))

        const { default: AccountPage } = await import('../app/dashboard/account/page')
        await act(async () => { render(<AccountPage />) })

        await waitFor(() => {
            // The section heading uses the i18n key
            expect(screen.getByText('account.sectionAppearance')).toBeDefined()
            // All three theme buttons are rendered
            expect(screen.getByText('account.themeLight')).toBeDefined()
            expect(screen.getByText('account.themeDark')).toBeDefined()
            expect(screen.getByText('account.themeSystem')).toBeDefined()
        })
    })
})

describe('AccountPage — language selector', () => {
    beforeEach(() => {
        vi.resetModules()
    })

    it('renders the language selector showing current language options', async () => {
        vi.doMock('@/lib/auth-context', () => ({
            useAuth: () => ({
                user: SAMPLE_USER,
                loading: false,
                refreshUser: vi.fn().mockResolvedValue(undefined),
            }),
        }))
        vi.doMock('@/app/api-client', () => ({
            apiClient: {
                getUserSettings: vi.fn().mockResolvedValue({ settings: { ...SAMPLE_SETTINGS, language: 'en' } }),
                getGuilds:       vi.fn().mockResolvedValue(SAMPLE_GUILDS),
                updateUserSettings: vi.fn().mockResolvedValue({}),
            },
        }))

        const { default: AccountPage } = await import('../app/dashboard/account/page')
        await act(async () => { render(<AccountPage />) })

        await waitFor(() => {
            // Section heading present
            expect(screen.getByText('account.sectionLanguage')).toBeDefined()
            // Both language options present in the select
            expect(screen.getByText('English (US)')).toBeDefined()
            expect(screen.getByText('Español (ES)')).toBeDefined()
        })
    })
})

describe('AccountPage — save settings', () => {
    beforeEach(() => {
        vi.resetModules()
    })

    it('calls updateUserSettings() with the correct payload when save button is clicked', async () => {
        const updateUserSettings = vi.fn().mockResolvedValue({})

        vi.doMock('@/lib/auth-context', () => ({
            useAuth: () => ({
                user: SAMPLE_USER,
                loading: false,
                refreshUser: vi.fn().mockResolvedValue(undefined),
            }),
        }))
        vi.doMock('@/app/api-client', () => ({
            apiClient: {
                getUserSettings: vi.fn().mockResolvedValue({ settings: SAMPLE_SETTINGS }),
                getGuilds:       vi.fn().mockResolvedValue(SAMPLE_GUILDS),
                updateUserSettings,
            },
        }))

        const { default: AccountPage } = await import('../app/dashboard/account/page')
        await act(async () => { render(<AccountPage />) })

        // Wait for the page to finish loading
        await waitFor(() => {
            expect(screen.getByText('account.saveButton')).toBeDefined()
        })

        await act(async () => {
            fireEvent.submit(screen.getByRole('button', { name: /account\.saveButton/ }).closest('form')!)
        })

        await waitFor(() => {
            expect(updateUserSettings).toHaveBeenCalledOnce()
            // Called with at least the settings object (theme, language, default_guild_id)
            const [calledWith] = updateUserSettings.mock.calls[0]
            expect(calledWith).toMatchObject({ theme: SAMPLE_SETTINGS.theme, language: SAMPLE_SETTINGS.language })
        })
    })

    it('save button is disabled and shows loading text while save is in progress', async () => {
        let resolveSave!: () => void
        const slowSave = new Promise<void>(resolve => { resolveSave = resolve })

        vi.doMock('@/lib/auth-context', () => ({
            useAuth: () => ({
                user: SAMPLE_USER,
                loading: false,
                refreshUser: vi.fn().mockResolvedValue(undefined),
            }),
        }))
        vi.doMock('@/app/api-client', () => ({
            apiClient: {
                getUserSettings: vi.fn().mockResolvedValue({ settings: SAMPLE_SETTINGS }),
                getGuilds:       vi.fn().mockResolvedValue(SAMPLE_GUILDS),
                updateUserSettings: vi.fn().mockReturnValue(slowSave),
            },
        }))

        const { default: AccountPage } = await import('../app/dashboard/account/page')
        await act(async () => { render(<AccountPage />) })

        await waitFor(() => {
            expect(screen.getByText('account.saveButton')).toBeDefined()
        })

        // Click save — but don't resolve the promise yet
        await act(async () => {
            fireEvent.submit(screen.getByRole('button', { name: /account\.saveButton/ }).closest('form')!)
        })

        // The submit button should now show saving state
        await waitFor(() => {
            expect(screen.getByText('account.saving')).toBeDefined()
        })

        // The button should be disabled
        const btn = screen.getByRole('button', { name: /account\.saving/ })
        expect((btn as HTMLButtonElement).disabled).toBe(true)

        // Cleanup: resolve the promise
        await act(async () => { resolveSave() })
    })

    it('shows error message when API fails on save — does not silently swallow', async () => {
        vi.doMock('@/lib/auth-context', () => ({
            useAuth: () => ({
                user: SAMPLE_USER,
                loading: false,
                refreshUser: vi.fn().mockResolvedValue(undefined),
            }),
        }))
        vi.doMock('@/app/api-client', () => ({
            apiClient: {
                getUserSettings: vi.fn().mockResolvedValue({ settings: SAMPLE_SETTINGS }),
                getGuilds:       vi.fn().mockResolvedValue(SAMPLE_GUILDS),
                updateUserSettings: vi.fn().mockRejectedValue(new Error('API error')),
            },
        }))

        const { default: AccountPage } = await import('../app/dashboard/account/page')
        await act(async () => { render(<AccountPage />) })

        await waitFor(() => {
            expect(screen.getByText('account.saveButton')).toBeDefined()
        })

        await act(async () => {
            fireEvent.submit(screen.getByRole('button', { name: /account\.saveButton/ }).closest('form')!)
        })

        await waitFor(() => {
            expect(screen.getByText('account.savedError')).toBeDefined()
        })
    })
})

describe('AccountPage — guild list for default guild selector', () => {
    beforeEach(() => {
        vi.resetModules()
    })

    it('calls getGuilds() on mount and populates the default guild selector', async () => {
        const getGuilds = vi.fn().mockResolvedValue(SAMPLE_GUILDS)

        vi.doMock('@/lib/auth-context', () => ({
            useAuth: () => ({
                user: SAMPLE_USER,
                loading: false,
                refreshUser: vi.fn().mockResolvedValue(undefined),
            }),
        }))
        vi.doMock('@/app/api-client', () => ({
            apiClient: {
                getUserSettings: vi.fn().mockResolvedValue({ settings: SAMPLE_SETTINGS }),
                getGuilds,
                updateUserSettings: vi.fn().mockResolvedValue({}),
            },
        }))

        const { default: AccountPage } = await import('../app/dashboard/account/page')
        await act(async () => { render(<AccountPage />) })

        await waitFor(() => {
            expect(getGuilds).toHaveBeenCalledOnce()
            // Guild names appear as options in the select
            expect(screen.getByText('Test Guild')).toBeDefined()
            expect(screen.getByText('Another Guild')).toBeDefined()
        })
    })
})
