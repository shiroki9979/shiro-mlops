// Verifies the Forecast View build (the only frontend deployed to the cloud) carries no Engineering
// Console trace (ADR-0014 §4): no console route paths in the built files, and no console source module
// or console-only dependency among the bundled modules. Run after `pnpm build`; CI runs it in the
// frontend job via `pnpm run check:bundle`.
import { existsSync, readFileSync, readdirSync } from 'node:fs'
import { dirname, join, relative } from 'node:path'
import { fileURLToPath, pathToFileURL } from 'node:url'

const FRONTEND_ROOT = dirname(dirname(fileURLToPath(import.meta.url)))
const FORECAST_VIEW = join(FRONTEND_ROOT, 'apps/forecast-view')
const DIST = join(FORECAST_VIEW, 'dist')
// Written by the bundle-modules-report plugin in apps/forecast-view/vite.config.ts; keep the two in sync.
const MODULES_REPORT = join(FORECAST_VIEW, 'node_modules/.cache/bundle-modules.json')
const CONSOLE_SOURCE_PREFIX = 'apps/engineering-console/'
const TEXT_EXTENSIONS = /\.(html|js|mjs|css|json|svg|txt|map|webmanifest)$/

// Engineering Console routes (ADR-0014 §2.5) and the pre-split URLs it replaced.
export const FORBIDDEN_PATHS = ['/console', '/monitoring', '/data/']

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
    const found = FORBIDDEN_PATHS.filter((forbidden) => text.includes(forbidden))
    if (found.length > 0) violations.push(`${path} contains console paths: ${found.join(', ')}`)
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
    console.error('Forecast View build output not found; run `pnpm build` first.')
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
