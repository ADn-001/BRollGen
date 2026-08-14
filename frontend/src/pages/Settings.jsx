/**
 * Settings page — App paths, LLM providers, global word list, analysis method.
 */
import { useState, useRef } from 'react'
import { useQuery, useMutation, useQueryClient } from '@tanstack/react-query'
import { settingsApi } from '../api'

const PROVIDER_TYPES = ['openai', 'anthropic', 'gemini', 'ollama', 'custom']

const defaultProvider = {
  name: '', provider_type: 'openai', api_key: '', base_url: '', model: '', priority: 0, enabled: true,
}

export default function Settings() {
  const qc = useQueryClient()
  const [editingProvider, setEditingProvider] = useState(null)
  const [providerForm, setProviderForm] = useState(defaultProvider)
  const [globalTagInput, setGlobalTagInput] = useState('')
  const [globalTagImportStatus, setGlobalTagImportStatus] = useState(null)
  const globalTagFileRef = useRef(null)

  const { data: settings } = useQuery({ queryKey: ['settings'], queryFn: settingsApi.get })
  const { data: providers = [] } = useQuery({ queryKey: ['llm-providers'], queryFn: settingsApi.listProviders })
  const { data: globalTags = [] } = useQuery({ queryKey: ['global-tags'], queryFn: settingsApi.listGlobalTags })

  const invalidateSettings = () => qc.invalidateQueries({ queryKey: ['settings'] })
  const invalidateProviders = () => qc.invalidateQueries({ queryKey: ['llm-providers'] })
  const invalidateTags = () => qc.invalidateQueries({ queryKey: ['global-tags'] })

  const updateSettings = useMutation({
    mutationFn: settingsApi.update,
    onSuccess: invalidateSettings,
  })

  const createProvider = useMutation({
    mutationFn: settingsApi.createProvider,
    onSuccess: () => { invalidateProviders(); setEditingProvider(null) },
    onError: (err) => alert(err.userMessage || 'Create failed.'),
  })

  const updateProvider = useMutation({
    mutationFn: ({ id, data }) => settingsApi.updateProvider(id, data),
    onSuccess: () => { invalidateProviders(); setEditingProvider(null) },
    onError: (err) => alert(err.userMessage || 'Update failed.'),
  })

  const deleteProvider = useMutation({
    mutationFn: settingsApi.deleteProvider,
    onSuccess: invalidateProviders,
  })

  const addGlobalTag = useMutation({
    mutationFn: (word) => settingsApi.addGlobalTag(word),
    onSuccess: () => { invalidateTags(); setGlobalTagInput('') },
  })

  const deleteGlobalTag = useMutation({
    mutationFn: settingsApi.deleteGlobalTag,
    onSuccess: invalidateTags,
  })

  const handleGlobalTagFileImport = async (e) => {
    const file = e.target.files?.[0]
    if (!file) return
    e.target.value = ''
    try {
      const result = await settingsApi.importGlobalTagsCsv(file)
      invalidateTags()
      setGlobalTagImportStatus({ added: result.added, skipped: result.skipped })
      setTimeout(() => setGlobalTagImportStatus(null), 4000)
    } catch (err) {
      alert(err.userMessage || 'Import failed.')
    }
  }

  if (!settings) return <div className="text-gray-400">Loading…</div>

  const openNewProvider = () => { setProviderForm(defaultProvider); setEditingProvider('new') }
  const openEditProvider = (p) => { setProviderForm({ ...p }); setEditingProvider(p) }
  const saveProvider = () => {
    if (editingProvider === 'new') createProvider.mutate(providerForm)
    else updateProvider.mutate({ id: editingProvider.id, data: providerForm })
  }

  const pf = (key) => ({ value: providerForm[key] ?? '', onChange: (e) => setProviderForm((f) => ({ ...f, [key]: e.target.value })) })

  return (
    <div className="max-w-2xl space-y-8">
      <h2 className="text-2xl font-bold">Settings</h2>

      {/* Analysis */}
      <div className="card space-y-4">
        <h3 className="font-semibold text-gray-300">Analysis</h3>

        <div>
          <label className="label">Analysis Method</label>
          <select className="input" value={settings.analysis_method}
            onChange={(e) => updateSettings.mutate({ analysis_method: e.target.value })}>
            <option value="algorithmic">Algorithmic (spaCy primary — LLM never called)</option>
            <option value="llm">LLM primary (spaCy is final fallback)</option>
          </select>
        </div>
      </div>

      {/* LLM Providers */}
      <div className="card space-y-4">
        <div className="flex items-center justify-between">
          <h3 className="font-semibold text-gray-300">LLM Providers</h3>
          <button className="btn-secondary text-sm" onClick={openNewProvider}>+ Add</button>
        </div>

        {editingProvider && (
          <div className="bg-gray-800 rounded-xl p-4 space-y-3">
            <div className="grid grid-cols-2 gap-3">
              <div><label className="label">Label</label><input className="input" {...pf('name')} /></div>
              <div>
                <label className="label">Provider Type</label>
                <select className="input" {...pf('provider_type')}>
                  {PROVIDER_TYPES.map((t) => <option key={t}>{t}</option>)}
                </select>
              </div>
            </div>
            <div><label className="label">API Key</label><input type="password" className="input" {...pf('api_key')} /></div>
            {['ollama', 'custom'].includes(providerForm.provider_type) && (
              <div><label className="label">Base URL</label><input className="input" {...pf('base_url')} placeholder="http://localhost:11434" /></div>
            )}
            <div className="grid grid-cols-2 gap-3">
              <div><label className="label">Model</label><input className="input" {...pf('model')} placeholder="gpt-4o-mini" /></div>
              <div><label className="label">Priority (lower = first)</label><input type="number" className="input"
                value={providerForm.priority} onChange={(e) => setProviderForm((f) => ({ ...f, priority: parseInt(e.target.value) || 0 }))} /></div>
            </div>
            <label className="flex items-center gap-2 cursor-pointer">
              <input type="checkbox" checked={providerForm.enabled} onChange={(e) => setProviderForm((f) => ({ ...f, enabled: e.target.checked }))} />
              <span className="text-sm">Enabled</span>
            </label>
            <div className="flex gap-2">
              <button className="btn-secondary flex-1 text-sm" onClick={() => setEditingProvider(null)}>Cancel</button>
              <button className="btn-primary flex-1 text-sm" onClick={saveProvider} disabled={!providerForm.name}>Save</button>
            </div>
          </div>
        )}

        {providers.length === 0 && !editingProvider && <p className="text-sm text-gray-500">No providers configured.</p>}
        <div className="space-y-2">
          {providers.map((p) => (
            <div key={p.id} className="flex items-center justify-between bg-gray-800 rounded-lg px-3 py-2">
              <div className="flex items-center gap-2">
                <div className={`w-1.5 h-1.5 rounded-full ${p.enabled ? 'bg-green-400' : 'bg-gray-600'}`} />
                <span className="text-sm font-medium">{p.name}</span>
                <span className="badge bg-gray-700 text-gray-400 text-xs">{p.provider_type}</span>
                <span className="text-xs text-gray-500">priority {p.priority}</span>
              </div>
              <div className="flex gap-1">
                <button className="btn-secondary text-xs py-1 px-2" onClick={() => openEditProvider(p)}>Edit</button>
                <button className="btn-danger text-xs py-1 px-2" onClick={() => deleteProvider.mutate(p.id)}>✕</button>
              </div>
            </div>
          ))}
        </div>
      </div>

      {/* Global Word List */}
      <div className="card space-y-4">
        <div className="flex items-center justify-between">
          <h3 className="font-semibold text-gray-300">Global Word List</h3>
          <button className="btn-secondary text-xs px-2 py-1" onClick={() => globalTagFileRef.current?.click()}>
            Import CSV / TXT
          </button>
        </div>
        <input ref={globalTagFileRef} type="file" accept=".csv,.txt" className="hidden" onChange={handleGlobalTagFileImport} />
        {globalTagImportStatus && (
          <p className="text-xs text-green-400">
            Imported: {globalTagImportStatus.added} added, {globalTagImportStatus.skipped} skipped.
          </p>
        )}
        <div className="flex flex-wrap gap-2">
          {globalTags.map((t) => (
            <span key={t.id} className="flex items-center gap-1.5 bg-gray-800 border border-gray-700 rounded-full px-3 py-1 text-sm">
              {t.word}
              <button onClick={() => deleteGlobalTag.mutate(t.id)} className="text-gray-500 hover:text-red-400 text-xs">✕</button>
            </span>
          ))}
        </div>
        <div className="flex gap-2">
          <input className="input flex-1" placeholder="Add word…" value={globalTagInput}
            onChange={(e) => setGlobalTagInput(e.target.value)}
            onKeyDown={(e) => { if (e.key === 'Enter' || e.key === ',') { e.preventDefault(); addGlobalTag.mutate(globalTagInput.trim()) }}} />
          <button className="btn-secondary" onClick={() => addGlobalTag.mutate(globalTagInput.trim())}>Add</button>
        </div>
      </div>
    </div>
  )
}
