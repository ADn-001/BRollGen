/**
 * Zustand store — client-side session state.
 * Server state (profiles, sources, settings) lives in React Query.
 */
import { create } from 'zustand'

export const useSessionStore = create((set, get) => ({
  // Current active session
  sessionId: null,
  profileId: null,
  itemCount: 10,
  scriptText: '',
  status: null,           // "analyzing" | "downloading" | "awaiting_review" | "sweeping" | "stitching" | "done" | "error"
  step: 1,               // UI wizard step: 1=setup, 2=tags, 3=download, 4=curation, 5=export

  // Tags (after analysis)
  extractedTags: [],
  needsMoreTags: false,

  // Download results (after download)
  downloadResults: [],
  missingTags: [],

  // Progress (from SSE)
  downloadProgress: { completed: 0, total: 0 },
  sweepProgress: { swept: 0, total: 0 },

  // Export
  videoPath: null,

  // Actions
  setSession: (data) => set({
    sessionId: data.session_id,
    status: data.status,
    extractedTags: data.extracted_tags || [],
    downloadResults: data.download_results || [],
    missingTags: data.missing_tags || [],
    needsMoreTags: data.needs_more_tags || false,
  }),

  setStep: (step) => set({ step }),

  setTags: (tags) => set({ extractedTags: tags }),

  updateDownloadResults: (results) => set({ downloadResults: results }),

  setDownloadProgress: (p) => set({ downloadProgress: p }),
  setSweepProgress: (p) => set({ sweepProgress: p }),

  setCuration: (filePath, kept) => set((state) => ({
    downloadResults: state.downloadResults.map((r) =>
      r.file_path === filePath ? { ...r, kept } : r
    ),
  })),

  keepAll: () => set((state) => ({
    downloadResults: state.downloadResults.map((r) => ({ ...r, kept: true })),
  })),

  dropAll: () => set((state) => ({
    downloadResults: state.downloadResults.map((r) => ({ ...r, kept: false })),
  })),

  resetSession: () => set({
    sessionId: null,
    profileId: null,
    status: null,
    step: 1,
    scriptText: '',
    extractedTags: [],
    needsMoreTags: false,
    downloadResults: [],
    missingTags: [],
    downloadProgress: { completed: 0, total: 0 },
    sweepProgress: { swept: 0, total: 0 },
    videoPath: null,
  }),
}))
