/**
 * Tests for the Welcome page (/app/welcome/page.tsx).
 *
 * Guards against:
 *   - Bot name not displayed from API response
 *   - "Add to Server" button shown/hidden based on invite_url presence
 *   - fetch() failure causing a crash or infinite loading state
 *   - Redirect to dashboard when logged-in user has guilds
 */
import React from 'react'
import { describe, it, expect, vi, beforeEach } from 'vitest'
import { render, screen, waitFor, act } from '@testing-library/react'

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
    useRouter:       () => ({ push: vi.fn(), replace: vi.fn() }),
    usePathname:     () => '/welcome',
    useSearchParams: () => new URLSearchParams(),
    useParams:       () => ({ guildId: '123456789' }),
}))

vi.mock('@tanstack/react-query', () => ({
    useQuery:            () => ({ data: null, isLoading: false, error: null }),
    QueryClient:         class {},
    QueryClientProvider: ({ children }: { children: React.ReactNode }) => children,
}))

// ── Helpers ───────────────────────────────────────────────────────────────────

function makeBotInfoResponse(overrides: Record<string, unknown> = {}) {
    return {
        name: 'AwesomeBot',
        tagline: 'The best bot',
        description: 'A very helpful bot',
        logo_url: '',
        invite_url: 'https://discord.com/oauth2/authorize?client_id=1',
        configured: true,
        ...overrides,
    }
}

function mockFetch(botInfoPayload: unknown, guildsPayload: unknown = []) {
    global.fetch = vi.fn().mockImplementation((url: string) => {
        if (typeof url === 'string' && url.includes('/api/v1/bot-info/public')) {
            if (botInfoPayload instanceof Error) {
                return Promise.resolve({ ok: false, json: async () => ({}) })
            }
            return Promise.resolve({ ok: true, json: async () => botInfoPayload })
        }
        if (typeof url === 'string' && url.includes('/api/v1/guilds/')) {
            return Promise.resolve({ ok: true, json: async () => guildsPayload })
        }
        return Promise.resolve({ ok: false, json: async () => ({}) })
    })
}

// ── Test suites ───────────────────────────────────────────────────────────────

describe('WelcomePage — bot info display', () => {
    beforeEach(() => {
        vi.resetModules()
    })

    it('renders bot name from API response', async () => {
        vi.doMock('@/lib/auth-context', () => ({
            useAuth: () => ({ user: null, loading: false }),
        }))

        mockFetch(makeBotInfoResponse({ name: 'SuperBot' }))

        const { default: WelcomePage } = await import('../app/welcome/page')
        await act(async () => { render(<WelcomePage />) })

        await waitFor(() => {
            expect(screen.getByRole('heading', { name: 'SuperBot' })).toBeDefined()
        })
    })

    it('"Add to Server" button is enabled when invite_url is present', async () => {
        vi.doMock('@/lib/auth-context', () => ({
            useAuth: () => ({ user: null, loading: false }),
        }))

        mockFetch(makeBotInfoResponse({ invite_url: 'https://discord.com/oauth2/authorize?client_id=1' }))

        const { default: WelcomePage } = await import('../app/welcome/page')
        await act(async () => { render(<WelcomePage />) })

        await waitFor(() => {
            // The button text comes through the t() mock as the key with args
            const btn = screen.getByRole('button', { name: /welcome\.addToServer/ })
            expect(btn).toBeDefined()
            expect((btn as HTMLButtonElement).disabled).toBe(false)
        })
    })

    it('"Add to Server" button is disabled when invite_url is null', async () => {
        vi.doMock('@/lib/auth-context', () => ({
            useAuth: () => ({ user: null, loading: false }),
        }))

        mockFetch(makeBotInfoResponse({ invite_url: '' }))

        const { default: WelcomePage } = await import('../app/welcome/page')
        await act(async () => { render(<WelcomePage />) })

        await waitFor(() => {
            const btn = screen.getByRole('button', { name: /welcome\.addToServer/ })
            expect(btn).toBeDefined()
            expect((btn as HTMLButtonElement).disabled).toBe(true)
        })
    })

    it('does not crash and shows fallback when fetch() fails', async () => {
        vi.doMock('@/lib/auth-context', () => ({
            useAuth: () => ({ user: null, loading: false }),
        }))

        // Return a non-ok response to trigger the error branch
        global.fetch = vi.fn().mockResolvedValue({ ok: false, json: async () => ({}) })

        const { default: WelcomePage } = await import('../app/welcome/page')
        await act(async () => { render(<WelcomePage />) })

        // Page must exit loading state — fallback bot name appears in heading
        await waitFor(() => {
            expect(screen.getByRole('heading', { name: 'My Discord Bot' })).toBeDefined()
        })
    })
})

describe('WelcomePage — authenticated user redirect', () => {
    beforeEach(() => {
        vi.resetModules()
    })

    it('redirects to dashboard when user is logged in and has guilds', async () => {
        const push = vi.fn()

        vi.doMock('@/lib/auth-context', () => ({
            useAuth: () => ({
                user: { user_id: '1', username: 'testuser', is_admin: false },
                loading: false,
            }),
        }))

        vi.doMock('next/navigation', () => ({
            useRouter:       () => ({ push, replace: vi.fn() }),
            usePathname:     () => '/welcome',
            useSearchParams: () => new URLSearchParams(),
            useParams:       () => ({}),
        }))

        // Bot info fetch + guilds fetch — guilds contains one active guild (bot_not_added: false)
        global.fetch = vi.fn().mockImplementation((url: string) => {
            if (typeof url === 'string' && url.includes('/api/v1/bot-info/public')) {
                return Promise.resolve({ ok: true, json: async () => makeBotInfoResponse() })
            }
            if (typeof url === 'string' && url.includes('/api/v1/guilds/')) {
                return Promise.resolve({
                    ok: true,
                    json: async () => [{ id: '111', bot_not_added: false }],
                })
            }
            return Promise.resolve({ ok: false, json: async () => ({}) })
        })

        // localStorage needs access_token stub
        Object.defineProperty(global, 'localStorage', {
            value: { getItem: vi.fn().mockReturnValue('fake-token') },
            writable: true,
        })

        const { default: WelcomePage } = await import('../app/welcome/page')
        await act(async () => { render(<WelcomePage />) })

        await waitFor(() => {
            expect(push).toHaveBeenCalledWith('/')
        })
    })
})
