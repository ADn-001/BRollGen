import { Routes, Route, Navigate } from 'react-router-dom'
import Layout from './components/Layout'
import Dashboard from './pages/Dashboard'
import Profiles from './pages/Profiles'
import Sources from './pages/Sources'
import Settings from './pages/Settings'
import LocalLibrary from './pages/LocalLibrary'
import AdapterDocs from './pages/AdapterDocs'

export default function App() {
  return (
    <Routes>
      <Route element={<Layout />}>
        <Route index element={<Dashboard />} />
        <Route path="profiles" element={<Profiles />} />
        <Route path="sources" element={<Sources />} />
        <Route path="library" element={<LocalLibrary />} />
        <Route path="settings" element={<Settings />} />
        <Route path="docs/adapter" element={<AdapterDocs />} />
        <Route path="*" element={<Navigate to="/" replace />} />
      </Route>
    </Routes>
  )
}
