import { Languages } from 'lucide-react'
import {
  isLocale,
  LOCALE_NATIVE_NAMES,
  SUPPORTED_LOCALES,
  useLocale,
  useLocaleStore,
} from './locale-store'

interface LocaleSwitcherProps {
  // Accessible name from the app's own dictionary; the options name themselves in their own language.
  label: string
}

export function LocaleSwitcher({ label }: LocaleSwitcherProps) {
  const locale = useLocale()
  const setLocale = useLocaleStore((state) => state.setLocale)

  return (
    <div className="flex items-center gap-1.5 text-xs">
      <Languages className="h-4 w-4 text-slate-400" aria-hidden="true" />
      <select
        aria-label={label}
        title={label}
        value={locale}
        onChange={(event) => {
          if (isLocale(event.target.value)) setLocale(event.target.value)
        }}
        className="h-8 rounded-md border border-slate-800 bg-slate-950/80 px-2 text-slate-300"
      >
        {SUPPORTED_LOCALES.map((option) => (
          <option key={option} value={option} lang={option}>
            {LOCALE_NATIVE_NAMES[option]}
          </option>
        ))}
      </select>
    </div>
  )
}
