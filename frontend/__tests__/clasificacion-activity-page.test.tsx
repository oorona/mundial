/**
 * Tests for the leaderboard Activity page (/app/activity/clasificacion/page.tsx).
 *
 * The page has a Global/Daily toggle that switches which API path it fetches. The
 * bug class here (the reason the component tier exists): the daily tab fetching the
 * wrong URL — e.g. re-fetching `/leaderboard` instead of `/leaderboard/daily`, or a
 * stale-closure capturing the previous tab. These assert the fetched URL tracks the
 * active tab, and that the empty-daily state renders the daily-specific message.
 *
 * Guards against:
 *   - global leaderboard not fetched on mount
 *   - clicking "Daily" not switching the fetch to /leaderboard/daily
 *   - clicking back to "Global" not returning to /leaderboard
 *   - rows from the response not rendered
 *   - empty daily showing the wrong empty message
 */
import React from 'react'
import { describe, it, expect, vi, beforeEach } from 'vitest'
import { render, screen, waitFor, act, fireEvent } from '@testing-library/react'

// ── Mocks ─────────────────────────────────────────────────────────────────────

// withActivityPage normally wraps with auth gating; collapse it to identity so we
// test the inner component directly.
vi.mock('@/lib/components/with-activity-page', () => ({
  withActivityPage: (C: React.ComponentType<any>) => C,
}))

vi.mock('@/lib/i18n', () => ({
  useTranslation: () => ({ t: (k: string) => k, language: 'es' }),
}))

// Hub already captured the guild → getActivityGuildId returns it, skipping handshake.
vi.mock('@/lib/activity', () => ({
  getActivityGuildId: () => 'G1',
  initActivity: vi.fn(async () => ({ guild_id: 'G1' })),
}))

// SSE: return a no-op subscription with a close().
const sseClose = vi.fn()
vi.mock('@/lib/streaming', () => ({
  subscribeSSE: () => ({ close: sseClose }),
}))

// apiClient.get records every path it is called with and returns per-path data.
const getCalls: string[] = []
const GLOBAL_ROWS = [
  { position: 1, user_id: '1001', username: 'ana', points: 9, exactos: 1, aciertos: 1 },
  { position: 2, user_id: '1002', username: 'beto', points: 1, exactos: 0, aciertos: 0 },
]
vi.mock('@/app/api-client', () => ({
  apiClient: {
    get: vi.fn(async (path: string) => {
      getCalls.push(path)
      if (path.endsWith('/leaderboard/daily')) return { standings: [] }
      return { standings: GLOBAL_ROWS }
    }),
  },
}))

import LeaderboardActivity from '@/app/activity/clasificacion/page'

describe('Leaderboard Activity — Global/Daily toggle', () => {
  beforeEach(() => {
    getCalls.length = 0
    sseClose.mockClear()
  })

  it('fetches the GLOBAL leaderboard on mount and renders its rows', async () => {
    await act(async () => { render(<LeaderboardActivity />) })
    await waitFor(() => expect(getCalls).toContain('/guilds/G1/leaderboard'))
    expect(getCalls.some((p) => p.endsWith('/leaderboard/daily'))).toBe(false)
    await screen.findByText('ana')
    expect(screen.getByText('beto')).toBeTruthy()
  })

  it('switches the fetch to /leaderboard/daily when the Daily tab is clicked', async () => {
    await act(async () => { render(<LeaderboardActivity />) })
    await waitFor(() => expect(getCalls).toContain('/guilds/G1/leaderboard'))

    await act(async () => { fireEvent.click(screen.getByText('leaderboard.tabDaily')) })

    await waitFor(() => expect(getCalls).toContain('/guilds/G1/leaderboard/daily'))
    // never fetched a malformed/zeroed path
    expect(getCalls.every((p) => p.startsWith('/guilds/G1/leaderboard'))).toBe(true)
  })

  it('shows the daily-specific empty message when yesterday had no matches', async () => {
    await act(async () => { render(<LeaderboardActivity />) })
    await waitFor(() => expect(getCalls).toContain('/guilds/G1/leaderboard'))

    await act(async () => { fireEvent.click(screen.getByText('leaderboard.tabDaily')) })

    // daily returns [] → must show leaderboard.dailyEmpty, not leaderboard.empty
    await screen.findByText('leaderboard.dailyEmpty')
    expect(screen.queryByText('leaderboard.empty')).toBeNull()
  })

  it('returns to the global path when toggled back to Global', async () => {
    await act(async () => { render(<LeaderboardActivity />) })
    await act(async () => { fireEvent.click(screen.getByText('leaderboard.tabDaily')) })
    await waitFor(() => expect(getCalls).toContain('/guilds/G1/leaderboard/daily'))

    getCalls.length = 0
    await act(async () => { fireEvent.click(screen.getByText('leaderboard.tabGlobal')) })

    await waitFor(() => expect(getCalls).toContain('/guilds/G1/leaderboard'))
    expect(getCalls.some((p) => p.endsWith('/leaderboard/daily'))).toBe(false)
  })
})
