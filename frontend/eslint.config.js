import js from '@eslint/js'
import globals from 'globals'
import reactHooks from 'eslint-plugin-react-hooks'
import reactRefresh from 'eslint-plugin-react-refresh'
import tseslint from 'typescript-eslint'

// Workspace boundaries (ADR-0014 §2.2): apps may depend on packages/shared, never on each other,
// and shared never depends on an app. Each regex matches both the package name
// (`@shiro-mlops/<app>`) and relative paths that climb into the other package's directory.
function forbidImports(regex, message) {
  // esquery ends a selector regex at the first `/`, so slashes are written as \x2F there.
  const source = `/${regex.replaceAll('/', '\\x2F')}/`
  return {
    'no-restricted-imports': ['error', { patterns: [{ regex, message }] }],
    // no-restricted-imports inspects neither dynamic import() nor CommonJS require(), and a bundler
    // follows both all the same.
    'no-restricted-syntax': [
      'error',
      { selector: `ImportExpression[source.value=${source}]`, message },
      { selector: `CallExpression[callee.name="require"][arguments.0.value=${source}]`, message },
    ],
  }
}

// Every source extension a bundler resolves, so a .js/.jsx/.mjs/.cjs file cannot bypass the boundary.
const SOURCES = '**/*.{ts,tsx,js,jsx,mjs,cjs}'

const pathSegment = (names) => `(^|/)(${names.join('|')})(/|$)`

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
  {
    files: [`apps/forecast-view/${SOURCES}`],
    rules: forbidImports(
      pathSegment(['engineering-console']),
      'The Forecast View must not import the Engineering Console; move shared code to packages/shared (ADR-0014 §2.3).',
    ),
  },
  {
    files: [`apps/engineering-console/${SOURCES}`],
    rules: forbidImports(
      pathSegment(['forecast-view']),
      'The Engineering Console must not import the Forecast View; move shared code to packages/shared (ADR-0014 §2.3).',
    ),
  },
  {
    files: [`packages/shared/${SOURCES}`],
    rules: forbidImports(
      `${pathSegment(['apps', 'forecast-view', 'engineering-console'])}|^@/`,
      'packages/shared must not import an app (`@/` resolves into whichever app bundles it); pass app values in as arguments (ADR-0014 §2.2).',
    ),
  },
)
