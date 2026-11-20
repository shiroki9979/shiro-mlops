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
  const selector = `ImportExpression[source.value=/${regex.replaceAll('/', '\\x2F')}/]`
  return {
    'no-restricted-imports': ['error', { patterns: [{ regex, message }] }],
    // no-restricted-imports does not inspect dynamic import(), which would bundle the module all the same.
    'no-restricted-syntax': ['error', { selector, message }],
  }
}

const pathSegment = (names) => `(^|/)(${names.join('|')})(/|$)`

export default tseslint.config(
  { ignores: ['**/dist', '**/node_modules', '**/*.config.js', '**/*.config.ts'] },
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
    files: ['apps/forecast-view/**/*.{ts,tsx}'],
    rules: forbidImports(
      pathSegment(['engineering-console']),
      'The Forecast View must not import the Engineering Console; move shared code to packages/shared (ADR-0014 §2.3).',
    ),
  },
  {
    files: ['apps/engineering-console/**/*.{ts,tsx}'],
    rules: forbidImports(
      pathSegment(['forecast-view']),
      'The Engineering Console must not import the Forecast View; move shared code to packages/shared (ADR-0014 §2.3).',
    ),
  },
  {
    files: ['packages/shared/**/*.{ts,tsx}'],
    rules: forbidImports(
      `${pathSegment(['apps', 'forecast-view', 'engineering-console'])}|^@/`,
      'packages/shared must not import an app (`@/` resolves into whichever app bundles it); pass app values in as arguments (ADR-0014 §2.2).',
    ),
  },
)
