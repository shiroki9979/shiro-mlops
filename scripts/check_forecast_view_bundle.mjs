// Verifies the Forecast View build (the only frontend deployed to the cloud) carries no Engineering
// Console trace (ADR-0014 §4): no console route paths in the built files, and no console source module
// or console-only dependency among the bundled modules. It also rejects any on-demand inference call,
// since the Forecast View only reads the precomputed `/published/` files (ADR-0015 §2.4). Run after
// the frontend build, via `make frontend-bundle-check` locally and in the CI frontend job. Its
// negative controls live in frontend/tooling/check-forecast-view-bundle.test.mjs.
import { existsSync, readFileSync, readdirSync } from 'node:fs'
import { dirname, join, relative } from 'node:path'
import { fileURLToPath, pathToFileURL } from 'node:url'

const FRONTEND_ROOT = join(dirname(dirname(fileURLToPath(import.meta.url))), 'frontend')
const FORECAST_VIEW = join(FRONTEND_ROOT, 'apps/forecast-view')
const DIST = join(FORECAST_VIEW, 'dist')
// Written by the bundle-modules-report plugin in apps/forecast-view/vite.config.ts; keep the two in sync.
const MODULES_REPORT = join(FORECAST_VIEW, 'node_modules/.cache/bundle-modules.json')
const CONSOLE_SOURCE_PREFIX = 'apps/engineering-console/'
const TEXT_EXTENSIONS = /\.(html|js|mjs|css|json|svg|txt|map|webmanifest)$/

// Paths no built file may contain, one violation per group. `wholeWord` paths match only where the
// next character is not a word character or `-`.
export const FORBIDDEN_PATH_GROUPS = [
  // Engineering Console routes (ADR-0014 §2.5) and the pre-split URLs it replaced. `/console` is the
  // console's Vite `base` without its trailing slash (CONSOLE_BASE_PATH in
  // frontend/apps/engineering-console/vite.config.ts); keep in sync.
  { label: 'console paths', paths: ['/console', '/monitoring', '/data/'] },
  // API endpoints for on-demand inference, which the cloud surface has no origin for (ADR-0015).
  // Whole word, so names such as `/prediction-table` are not mistaken for the endpoint.
  { label: 'on-demand inference paths', paths: ['/predict'], wholeWord: true },
]

function containsPath(text, path, wholeWord) {
  if (!wholeWord) return text.includes(path)
  const escaped = path.replace(/[.*+?^${}()|[\]\\]/g, '\\$&')
  return new RegExp(`${escaped}(?![\\w-])`).test(text)
}

// Runtime dependencies that only the Engineering Console declares. Workspace packages are skipped:
// their sources are checked by path instead.
export function consoleOnlyDependencies({ engineeringConsole, forecastView, shared }) {
  const elsewhere = new Set([
    ...Object.keys(forecastView.dependencies ?? {}),
    ...Object.keys(shared.dependencies ?? {}),
  ])
  return Object.entries(engineeringConsole.dependencies ?? {})
    .filter(([name, spec]) => !spec.startsWith('workspace:') && !elsewhere.has(name))
    .map(([name]) => name)
    .sort()
}

// The npm package a bundled module belongs to, from its last node_modules segment.
function packageOf(moduleId) {
  const match = /(?:^|\/)node_modules\/((?:@[^/]+\/)?[^/]+)\/(?!.*\/node_modules\/)/.exec(moduleId)
  return match?.[1] ?? null
}

// `files` are the built files ({ path, text }); `moduleIds` are bundled module ids relative to frontend/.
export function findBundleViolations({ files, moduleIds, consoleOnly }) {
  const violations = []
  for (const { path, text } of files) {
    for (const { label, paths, wholeWord = false } of FORBIDDEN_PATH_GROUPS) {
      const found = paths.filter((forbidden) => containsPath(text, forbidden, wholeWord))
      if (found.length > 0) violations.push(`${path} contains ${label}: ${found.join(', ')}`)
    }
  }
  const consoleOnlySet = new Set(consoleOnly)
  for (const id of moduleIds) {
    if (id.startsWith(CONSOLE_SOURCE_PREFIX)) {
      violations.push(`bundles Engineering Console module ${id}`)
      continue
    }
    const name = packageOf(id)
    if (name && consoleOnlySet.has(name)) violations.push(`bundles console-only dependency ${name} (${id})`)
  }
  return violations
}

function readJson(path) {
  return JSON.parse(readFileSync(path, 'utf8'))
}

function builtFiles(dir) {
  return readdirSync(dir, { recursive: true, withFileTypes: true })
    .filter((entry) => entry.isFile() && TEXT_EXTENSIONS.test(entry.name))
    .map((entry) => {
      const fullPath = join(entry.parentPath, entry.name)
      return { path: relative(dir, fullPath), text: readFileSync(fullPath, 'utf8') }
    })
}

function main() {
  if (!existsSync(DIST) || !existsSync(MODULES_REPORT)) {
    console.error('Forecast View build output not found; run `make frontend-build` first.')
    return 1
  }
  const consoleOnly = consoleOnlyDependencies({
    engineeringConsole: readJson(join(FRONTEND_ROOT, 'apps/engineering-console/package.json')),
    forecastView: readJson(join(FORECAST_VIEW, 'package.json')),
    shared: readJson(join(FRONTEND_ROOT, 'packages/shared/package.json')),
  })
  const violations = findBundleViolations({
    files: builtFiles(DIST),
    moduleIds: readJson(MODULES_REPORT),
    consoleOnly,
  })
  if (violations.length > 0) {
    console.error(`Forecast View bundle check failed:\n${violations.map((v) => `- ${v}`).join('\n')}`)
    return 1
  }
  console.log(
    `Forecast View bundle check passed (console-only dependencies: ${consoleOnly.join(', ') || 'none'})`,
  )
  return 0
}

if (import.meta.url === pathToFileURL(process.argv[1]).href) {
  process.exitCode = main()
}
