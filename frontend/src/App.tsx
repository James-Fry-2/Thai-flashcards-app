import { Routes, Route, Navigate } from 'react-router-dom'
import Layout from './components/Layout'
import DashboardPage from './pages/DashboardPage'
import DecksPage from './pages/DecksPage'
import DeckDetailPage from './pages/DeckDetailPage'
import UploadPage from './pages/UploadPage'
import ReviewPage from './pages/ReviewPage'
import TopicsPage from './pages/TopicsPage'
import AtRiskPage from './pages/AtRiskPage'
import SearchPage from './pages/SearchPage'

export default function App() {
  return (
    <Routes>
      <Route element={<Layout />}>
        <Route index element={<Navigate to="/dashboard" replace />} />
        <Route path="/dashboard" element={<DashboardPage />} />
        <Route path="/decks" element={<DecksPage />} />
        <Route path="/decks/:deckId" element={<DeckDetailPage />} />
        <Route path="/decks/:deckId/review" element={<ReviewPage />} />
        <Route path="/upload" element={<UploadPage />} />
        <Route path="/topics" element={<TopicsPage />} />
        <Route path="/topics/:topicId" element={<TopicsPage />} />
        <Route path="/topics/:topicId/review" element={<ReviewPage />} />
        <Route path="/review/library" element={<ReviewPage />} />
        <Route path="/at-risk" element={<AtRiskPage />} />
        <Route path="/at-risk/review" element={<ReviewPage />} />
        <Route path="/search" element={<SearchPage />} />
        <Route path="/search/review" element={<ReviewPage />} />
      </Route>
    </Routes>
  )
}
