import '@testing-library/jest-dom/vitest'
import { beforeEach } from 'vitest'
import { resetLocaleForTest } from './testing/locale'

beforeEach(() => resetLocaleForTest())
