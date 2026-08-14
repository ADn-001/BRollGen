/**
 * Axios instance + API helper functions.
 * All API calls go through /api/* which is proxied to FastAPI in dev.
 */
import axios from 'axios'

export const api = axios.create({
  baseURL: '/api',
  headers: { 'Content-Type': 'application/json' },
})

// Intercept errors and normalize them
api.interceptors.response.use(
  (res) => res,
  (err) => {
    const detail = err.response?.data?.detail || err.response?.data?.error || err.message
    err.userMessage = detail
    return Promise.reject(err)
  }
)

// ── Profiles ──────────────────────────────────────────────────────────────────
export const profilesApi = {
  list: () => api.get('/profiles').then((r) => r.data),
  get: (id) => api.get(`/profiles/${id}`).then((r) => r.data),
  create: (data) => api.post('/profiles', data).then((r) => r.data),
  update: (id, data) => api.put(`/profiles/${id}`, data).then((r) => r.data),
  delete: (id) => api.delete(`/profiles/${id}`),
  listTags: (id) => api.get(`/profiles/${id}/tags`).then((r) => r.data),
  addTag: (id, word) => api.post(`/profiles/${id}/tags`, { word }).then((r) => r.data),
  deleteTag: (profileId, tagId) => api.delete(`/profiles/${profileId}/tags/${tagId}`),
  importTagsCsv: (id, file) => {
    const fd = new FormData()
    fd.append('file', file)
    return api.post(`/profiles/${id}/tags/import-csv`, fd, {
      headers: { 'Content-Type': 'multipart/form-data' },
    }).then((r) => r.data)
  },
  listSources: (id) => api.get(`/profiles/${id}/sources`).then((r) => r.data),
  setSources: (id, sourceIds) => api.put(`/profiles/${id}/sources`, { source_ids: sourceIds }).then((r) => r.data),
  startAdapters: (id) => api.post(`/profiles/${id}/adapters/start`).then((r) => r.data),
}

// ── Sources ───────────────────────────────────────────────────────────────────
export const sourcesApi = {
  list: () => api.get('/sources').then((r) => r.data),
  create: (data) => api.post('/sources', data).then((r) => r.data),
  update: (id, data) => api.put(`/sources/${id}`, data).then((r) => r.data),
  delete: (id) => api.delete(`/sources/${id}`),
  test: (id) => api.post(`/sources/${id}/test`).then((r) => r.data),
  // Upload real file bytes for a local_folder source instead of typing a host path.
  // `files` is an array of File objects; webkitRelativePath (if present, e.g. from a
  // webkitdirectory picker or a dropped folder) is sent as each file's name so the
  // server can report it, even though the library itself is stored flat.
  uploadFolder: (id, files) => {
    const fd = new FormData()
    files.forEach((f) => fd.append('files', f, f.webkitRelativePath || f.name))
    return api.post(`/sources/${id}/upload/folder`, fd, {
      headers: { 'Content-Type': 'multipart/form-data' },
    }).then((r) => r.data)
  },
  folderStatus: (id) => api.get(`/sources/${id}/upload/folder/status`).then((r) => r.data),
  clearFolder: (id) => api.delete(`/sources/${id}/upload/folder`),
  // Upload a .py adapter entry-point script for a custom_adapter source instead of
  // (or in addition to) typing its path — sets config.adapter_script_path server-side.
  uploadAdapterScript: (id, file) => {
    const fd = new FormData()
    fd.append('file', file)
    return api.post(`/sources/${id}/upload/adapter-script`, fd, {
      headers: { 'Content-Type': 'multipart/form-data' },
    }).then((r) => r.data)
  },
}

// ── Sessions ──────────────────────────────────────────────────────────────────
export const sessionsApi = {
  create: (data) => api.post('/sessions', data).then((r) => r.data),
  createFromTags: (data) => api.post('/sessions/from-tags', data).then((r) => r.data),
  get: (id) => api.get(`/sessions/${id}`).then((r) => r.data),
  updateTags: (id, tags) => api.put(`/sessions/${id}/tags`, { tags }).then((r) => r.data),
  startDownload: (id) => api.post(`/sessions/${id}/download`).then((r) => r.data),
  updateCuration: (id, items) => api.put(`/sessions/${id}/curation`, { items }).then((r) => r.data),
  exportZip: (id) => `/api/sessions/${id}/export/zip`,
  exportVideoStitch: (id) => `/api/sessions/${id}/export/videostitch`,
  missingTagsTxt: (id) => `/api/sessions/${id}/export/missing-tags`,
  delete: (id) => api.delete(`/sessions/${id}`),
}

// ── Settings ──────────────────────────────────────────────────────────────────
export const settingsApi = {
  get: () => api.get('/settings').then((r) => r.data),
  update: (data) => api.put('/settings', data).then((r) => r.data),
  listProviders: () => api.get('/llm-providers').then((r) => r.data),
  createProvider: (data) => api.post('/llm-providers', data).then((r) => r.data),
  updateProvider: (id, data) => api.put(`/llm-providers/${id}`, data).then((r) => r.data),
  deleteProvider: (id) => api.delete(`/llm-providers/${id}`),
  listGlobalTags: () => api.get('/global-tags').then((r) => r.data),
  addGlobalTag: (word) => api.post('/global-tags', { word }).then((r) => r.data),
  deleteGlobalTag: (id) => api.delete(`/global-tags/${id}`),
  importGlobalTagsCsv: (file) => {
    const fd = new FormData()
    fd.append('file', file)
    return api.post('/global-tags/import-csv', fd, {
      headers: { 'Content-Type': 'multipart/form-data' },
    }).then((r) => r.data)
  },
}

// ── Library ───────────────────────────────────────────────────────────────────
export const libraryApi = {
  listSources: () => api.get('/library/sources').then((r) => r.data),
  listFiles: (sourceId, page = 1, pageSize = 50) =>
    api.get(`/library/${sourceId}/files`, { params: { page, page_size: pageSize } }).then((r) => r.data),
  getFile: (sourceId, filename) => api.get(`/library/${sourceId}/files/${filename}`).then((r) => r.data),
  saveTag: (sourceId, filename, data) =>
    api.post(`/library/${sourceId}/files/${filename}/tag`, data).then((r) => r.data),
  deleteFile: (sourceId, filename) =>
    api.delete(`/library/${sourceId}/files/${encodeURIComponent(filename)}`),
  previewUrl: (sourceId, filename) => `/api/library/preview/${sourceId}/${filename}`,
  downloadFolderUrl: (sourceId) => `/api/library/${sourceId}/download`,
}

// ── Adapter docs ──────────────────────────────────────────────────────────────
export const docsApi = {
  getAdapterGuide: () => api.get('/docs/adapter').then((r) => r.data),
}

/**
 * Create an SSE connection and call `onMessage(data)` on each event.
 * Returns a cleanup function.
 */
export function createSSE(url, onMessage, onError) {
  const es = new EventSource(url)
  es.onmessage = (e) => {
    try {
      onMessage(JSON.parse(e.data))
    } catch {
      onMessage(e.data)
    }
  }
  if (onError) es.onerror = onError
  return () => es.close()
}
