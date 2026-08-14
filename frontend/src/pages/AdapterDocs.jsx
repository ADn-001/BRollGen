/**
 * In-app custom adapter documentation page.
 * Fetches and renders the bundled CUSTOM_ADAPTER_GUIDE.md from the backend.
 */
import { useQuery } from '@tanstack/react-query'
import { api } from '../api'

export default function AdapterDocs() {
  const { data, isLoading, error } = useQuery({
    queryKey: ['adapter-docs'],
    queryFn: () => api.get('/docs/adapter').then((r) => r.data),
  })

  if (isLoading) return <div className="text-gray-400">Loading documentation…</div>
  if (error) return <div className="text-red-400">Failed to load docs: {error.userMessage}</div>

  return (
    <div className="max-w-3xl">
      <h2 className="text-2xl font-bold mb-6">Custom Adapter Guide</h2>
      <div className="card">
        <pre className="text-sm text-gray-300 whitespace-pre-wrap font-mono leading-relaxed overflow-x-auto">
          {typeof data === 'string' ? data : JSON.stringify(data, null, 2)}
        </pre>
      </div>
    </div>
  )
}
