// Negative controls for the Forecast View bundle check (ADR-0014 §4, ADR-0015): each fixture plants one
// Engineering Console trace or on-demand inference call in an otherwise clean bundle and expects the
// check to name it.
import assert from 'node:assert/strict'
import { spawnSync } from 'node:child_process'
import { copyFileSync, mkdirSync, mkdtempSync, realpathSync, rmSync, symlinkSync } from 'node:fs'
import { tmpdir } from 'node:os'
import { join } from 'node:path'
import { describe, it } from 'node:test'
import { fileURLToPath } from 'node:url'
import { consoleOnlyDependencies, findBundleViolations } from '../../scripts/check_forecast_view_bundle.mjs'

const SCRIPT = fileURLToPath(new URL('../../scripts/check_forecast_view_bundle.mjs', import.meta.url))

const CLEAN_FILES = [
  { path: 'index.html', text: '<script type="module" src="/assets/index-abc.js"></script>' },
  { path: 'assets/index-abc.js', text: 'fetch("/published/latest_issued_forecast.json");const r="/history"' },
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

  it('reports an on-demand inference call apart from console paths', () => {
    const files = [...CLEAN_FILES, { path: 'assets/chunk-2.js', text: 'fetch(`${base}/predict`,{method:"POST"})' }]

    assert.deepEqual(check({ files }), ['assets/chunk-2.js contains on-demand inference paths: /predict'])
  })

  it('passes a name that merely starts with the inference path, and still reports the path itself', () => {
    const lookalike = { path: 'assets/chunk-4.js', text: 'const href="/prediction-table"' }
    const endpoint = { path: 'assets/chunk-5.js', text: 'fetch("/predict?h=24")' }

    assert.deepEqual(check({ files: [...CLEAN_FILES, lookalike] }), [])
    assert.deepEqual(check({ files: [...CLEAN_FILES, lookalike, endpoint] }), [
      'assets/chunk-5.js contains on-demand inference paths: /predict',
    ])
  })

  it('reports console paths and an inference call in one file as two violations', () => {
    const files = [...CLEAN_FILES, { path: 'assets/chunk-3.js', text: 'const a="/console";fetch("/api/predict")' }]

    assert.deepEqual(check({ files }), [
      'assets/chunk-3.js contains console paths: /console',
      'assets/chunk-3.js contains on-demand inference paths: /predict',
    ])
  })

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

describe('running the check as a script', () => {
  // A copy of the script in a checkout with no frontend build, so a run that reaches the check
  // always fails for want of build output. The root is resolved so the direct path has no symlink
  // in it (macOS's tmpdir is one).
  function inUnbuiltCheckout(run) {
    const root = realpathSync(mkdtempSync(join(tmpdir(), 'bundle-check-')))
    try {
      mkdirSync(join(root, 'checkout/scripts'), { recursive: true })
      const script = join(root, 'checkout/scripts/check_forecast_view_bundle.mjs')
      copyFileSync(SCRIPT, script)
      symlinkSync(join(root, 'checkout'), join(root, 'linked-checkout'), 'dir')
      symlinkSync(script, join(root, 'check.mjs'))
      run({
        'its own path': script,
        'a symlink to the script': join(root, 'check.mjs'),
        'a symlinked directory': join(root, 'linked-checkout/scripts/check_forecast_view_bundle.mjs'),
      })
    } finally {
      rmSync(root, { recursive: true, force: true })
    }
  }

  for (const invocation of ['its own path', 'a symlink to the script', 'a symlinked directory']) {
    it(`fails for missing build output when invoked through ${invocation}`, () => {
      inUnbuiltCheckout((paths) => {
        const result = spawnSync(process.execPath, [paths[invocation]], { encoding: 'utf8' })

        assert.match(result.stderr, /build output not found/)
        assert.equal(result.status, 1)
      })
    })
  }
})
