import { useMessages } from '@/i18n/messages'

// The Taipower and CWA datasets are licensed under the Open Government Data License v1.0, whose
// clause 3 requires every derived work to carry the attribution statement of its annex.
const LICENSE_URL = 'https://data.gov.tw/license'

export function Footer() {
  const m = useMessages()

  return (
    <footer className="border-t border-slate-800 px-6 py-4 text-xs leading-relaxed text-slate-500">
      <div className="max-w-7xl mx-auto space-y-1">
        <p>
          {m.attribution.sourceLabel}
          <span className="text-slate-400">{m.attribution.providers}</span>
        </p>
        <p>{m.attribution.statement}</p>
        <p>
          {m.attribution.licenseLabel}
          <a
            href={LICENSE_URL}
            target="_blank"
            rel="noopener noreferrer"
            className="text-cyan-400 underline-offset-2 hover:underline"
          >
            {m.attribution.licenseLink}
          </a>
        </p>
      </div>
    </footer>
  )
}
