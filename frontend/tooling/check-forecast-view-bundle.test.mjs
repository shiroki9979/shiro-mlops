// Negative controls for the Forecast View bundle check (ADR-0014 §4): each fixture plants one
// Engineering Console trace in an otherwise clean bundle and expects the check to name it.
import assert from 'node:assert/strict'
import { describe, it } from 'node:test'
import { consoleOnlyDependencies, findBundleViolations } from '../../scripts/check_forecast_view_bundle.mjs'

const CLEAN_FILES = [
  { path: 'index.html', text: '<script type="module" src="/assets/index-abc.js"></script>' },
  { path: 'assets/index-abc.js', text: 'fetch(`${base}/predict`);console.error("x");const r="/history"' },
]
const CLEAN_MODULES = [
  '\0vite/preload-helper.js',
  'apps/forecast-view/src/main.tsx',
  'packages/shared/src/ui/card.tsx',
  'node_modules/.pnpm/recharts@2.15.4_react@19.2.6/node_modules/recharts/es6/index.js',
  'node_modules/.pnpm/@tanstack+react-router@1.170.32/node_modules/@tanstack/react-router/dist/esm/index.js',
]

function check({ files = CLEAN_FILES, moduleIds = CLEAN_MODULES, consoleOnly = ['@tanstack/react-table', 'date-fns'] } = {}) {
  return findBundleViolations({ files, moduleIds, consoleOnly })
}

describe('findBundleViolations', () => {
  it('passes a bundle with no Engineering Console traces', () => {
    assert.deepEqual(check(), [])
  })

  for (const path of ['/console', '/console/monitoring', '/monitoring', '/data/power/load']) {
    it(`reports the console path ${path} in a built file`, () => {
      const files = [...CLEAN_FILES, { path: 'assets/chunk-1.js', text: `const href="${path}"` }]

      const violations = check({ files })

      assert.equal(violations.length, 1)
      assert.match(violations[0], /assets\/chunk-1\.js/)
    })
  }

  it('reports a bundled Engineering Console source module', () => {
    const moduleIds = [...CLEAN_MODULES, 'apps/engineering-console/src/lib/api-client.ts']

    assert.deepEqual(check({ moduleIds }), [
      'bundles Engineering Console module apps/engineering-console/src/lib/api-client.ts',
    ])
  })

  for (const [name, id] of [
    ['@tanstack/react-table', 'node_modules/.pnpm/@tanstack+react-table@8.21.3/node_modules/@tanstack/react-table/build/lib/index.mjs'],
    ['date-fns', 'node_modules/.pnpm/date-fns@4.1.0/node_modules/date-fns/format.js'],
  ]) {
    it(`reports the console-only dependency ${name}`, () => {
      assert.deepEqual(check({ moduleIds: [...CLEAN_MODULES, id] }), [
        `bundles console-only dependency ${name} (${id})`,
      ])
    })
  }

  it('does not mistake a package whose name merely starts like a console-only one', () => {
    const moduleIds = [...CLEAN_MODULES, 'node_modules/.pnpm/date-fns-tz@3.2.0/node_modules/date-fns-tz/index.js']

    assert.deepEqual(check({ moduleIds }), [])
  })
})

describe('consoleOnlyDependencies', () => {
  it('lists runtime dependencies only the Engineering Console declares', () => {
    const manifests = {
      engineeringConsole: {
        dependencies: { '@shiro-mlops/shared': 'workspace:*', react: '^19', '@tanstack/react-table': '^8', zod: '^3' },
        devDependencies: { msw: '^2' },
      },
      forecastView: { dependencies: { react: '^19', recharts: '^2' } },
      shared: { dependencies: { zod: '^3' } },
    }

    assert.deepEqual(consoleOnlyDependencies(manifests), ['@tanstack/react-table'])
  })
})
