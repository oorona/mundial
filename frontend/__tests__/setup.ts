/**
 * Global Vitest setup — runs once before each test file.
 *
 * Suppresses console.error and console.warn so that intentional error-path
 * tests (components catching rejected promises and logging the failure) do
 * not pollute test runner output.  Unexpected failures still surface because
 * they cause test *assertions* to fail — silence here does not hide real bugs.
 */
import { beforeAll, afterAll, vi } from 'vitest'

beforeAll(() => {
  vi.spyOn(console, 'error').mockImplementation(() => {})
  vi.spyOn(console, 'warn').mockImplementation(() => {})
})

afterAll(() => {
  vi.mocked(console.error).mockRestore()
  vi.mocked(console.warn).mockRestore()
})
