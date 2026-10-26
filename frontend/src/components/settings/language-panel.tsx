import { Card, CardContent, CardDescription, CardHeader, CardTitle } from '@/components/ui/card'
import {
  LOCALE_NATIVE_NAMES,
  type Locale,
  SUPPORTED_LOCALES,
  useLocale,
  useLocaleStore,
} from '@/i18n/locale-store'
import { useMessages } from '@/i18n/use-messages'
import { Languages } from 'lucide-react'

function isLocale(value: string): value is Locale {
  return (SUPPORTED_LOCALES as readonly string[]).includes(value)
}

export function LanguagePanel() {
  const m = useMessages()
  const locale = useLocale()
  const setLocale = useLocaleStore((state) => state.setLocale)

  return (
    <Card className="border-slate-800 bg-slate-900/60 backdrop-blur-md">
      <CardHeader>
        <div className="flex items-center gap-2">
          <Languages className="h-5 w-5 text-cyan-400" />
          <CardTitle className="text-base font-semibold text-slate-200">{m.settings.language.title}</CardTitle>
        </div>
        <CardDescription>{m.settings.language.description}</CardDescription>
      </CardHeader>
      <CardContent className="space-y-1.5 text-xs">
        <label htmlFor="interface-language" className="text-slate-400 font-medium">
          {m.settings.language.label}
        </label>
        <select
          id="interface-language"
          value={locale}
          onChange={(event) => {
            if (isLocale(event.target.value)) setLocale(event.target.value)
          }}
          className="w-full bg-slate-950/80 border border-slate-800 rounded-lg px-3 py-2 text-slate-300"
        >
          {SUPPORTED_LOCALES.map((option) => (
            <option key={option} value={option} lang={option}>
              {LOCALE_NATIVE_NAMES[option]}
            </option>
          ))}
        </select>
      </CardContent>
    </Card>
  )
}
