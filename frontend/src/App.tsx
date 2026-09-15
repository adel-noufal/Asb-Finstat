import { useEffect, useRef, useState } from 'react'
import { COUNTRIES, flagUrl, type Country } from './countries'

type Company = {
  id: string
  name: string
  description?: string
  source: 'GLEIF' | 'SEC EDGAR' | 'Wikidata' | 'AI'
  verification: 'source_record' | 'community' | 'unverified'
  country_code: string
  source_url?: string | null
  jurisdiction?: string | null
  headquarters_country?: string | null
  lei?: string | null
  cik?: string | null
  lei_status?: string | null
}

function companySource(company: Company) {
  if (company.verification === 'unverified') return 'AI suggestion · Unverified'
  if (company.verification === 'community') return 'Wikidata · Community data; incorporation unverified'
  return `${company.source} · Incorporation recorded${company.lei_status === 'LAPSED' ? ' · LEI renewal overdue' : ''}`
}
type StepUpdate = {
  type: 'step_update'
  step: string
  status: 'running' | 'done' | 'error' | 'skipped'
  message: string
  data?: {
    source_pdf?: string
    artifacts?: { json: string; xlsx: string }
    missing_statements?: string[]
    warnings?: string[]
    [key: string]: unknown
  } | null
}
type CompaniesMsg = { type: 'companies'; requestId: number; companies: Company[]; error?: string; warnings?: string[] }
type ServerMessage = StepUpdate | CompaniesMsg

const STEP_LABELS: Record<string, string> = {
  pipeline: 'Pipeline',
  find_statements: '#2 Find statements',
  language_check: '#3 Language check',
  translate: '#4 Translate',
  extract: '#5 Extract',
}

const STATUS_ICONS: Record<StepUpdate['status'], string> = {
  running: '●',
  done: '✓',
  error: '✕',
  skipped: '○',
}

type Mood = 'happy' | 'sad' | 'busy' | 'curious'

const MOOD_LABELS: Record<Mood, string> = {
  happy: 'connected',
  sad: 'disconnected',
  busy: 'working…',
  curious: 'searching…',
}

function Robot({ mood }: { mood: Mood }) {
  return (
    <svg className={`robot ${mood}`} viewBox="0 0 72 84" width="200" height="233" aria-hidden="true">
      <defs>
        <clipPath id="visor">
          <rect x="21" y="13" width="30" height="16" rx="5" />
        </clipPath>
      </defs>
      <g className="head">
        <line x1="36" y1="4" x2="36" y2="9" stroke="#dde3f0" strokeWidth="2" />
        <circle className="antenna-tip" cx="36" cy="3" r="2.4" />
        <rect x="12.5" y="16" width="4" height="12" rx="2" fill="#dde3f0" />
        <rect x="55.5" y="16" width="4" height="12" rx="2" fill="#dde3f0" />
        <rect x="16" y="8" width="40" height="26" rx="8" fill="#eef1f8" />
        <rect x="21" y="13" width="30" height="16" rx="5" fill="#0c0f16" />
        <g className="eyes" clipPath="url(#visor)">
          <g className="eye-group left">
            <rect className="eye" x="26.5" y="16" width="7" height="10" rx="2.5" />
            <path className="smile" d="M26 24.5 Q30 18 34 24.5" />
          </g>
          <g className="eye-group right">
            <rect className="eye" x="38.5" y="16" width="7" height="10" rx="2.5" />
            <path className="smile" d="M38 24.5 Q42 18 46 24.5" />
          </g>
        </g>
      </g>
      <g className="body">
        <rect className="arm left" x="13" y="46" width="5" height="16" rx="2.5" fill="#dde3f0" />
        <rect className="arm right" x="54" y="46" width="5" height="16" rx="2.5" fill="#dde3f0" />
        <path
          d="M26 40 L46 40 L52 48 L52 66 Q52 70 48 70 L24 70 Q20 70 20 66 L20 48 Z"
          fill="#eef1f8"
        />
        <rect className="chest" x="30" y="47" width="12" height="6" rx="2" />
        <line x1="22" y1="60" x2="50" y2="60" stroke="#d3dae8" strokeWidth="1.5" />
      </g>
    </svg>
  )
}

function Flag({ code, className }: { code: string; className?: string }) {
  return (
    <img
      className={className ?? 'flag'}
      src={flagUrl(code)}
      alt=""
      onError={(e) => (e.currentTarget.style.visibility = 'hidden')}
    />
  )
}

function CountrySelect({ value, onChange }: { value: Country | null; onChange: (c: Country) => void }) {
  const [open, setOpen] = useState(false)
  const [filter, setFilter] = useState('')
  const ref = useRef<HTMLDivElement>(null)

  useEffect(() => {
    const onClick = (e: MouseEvent) => {
      if (ref.current && !ref.current.contains(e.target as Node)) setOpen(false)
    }
    document.addEventListener('mousedown', onClick)
    return () => document.removeEventListener('mousedown', onClick)
  }, [])

  const list = COUNTRIES.filter((c) =>
    [c.name, ...(c.aliases ?? [])].some((name) => name.toLowerCase().includes(filter.trim().toLowerCase())),
  )

  return (
    <div className="country-select" ref={ref}>
      <button
        type="button"
        className={`field ${open ? 'open' : ''}`}
        onClick={() => {
          setOpen(!open)
          setFilter('')
        }}
      >
        {value ? (
          <span className="value">
            <Flag code={value.code} />
            {value.name}
          </span>
        ) : (
          <span className="placeholder">Select a country…</span>
        )}
        <span className="chevron">▾</span>
      </button>
      {open && (
        <div className="dropdown">
          <input
            autoFocus
            placeholder="Filter countries…"
            value={filter}
            onChange={(e) => setFilter(e.target.value)}
          />
          <ul>
            {list.map((c) => (
              <li
                key={c.code}
                className={value?.code === c.code ? 'active' : ''}
                onClick={() => {
                  onChange(c)
                  setOpen(false)
                }}
              >
                <Flag code={c.code} />
                {c.name}
              </li>
            ))}
            {list.length === 0 && <li className="empty">No matches</li>}
          </ul>
        </div>
      )}
    </div>
  )
}

export default function App() {
  const [connected, setConnected] = useState(false)
  const [country, setCountry] = useState<Country | null>(null)
  const [query, setQuery] = useState('')
  const [companies, setCompanies] = useState<Company[]>([])
  const [searching, setSearching] = useState(false)
  const [searchError, setSearchError] = useState('')
  const [searchWarnings, setSearchWarnings] = useState<string[]>([])
  const [searchComplete, setSearchComplete] = useState(false)
  const [selected, setSelected] = useState<Company | null>(null)
  const [events, setEvents] = useState<StepUpdate[]>([])
  const wsRef = useRef<WebSocket | null>(null)
  const requestId = useRef(0)

  useEffect(() => {
    let ws: WebSocket
    let closed = false
    const connect = () => {
      const proto = location.protocol === 'https:' ? 'wss' : 'ws'
      ws = new WebSocket(`${proto}://${location.host}/ws`)
      wsRef.current = ws
      ws.onopen = () => setConnected(true)
      ws.onclose = () => {
        if (wsRef.current !== ws || closed) return
        setConnected(false)
        requestId.current++
        setSearching(false)
        if (!closed) setTimeout(connect, 1000)
      }
      ws.onmessage = (e) => {
        const msg: ServerMessage = JSON.parse(e.data)
        if (msg.type === 'companies') {
          if (msg.requestId === requestId.current) {
            setCompanies(msg.companies)
            setSearchError(msg.error ?? '')
            setSearchWarnings(msg.warnings ?? [])
            setSearchComplete(true)
            setSearching(false)
          }
        } else if (msg.type === 'step_update') {
          setEvents((prev) => [...prev, msg])
        }
      }
    }
    connect()
    return () => {
      closed = true
      ws.close()
    }
  }, [])

  // Public sources first, with AI as the last fallback. Invalidate responses
  // immediately, including when the query becomes too short or country changes.
  useEffect(() => {
    const id = ++requestId.current
    setCompanies([])
    setSearchError('')
    setSearchWarnings([])
    setSearchComplete(false)
    setSearching(false)
    if (wsRef.current?.readyState === WebSocket.OPEN) {
      wsRef.current.send(JSON.stringify({ type: 'cancel_search' }))
    }
    if (!connected || !country || query.trim().length < 2 || selected) {
      return
    }
    const t = setTimeout(() => {
      if (wsRef.current?.readyState !== WebSocket.OPEN) return
      setSearching(true)
      wsRef.current.send(
        JSON.stringify({ type: 'search_companies', country: country.name, countryCode: country.code, query: query.trim(), requestId: id }),
      )
    }, 300)
    return () => clearTimeout(t)
  }, [country, query, selected, connected])

  useEffect(() => {
    if (events.length === 0) return
    // instant, after paint - smooth scrolling gets cancelled by rapid successive events
    requestAnimationFrame(() => window.scrollTo(0, document.documentElement.scrollHeight))
  }, [events])

  const selectCompany = (c: Company) => {
    if (!country || wsRef.current?.readyState !== WebSocket.OPEN) return
    requestId.current++
    setSelected(c)
    setCompanies([])
    setQuery(c.name)
    setEvents([])
    wsRef.current?.send(JSON.stringify({ type: 'run_pipeline', country: country.name, company: c }))
  }

  const pipelineActive =
    events.length > 0 &&
    !events.some((e) => e.step === 'pipeline' && (e.status === 'done' || e.status === 'error'))
  const mood: Mood = !connected ? 'sad' : searching ? 'curious' : pipelineActive ? 'busy' : 'happy'

  // a "running" row is only live while it's the latest event of its step and the
  // pipeline is still going - older ones are progress log lines, not active work
  const lastEventOfStep = new Map<string, number>()
  events.forEach((e, i) => lastEventOfStep.set(e.step, i))

  return (
    <div className="app">
      <header>
        <div className="brand">
          <h1>ASB Finstat</h1>
          <span className="team">{'// team: friendly_strangers'}</span>
        </div>
      </header>

      <div className="robot-dock">
        <Robot mood={mood} />
        <span className="status-label">{MOOD_LABELS[mood]}</span>
      </div>

      <section className="card controls">
        <div className="fieldgroup">
          <span className="caption" title="Country where the headquarters legal entity is incorporated">Country of incorporation</span>
          <CountrySelect
            value={country}
            onChange={(c) => {
              requestId.current++
              setCountry(c)
              setSelected(null)
              setQuery('')
              setCompanies([])
              setEvents([])
            }}
          />
        </div>

        <div className="fieldgroup">
          <span className="caption">Company</span>
          <div className="typeahead">
            <input
              value={query}
              maxLength={100}
              disabled={!country}
              placeholder={country ? 'Start typing a company name (2+ chars)…' : 'Pick a country first'}
              onChange={(e) => {
                requestId.current++
                setQuery(e.target.value)
                setSelected(null)
              }}
            />
            {searching && <span className="spinner" />}
            {searchError && <div className="hint error">{searchError}</div>}
            {searchWarnings.map((warning) => <div className="hint" key={warning}>{warning}</div>)}
            {searchComplete && !searching && !searchError && companies.length === 0 && (
              <div className="hint">No suggestions found. Try a longer name or another spelling.</div>
            )}
            {companies.length > 0 && (
              <ul className="suggestions">
                {companies.map((c) => (
                  <li key={c.id}>
                    <button type="button" className="company-option" onClick={() => selectCompany(c)}>
                      <span className="avatar">{c.name[0]}</span>
                      <span className="text">
                        <strong>{c.name}</strong>
                        {c.description && <span>{c.description}</span>}
                        <span className="company-source">{companySource(c)}</span>
                      </span>
                    </button>
                    {c.source_url && <a className="source-link" href={c.source_url} target="_blank" rel="noreferrer">Source</a>}
                  </li>
                ))}
              </ul>
            )}
          </div>
        </div>
      </section>

      {selected && country && (
        <section className="card activity">
          <h2>
            <Flag code={country.code} />
            {selected.name}
            <span className="sub">agent activity</span>
          </h2>
          <p className="hint">
            {companySource(selected)}
            {selected.source_url && <> · <a href={selected.source_url} target="_blank" rel="noreferrer">View source</a></>}
          </p>
          <ol>
            {events.map((e, i) => {
              const settled =
                e.status === 'running' && (lastEventOfStep.get(e.step) !== i || !pipelineActive)
              return (
                <li key={i} className={`event ${settled ? 'settled' : e.status}`}>
                  <span className="icon">{STATUS_ICONS[e.status]}</span>
                  <span className="step">{STEP_LABELS[e.step] ?? e.step}</span>
                  <span className="msg">{e.message}</span>
                </li>
              )
            })}
          </ol>
          {events.filter((event) => event.step === 'extract' && event.status === 'done' && event.data?.artifacts).map((event, index) => (
            <div className="extraction-result" key={index}>
              <strong>{event.data?.source_pdf}</strong>
              <div className="artifact-links">
                <a href={event.data!.artifacts!.xlsx} download>Download Excel</a>
                <a href={event.data!.artifacts!.json} download>Download JSON</a>
              </div>
              {!!event.data?.missing_statements?.length && (
                <p className="hint">Tables not recovered: {event.data.missing_statements.join(', ')}</p>
              )}
              {event.data?.warnings?.map((warning, i) => <p className="hint" key={i}>{warning}</p>)}
              <p className="hint">Review the source pages and extraction notes in the files.</p>
            </div>
          ))}
        </section>
      )}
    </div>
  )
}
