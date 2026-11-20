import js from '@eslint/js'
import globals from 'globals'
import reactHooks from 'eslint-plugin-react-hooks'
import reactRefresh from 'eslint-plugin-react-refresh'
import tseslint from 'typescript-eslint'

// Each restriction's regex is matched against import sources: both package names
// (`@shiro-mlops/<app>`) and relative paths that climb into another package's directory.
function forbidImports(restrictions) {
  // esquery ends a selector regex at the first `/`, so slashes are written as \x2F there.
  const literal = (regex) => `/${regex.replaceAll('/', '\\x2F')}/`
  return {
    'no-restricted-imports': ['error', { patterns: restrictions }],
    // no-restricted-imports inspects neither dynamic import() nor CommonJS require(), and a bundler
    // follows both all the same.
    'no-restricted-syntax': [
      'error',
      ...restrictions.flatMap(({ regex, message }) => [
        { selector: `ImportExpression[source.value=${literal(regex)}]`, message },
        { selector: `CallExpression[callee.name="require"][arguments.0.value=${literal(regex)}]`, message },
      ]),
    ],
  }
}

// Every source extension a bundler resolves, so a .js/.jsx/.mjs/.cjs file cannot bypass the boundary.
const SOURCES = '**/*.{ts,tsx,js,jsx,mjs,cjs}'

const pathSegment = (names) => `(^|/)(${names.join('|')})(/|$)`

// Workspace boundaries (ADR-0014 §2.2): apps may depend on packages/shared, never on each other,
// and shared never depends on an app.
const WORKSPACE_BOUNDARIES = [
  {
    dir: 'apps/forecast-view',
    regex: pathSegment(['engineering-console']),
    message:
      'The Forecast View must not import the Engineering Console; move shared code to packages/shared (ADR-0014 §2.3).',
  },
  {
    dir: 'apps/engineering-console',
    regex: pathSegment(['forecast-view']),
    message:
      'The Engineering Console must not import the Forecast View; move shared code to packages/shared (ADR-0014 §2.3).',
  },
  {
    dir: 'packages/shared',
    regex: `${pathSegment(['apps', 'forecast-view', 'engineering-console'])}|^@/`,
    message:
      'packages/shared must not import an app (`@/` resolves into whichever app bundles it); pass app values in as arguments (ADR-0014 §2.2).',
  },
]

// packages/shared/testing is imported by tests and vitest setup only; production sources (each
// package's src/) must not pull it into a bundle, by package name or by relative path.
const TEST_SUPPORT = {
  regex: '(^@shiro-mlops/shared|^\\.\\.?(/\\.\\.)*)/testing(/|$)',
  message: 'Test support must stay out of production bundles; import it from tests and vitest setup only.',
}

export default tseslint.config(
  // Config files run in Node, not in a bundle, so they are outside the workspace boundaries.
  { ignores: ['**/dist', '**/node_modules', '**/*.config.{js,mjs,cjs,ts,mts,cts}'] },
  {
    extends: [js.configs.recommended, ...tseslint.configs.recommended],
    files: ['**/*.{ts,tsx}'],
    languageOptions: {
      ecmaVersion: 2020,
      globals: globals.browser,
    },
    plugins: {
      'react-hooks': reactHooks,
      'react-refresh': reactRefresh,
    },
    rules: {
      ...reactHooks.configs.recommended.rules,
      'react-refresh/only-export-components': [
        'warn',
        { allowConstantExport: true },
      ],
      '@typescript-eslint/no-unused-vars': [
        'warn',
        { argsIgnorePattern: '^_', varsIgnorePattern: '^_' },
      ],
    },
  },
  {
    // JavaScript sources get no other rules here; they are parsed only so the boundaries below apply.
    files: ['apps/**/*.{js,jsx,mjs,cjs}', 'packages/**/*.{js,jsx,mjs,cjs}'],
    languageOptions: {
      parserOptions: { ecmaFeatures: { jsx: true } },
    },
  },
  // A later config object replaces an earlier one's rule options, so each file gets one combined list.
  ...WORKSPACE_BOUNDARIES.flatMap(({ dir, regex, message }) => [
    {
      files: [`${dir}/${SOURCES}`],
      ignores: [`${dir}/src/**`],
      rules: forbidImports([{ regex, message }]),
    },
    {
      files: [`${dir}/src/${SOURCES}`],
      rules: forbidImports([{ regex, message }, TEST_SUPPORT]),
    },
  ]),
)
