/**
 * Dashboard — 5-step session wizard.
 * Step 1: Setup (profile, script, N)
 * Step 2: Tag review
 * Step 3: Download progress
 * Step 4: Preview & curation
 * Step 5: Export
 */
import { useState, useEffect, useRef } from 'react'
import { useQuery, useMutation, useQueryClient } from '@tanstack/react-query'
import { motion, AnimatePresence } from 'framer-motion'
import { profilesApi, sessionsApi, createSSE } from '../api'
import { useSessionStore } from '../store'

// ── Sub-components ─────────────────────────────────────────────────────────────

function StepIndicator({ current }) {
  const steps = ['Setup', 'Tags', 'Download', 'Review', 'Export']
  return (
    <div className="flex items-center gap-2 mb-8">
      {steps.map((label, i) => {
        const n = i + 1
        const active = n === current
        const done = n < current
        return (
          <div key={n} className="flex items-center gap-2">
            <div className={`w-7 h-7 rounded-full flex items-center justify-center text-xs font-bold
              ${active ? 'bg-brand-600 text-white' : done ? 'bg-green-600 text-white' : 'bg-gray-700 text-gray-400'}`}>
              {done ? '✓' : n}
            </div>
            <span className={`text-sm ${active ? 'text-gray-100' : 'text-gray-500'}`}>{label}</span>
            {i < steps.length - 1 && <div className="w-6 h-px bg-gray-700" />}
          </div>
        )
      })}
    </div>
  )
}

// ── Example tag list shown in the Direct Tags mode ────────────────────────────

const EXAMPLE_TAGS = `space battle
futuristic cityscape
neon city rain
soldier running
explosion slow motion
dark gothic cathedral
glowing runes
armored vehicle
crowd cheering
aerial drone shot`

const TAG_FORMAT_HINT = `One search phrase per line.
Commas also work: space battle, neon city, explosion
Each line = one media search query sent to your sources.`

// ── Step 1: Setup ──────────────────────────────────────────────────────────────

function StepSetup({ onAnalyzed }) {
  const [mode, setMode] = useState('script')   // 'script' | 'tags'
  const [profileId, setProfileId] = useState('')
  const [script, setScript] = useState('')
  const [tagText, setTagText] = useState('')
  const [itemCount, setItemCount] = useState(10)
  const [analysisMethod, setAnalysisMethod] = useState('algorithmic')
  const [showExample, setShowExample] = useState(false)
  const [allowDuplicateTags, setAllowDuplicateTags] = useState(false)

  const { data: profiles = [] } = useQuery({
    queryKey: ['profiles'],
    queryFn: profilesApi.list,
  })

  const createSession = useMutation({
    mutationFn: sessionsApi.create,
    onSuccess: (data) => onAnalyzed(data),
    onError: (err) => alert(err.userMessage || 'Analysis failed.'),
  })

  const createFromTags = useMutation({
    mutationFn: sessionsApi.createFromTags,
    onSuccess: (data) => onAnalyzed(data),
    onError: (err) => alert(err.userMessage || 'Failed to create session.'),
  })

  const handleProfileChange = (id) => {
    setProfileId(id)
    const p = profiles.find((p) => String(p.id) === id)
    if (p) {
      setItemCount(p.default_item_count)
      // Auto-start adapters for this profile (fire-and-forget — non-blocking,
      // per OQ4: adapter start failures never block session setup)
      if (id) {
        profilesApi.startAdapters(id)
          .then((result) => {
            const started = result.adapters?.filter(a => a.status === 'started') || []
            const failed = result.adapters?.filter(
              a => a.status === 'start_timeout' || a.status === 'launch_failed'
            ) || []
            if (started.length > 0) {
              console.log(`Started adapters: ${started.map(a => a.source).join(', ')}`)
            }
            if (failed.length > 0) {
              console.warn(`Adapter start issues: ${JSON.stringify(failed)}`)
            }
          })
          .catch(() => {
            // Non-fatal — adapters may already be running or user manages them manually
          })
      }
    }
  }

  const parsedTags = tagText
    .split(/[\n,]+/)
    .map((s) => s.trim().toLowerCase())
    .filter(Boolean)

  const handleSubmitTags = () => {
    createFromTags.mutate({
      profile_id: parseInt(profileId),
      tags: parsedTags,
    })
  }

  const isPending = createSession.isPending || createFromTags.isPending

  return (
    <div className="max-w-2xl">
      <h2 className="text-2xl font-bold mb-6">New B-Roll Session</h2>

      <div className="card space-y-5">

        {/* Profile */}
        <div>
          <label className="label">Niche Profile</label>
          <select className="input" value={profileId} onChange={(e) => handleProfileChange(e.target.value)}>
            <option value="">Select a profile…</option>
            {profiles.map((p) => (
              <option key={p.id} value={p.id}>{p.name}</option>
            ))}
          </select>
          {profiles.length === 0 && (
            <p className="text-xs text-yellow-400 mt-1">
              No profiles yet. <a className="underline" href="/profiles">Create one first.</a>
            </p>
          )}
        </div>

        {/* Mode toggle */}
        <div>
          <label className="label">Input Mode</label>
          <div className="flex rounded-lg overflow-hidden border border-gray-700 w-full">
            <button
              className={`flex-1 py-2 text-sm font-medium transition-colors
                ${mode === 'script' ? 'bg-brand-600 text-white' : 'bg-gray-800 text-gray-400 hover:text-gray-200'}`}
              onClick={() => setMode('script')}
            >
              📄 Script Analysis
            </button>
            <button
              className={`flex-1 py-2 text-sm font-medium transition-colors
                ${mode === 'tags' ? 'bg-brand-600 text-white' : 'bg-gray-800 text-gray-400 hover:text-gray-200'}`}
              onClick={() => setMode('tags')}
            >
              🏷️ Direct Tag List
            </button>
          </div>
          <p className="text-xs text-gray-500 mt-1">
            {mode === 'script'
              ? 'Paste your video script — tags are extracted automatically.'
              : 'Enter your search tags directly — skips analysis entirely.'}
          </p>
        </div>

        {/* Script mode */}
        {mode === 'script' && (
          <>
            <div>
              <label className="label">Video Script</label>
              <textarea
                className="input h-48 resize-y font-mono text-sm"
                placeholder="Paste your script here…"
                value={script}
                onChange={(e) => setScript(e.target.value)}
              />
            </div>

            <div className="grid grid-cols-2 gap-4">
              <div>
                <label className="label">Item Count (N)</label>
                <input
                  type="number" className="input" value={itemCount} min={1} max={100}
                  onChange={(e) => setItemCount(parseInt(e.target.value) || 10)}
                />
              </div>
              <div>
                <label className="label">Analysis Method</label>
                <select className="input" value={analysisMethod} onChange={(e) => setAnalysisMethod(e.target.value)}>
                  <option value="algorithmic">Algorithmic (spaCy)</option>
                  <option value="llm">LLM (primary)</option>
                </select>
              </div>
            </div>

            {/* Duplicate Tags Toggle — script mode only */}
            <div className="flex items-center justify-between rounded-lg bg-gray-800/50 border border-gray-700 px-4 py-3">
              <div>
                <p className="text-sm font-medium text-gray-200">Allow Duplicate Tags</p>
                <p className="text-xs text-gray-500 mt-0.5">
                  {allowDuplicateTags
                    ? 'Each occurrence of the same word creates its own tag slot'
                    : 'Repeated words are collapsed into one tag (default)'}
                </p>
              </div>
              <button
                type="button"
                onClick={() => setAllowDuplicateTags(v => !v)}
                className={`relative inline-flex h-6 w-11 flex-shrink-0 rounded-full border-2 border-transparent
                  transition-colors duration-200 focus:outline-none
                  ${allowDuplicateTags ? 'bg-brand-600' : 'bg-gray-600'}`}
                role="switch"
                aria-checked={allowDuplicateTags}
              >
                <span
                  className={`pointer-events-none inline-block h-5 w-5 rounded-full bg-white shadow transform
                    transition duration-200 ease-in-out
                    ${allowDuplicateTags ? 'translate-x-5' : 'translate-x-0'}`}
                />
              </button>
            </div>

            <button
              className="btn-primary w-full"
              disabled={!profileId || !script.trim() || isPending}
              onClick={() => createSession.mutate({
                profile_id: parseInt(profileId),
                script_text: script,
                item_count: itemCount,
                analysis_method: analysisMethod,
                allow_duplicate_tags: allowDuplicateTags,
              })}
            >
              {createSession.isPending ? 'Analyzing…' : 'Analyze Script'}
            </button>
          </>
        )}

        {/* Direct tag list mode */}
        {mode === 'tags' && (
          <>
            <div>
              <div className="flex items-center justify-between mb-1">
                <label className="label mb-0">Search Tag List</label>
                <button
                  className="text-xs text-brand-400 hover:text-brand-300 underline"
                  onClick={() => setShowExample((v) => !v)}
                >
                  {showExample ? 'Hide example' : 'Show example'}
                </button>
              </div>

              {showExample && (
                <div className="mb-3 rounded-lg border border-gray-700 bg-gray-900 p-3 space-y-2">
                  <p className="text-xs text-gray-400 whitespace-pre-line">{TAG_FORMAT_HINT}</p>
                  <div className="border-t border-gray-700 pt-2">
                    <div className="flex items-center justify-between mb-1">
                      <span className="text-xs text-gray-500 font-mono">example_tags.txt</span>
                      <button
                        className="text-xs text-brand-400 hover:text-brand-300"
                        onClick={() => setTagText(EXAMPLE_TAGS)}
                      >
                        Copy to editor ↑
                      </button>
                    </div>
                    <pre className="text-xs text-green-400 font-mono leading-relaxed">{EXAMPLE_TAGS}</pre>
                  </div>
                </div>
              )}

              <textarea
                className="input h-48 resize-y font-mono text-sm"
                placeholder={"space battle\nfuturistic cityscape\nneon city rain\n…one tag per line"}
                value={tagText}
                onChange={(e) => setTagText(e.target.value)}
              />
              {parsedTags.length > 0 && (
                <p className="text-xs text-gray-500 mt-1">
                  {parsedTags.length} tag{parsedTags.length !== 1 ? 's' : ''} detected
                </p>
              )}
            </div>

            <button
              className="btn-primary w-full"
              disabled={!profileId || parsedTags.length === 0 || isPending}
              onClick={handleSubmitTags}
            >
              {createFromTags.isPending ? 'Creating session…' : `Use ${parsedTags.length || 0} Tags →`}
            </button>
          </>
        )}

      </div>
    </div>
  )
}

// ── Step 2: Tag Review ─────────────────────────────────────────────────────────

function StepTags({ session, onProceed }) {
  const [tags, setTags] = useState(session.extracted_tags || [])
  const [newTag, setNewTag] = useState('')
  const store = useSessionStore()

  const needed = session.item_count
  const count = tags.length
  const ready = count > 0

  const updateTags = useMutation({
    mutationFn: (t) => sessionsApi.updateTags(session.session_id, t),
    onSuccess: () => onProceed(tags),
    onError: (err) => alert(err.userMessage || 'Failed to save tags.'),
  })

  const removeTag = (i) => setTags((t) => t.filter((_, idx) => idx !== i))

  const addTag = () => {
    const word = newTag.trim()
    if (!word) return
    setTags((t) => [...t, { word, source: 'manual', occurrence_index: t.length, is_duplicate: false }])
    setNewTag('')
  }

  return (
    <div className="max-w-2xl">
      <h2 className="text-2xl font-bold mb-2">Review Tags</h2>
      <p className="text-gray-400 mb-6">
        {count} / {needed} tags
      </p>

      <div className="card mb-4">
        <div className="flex flex-wrap gap-2 min-h-[60px]">
          {tags.map((t, i) => (
            <span key={i} className="flex items-center gap-1.5 bg-gray-800 border border-gray-700 rounded-full px-3 py-1 text-sm">
              <span className="text-brand-400 text-xs">{t.source?.slice(0, 3).toUpperCase()}</span>
              {t.word}
              <button onClick={() => removeTag(i)} className="text-gray-500 hover:text-red-400 text-xs ml-1">✕</button>
            </span>
          ))}
        </div>

        <div className="flex gap-2 mt-4">
          <input
            className="input flex-1"
            placeholder="Add tag…"
            value={newTag}
            onChange={(e) => setNewTag(e.target.value)}
            onKeyDown={(e) => { if (e.key === 'Enter' || e.key === ',') { e.preventDefault(); addTag() } }}
          />
          <button className="btn-secondary" onClick={addTag}>Add</button>
        </div>
      </div>

      <button
        className="btn-primary w-full"
        disabled={!ready || updateTags.isPending}
        onClick={() => updateTags.mutate(tags)}
      >
        {updateTags.isPending ? 'Saving…' : 'Proceed to Download'}
      </button>
    </div>
  )
}

// ── Step 3: Download Progress ──────────────────────────────────────────────────

function StepDownload({ session, onComplete }) {
  const [progress, setProgress] = useState({
    status: 'downloading',
    completed: 0,
    total: session.item_count,
    current_item_label: '',
  })

  const startDownload = useMutation({
    mutationFn: () => sessionsApi.startDownload(session.session_id),
  })

  useEffect(() => {
    startDownload.mutate()
    const cleanup = createSSE(
      `/api/sessions/${session.session_id}/progress`,
      (data) => {
        setProgress(data)
        if (data.status === 'awaiting_review') onComplete()
        if (data.status === 'error') alert('Download failed.')
      }
    )
    return cleanup
  }, [])

  const pct = progress.total > 0 ? Math.round((progress.completed / progress.total) * 100) : 0

  return (
    <div className="max-w-xl">
      <h2 className="text-2xl font-bold mb-6">Downloading Media</h2>
      <div className="card space-y-4">
        <div className="flex justify-between text-sm text-gray-400">
          <span>Progress</span>
          <span>{progress.completed} / {progress.total}</span>
        </div>
        <div className="w-full bg-gray-800 rounded-full h-3">
          <div className="bg-brand-600 h-3 rounded-full transition-all" style={{ width: `${pct}%` }} />
        </div>
        <p className="text-sm text-brand-300 font-mono min-h-[1.25rem]">
          {progress.current_item_label || (progress.status === 'downloading' ? 'Starting…' : '')}
        </p>
        <p className="text-sm text-gray-500 capitalize">{progress.status.replace('_', ' ')}…</p>
      </div>
    </div>
  )
}

// ── Step 4: Curation ───────────────────────────────────────────────────────────

function ItemCard({ item, session, onToggle }) {
  return (
    <div
      className={`card cursor-pointer transition-all ${item.kept ? 'ring-2 ring-brand-500' : 'opacity-50'}`}
      onClick={() => onToggle(item.file_path)}
    >
      <div className="aspect-video bg-gray-800 rounded-lg mb-3 flex items-center justify-center overflow-hidden">
        {item.media_type === 'image'
          ? <img src={`/api/preview/${session.session_id}/${item.file_path.split(/[\\/]/).pop()}`}
              className="w-full h-full object-cover" alt={item.tag_word} />
          : <div className="text-4xl">🎬</div>}
      </div>
      <p className="text-xs font-medium truncate">{item.tag_word}</p>
      <p className="text-xs text-gray-500">{item.source_name}</p>
      <div className="flex justify-between mt-2">
        <span className="badge bg-gray-700 text-gray-300">{item.media_type}</span>
        <span className={`badge ${item.kept ? 'bg-green-900 text-green-300' : 'bg-red-900 text-red-300'}`}>
          {item.kept ? 'Keep' : 'Drop'}
        </span>
      </div>
    </div>
  )
}

function StepCuration({ session, onProceed }) {
  const store = useSessionStore()
  const [items, setItems] = useState(
    (session.download_results || []).map((r) => ({ ...r, kept: true }))
  )

  const isRedundant = session.redundant_source_download

  const updateCuration = useMutation({
    mutationFn: (its) => sessionsApi.updateCuration(session.session_id, its.map((r) => ({ file_path: r.file_path, kept: r.kept }))),
    onSuccess: () => onProceed(),
    onError: (err) => alert(err.userMessage || 'Curation save failed.'),
  })

  const keptCount = items.filter((r) => r.kept).length

  const toggle = (filePath) => setItems((its) =>
    its.map((r) => r.file_path === filePath ? { ...r, kept: !r.kept } : r)
  )

  // Group items by tag_word for redundant mode display
  const grouped = items.reduce((acc, item) => {
    const key = item.tag_word
    if (!acc[key]) acc[key] = []
    acc[key].push(item)
    return acc
  }, {})

  const missingTagsPanel = session.missing_tags?.length > 0 && (
    <div className="card bg-red-900/20 border-red-800 mb-6">
      <p className="text-red-400 font-medium mb-2">Missing tags ({session.missing_tags.length})</p>
      <ul className="text-sm text-gray-400 list-disc list-inside">
        {session.missing_tags.map((t) => <li key={t}>{t}</li>)}
      </ul>
      <a href={sessionsApi.missingTagsTxt(session.session_id)} className="btn-secondary text-xs mt-3 inline-flex" download>
        Export as .txt
      </a>
    </div>
  )

  if (isRedundant && Object.keys(grouped).length > 0) {
    return (
      <div>
        <div className="flex items-center justify-between mb-6">
          <div>
            <h2 className="text-2xl font-bold">Review Media</h2>
            <p className="text-gray-400 text-sm mt-1">
              {keptCount} of {items.length} items kept · {Object.keys(grouped).length} tags
            </p>
          </div>
          <div className="flex gap-2">
            <button className="btn-secondary text-sm" onClick={() => setItems((its) => its.map((r) => ({ ...r, kept: true })))}>Keep All</button>
            <button className="btn-secondary text-sm" onClick={() => setItems((its) => its.map((r) => ({ ...r, kept: false })))}>Drop All</button>
          </div>
        </div>

        {Object.entries(grouped).map(([tagWord, tagItems]) => (
          <div key={tagWord} className="mb-8">
            <div className="flex items-center gap-2 mb-3">
              <span className="text-xs font-bold text-brand-400 uppercase tracking-wide">TAG</span>
              <h3 className="text-sm font-bold text-gray-200">{tagWord}</h3>
              <span className="text-xs text-gray-500">{tagItems.filter(i => i.kept).length} kept</span>
            </div>
            <div className="grid grid-cols-2 md:grid-cols-3 lg:grid-cols-4 gap-3">
              {tagItems.map((item, i) => (
                <ItemCard key={i} item={item} session={session} onToggle={toggle} />
              ))}
            </div>
          </div>
        ))}

        {missingTagsPanel}

        <button
          className="btn-primary mt-4"
          disabled={keptCount === 0 || updateCuration.isPending}
          onClick={() => updateCuration.mutate(items)}
        >
          {updateCuration.isPending ? 'Saving…' : 'Proceed to Export'}
        </button>
      </div>
    )
  }

  // Non-redundant: flat grid view
  return (
    <div>
      <div className="flex items-center justify-between mb-6">
        <div>
          <h2 className="text-2xl font-bold">Review Media</h2>
          <p className="text-gray-400 text-sm mt-1">{keptCount} of {items.length} items kept</p>
        </div>
        <div className="flex gap-2">
          <button className="btn-secondary text-sm" onClick={() => setItems((its) => its.map((r) => ({ ...r, kept: true })))}>Keep All</button>
          <button className="btn-secondary text-sm" onClick={() => setItems((its) => its.map((r) => ({ ...r, kept: false })))}>Drop All</button>
        </div>
      </div>

      <div className="grid grid-cols-2 md:grid-cols-3 lg:grid-cols-4 gap-4 mb-6">
        {items.map((item, i) => (
          <ItemCard key={i} item={item} session={session} onToggle={toggle} />
        ))}
      </div>

      {missingTagsPanel}

      <button
        className="btn-primary"
        disabled={keptCount === 0 || updateCuration.isPending}
        onClick={() => updateCuration.mutate(items)}
      >
        {updateCuration.isPending ? 'Saving…' : 'Proceed to Export'}
      </button>
    </div>
  )
}

// ── Step 5: Export ─────────────────────────────────────────────────────────────

function StepExport({ session }) {
  return (
    <div className="max-w-xl">
      <h2 className="text-2xl font-bold mb-6">Export</h2>
      <div className="card space-y-5">
        <p className="text-sm text-gray-400">
          {session.download_results?.filter(r => r.kept !== false).length ?? 0} items ready for export.
        </p>
        <div className="space-y-3">
          <a
            href={sessionsApi.exportZip(session.session_id)}
            download
            className="btn-secondary w-full text-center block"
          >
            📦 Download ZIP
            <span className="block text-xs text-gray-500 mt-0.5">Standard format · 001_emperor.jpg</span>
          </a>

          <a
            href={sessionsApi.exportVideoStitch(session.session_id)}
            download
            className="btn-secondary w-full text-center block"
          >
            🎬 Export for VideoStitch
            <span className="block text-xs text-gray-500 mt-0.5">No zero-padding · 1_emperor.jpg</span>
          </a>
        </div>
      </div>
    </div>
  )
}

// ── Main Dashboard ─────────────────────────────────────────────────────────────

export default function Dashboard() {
  const [step, setStep] = useState(1)
  const [session, setSession] = useState(null)

  const handleAnalyzed = (data) => {
    setSession(data)
    setStep(2)
  }

  const handleTagsProceed = (tags) => {
    setSession((s) => ({ ...s, extracted_tags: tags }))
    setStep(3)
  }

  const handleDownloadComplete = async () => {
    const updated = await sessionsApi.get(session.session_id)
    setSession(updated)
    setStep(4)
  }

  const handleCurationProceed = async () => {
    const updated = await sessionsApi.get(session.session_id)
    setSession(updated)
    setStep(5)
  }

  return (
    <div>
      <StepIndicator current={step} />
      <AnimatePresence mode="wait">
        <motion.div
          key={step}
          initial={{ opacity: 0, x: 20 }}
          animate={{ opacity: 1, x: 0 }}
          exit={{ opacity: 0, x: -20 }}
          transition={{ duration: 0.2 }}
        >
          {step === 1 && <StepSetup onAnalyzed={handleAnalyzed} />}
          {step === 2 && session && <StepTags session={session} onProceed={handleTagsProceed} />}
          {step === 3 && session && <StepDownload session={session} onComplete={handleDownloadComplete} />}
          {step === 4 && session && <StepCuration session={session} onProceed={handleCurationProceed} />}
          {step === 5 && session && <StepExport session={session} />}
        </motion.div>
      </AnimatePresence>
    </div>
  )
}
