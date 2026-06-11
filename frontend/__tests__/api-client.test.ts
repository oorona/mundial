/**
 * Tests for the axios interceptors in APIClient (app/api-client.ts).
 *
 * Guards against:
 *   - Request interceptor failing to attach Authorization header when token is present
 *   - Request interceptor attaching a header when no token exists
 *   - 401 on any non-/auth/me endpoint NOT redirecting to /login and NOT clearing the token
 *   - 401 on /auth/me causing a redirect (should propagate silently)
 *   - 401 redirect loop when already on /login
 *   - 403 NOT redirecting to /access-denied
 *   - 403 redirect loop when already on /access-denied
 *   - 200 success responses not being passed through
 *   - /auth/discord/callback response with session_id not storing the token
 */
import { vi, describe, it, expect, beforeEach } from 'vitest'

// ── Capture interceptor handlers via axios.create mock ────────────────────────
// vi.hoisted() ensures the container is initialized before the vi.mock factory
// runs (vi.mock factories are hoisted to the top of the module by Vitest).

const handlers = vi.hoisted(() => ({
    requestSuccess:  undefined as ((config: any) => any) | undefined,
    responseSuccess: undefined as ((response: any) => any) | undefined,
    responseError:   undefined as ((error: any) => Promise<any>) | undefined,
}))

vi.mock('axios', () => {
    const mockClient = {
        interceptors: {
            request: {
                use: vi.fn((s: (config: any) => any) => {
                    handlers.requestSuccess = s
                }),
            },
            response: {
                use: vi.fn((s: (response: any) => any, e: (error: any) => Promise<any>) => {
                    handlers.responseSuccess = s
                    handlers.responseError = e
                }),
            },
        },
        get:  vi.fn(),
        post: vi.fn(),
    }

    return {
        default: {
            create: vi.fn(() => mockClient),
        },
        AxiosError: class AxiosError extends Error {
            response?: any
            config?: any
        },
    }
})

// ── Import APIClient after the mock is in place ───────────────────────────────
// The import triggers class instantiation and registers the interceptors.
import '@/app/api-client'

// ── Helpers ───────────────────────────────────────────────────────────────────

function makeError(status: number, url: string): any {
    return {
        response: { status },
        config:   { url },
    }
}

// localStorage mock — we replace window.localStorage with a plain object
// so that both the api-client code and our spies share the same reference.
const localStorageMock = (() => {
    let store: Record<string, string> = {}
    return {
        getItem:    vi.fn((key: string): string | null => store[key] ?? null),
        setItem:    vi.fn((key: string, value: string) => { store[key] = value }),
        removeItem: vi.fn((key: string) => { delete store[key] }),
        clear:      vi.fn(() => { store = {} }),
    }
})()

// ── beforeEach ────────────────────────────────────────────────────────────────

beforeEach(() => {
    // Install a writable, configurable window.location stub
    Object.defineProperty(window, 'location', {
        value:        { href: '', pathname: '/' },
        writable:     true,
        configurable: true,
    })

    // Install localStorage mock on the global window
    Object.defineProperty(window, 'localStorage', {
        value:        localStorageMock,
        writable:     true,
        configurable: true,
    })

    // Clear call history before each test
    localStorageMock.getItem.mockClear()
    localStorageMock.setItem.mockClear()
    localStorageMock.removeItem.mockClear()
    localStorageMock.clear()
})

// ── Request interceptor ───────────────────────────────────────────────────────

describe('Request interceptor', () => {
    it('adds Authorization header when token is present in localStorage', () => {
        localStorageMock.getItem.mockReturnValue('my-token')

        const config = { headers: {} as Record<string, string> }
        const result = handlers.requestSuccess!(config)

        expect(result.headers.Authorization).toBe('Bearer my-token')
    })

    it('does not add Authorization header when localStorage returns null', () => {
        localStorageMock.getItem.mockReturnValue(null)

        const config = { headers: {} as Record<string, string> }
        const result = handlers.requestSuccess!(config)

        expect(result.headers.Authorization).toBeUndefined()
    })

    it('passes the config object through unchanged aside from the header', () => {
        localStorageMock.getItem.mockReturnValue(null)

        const config = { headers: {}, url: '/some/endpoint', method: 'get' }
        const result = handlers.requestSuccess!(config)

        expect(result.url).toBe('/some/endpoint')
        expect(result.method).toBe('get')
    })
})

// ── Response interceptor — 401 handling ──────────────────────────────────────

describe('Response interceptor — 401 handling', () => {
    it('removes access_token from localStorage on 401 (non-/auth/me)', async () => {
        await handlers.responseError!(makeError(401, '/api/v1/guilds/123/settings')).catch(() => {})

        expect(localStorageMock.removeItem).toHaveBeenCalledWith('access_token')
    })

    it('redirects to /login on 401 when not already on /login', async () => {
        window.location.pathname = '/'

        await handlers.responseError!(makeError(401, '/api/v1/guilds/123/settings')).catch(() => {})

        expect(window.location.href).toBe('/login')
    })

    it('does NOT redirect to /login on 401 when already on /login', async () => {
        Object.defineProperty(window, 'location', {
            value:        { href: '', pathname: '/login' },
            writable:     true,
            configurable: true,
        })

        await handlers.responseError!(makeError(401, '/api/v1/guilds/123/settings')).catch(() => {})

        expect(window.location.href).toBe('')
    })

    it('still removes token from localStorage on 401 even when already on /login', async () => {
        Object.defineProperty(window, 'location', {
            value:        { href: '', pathname: '/login' },
            writable:     true,
            configurable: true,
        })

        await handlers.responseError!(makeError(401, '/api/v1/guilds/123/settings')).catch(() => {})

        expect(localStorageMock.removeItem).toHaveBeenCalledWith('access_token')
    })

    it('propagates the error (Promise.reject) on 401 for /auth/me', async () => {
        const error = makeError(401, '/auth/me')

        await expect(handlers.responseError!(error)).rejects.toBe(error)
    })

    it('does NOT redirect to /login on 401 for /auth/me', async () => {
        await handlers.responseError!(makeError(401, '/auth/me')).catch(() => {})

        expect(window.location.href).not.toBe('/login')
    })

    it('does NOT call localStorage.removeItem on 401 for /auth/me', async () => {
        await handlers.responseError!(makeError(401, '/auth/me')).catch(() => {})

        expect(localStorageMock.removeItem).not.toHaveBeenCalled()
    })
})

// ── Response interceptor — 403 handling ──────────────────────────────────────

describe('Response interceptor — 403 handling', () => {
    it('redirects to /access-denied on 403 when not already on /access-denied', async () => {
        window.location.pathname = '/dashboard/123'

        await handlers.responseError!(makeError(403, '/api/v1/guilds/123/settings')).catch(() => {})

        expect(window.location.href).toBe('/access-denied')
    })

    it('does NOT redirect on 403 when already on /access-denied', async () => {
        Object.defineProperty(window, 'location', {
            value:        { href: '', pathname: '/access-denied' },
            writable:     true,
            configurable: true,
        })

        await handlers.responseError!(makeError(403, '/api/v1/guilds/123/settings')).catch(() => {})

        expect(window.location.href).toBe('')
    })

    it('still rejects the promise on 403', async () => {
        const error = makeError(403, '/api/v1/guilds/123/settings')

        await expect(handlers.responseError!(error)).rejects.toBe(error)
    })
})

// ── Response interceptor — success ───────────────────────────────────────────

describe('Response interceptor — success', () => {
    it('returns the response unchanged on 200', () => {
        const response = { status: 200, data: { foo: 'bar' }, config: { url: '/api/v1/some-endpoint' } }
        const result = handlers.responseSuccess!(response)

        expect(result).toBe(response)
        expect(result.data).toEqual({ foo: 'bar' })
    })

    it('stores session_id in localStorage for /auth/discord/callback responses', () => {
        const response = {
            status: 200,
            data:   { session_id: 'abc-123', user: {} },
            config: { url: '/auth/discord/callback' },
        }
        handlers.responseSuccess!(response)

        expect(localStorageMock.setItem).toHaveBeenCalledWith('access_token', 'abc-123')
    })

    it('does NOT call localStorage.setItem for /auth/discord/callback when session_id is absent', () => {
        const response = {
            status: 200,
            data:   { error: 'oauth_failed' },
            config: { url: '/auth/discord/callback' },
        }
        handlers.responseSuccess!(response)

        expect(localStorageMock.setItem).not.toHaveBeenCalled()
    })

    it('does NOT store token for a regular 200 response on a non-callback URL', () => {
        const response = {
            status: 200,
            data:   { session_id: 'should-not-be-stored' },
            config: { url: '/api/v1/guilds/123/settings' },
        }
        handlers.responseSuccess!(response)

        expect(localStorageMock.setItem).not.toHaveBeenCalled()
    })
})
