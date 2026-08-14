/**
 * Profiles page — list, create, edit, delete niche profiles.
 * Full editor with tags panel and source assignment.
 */
import { useState, useRef } from 'react'
import { useQuery, useMutation, useQueryClient } from '@tanstack/react-query'
import { profilesApi, sourcesApi } from '../api'

const defaultForm = {
  name: '', description: '',
  multi_item_per_tag: true, dedupe_repeat_tags: true, redundant_source_download: false,
  default_item_count: 10,
  llm_enabled: true, llm_provider_id: null,
}

export default function Profiles() {
  const qc = useQueryClient()
  const [editing, setEditing] = useState(null)   // null = list view, object = editor
  const [form, setForm] = useState(defaultForm)
  const [tagInput, setTagInput] = useState('')
  const [profileTags, setProfileTags] = useState([])
  const [selectedSourceIds, setSelectedSourceIds] = useState([])
  const [tagImportStatus, setTagImportStatus] = useState(null)  // null | {added,skipped}
  const tagFileRef = useRef(null)

  const { data: profiles = [] } = useQuery({ queryKey: ['profiles'], queryFn: profilesApi.list })
  const { data: sources = [] } = useQuery({ queryKey: ['sources'], queryFn: sourcesApi.list })

  const invalidate = () => {
    qc.invalidateQueries({ queryKey: ['profiles'] })
  }

  const createProfile = useMutation({
    mutationFn: profilesApi.create,
    onSuccess: async (p) => {
      // Save tags
      for (const tag of profileTags) await profilesApi.addTag(p.id, tag.word)
      // Save source links
      await profilesApi.setSources(p.id, selectedSourceIds)
      invalidate()
      setEditing(null)
    },
    onError: (err) => alert(err.userMessage || 'Create failed.'),
  })

  const updateProfile = useMutation({
    mutationFn: ({ id, data }) => profilesApi.update(id, data),
    onSuccess: async (p) => {
      // Sync source links
      await profilesApi.setSources(p.id, selectedSourceIds)
      invalidate()
      setEditing(null)
    },
    onError: (err) => alert(err.userMessage || 'Update failed.'),
  })

  const deleteProfile = useMutation({
    mutationFn: profilesApi.delete,
    onSuccess: invalidate,
    onError: (err) => alert(err.userMessage || 'Delete failed.'),
  })

  const openNew = () => {
    setForm(defaultForm)
    setProfileTags([])
    setSelectedSourceIds([])
    setEditing('new')
  }

  const openEdit = async (p) => {
    setForm({ ...p })
    const [tags, links] = await Promise.all([
      profilesApi.listTags(p.id),
      profilesApi.listSources(p.id),
    ])
    setProfileTags(tags)
    setSelectedSourceIds(links.map((l) => l.source_id))
    setEditing(p)
  }

  const handleSave = () => {
    if (editing === 'new') {
      createProfile.mutate(form)
    } else {
      updateProfile.mutate({ id: editing.id, data: form })
    }
  }

  const addTagLocally = () => {
    const word = tagInput.trim().toLowerCase()
    if (!word || profileTags.find((t) => t.word === word)) return
    setProfileTags((ts) => [...ts, { word }])
    setTagInput('')
  }

  const removeTagLocally = (word) => setProfileTags((ts) => ts.filter((t) => t.word !== word))

  const handleTagFileImport = async (e) => {
    const file = e.target.files?.[0]
    if (!file) return
    e.target.value = ''  // reset so same file can be re-selected

    if (editing !== 'new') {
      // Existing profile: let the backend do the dedup + insert
      try {
        const result = await profilesApi.importTagsCsv(editing.id, file)
        const freshTags = await profilesApi.listTags(editing.id)
        setProfileTags(freshTags)
        setTagImportStatus({ added: result.added, skipped: result.skipped })
        setTimeout(() => setTagImportStatus(null), 4000)
      } catch (err) {
        alert(err.userMessage || 'Import failed.')
      }
    } else {
      // New profile (not yet saved): parse client-side, add to local state
      const text = await file.text()
      const lines = text.split(/\r?\n/)
      const hasComma = lines.some((l) => l.includes(','))
      const words = lines.flatMap((line) => {
        const cell = hasComma ? line.split(',')[0] : line
        const w = cell.trim().toLowerCase()
        return w ? [w] : []
      })
      let added = 0, skipped = 0
      setProfileTags((prev) => {
        const existing = new Set(prev.map((t) => t.word))
        const toAdd = []
        for (const w of words) {
          if (existing.has(w)) { skipped++; continue }
          existing.add(w)
          toAdd.push({ word: w })
          added++
        }
        return [...prev, ...toAdd]
      })
      setTagImportStatus({ added, skipped })
      setTimeout(() => setTagImportStatus(null), 4000)
    }
  }

  const toggleSource = (id) => setSelectedSourceIds((ids) =>
    ids.includes(id) ? ids.filter((i) => i !== id) : [...ids, id]
  )

  const f = (key) => ({ value: form[key], onChange: (e) => setForm((p) => ({ ...p, [key]: e.target.value })) })
  const fb = (key) => ({ checked: form[key], onChange: (e) => setForm((p) => ({ ...p, [key]: e.target.checked })) })

  if (editing) {
    return (
      <div className="max-w-2xl">
        <div className="flex items-center gap-3 mb-6">
          <button className="btn-secondary text-sm" onClick={() => setEditing(null)}>← Back</button>
          <h2 className="text-2xl font-bold">{editing === 'new' ? 'New Profile' : 'Edit Profile'}</h2>
        </div>

        <div className="space-y-6">
          <div className="card space-y-4">
            <h3 className="font-semibold text-gray-300">Basic Info</h3>
            <div>
              <label className="label">Name *</label>
              <input className="input" {...f('name')} placeholder="e.g. Warhammer 40K" />
            </div>
            <div>
              <label className="label">Description</label>
              <textarea className="input h-20 resize-none" {...f('description')} placeholder="Optional…" />
            </div>
            <div>
              <label className="label">Default Item Count (N)</label>
              <input type="number" className="input" min={1} max={100}
                value={form.default_item_count}
                onChange={(e) => setForm((p) => ({ ...p, default_item_count: parseInt(e.target.value) || 10 }))} />
            </div>
          </div>

          <div className="card space-y-3">
            <h3 className="font-semibold text-gray-300">Behaviour</h3>
            <label className="flex items-center gap-3 cursor-pointer">
              <input type="checkbox" className="w-4 h-4 rounded" {...fb('multi_item_per_tag')} />
              <span className="text-sm">Multi-item per tag (best quality per source)</span>
            </label>
            <label className="flex items-center gap-3 cursor-pointer">
              <input type="checkbox" className="w-4 h-4 rounded" {...fb('dedupe_repeat_tags')} />
              <span className="text-sm">Deduplicate repeated tags</span>
            </label>
            <label className="flex items-start gap-3 cursor-pointer">
              <input type="checkbox" className="w-4 h-4 rounded mt-0.5" {...fb('redundant_source_download')} />
              <span>
                <span className="text-sm block">Redundant Source Download</span>
                <span className="text-xs text-gray-500 block mt-0.5">
                  Download the best result from each source per tag. Shows all variants in review
                  so you can pick the best or keep extras as additional B-roll.
                </span>
              </span>
            </label>
            <label className="flex items-center gap-3 cursor-pointer">
              <input type="checkbox" className="w-4 h-4 rounded" {...fb('llm_enabled')} />
              <span className="text-sm">Enable LLM tag extraction</span>
            </label>
          </div>

          <div className="card space-y-3">
            <div className="flex items-center justify-between">
              <h3 className="font-semibold text-gray-300">Profile Tags</h3>
              <button className="btn-secondary text-xs px-2 py-1" onClick={() => tagFileRef.current?.click()}>
                Import CSV / TXT
              </button>
            </div>
            <input ref={tagFileRef} type="file" accept=".csv,.txt" className="hidden" onChange={handleTagFileImport} />
            {tagImportStatus && (
              <p className="text-xs text-green-400">
                Imported: {tagImportStatus.added} added, {tagImportStatus.skipped} skipped.
              </p>
            )}
            <div className="flex flex-wrap gap-2">
              {profileTags.map((t) => (
                <span key={t.word} className="flex items-center gap-1.5 bg-brand-600/20 border border-brand-500/30 rounded-full px-3 py-1 text-sm text-brand-300">
                  {t.word}
                  <button onClick={() => removeTagLocally(t.word)} className="text-brand-400 hover:text-red-400">✕</button>
                </span>
              ))}
            </div>
            <div className="flex gap-2">
              <input className="input flex-1" placeholder="Add tag word…" value={tagInput}
                onChange={(e) => setTagInput(e.target.value)}
                onKeyDown={(e) => { if (e.key === 'Enter' || e.key === ',') { e.preventDefault(); addTagLocally() }}} />
              <button className="btn-secondary" onClick={addTagLocally}>Add</button>
            </div>
          </div>

          <div className="card space-y-3">
            <h3 className="font-semibold text-gray-300">Sources</h3>
            {sources.length === 0 && <p className="text-sm text-gray-500">No sources configured.</p>}
            {sources.map((s) => (
              <label key={s.id} className="flex items-center gap-3 cursor-pointer">
                <input type="checkbox" className="w-4 h-4 rounded"
                  checked={selectedSourceIds.includes(s.id)}
                  onChange={() => toggleSource(s.id)} />
                <span className="text-sm">{s.name}</span>
                <span className="badge bg-gray-700 text-gray-400">{s.type}</span>
              </label>
            ))}
          </div>

          <div className="flex gap-3">
            <button className="btn-secondary flex-1" onClick={() => setEditing(null)}>Cancel</button>
            <button className="btn-primary flex-1" disabled={!form.name} onClick={handleSave}>
              {(createProfile.isPending || updateProfile.isPending) ? 'Saving…' : 'Save Profile'}
            </button>
          </div>
        </div>
      </div>
    )
  }

  return (
    <div>
      <div className="flex items-center justify-between mb-6">
        <h2 className="text-2xl font-bold">Profiles</h2>
        <button className="btn-primary" onClick={openNew}>+ New Profile</button>
      </div>

      {profiles.length === 0 && (
        <div className="card text-center py-12">
          <p className="text-gray-400 mb-4">No profiles yet. Create one to get started.</p>
          <button className="btn-primary" onClick={openNew}>Create Profile</button>
        </div>
      )}

      <div className="grid grid-cols-1 md:grid-cols-2 gap-4">
        {profiles.map((p) => (
          <div key={p.id} className="card hover:border-gray-700 transition-colors">
            <div className="flex items-start justify-between mb-2">
              <h3 className="font-semibold">{p.name}</h3>
            </div>
            {p.description && <p className="text-sm text-gray-400 mb-3">{p.description}</p>}
            <div className="flex gap-4 text-xs text-gray-500 mb-4">
              <span>📌 {p.tag_count} tags</span>
              <span>🔌 {p.source_count} sources</span>
              <span>N={p.default_item_count}</span>
            </div>
            <div className="flex gap-2">
              <button className="btn-secondary text-sm flex-1" onClick={() => openEdit(p)}>Edit</button>
              <button className="btn-danger text-sm" onClick={() => { if (confirm('Delete profile?')) deleteProfile.mutate(p.id) }}>Delete</button>
            </div>
          </div>
        ))}
      </div>
    </div>
  )
}
