import React from 'react'
import { describe, it, expect, vi } from 'vitest'
import { render, screen, act } from '@testing-library/react'
import AccessDeniedPage from '../app/access-denied/page'

vi.mock('next/navigation', () => ({
    useSearchParams: () => new URLSearchParams(),
    useRouter: () => ({ push: vi.fn(), replace: vi.fn() }),
    usePathname: () => '/',
}))

// Provide a minimal t() stub so components that call useTranslation() work
// without a real LanguageProvider in the test tree.
vi.mock('@/lib/i18n', () => ({
    useTranslation: () => ({
        t: (key: string) => key,
        language: 'en',
    }),
    LanguageProvider: ({ children }: { children: React.ReactNode }) => children,
}))

describe('Frontend Smoke Test', () => {
    it('renders access denied page without crashing', async () => {
        await act(async () => {
            render(<AccessDeniedPage />)
        })
        // t() stub returns the key — verify key strings are rendered
        expect(screen.getByText('accessDenied.title')).toBeDefined()
        expect(screen.getByText('accessDenied.returnHome')).toBeDefined()
    })
})
