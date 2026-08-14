/**
 * Sources page — configure all media source types.
 */
import { useState } from 'react'
import { useQuery, useMutation, useQueryClient } from '@tanstack/react-query'
import { sourcesApi } from '../api'
import { Dropzone } from '../components/Dropzone'

const SOURCE_TYPES = ['pexels', 'pixabay', 'unsplash', 'serp_scraper', 'custom_adapter', 'local_folder']

const TYPE_LABELS = {
  pexels: 'Pexels', pixabay: 'Pixabay', unsplash: 'Unsplash',
  serp_scraper: 'SerpAPI / Playwright', custom_adapter: 'Custom Adapter', local_folder: 'Local Folder',
}

const TYPE_BADGE_COLOR = {
  pexels: 'bg-green-900 text-green-300', pixabay: 'bg-yellow-900 text-yellow-300',
  unsplash: 'bg-blue-900 text-blue-300', serp_scraper: 'bg-purple-900 text-purple-300',
  custom_adapter: 'bg-orange-900 text-orange-300', local_folder: 'bg-gray-700 text-gray-300',
}

const defaultForm = { name: '', type: 'pexels', config: {}, enabled: true, request_delay_seconds: null }

// ── Local folder upload panel ──────────────────────────────────────────────────

function LocalFolderUploadPanel({ sourceId, onFolderPathChange }) {
  const qc = useQueryClient()
  const [status, setStatus] = useState(null)  // {ok, message}

  const { data: folderInfo } = useQuery({
    queryKey: ['source-folder-status', sourceId],
    queryFn: () => sourcesApi.folderStatus(sourceId),
    enabled: !!sourceId,
  })

  const upload = useMutation({
    mutationFn: (files) => sourcesApi.uploadFolder(sourceId, files),
    onSuccess: (result) => {
      qc.invalidateQueries({ queryKey: ['source-folder-status', sourceId] })
      // The upload endpoint sets config.folder_path server-side — sync it
      // into this form's local state too, or a later Save (e.g. after just
      // editing Enabled Extensions) would overwrite it with the stale
      // pre-upload config and silently break the library for this source.
      onFolderPathChange?.(result.folder_path)
      const skippedNote = result.skipped?.length ? ` (${result.skipped.length} skipped)` : ''
      setStatus({ ok: true, message: `Uploaded ${result.uploaded} file(s)${skippedNote}. Library now has ${result.total_files_in_library} file(s).` })
    },
    onError: (err) => setStatus({ ok: false, message: err.userMessage || 'Upload failed.' }),
  })

  const clear = useMutation({
    mutationFn: () => sourcesApi.clearFolder(sourceId),
    onSuccess: () => {
      qc.invalidateQueries({ queryKey: ['source-folder-status', sourceId] })
      setStatus({ ok: true, message: 'Library cleared.' })
    },
    onError: (err) => setStatus({ ok: false, message: err.userMessage || 'Clear failed.' }),
  })

  return (
    <div className="space-y-3">
      <label className="label mb-0">Media Library</label>
      <Dropzone
        label="Drag and drop a folder (or files) here"
        hint="Files are stored flat inside the app — subfolder names aren't kept, matching how this source is searched. Re-uploading adds to the existing library; same-name files are kept as separate copies, not overwritten."
        directory
        disabled={!sourceId || upload.isPending}
        disabledHint={!sourceId ? 'Save this source first (enter a Name above and click Save) — the upload area unlocks once it has an ID.' : undefined}
        onFiles={(files) => upload.mutate(files)}
      />
      {upload.isPending && <p className="text-xs text-gray-400">Uploading…</p>}
      {status && (
        <p className={`text-xs ${status.ok ? 'text-green-400' : 'text-red-400'}`}>{status.message}</p>
      )}
      {sourceId && (
        <div className="flex items-center justify-between text-xs text-gray-500">
          <span>{folderInfo?.file_count ?? 0} file(s) currently in this source's library</span>
          {folderInfo?.file_count > 0 && (
            <button
              type="button"
              className="text-red-400 hover:text-red-300"
              onClick={() => { if (confirm('Remove every uploaded file for this source?')) clear.mutate() }}
              disabled={clear.isPending}
            >
              {clear.isPending ? 'Clearing…' : 'Clear library'}
            </button>
          )}
        </div>
      )}
    </div>
  )
}

// ── Custom adapter script upload panel ─────────────────────────────────────────

function AdapterScriptUploadPanel({ sourceId, currentPath, onUploaded }) {
  const [status, setStatus] = useState(null)

  const upload = useMutation({
    mutationFn: (files) => sourcesApi.uploadAdapterScript(sourceId, files[0]),
    onSuccess: (result) => {
      onUploaded(result.adapter_script_path)
      setStatus({ ok: true, message: `Uploaded. Path set to: ${result.adapter_script_path}` })
    },
    onError: (err) => setStatus({ ok: false, message: err.userMessage || 'Upload failed.' }),
  })

  return (
    <div className="space-y-2">
      <p className="text-xs text-gray-500">
        {currentPath ? `Currently: ${currentPath}` : 'No script uploaded yet — you can also type an existing server path above instead.'}
      </p>
      <Dropzone
        label="Drag and drop your adapter's .py file here"
        accept=".py"
        disabled={!sourceId || upload.isPending}
        disabledHint={!sourceId ? 'Save this source first (enter a Name above and click Save) — upload unlocks once it has an ID.' : undefined}
        onFiles={(files) => upload.mutate(files)}
      />
      {upload.isPending && <p className="text-xs text-gray-400">Uploading…</p>}
      {status && (
        <p className={`text-xs ${status.ok ? 'text-green-400' : 'text-red-400'}`}>{status.message}</p>
      )}
    </div>
  )
}

// ── Per-type config fields ──────────────────────────────────────────────────────

function ConfigFields({ type, config, sourceId, onChange }) {
  const set = (key, val) => onChange({ ...config, [key]: val })
  const input = (key, label, placeholder = '', isPassword = false) => (
    <div>
      <label className="label">{label}</label>
      <input type={isPassword ? 'password' : 'text'} className="input" value={config[key] || ''}
        onChange={(e) => set(key, e.target.value)} placeholder={placeholder} />
    </div>
  )

  if (type === 'pexels') return input('api_key', 'API Key', 'px-…', true)
  if (type === 'pixabay') return input('api_key', 'API Key', 'Your Pixabay key', true)
  if (type === 'unsplash') return input('access_key', 'Access Key', 'Your Unsplash access key', true)
  if (type === 'serp_scraper') return (
    <div className="space-y-3">
      {input('serpapi_key', 'SerpAPI Key (optional — leave blank to use Playwright)', '', true)}
      <div>
        <label className="label">Max results per query</label>
        <input type="number" className="input" value={config.max_results || 10}
          onChange={(e) => set('max_results', parseInt(e.target.value))} min={1} max={50} />
      </div>
    </div>
  )
  if (type === 'custom_adapter') return (
    <div className="space-y-3">
      {input('adapter_url', 'Adapter Base URL', 'http://localhost:8080')}
      {input('auth_token', 'Auth Token (optional)', '', true)}
      <div>
        <label className="label">Adapter Script Path (for auto-launch)</label>
        <input className="input" value={config.adapter_script_path || ''}
          onChange={(e) => set('adapter_script_path', e.target.value)}
          placeholder="D:\yt_vids\automation ecosystem\BRollGen\CustomAdapters\wh40k\40k_adapter.py" />
        <p className="text-xs text-gray-500 mt-1">
          Full path to the adapter .py file, or upload it below. The app launches it when this source's profile is selected.
        </p>
      </div>
      <AdapterScriptUploadPanel
        sourceId={sourceId}
        currentPath={config.adapter_script_path}
        onUploaded={(path) => set('adapter_script_path', path)}
      />
    </div>
  )
  if (type === 'local_folder') return (
    <div className="space-y-3">
      <LocalFolderUploadPanel sourceId={sourceId} onFolderPathChange={(path) => set('folder_path', path)} />
      <div>
        <label className="label">Enabled Extensions (comma-separated, leave blank for all)</label>
        <input className="input" value={(config.enabled_extensions || []).join(', ')}
          onChange={(e) => set('enabled_extensions', e.target.value.split(',').map(s => s.trim()).filter(Boolean))}
          placeholder=".jpg, .png, .mp4" />
      </div>
    </div>
  )
  return null
}

export default function Sources() {
  const qc = useQueryClient()
  const [editing, setEditing] = useState(null)
  const [form, setForm] = useState(defaultForm)
  const [testResult, setTestResult] = useState(null)

  const { data: sources = [] } = useQuery({ queryKey: ['sources'], queryFn: sourcesApi.list })

  const invalidate = () => qc.invalidateQueries({ queryKey: ['sources'] })

  const createSource = useMutation({
    mutationFn: sourcesApi.create,
    onSuccess: (created) => {
      invalidate()
      // Stay in the editor (switched to edit-mode for the new id) instead of
      // closing, so the upload areas above — which need a saved source id —
      // unlock immediately without the user having to re-open the source.
      setForm({ ...created })
      setEditing(created)
    },
    onError: (err) => alert(err.userMessage || 'Create failed.'),
  })

  const updateSource = useMutation({
    mutationFn: ({ id, data }) => sourcesApi.update(id, data),
    onSuccess: () => { invalidate(); setEditing(null) },
    onError: (err) => alert(err.userMessage || 'Update failed.'),
  })

  const deleteSource = useMutation({
    mutationFn: sourcesApi.delete,
    onSuccess: invalidate,
    onError: (err) => alert(err.userMessage || 'Delete failed.'),
  })

  const testSource = useMutation({
    mutationFn: sourcesApi.test,
    onSuccess: (data) => setTestResult(data),
    onError: (err) => setTestResult({ ok: false, detail: err.userMessage }),
  })

  const openNew = () => { setForm(defaultForm); setTestResult(null); setEditing('new') }
  const openEdit = (s) => {
    setForm({
      name: s.name,
      type: s.type,
      config: s.config || {},
      enabled: s.enabled,
      request_delay_seconds: s.request_delay_seconds ?? null,
    })
    setTestResult(null)
    setEditing(s)
  }

  const handleSave = () => {
    if (editing === 'new') createSource.mutate(form)
    else updateSource.mutate({ id: editing.id, data: form })
  }

  const currentSourceId = editing && editing !== 'new' ? editing.id : null

  if (editing) {
    return (
      <div className="max-w-xl">
        <div className="flex items-center gap-3 mb-6">
          <button className="btn-secondary text-sm" onClick={() => setEditing(null)}>← Back</button>
          <h2 className="text-2xl font-bold">{editing === 'new' ? 'Add Source' : 'Edit Source'}</h2>
        </div>

        <div className="card space-y-4">
          <div>
            <label className="label">Name</label>
            <input className="input" value={form.name} onChange={(e) => setForm((f) => ({ ...f, name: e.target.value }))} placeholder="My Pexels Source" />
          </div>
          <div>
            <label className="label">Type</label>
            <select className="input" value={form.type} onChange={(e) => setForm((f) => ({ ...f, type: e.target.value, config: {} }))}>
              {SOURCE_TYPES.map((t) => <option key={t} value={t}>{TYPE_LABELS[t]}</option>)}
            </select>
          </div>

          <ConfigFields type={form.type} config={form.config} sourceId={currentSourceId}
            onChange={(c) => setForm((f) => ({ ...f, config: c }))} />

          {/* Rate-limit delay — not shown for local_folder (no network) */}
          {form.type !== 'local_folder' && (
            <div>
              <label className="label">Request Delay (seconds)</label>
              <input
                type="number"
                className="input"
                min={0}
                step={0.5}
                placeholder="Random 2–30 s (default)"
                value={form.request_delay_seconds ?? ''}
                onChange={(e) => {
                  const raw = e.target.value
                  setForm((f) => ({
                    ...f,
                    request_delay_seconds: raw === '' ? null : parseFloat(raw),
                  }))
                }}
              />
              <p className="text-xs text-gray-500 mt-1">
                Minimum wait between consecutive download requests to this source.
                Leave blank for a random 2–30 s delay · enter <code className="text-gray-400">0</code> to disable.
              </p>
            </div>
          )}

          <label className="flex items-center gap-3 cursor-pointer">
            <input type="checkbox" className="w-4 h-4 rounded" checked={form.enabled} onChange={(e) => setForm((f) => ({ ...f, enabled: e.target.checked }))} />
            <span className="text-sm">Enabled</span>
          </label>

          {editing !== 'new' && (
            <div>
              <button className="btn-secondary text-sm"
                onClick={() => testSource.mutate(editing.id)}
                disabled={testSource.isPending}>
                {testSource.isPending ? 'Testing…' : 'Test Connection'}
              </button>
              {testResult && (
                <div className={`mt-2 text-sm p-3 rounded-lg ${testResult.ok ? 'bg-green-900/30 text-green-300' : 'bg-red-900/30 text-red-300'}`}>
                  {testResult.ok ? '✓ ' : '✗ '}{typeof testResult.detail === 'object' ? JSON.stringify(testResult.detail) : testResult.detail}
                </div>
              )}
            </div>
          )}

          <div className="flex gap-3">
            <button className="btn-secondary flex-1" onClick={() => setEditing(null)}>
              {editing !== 'new' ? 'Done' : 'Cancel'}
            </button>
            <button className="btn-primary flex-1" disabled={!form.name} onClick={handleSave}>
              {(createSource.isPending || updateSource.isPending) ? 'Saving…' : 'Save'}
            </button>
          </div>
        </div>
      </div>
    )
  }

  return (
    <div>
      <div className="flex items-center justify-between mb-6">
        <h2 className="text-2xl font-bold">Media Sources</h2>
        <button className="btn-primary" onClick={openNew}>+ Add Source</button>
      </div>

      {sources.length === 0 && (
        <div className="card text-center py-12">
          <p className="text-gray-400 mb-4">No sources configured.</p>
          <button className="btn-primary" onClick={openNew}>Add Source</button>
        </div>
      )}

      <div className="space-y-3">
        {sources.map((s) => (
          <div key={s.id} className="card flex items-center justify-between">
            <div className="flex items-center gap-3">
              <div className={`w-2 h-2 rounded-full ${s.enabled ? 'bg-green-400' : 'bg-gray-600'}`} />
              <div>
                <span className="font-medium">{s.name}</span>
                <span className={`ml-2 badge ${TYPE_BADGE_COLOR[s.type] || 'bg-gray-700 text-gray-300'}`}>{TYPE_LABELS[s.type]}</span>
                {s.type !== 'local_folder' && (
                  <span className="ml-2 text-xs text-gray-500">
                    {s.request_delay_seconds === null || s.request_delay_seconds === undefined
                      ? '⏱ random 2–30s'
                      : s.request_delay_seconds === 0
                        ? '⚡ no delay'
                        : `⏱ ${s.request_delay_seconds}s`}
                  </span>
                )}
              </div>
            </div>
            <div className="flex gap-2">
              <button className="btn-secondary text-sm" onClick={() => openEdit(s)}>Edit</button>
              <button className="btn-danger text-sm" onClick={() => { if (confirm('Delete source?')) deleteSource.mutate(s.id) }}>Delete</button>
            </div>
          </div>
        ))}
      </div>
    </div>
  )
}
