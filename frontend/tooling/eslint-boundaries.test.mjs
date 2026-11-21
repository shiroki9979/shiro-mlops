// Proves the workspace boundary rules in eslint.config.js fire (ADR-0014 §2.2, §4).
// Each case lints a one-line fixture as if it lived at `filePath`, using the real config.
import assert from 'node:assert/strict'
import { dirname } from 'node:path'
import { describe, it } from 'node:test'
import { fileURLToPath } from 'node:url'
import { ESLint } from 'eslint'

const FRONTEND_ROOT = dirname(dirname(fileURLToPath(import.meta.url)))
const eslint = new ESLint({ cwd: FRONTEND_ROOT })
const BOUNDARY_RULES = new Set(['no-restricted-imports', 'no-restricted-syntax'])

async function boundaryErrors(filePath, source) {
  // A CommonJS file cannot hold an `export` statement.
  const text = filePath.endsWith('.cjs') ? `${source}\n` : `${source}\nexport {}\n`
  const [result] = await eslint.lintText(text, { filePath })
  // A file no config matches comes back as one rule-less warning, and a parse failure as a fatal
  // message; either would make every case below pass vacuously.
  const unlinted = result.messages.filter((message) => message.ruleId === null)
  assert.deepEqual(unlinted, [], `${filePath} was not linted`)
  return result.messages.filter((message) => BOUNDARY_RULES.has(message.ruleId))
}

const FORECAST_VIEW_FILE = 'apps/forecast-view/src/fixture.ts'
const CONSOLE_FILE = 'apps/engineering-console/src/fixture.ts'
const SHARED_FILE = 'packages/shared/src/fixture.ts'

describe('apps cannot import each other', () => {
  for (const [from, source] of [
    [FORECAST_VIEW_FILE, "import { x } from '@shiro-mlops/engineering-console'"],
    [FORECAST_VIEW_FILE, "import { x } from '@shiro-mlops/engineering-console/src/lib/api-client'"],
    [FORECAST_VIEW_FILE, "import { x } from '../../engineering-console/src/lib/api-client'"],
    [FORECAST_VIEW_FILE, "export { x } from '../../../apps/engineering-console/src/routes/data'"],
    [FORECAST_VIEW_FILE, "const page = import('../../engineering-console/src/routes/monitoring')"],
    [CONSOLE_FILE, "import { x } from '@shiro-mlops/forecast-view/src/hooks/use-prediction'"],
    [CONSOLE_FILE, "import { x } from '../../forecast-view/src/components/dashboard/metric-cards'"],
  ]) {
    it(`rejects ${source} in ${from}`, async () => {
      assert.equal((await boundaryErrors(from, source)).length, 1)
    })
  }
})

describe('shared cannot import any app', () => {
  for (const source of [
    "import { x } from '@shiro-mlops/forecast-view'",
    "import { x } from '@shiro-mlops/engineering-console/src/i18n/messages'",
    "import { x } from '../../../apps/forecast-view/src/i18n/messages'",
    // In shared, `@/` would resolve into whichever app is bundling it.
    "import { x } from '@/i18n/messages'",
  ]) {
    it(`rejects ${source}`, async () => {
      assert.equal((await boundaryErrors(SHARED_FILE, source)).length, 1)
    })
  }
})

// The boundary must hold for every source a bundler can pick up, not only TypeScript.
describe('boundaries cover JavaScript sources', () => {
  for (const [from, source] of [
    ['apps/forecast-view/src/fixture.js', "import { x } from '@shiro-mlops/engineering-console'"],
    ['apps/forecast-view/src/fixture.jsx', "import { Page } from '../../engineering-console/src/routes/data'\nconst page = <Page />"],
    ['apps/forecast-view/src/fixture.mjs', "const page = import('../../engineering-console/src/routes/monitoring')"],
    ['apps/forecast-view/src/fixture.cjs', "const { x } = require('@shiro-mlops/engineering-console/src/lib/api-client')"],
    ['apps/engineering-console/src/fixture.js', "import { x } from '../../forecast-view/src/hooks/use-prediction'"],
    ['apps/engineering-console/src/fixture.cjs', "const { x } = require('../../forecast-view/src/hooks/use-prediction')"],
    ['packages/shared/src/fixture.js', "import { x } from '@/i18n/messages'"],
    ['packages/shared/src/fixture.jsx', "import { x } from '@shiro-mlops/forecast-view'\nconst el = <div />"],
  ]) {
    it(`rejects ${source} in ${from}`, async () => {
      assert.equal((await boundaryErrors(from, source)).length, 1)
    })
  }

  for (const [from, source] of [
    ['apps/forecast-view/src/fixture.jsx', "import { Card } from '@shiro-mlops/shared/ui/card'\nconst el = <Card />"],
    ['apps/engineering-console/src/fixture.cjs', "const { request } = require('@shiro-mlops/shared/api')"],
    ['packages/shared/src/fixture.mjs', "import { create } from 'zustand'"],
  ]) {
    it(`allows ${source} in ${from}`, async () => {
      assert.deepEqual(await boundaryErrors(from, source), [])
    })
  }
})

describe('allowed dependency directions', () => {
  for (const [from, source] of [
    [FORECAST_VIEW_FILE, "import { Card } from '@shiro-mlops/shared/ui/card'"],
    [FORECAST_VIEW_FILE, "import { useMessages } from '@/i18n/messages'"],
    [FORECAST_VIEW_FILE, "import { x } from '../lib/api-client'"],
    [CONSOLE_FILE, "import { request } from '@shiro-mlops/shared/api'"],
    [CONSOLE_FILE, "import { x } from '@/components/data-explorer/catalog'"],
    [SHARED_FILE, "import { cn } from '../lib/utils'"],
    [SHARED_FILE, "import { create } from 'zustand'"],
  ]) {
    it(`allows ${source} in ${from}`, async () => {
      assert.deepEqual(await boundaryErrors(from, source), [])
    })
  }
})

// Test support lives in packages/shared/testing and must never reach a production bundle.
describe('production sources cannot import test support', () => {
  for (const [from, source] of [
    [FORECAST_VIEW_FILE, "import { resetLocaleForTest } from '@shiro-mlops/shared/testing/locale'"],
    [CONSOLE_FILE, "const helpers = import('@shiro-mlops/shared/testing/locale')"],
    ['packages/shared/src/i18n/fixture.ts', "import { resetLocaleForTest } from '../../testing/locale'"],
  ]) {
    it(`rejects ${source} in ${from}`, async () => {
      assert.equal((await boundaryErrors(from, source)).length, 1)
    })
  }

  for (const [from, source] of [
    ['apps/forecast-view/vitest.setup.ts', "import { resetLocaleForTest } from '@shiro-mlops/shared/testing/locale'"],
    ['apps/engineering-console/tests/unit/fixture.test.ts', "import { resetLocaleForTest } from '@shiro-mlops/shared/testing/locale'"],
    ['packages/shared/vitest.setup.ts', "import { resetLocaleForTest } from './testing/locale'"],
  ]) {
    it(`allows ${source} in ${from}`, async () => {
      assert.deepEqual(await boundaryErrors(from, source), [])
    })
  }
})
