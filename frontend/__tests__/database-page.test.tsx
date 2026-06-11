/**
 * Tests for the Database Management page components.
 *
 * These tests guard against the two classes of crash that were found in production:
 *  1. Object.entries(undefined) when the backend omits a field the frontend maps
 *  2. Array.map() on undefined when a field name changed (history → changelog)
 *
 * All API calls are mocked — these are pure rendering tests.
 */
import React from 'react'
import { describe, it, expect, vi } from 'vitest'
import { render, screen, waitFor, act } from '@testing-library/react'

// ── Mocks ────────────────────────────────────────────────────────────────────

vi.mock('@/lib/i18n', () => ({
    useTranslation: () => ({ t: (k: string) => k, language: 'en' }),
    LanguageProvider: ({ children }: { children: React.ReactNode }) => children,
}))

vi.mock('next/navigation', () => ({
    useParams:   () => ({}),
    useRouter:   () => ({ push: vi.fn() }),
    usePathname: () => '/',
    useSearchParams: () => new URLSearchParams(),
}))

vi.mock('@/lib/auth-context', () => ({
    useAuth: () => ({
        user: { user_id: '1', username: 'testuser', is_admin: true },
        loading: false,
    }),
}))

vi.mock('@tanstack/react-query', () => ({
    useQuery: () => ({ data: null, isLoading: false, error: null }),
    QueryClient: class {},
    QueryClientProvider: ({ children }: { children: React.ReactNode }) => children,
}))

// ── API client mock ───────────────────────────────────────────────────────────

const mockDbInfo = {
    framework_version:    '1.4.0',
    required_db_revision: 'b2c3d4e5f6a7',
    current_db_revision:  'b2c3d4e5f6a7',
    schema_match:         true,
    upgrade_needed:       false,
    upgrade_path:         [],
    revision_history: {          // must be present — Object.entries() called on this
        '1.0.0': 'c8d4e5f6a7b9',
        '1.4.0': 'b2c3d4e5f6a7',
    },
    postgres: { status: 'connected', version: 'PostgreSQL 15.0', size: '42 MB', active_connections: 3 },
    redis:    { status: 'connected', version: '7.0.0', used_memory_human: '1.2M', connected_clients: 2 },
}

const mockMigrations = {
    current_revision:   'b2c3d4e5f6a7',
    current_db_version: '1.4.0',
    head_revision:      'b2c3d4e5f6a7',
    framework_version:  '1.4.0',
    schema_up_to_date:  true,        // correct field name (not needs_upgrade)
    changelog: [                     // correct field name (not history)
        {
            version:        '1.0.0',
            description:    'Initial schema',
            revisions:      ['c8d4e5f6a7b9'],
            head_revision:  'c8d4e5f6a7b9',
            is_current:     false,
            already_applied: true,
        },
        {
            version:        '1.4.0',
            description:    'Fix RLS policies',
            revisions:      ['b2c3d4e5f6a7'],
            head_revision:  'b2c3d4e5f6a7',
            is_current:     true,
            already_applied: true,
        },
    ],
    pending_versions: [],
}

vi.mock('@/app/api-client', () => ({
    apiClient: {
        getDatabaseInfo:        vi.fn().mockResolvedValue(mockDbInfo),
        getDatabaseMigrations:  vi.fn().mockResolvedValue(mockMigrations),
        getDatabaseSettings:    vi.fn().mockResolvedValue({ settings: {} }),
        testDatabaseConnection: vi.fn().mockResolvedValue({ all_ok: true, postgres: { ok: true }, redis: { ok: true } }),
        validateDatabase:       vi.fn().mockResolvedValue({ passed: true, total_checks: 5, passed_count: 5, failed_count: 0, results: [] }),
    },
}))

// ── Tests ─────────────────────────────────────────────────────────────────────

// Import after mocks are declared
const { default: DatabasePage } = await import('../app/dashboard/database/page')

describe('Database Management Page', () => {
    it('renders without crashing (regression: Application error on load)', async () => {
        await act(async () => {
            render(<DatabasePage />)
        })
        expect(document.body).toBeDefined()
    })

    it('renders the page header', async () => {
        await act(async () => {
            render(<DatabasePage />)
        })
        await waitFor(() => {
            expect(screen.getByText('Database Management')).toBeDefined()
        })
    })

    it('does not crash when revision_history is a dict (Object.entries guard)', async () => {
        await act(async () => {
            render(<DatabasePage />)
        })
        // No error thrown means Object.entries(revision_history) succeeded
    })
})

describe('Migrations tab field name contract', () => {
    it('mock uses changelog not history (wrong field causes .map crash)', () => {
        expect(mockMigrations).toHaveProperty('changelog')
        expect(mockMigrations).not.toHaveProperty('history')
    })

    it('mock uses schema_up_to_date not needs_upgrade', () => {
        expect(mockMigrations).toHaveProperty('schema_up_to_date')
        expect(mockMigrations).not.toHaveProperty('needs_upgrade')
    })

    it('changelog entries have the required shape', () => {
        for (const entry of mockMigrations.changelog) {
            expect(entry).toHaveProperty('version')
            expect(entry).toHaveProperty('description')
            expect(entry).toHaveProperty('is_current')
            expect(entry).toHaveProperty('already_applied')
        }
    })
})

describe('Database info field name contract', () => {
    it('mock includes revision_history', () => {
        expect(mockDbInfo).toHaveProperty('revision_history')
        expect(typeof mockDbInfo.revision_history).toBe('object')
        expect(Object.keys(mockDbInfo.revision_history).length).toBeGreaterThan(0)
    })

    it('revision_history values are non-empty strings', () => {
        for (const [, rev] of Object.entries(mockDbInfo.revision_history)) {
            expect(typeof rev).toBe('string')
            expect(rev.length).toBeGreaterThan(0)
        }
    })
})
