import { vi } from 'vitest'

Object.defineProperty(globalThis, 'crypto', {
  value: { randomUUID: vi.fn(() => '00000000-0000-4000-8000-000000000001') },
  configurable: true,
})
Object.defineProperty(globalThis, 'ResizeObserver', {
  value: class { observe() {} unobserve() {} disconnect() {} },
  configurable: true,
})
