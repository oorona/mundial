/**
 * Tests for the LLM Configs page (/app/dashboard/llm-configs/page.tsx).
 *
 * Guards against:
 *   - Schemas and function sets not loaded on mount
 *   - Log entries not rendered in the table
 *   - Empty states causing crashes
 *   - Delete handlers not wired to API calls
 *   - Tab switching broken
 *   - API failure on load crashing the page
 */
import React from 'react'
import { describe, it, expect, vi, beforeEach } from 'vitest'
import { render, screen, waitFor, act, fireEvent } from '@testing-library/react'

// ── Shared mocks ──────────────────────────────────────────────────────────────

vi.mock('next/navigation', () => ({
    useRouter:       () => ({ push: vi.fn() }),
    usePathname:     () => '/dashboard/llm-configs',
    useSearchParams: () => new URLSearchParams(),
    useParams:       () => ({}),
}))

vi.mock('@tanstack/react-query', () => ({
    useQuery:            () => ({ data: null, isLoading: false, error: null }),
    QueryClient:         class {},
    QueryClientProvider: ({ children }: { children: React.ReactNode }) => children,
}))

vi.mock('@/lib/i18n', () => ({
    useTranslation: () => ({ t: (k: string, a?: any) => a ? `${k}:${JSON.stringify(a)}` : k, language: 'en' }),
    LanguageProvider: ({ children }: { children: React.ReactNode }) => children,
}))

// withPermission must render its child directly so the page is visible in tests
vi.mock('@/lib/components/with-permission', () => ({
    withPermission: (Component: React.ComponentType<any>) => Component,
}))

vi.mock('@/lib/permissions', () => ({
    PermissionLevel: { DEVELOPER: 5 },
}))

// ── Sample data ───────────────────────────────────────────────────────────────

const SAMPLE_LOGS = [
    {
        id: 'log-1',
        endpoint: 'generate',
        model: 'gemini-3.1-flash',
        user_id: 'u1',
        prompt_preview: 'Hello world',
        output_preview: 'Hi there',
        prompt_tokens: 10,
        completion_tokens: 5,
        thoughts_tokens: 0,
        total_tokens: 15,
        estimated_cost: 0.000001,
        latency_ms: 800,
        timestamp: '2026-01-01T00:00:00Z',
    },
]

const SAMPLE_SCHEMAS = [
    {
        id: 'schema1',
        name: 'Test Schema',
        description: 'A test schema',
        example_prompt: 'Extract data',
        properties: ['field_one', 'field_two'],
    },
]

const SAMPLE_FUNCTION_SETS = [
    {
        id: 'fs1',
        name: 'Test Functions',
        description: 'A test function set',
        function_count: 2,
        function_names: ['fn_a', 'fn_b'],
        example_prompts: ['Do something'],
    },
]

// ── Test suites ───────────────────────────────────────────────────────────────

describe('LLMConfigsPage — schemas tab', () => {
    beforeEach(() => {
        vi.resetModules()
    })

    it('calls listLlmSchemas on mount', async () => {
        const listLlmSchemas = vi.fn().mockResolvedValue({ schemas: [] })
        const listLlmFunctionSets = vi.fn().mockResolvedValue({ function_sets: [] })

        vi.doMock('@/app/api-client', () => ({
            apiClient: {
                listLlmSchemas,
                listLlmFunctionSets,
                getLlmLogs: vi.fn().mockResolvedValue({ logs: [], total_indexed: 0 }),
            },
        }))

        const { default: Page } = await import('../app/dashboard/llm-configs/page')
        await act(async () => { render(<Page />) })

        await waitFor(() => {
            expect(listLlmSchemas).toHaveBeenCalledOnce()
        })
    })

    it('renders schema names in the schema list', async () => {
        vi.doMock('@/app/api-client', () => ({
            apiClient: {
                listLlmSchemas:    vi.fn().mockResolvedValue({ schemas: SAMPLE_SCHEMAS }),
                listLlmFunctionSets: vi.fn().mockResolvedValue({ function_sets: [] }),
                getLlmLogs:        vi.fn().mockResolvedValue({ logs: [], total_indexed: 0 }),
            },
        }))

        const { default: Page } = await import('../app/dashboard/llm-configs/page')
        await act(async () => { render(<Page />) })

        await waitFor(() => {
            expect(screen.getByText('Test Schema')).toBeDefined()
            expect(screen.getByText('schema1')).toBeDefined()
        })
    })

    it('shows no crash and no schema entries when schemas list is empty', async () => {
        vi.doMock('@/app/api-client', () => ({
            apiClient: {
                listLlmSchemas:    vi.fn().mockResolvedValue({ schemas: [] }),
                listLlmFunctionSets: vi.fn().mockResolvedValue({ function_sets: [] }),
                getLlmLogs:        vi.fn().mockResolvedValue({ logs: [], total_indexed: 0 }),
            },
        }))

        const { default: Page } = await import('../app/dashboard/llm-configs/page')
        await act(async () => { render(<Page />) })

        await waitFor(() => {
            // The empty-state text is rendered when no schemas exist
            expect(screen.getByText(/No schemas yet/)).toBeDefined()
        })
    })

    it('calls deleteLlmSchema when Delete button is clicked on a schema', async () => {
        const deleteLlmSchema = vi.fn().mockResolvedValue(undefined)
        const listLlmSchemas  = vi.fn().mockResolvedValue({ schemas: SAMPLE_SCHEMAS })

        vi.doMock('@/app/api-client', () => ({
            apiClient: {
                listLlmSchemas,
                listLlmFunctionSets: vi.fn().mockResolvedValue({ function_sets: [] }),
                getLlmLogs:         vi.fn().mockResolvedValue({ logs: [], total_indexed: 0 }),
                getLlmSchema:        vi.fn().mockResolvedValue({}),
                deleteLlmSchema,
            },
        }))

        const { default: Page } = await import('../app/dashboard/llm-configs/page')
        await act(async () => { render(<Page />) })

        // Click the schema to open it in the editor (required to show the Delete button)
        await waitFor(() => screen.getByText('Test Schema'))
        await act(async () => { fireEvent.click(screen.getByText('Test Schema')) })

        // First click shows inline confirmation
        await waitFor(() => screen.getByText('Delete'))
        await act(async () => { fireEvent.click(screen.getByText('Delete')) })

        // Second click on "Confirm Delete" actually triggers the API call
        await waitFor(() => screen.getByText('Confirm Delete'))
        await act(async () => { fireEvent.click(screen.getByText('Confirm Delete')) })

        await waitFor(() => {
            expect(deleteLlmSchema).toHaveBeenCalledWith('schema1')
        })
    })

    it('schema is removed from list after successful delete', async () => {
        const deleteLlmSchema = vi.fn().mockResolvedValue(undefined)
        // After delete, listLlmSchemas returns empty
        const listLlmSchemas = vi.fn()
            .mockResolvedValueOnce({ schemas: SAMPLE_SCHEMAS })
            .mockResolvedValue({ schemas: [] })

        vi.doMock('@/app/api-client', () => ({
            apiClient: {
                listLlmSchemas,
                listLlmFunctionSets: vi.fn().mockResolvedValue({ function_sets: [] }),
                getLlmLogs:         vi.fn().mockResolvedValue({ logs: [], total_indexed: 0 }),
                getLlmSchema:        vi.fn().mockResolvedValue({}),
                deleteLlmSchema,
            },
        }))

        const { default: Page } = await import('../app/dashboard/llm-configs/page')
        await act(async () => { render(<Page />) })

        await waitFor(() => screen.getByText('Test Schema'))
        await act(async () => { fireEvent.click(screen.getByText('Test Schema')) })
        await waitFor(() => screen.getByText('Delete'))
        await act(async () => { fireEvent.click(screen.getByText('Delete')) })
        await waitFor(() => screen.getByText('Confirm Delete'))
        await act(async () => { fireEvent.click(screen.getByText('Confirm Delete')) })

        await waitFor(() => {
            expect(screen.queryByText('Test Schema')).toBeNull()
        })
    })
})

describe('LLMConfigsPage — function sets tab', () => {
    beforeEach(() => {
        vi.resetModules()
    })

    it('renders function set names in the function sets list', async () => {
        vi.doMock('@/app/api-client', () => ({
            apiClient: {
                listLlmSchemas:      vi.fn().mockResolvedValue({ schemas: [] }),
                listLlmFunctionSets: vi.fn().mockResolvedValue({ function_sets: SAMPLE_FUNCTION_SETS }),
                getLlmLogs:          vi.fn().mockResolvedValue({ logs: [], total_indexed: 0 }),
            },
        }))

        const { default: Page } = await import('../app/dashboard/llm-configs/page')
        await act(async () => { render(<Page />) })

        // Switch to Function Sets tab
        await waitFor(() => screen.getByText('Function Sets'))
        await act(async () => { fireEvent.click(screen.getByText('Function Sets')) })

        await waitFor(() => {
            expect(screen.getByText('Test Functions')).toBeDefined()
            expect(screen.getByText('fs1')).toBeDefined()
        })
    })

    it('calls deleteLlmFunctionSet when Delete button is clicked on a function set', async () => {
        const deleteLlmFunctionSet = vi.fn().mockResolvedValue(undefined)
        const listLlmFunctionSets  = vi.fn().mockResolvedValue({ function_sets: SAMPLE_FUNCTION_SETS })

        vi.doMock('@/app/api-client', () => ({
            apiClient: {
                listLlmSchemas:      vi.fn().mockResolvedValue({ schemas: [] }),
                listLlmFunctionSets,
                getLlmLogs:          vi.fn().mockResolvedValue({ logs: [], total_indexed: 0 }),
                getLlmFunctionSet:   vi.fn().mockResolvedValue({}),
                deleteLlmFunctionSet,
            },
        }))

        const { default: Page } = await import('../app/dashboard/llm-configs/page')
        await act(async () => { render(<Page />) })

        // Switch to Function Sets tab
        await waitFor(() => screen.getByText('Function Sets'))
        await act(async () => { fireEvent.click(screen.getByText('Function Sets')) })

        // Click the function set entry to open editor
        await waitFor(() => screen.getByText('Test Functions'))
        await act(async () => { fireEvent.click(screen.getByText('Test Functions')) })

        // First click shows inline confirmation
        await waitFor(() => screen.getByText('Delete'))
        await act(async () => { fireEvent.click(screen.getByText('Delete')) })

        // Second click on "Confirm Delete" triggers the API call
        await waitFor(() => screen.getByText('Confirm Delete'))
        await act(async () => { fireEvent.click(screen.getByText('Confirm Delete')) })

        await waitFor(() => {
            expect(deleteLlmFunctionSet).toHaveBeenCalledWith('fs1')
        })
    })
})

describe('LLMConfigsPage — logs tab', () => {
    beforeEach(() => {
        vi.resetModules()
    })

    it('calls getLlmLogs when the LLM Call Logs tab is clicked', async () => {
        const getLlmLogs = vi.fn().mockResolvedValue({ logs: SAMPLE_LOGS, total_indexed: 1 })

        vi.doMock('@/app/api-client', () => ({
            apiClient: {
                listLlmSchemas:      vi.fn().mockResolvedValue({ schemas: [] }),
                listLlmFunctionSets: vi.fn().mockResolvedValue({ function_sets: [] }),
                getLlmLogs,
            },
        }))

        const { default: Page } = await import('../app/dashboard/llm-configs/page')
        await act(async () => { render(<Page />) })

        await waitFor(() => screen.getByText('LLM Call Logs'))
        await act(async () => { fireEvent.click(screen.getByText('LLM Call Logs')) })

        await waitFor(() => {
            expect(getLlmLogs).toHaveBeenCalled()
        })
    })

    it('renders log entries with endpoint and model in the logs tab', async () => {
        vi.doMock('@/app/api-client', () => ({
            apiClient: {
                listLlmSchemas:      vi.fn().mockResolvedValue({ schemas: [] }),
                listLlmFunctionSets: vi.fn().mockResolvedValue({ function_sets: [] }),
                getLlmLogs:          vi.fn().mockResolvedValue({ logs: SAMPLE_LOGS, total_indexed: 1 }),
            },
        }))

        const { default: Page } = await import('../app/dashboard/llm-configs/page')
        await act(async () => { render(<Page />) })

        await waitFor(() => screen.getByText('LLM Call Logs'))
        await act(async () => { fireEvent.click(screen.getByText('LLM Call Logs')) })

        await waitFor(() => {
            expect(screen.getAllByText('generate').length).toBeGreaterThan(0)
            expect(screen.getAllByText('gemini-3.1-flash').length).toBeGreaterThan(0)
        })
    })

    it('shows empty state text when logs list is empty — does not crash', async () => {
        vi.doMock('@/app/api-client', () => ({
            apiClient: {
                listLlmSchemas:      vi.fn().mockResolvedValue({ schemas: [] }),
                listLlmFunctionSets: vi.fn().mockResolvedValue({ function_sets: [] }),
                getLlmLogs:          vi.fn().mockResolvedValue({ logs: [], total_indexed: 0 }),
            },
        }))

        const { default: Page } = await import('../app/dashboard/llm-configs/page')
        await act(async () => { render(<Page />) })

        await waitFor(() => screen.getByText('LLM Call Logs'))
        await act(async () => { fireEvent.click(screen.getByText('LLM Call Logs')) })

        await waitFor(() => {
            expect(screen.getByText(/No logs found/)).toBeDefined()
        })
    })
})

describe('LLMConfigsPage — tab switching', () => {
    beforeEach(() => {
        vi.resetModules()
    })

    it('clicking Output Schemas tab keeps schema list visible', async () => {
        vi.doMock('@/app/api-client', () => ({
            apiClient: {
                listLlmSchemas:      vi.fn().mockResolvedValue({ schemas: SAMPLE_SCHEMAS }),
                listLlmFunctionSets: vi.fn().mockResolvedValue({ function_sets: [] }),
                getLlmLogs:          vi.fn().mockResolvedValue({ logs: [], total_indexed: 0 }),
            },
        }))

        const { default: Page } = await import('../app/dashboard/llm-configs/page')
        await act(async () => { render(<Page />) })

        // Default tab is schemas — schema should be visible
        await waitFor(() => {
            expect(screen.getByText('Test Schema')).toBeDefined()
        })

        // Switch away to Function Sets then back
        await act(async () => { fireEvent.click(screen.getByText('Function Sets')) })
        await act(async () => { fireEvent.click(screen.getByText('Output Schemas')) })

        await waitFor(() => {
            expect(screen.getByText('Test Schema')).toBeDefined()
        })
    })

    it('clicking Function Sets tab shows function set list and hides schema list', async () => {
        vi.doMock('@/app/api-client', () => ({
            apiClient: {
                listLlmSchemas:      vi.fn().mockResolvedValue({ schemas: SAMPLE_SCHEMAS }),
                listLlmFunctionSets: vi.fn().mockResolvedValue({ function_sets: SAMPLE_FUNCTION_SETS }),
                getLlmLogs:          vi.fn().mockResolvedValue({ logs: [], total_indexed: 0 }),
            },
        }))

        const { default: Page } = await import('../app/dashboard/llm-configs/page')
        await act(async () => { render(<Page />) })

        await waitFor(() => screen.getByText('Function Sets'))
        await act(async () => { fireEvent.click(screen.getByText('Function Sets')) })

        await waitFor(() => {
            expect(screen.getByText('Test Functions')).toBeDefined()
            // Schema entry should no longer be visible
            expect(screen.queryByText('Test Schema')).toBeNull()
        })
    })
})

describe('LLMConfigsPage — API failure resilience', () => {
    beforeEach(() => {
        vi.resetModules()
    })

    it('does not crash when listLlmSchemas and listLlmFunctionSets both fail', async () => {
        vi.doMock('@/app/api-client', () => ({
            apiClient: {
                listLlmSchemas:      vi.fn().mockRejectedValue(new Error('Network error')),
                listLlmFunctionSets: vi.fn().mockRejectedValue(new Error('Network error')),
                getLlmLogs:          vi.fn().mockResolvedValue({ logs: [], total_indexed: 0 }),
            },
        }))

        const { default: Page } = await import('../app/dashboard/llm-configs/page')
        await act(async () => { render(<Page />) })

        // Page must settle — empty state text (or at minimum the tab bar) should render
        await waitFor(() => {
            expect(screen.getByText('Output Schemas')).toBeDefined()
        })
    })
})
