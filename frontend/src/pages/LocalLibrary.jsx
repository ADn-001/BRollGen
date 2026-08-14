/**
 * Local Library tagger page.
 *
 * Layout, top to bottom:
 *   1. Source picker — choose which uploaded local_folder library to browse.
 *   2. Central preview — the selected file's image/gif or a playable video.
 *   3. Controls directly under the preview — ← / → to cycle files, the tag
 *      editor (chips + a Niche Profile picker whose tag buttons quick-add/
 *      remove tags, plus a free-text fallback + quality grade), a Save
 *      button, and a Delete button for the currently selected file.
 *   4. A flex-wrap grid of every file in the library as small cards
 *      (thumbnail + filename + a small delete ✕) — click a card to load it
 *      into the preview above.
 *   5. An upload area at the very bottom to add more files to this library.
 */
import { useEffect, useState } from 'react'
import { useQuery, useMutation, useQueryClient } from '@tanstack/react-query'
import { libraryApi, profilesApi, settingsApi, sourcesApi } from '../api'
import { Dropzone } from '../components/Dropzone'

const QUALITY_GRADES = ['', 'U', 'H', 'M', 'L']

async function fetchAllLibraryFiles(sourceId) {
  const pageSize = 200
  let page = 1
  let all = []
  while (true) {
    const res = await libraryApi.listFiles(sourceId, page, pageSize)
    all = all.concat(res.files)
    if (all.length >= res.total || res.files.length === 0) break
    page += 1
  }
  return all
}

function Thumbnail({ file, sourceId }) {
  if (file.media_type === 'video') {
    return <div className="w-full h-full flex items-center justify-center text-3xl bg-gray-800">🎬</div>
  }
  return (
    <img
      src={libraryApi.previewUrl(sourceId, file.filename)}
      className="w-full h-full object-cover"
      alt={file.filename}
      loading="lazy"
    />
  )
}

export default function LocalLibrary() {
  const qc = useQueryClient()
  const [selectedSourceId, setSelectedSourceId] = useState('')
  const [selectedIndex, setSelectedIndex] = useState(0)
  const [tags, setTags] = useState([])
  const [tagInput, setTagInput] = useState('')
  const [quality, setQuality] = useState('')
  const [newWordModal, setNewWordModal] = useState(null)
  const [uploadStatus, setUploadStatus] = useState(null)
  const [selectedProfileId, setSelectedProfileId] = useState('')

  const { data: sources = [] } = useQuery({ queryKey: ['library-sources'], queryFn: libraryApi.listSources })
  const { data: files = [], isLoading: filesLoading, isError: filesErrored, error: filesError } = useQuery({
    queryKey: ['library-all-files', selectedSourceId],
    queryFn: () => fetchAllLibraryFiles(selectedSourceId),
    enabled: !!selectedSourceId,
  })
  const { data: globalTags = [] } = useQuery({ queryKey: ['global-tags'], queryFn: settingsApi.listGlobalTags })
  // Niche Profile picker for the tag buttons — lists every profile, and (once
  // one's picked) that profile's own tag words, which render as quick-add/
  // remove buttons below it.
  const { data: profiles = [] } = useQuery({ queryKey: ['profiles-for-tagger'], queryFn: profilesApi.list })
  const { data: profileTags = [] } = useQuery({
    queryKey: ['profile-tags-for-tagger', selectedProfileId],
    queryFn: () => profilesApi.listTags(selectedProfileId),
    enabled: !!selectedProfileId,
  })

  const selectedFile = files[selectedIndex] || null

  useEffect(() => {
    if (selectedFile) {
      setTags(selectedFile.tags || [])
      setQuality(selectedFile.quality || '')
    } else {
      setTags([])
      setQuality('')
    }
    setTagInput('')
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [selectedFile?.filename])

  const refreshFiles = () => qc.invalidateQueries({ queryKey: ['library-all-files', selectedSourceId] })

  const handleSourceChange = (id) => {
    setSelectedSourceId(id)
    setSelectedIndex(0)
    setUploadStatus(null)
  }

  const saveTag = useMutation({
    mutationFn: ({ filename, data }) => libraryApi.saveTag(selectedSourceId, filename, data),
    onSuccess: async (result) => {
      const knownWords = globalTags.map((t) => t.word)
      const newWords = tags.filter((w) => !knownWords.includes(w.toLowerCase()))
      await refreshFiles()
      const fresh = await fetchAllLibraryFiles(selectedSourceId)
      const idx = fresh.findIndex((f) => f.filename === result.new_filename)
      setSelectedIndex(idx >= 0 ? idx : 0)
      if (newWords.length > 0) setNewWordModal({ words: newWords })
    },
    onError: (err) => alert(err.userMessage || 'Save failed.'),
  })

  const deleteFile = useMutation({
    mutationFn: (filename) => libraryApi.deleteFile(selectedSourceId, filename),
    onSuccess: async (_data, deletedFilename) => {
      const wasSelected = selectedFile?.filename === deletedFilename
      await refreshFiles()
      if (wasSelected) {
        setSelectedIndex((i) => Math.max(0, i - 1))
      }
    },
    onError: (err) => alert(err.userMessage || 'Delete failed.'),
  })

  const addGlobalTag = useMutation({
    mutationFn: (word) => settingsApi.addGlobalTag(word),
    onSuccess: () => qc.invalidateQueries({ queryKey: ['global-tags'] }),
  })

  const upload = useMutation({
    mutationFn: (uploadedFiles) => sourcesApi.uploadFolder(selectedSourceId, uploadedFiles),
    onSuccess: (result) => {
      refreshFiles()
      const skippedNote = result.skipped?.length ? ` (${result.skipped.length} skipped)` : ''
      setUploadStatus({ ok: true, message: `Uploaded ${result.uploaded} file(s)${skippedNote}.` })
    },
    onError: (err) => setUploadStatus({ ok: false, message: err.userMessage || 'Upload failed.' }),
  })

  const addTag = () => {
    const word = tagInput.trim().toLowerCase()
    if (!word || tags.includes(word)) return
    setTags((t) => [...t, word])
    setTagInput('')
  }

  const handleSave = () => {
    if (!selectedFile) return
    saveTag.mutate({
      filename: selectedFile.filename,
      data: { tags, quality: quality || null, original_filename: selectedFile.filename },
    })
  }

  const handleDeleteSelected = () => {
    if (!selectedFile) return
    if (confirm(`Delete "${selectedFile.filename}"? This cannot be undone.`)) {
      deleteFile.mutate(selectedFile.filename)
    }
  }

  const handleDeleteCard = (e, filename) => {
    e.stopPropagation()
    if (confirm(`Delete "${filename}"? This cannot be undone.`)) {
      deleteFile.mutate(filename)
    }
  }

  const goPrev = () => setSelectedIndex((i) => Math.max(0, i - 1))
  const goNext = () => setSelectedIndex((i) => Math.min(files.length - 1, i + 1))

  // Clicking a niche-profile tag button toggles it on the current file's tag
  // list — same effect as adding/removing it via the free-text box + chip ✕.
  const toggleProfileTag = (word) => {
    if (!selectedFile) return
    setTags((t) => (t.includes(word) ? t.filter((w) => w !== word) : [...t, word]))
  }

  return (
    <div className="max-w-4xl space-y-6">
      <div>
        <h2 className="text-2xl font-bold mb-1">Local Library</h2>
        <p className="text-sm text-gray-400">Preview, tag, and manage the files uploaded to your local folder sources.</p>
      </div>

      {/* 1. Source picker */}
      <div>
        <label className="label">Source</label>
        <select className="input max-w-sm" value={selectedSourceId}
          onChange={(e) => handleSourceChange(e.target.value)}>
          <option value="">Select a local folder source…</option>
          {sources.map((s) => <option key={s.id} value={s.id}>{s.name}</option>)}
        </select>
        {sources.length === 0 && (
          <p className="text-xs text-yellow-400 mt-1">
            No local folder sources yet. Create one and upload files on the <a className="underline" href="/sources">Sources</a> page first.
          </p>
        )}
      </div>

      {!selectedSourceId ? (
        <div className="card text-center py-16 text-gray-500">Select a source above to browse its library.</div>
      ) : filesLoading ? (
        <div className="card text-center py-16 text-gray-500">Loading…</div>
      ) : filesErrored ? (
        <div className="card text-center py-16 text-red-400">
          Couldn't load this library: {filesError?.userMessage || filesError?.message || 'unknown error.'}
        </div>
      ) : (
        <>
          {/* 2. Central preview */}
          <div className="bg-gray-900 border border-gray-800 rounded-xl overflow-hidden aspect-video flex items-center justify-center">
            {!selectedFile ? (
              <p className="text-gray-500">No files in this library yet — upload some below.</p>
            ) : selectedFile.media_type === 'image' ? (
              <img src={libraryApi.previewUrl(selectedSourceId, selectedFile.filename)}
                className="max-w-full max-h-full object-contain" alt={selectedFile.filename} />
            ) : (
              <video src={libraryApi.previewUrl(selectedSourceId, selectedFile.filename)}
                controls autoPlay loop className="max-w-full max-h-full" />
            )}
          </div>
          {selectedFile && <p className="text-sm text-gray-400 font-mono truncate">{selectedFile.filename}</p>}

          {/* 3. Controls directly under the preview */}
          <div className="card space-y-4">
            <div className="flex items-center gap-3">
              <button className="btn-secondary" onClick={goPrev} disabled={!files.length || selectedIndex === 0}>
                ← Prev
              </button>
              <span className="text-xs text-gray-500 flex-1 text-center">
                {files.length ? `${selectedIndex + 1} / ${files.length}` : '0 / 0'}
              </span>
              <button className="btn-secondary" onClick={goNext} disabled={!files.length || selectedIndex >= files.length - 1}>
                Next →
              </button>
            </div>

            <div className="flex flex-wrap gap-2 min-h-[2rem]">
              {tags.map((tag) => (
                <span key={tag} className="flex items-center gap-1.5 bg-brand-600/20 border border-brand-500/30 rounded-full px-3 py-1 text-sm text-brand-300">
                  {tag}
                  <button onClick={() => setTags((t) => t.filter((w) => w !== tag))} className="text-brand-400 hover:text-red-400">✕</button>
                </span>
              ))}
              {!selectedFile && <span className="text-xs text-gray-600">Select a file to tag it.</span>}
            </div>

            {/* Niche Profile tag buttons — pick a profile, click its tags to quick-add/remove them */}
            <div>
              <label className="label">Niche Profile</label>
              <select className="input max-w-sm" value={selectedProfileId}
                onChange={(e) => setSelectedProfileId(e.target.value)}>
                <option value="">Select a niche profile…</option>
                {profiles.map((p) => <option key={p.id} value={p.id}>{p.name}</option>)}
              </select>
              {profiles.length === 0 && (
                <p className="text-xs text-gray-500 mt-1">
                  No niche profiles yet — create one on the <a className="underline" href="/profiles">Profiles</a> page to get quick-tag buttons here.
                </p>
              )}
            </div>

            {selectedProfileId && (
              <div className="flex flex-wrap gap-2 min-h-[2rem] p-3 rounded-lg bg-gray-900/60 border border-gray-800">
                {profileTags.length === 0 ? (
                  <span className="text-xs text-gray-600">This profile has no tags yet — add some on the Profiles page.</span>
                ) : (
                  profileTags.map((t) => {
                    const active = tags.includes(t.word)
                    return (
                      <button
                        key={t.id}
                        type="button"
                        disabled={!selectedFile}
                        onClick={() => toggleProfileTag(t.word)}
                        title={t.word}
                        className={`px-3 py-1 rounded-full text-sm font-medium transition-colors disabled:opacity-40
                          ${active ? 'bg-brand-600 text-white' : 'bg-gray-800 text-gray-300 hover:bg-gray-700'}`}
                      >
                        {t.word}
                      </button>
                    )
                  })
                )}
              </div>
            )}

            <div className="flex gap-2">
              <label className="label sr-only">Add tag manually (fallback if the profile's tag buttons above don't have what you need)</label>
              <input className="input flex-1" placeholder="Add tag…" value={tagInput} disabled={!selectedFile}
                onChange={(e) => setTagInput(e.target.value)}
                onKeyDown={(e) => { if (e.key === 'Enter' || e.key === ',') { e.preventDefault(); addTag() }}} />
              <button className="btn-secondary" onClick={addTag} disabled={!selectedFile}>Add</button>
            </div>

            <div>
              <label className="label">Quality Grade</label>
              <div className="flex gap-2">
                {QUALITY_GRADES.map((q) => (
                  <button key={q} disabled={!selectedFile}
                    className={`px-3 py-1 rounded-lg text-sm font-medium transition-colors disabled:opacity-40 ${quality === q ? 'bg-brand-600 text-white' : 'bg-gray-800 text-gray-400 hover:bg-gray-700'}`}
                    onClick={() => setQuality(q)}>
                    {q || 'None'}
                  </button>
                ))}
              </div>
            </div>

            <div className="flex gap-3">
              <button className="btn-primary flex-1" disabled={!selectedFile || saveTag.isPending} onClick={handleSave}>
                {saveTag.isPending ? 'Saving…' : 'Save Tagged Name'}
              </button>
              <button className="btn-danger" disabled={!selectedFile || deleteFile.isPending} onClick={handleDeleteSelected}>
                {deleteFile.isPending ? 'Deleting…' : 'Delete'}
              </button>
            </div>
          </div>

          {/* 4. Card grid */}
          <div>
            <h3 className="font-semibold text-gray-300 mb-3">Files ({files.length})</h3>
            {files.length === 0 ? (
              <p className="text-sm text-gray-500">Nothing uploaded yet.</p>
            ) : (
              <div className="flex flex-wrap gap-3">
                {files.map((file, i) => (
                  <button
                    key={file.filename}
                    onClick={() => setSelectedIndex(i)}
                    className={`w-32 h-40 flex flex-col rounded-lg overflow-hidden border text-left transition-colors
                      ${i === selectedIndex ? 'border-brand-500 ring-2 ring-brand-500/50' : 'border-gray-800 hover:border-gray-600'}`}
                  >
                    <div className="relative" style={{ height: '70%' }}>
                      <Thumbnail file={file} sourceId={selectedSourceId} />
                      {!file.tagged && (
                        <span className="absolute top-1 left-1 badge bg-yellow-900 text-yellow-300 text-[10px] px-1.5 py-0.5">Untagged</span>
                      )}
                    </div>
                    <div className="flex-1 flex items-center justify-between gap-1 px-2 bg-gray-900">
                      <span className="text-[11px] text-gray-300 truncate">{file.filename}</span>
                      <span
                        role="button"
                        onClick={(e) => handleDeleteCard(e, file.filename)}
                        className="flex-shrink-0 w-4 h-4 flex items-center justify-center rounded-full bg-red-900/60 text-red-300 hover:bg-red-700 hover:text-white text-[10px] leading-none"
                        title="Delete file"
                      >
                        ✕
                      </span>
                    </div>
                  </button>
                ))}
              </div>
            )}
          </div>

          {/* 5. Upload more files */}
          <div className="card space-y-3">
            <h3 className="font-semibold text-gray-300">Upload More Files</h3>
            <Dropzone
              label="Drag and drop files or a folder here"
              hint="Adds to this library — subfolder structure isn't preserved, matching how this source is searched."
              directory
              disabled={upload.isPending}
              onFiles={(uploadedFiles) => upload.mutate(uploadedFiles)}
            />
            {upload.isPending && <p className="text-xs text-gray-400">Uploading…</p>}
            {uploadStatus && (
              <p className={`text-xs ${uploadStatus.ok ? 'text-green-400' : 'text-red-400'}`}>{uploadStatus.message}</p>
            )}
          </div>

          {/* Download the whole library as a ZIP, tags baked in via filename (see Save Tagged Name above) */}
          <a
            href={libraryApi.downloadFolderUrl(selectedSourceId)}
            download
            className={`btn-secondary w-full text-center ${!files.length ? 'pointer-events-none opacity-40' : ''}`}
            aria-disabled={!files.length}
          >
            ⬇ Download Folder
          </a>
        </>
      )}

      {/* New word modal */}
      {newWordModal && (
        <div className="fixed inset-0 bg-black/60 flex items-center justify-center z-50">
          <div className="bg-gray-900 border border-gray-700 rounded-xl p-6 max-w-md w-full mx-4">
            <h3 className="font-semibold mb-3">New Tags Detected</h3>
            <p className="text-sm text-gray-400 mb-4">These words aren't in any tag list. Add them to the Global list?</p>
            <div className="flex flex-wrap gap-2 mb-4">
              {newWordModal.words.map((w) => (
                <span key={w} className="badge bg-gray-800 text-gray-300">{w}</span>
              ))}
            </div>
            <div className="flex gap-3">
              <button className="btn-secondary flex-1" onClick={() => setNewWordModal(null)}>Skip</button>
              <button className="btn-primary flex-1" onClick={() => {
                newWordModal.words.forEach((w) => addGlobalTag.mutate(w))
                setNewWordModal(null)
              }}>Add to Global List</button>
            </div>
          </div>
        </div>
      )}
    </div>
  )
}
