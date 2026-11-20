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
  const [result] = await eslint.lintText(`${source}\nexport {}\n`, { filePath })
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
