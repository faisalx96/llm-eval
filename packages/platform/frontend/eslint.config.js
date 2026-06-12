import js from '@eslint/js'
import tseslint from 'typescript-eslint'
import jsxA11y from 'eslint-plugin-jsx-a11y'
import noUnsanitized from 'eslint-plugin-no-unsanitized'
import reactHooks from 'eslint-plugin-react-hooks'

export default tseslint.config(
  {
    // scripts/ holds dev-only smoke/fixture harnesses that run under node +
    // playwright (their own globals); they are not part of the shipped SPA.
    ignores: ['node_modules', 'dist', 'src/api/generated.d.ts', 'scripts'],
  },
  js.configs.recommended,
  tseslint.configs.recommended,
  jsxA11y.flatConfigs.recommended,
  {
    files: ['**/*.{ts,tsx,js,jsx}'],
    plugins: {
      'react-hooks': reactHooks,
      'no-unsanitized': noUnsanitized,
    },
    rules: {
      'react-hooks/rules-of-hooks': 'error',
      'react-hooks/exhaustive-deps': 'warn',
      // The legacy dashboard was vanilla JS + innerHTML; the SPA must never
      // assign unsanitized markup. Both rules hard-error.
      'no-unsanitized/method': 'error',
      'no-unsanitized/property': 'error',
    },
  },
)
