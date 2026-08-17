import { Routes, Route, Navigate } from 'react-router-dom'
import Layout from './components/Layout'
import DashboardPage from './pages/DashboardPage'
import DecksPage from './pages/DecksPage'
import DeckDetailPage from './pages/DeckDetailPage'
import UploadPage from './pages/UploadPage'
import ReviewPage from './pages/ReviewPage'
import QuizPage from './pages/QuizPage'
import TopicsPage from './pages/TopicsPage'
import AtRiskPage from './pages/AtRiskPage'
import SearchPage from './pages/SearchPage'
import SettingsPage from './pages/SettingsPage'
import SplitReviewPage from './pages/SplitReviewPage'
import BookChaptersPage from './pages/BookChaptersPage'
import BooksPage from './pages/BooksPage'

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
        <Route path="/books" element={<BooksPage />} />
        <Route path="/uploads/:uploadId/split-review" element={<SplitReviewPage />} />
        <Route path="/uploads/:uploadId/chapters" element={<BookChaptersPage />} />
        <Route path="/uploads/:uploadId/review" element={<ReviewPage />} />
        <Route path="/topics" element={<TopicsPage />} />
        <Route path="/topics/:topicId" element={<TopicsPage />} />
        <Route path="/topics/:topicId/review" element={<ReviewPage />} />
        <Route path="/review/library" element={<ReviewPage />} />
        <Route path="/quiz" element={<QuizPage />} />
        <Route path="/at-risk" element={<AtRiskPage />} />
        <Route path="/at-risk/review" element={<ReviewPage />} />
        <Route path="/search" element={<SearchPage />} />
        <Route path="/search/review" element={<ReviewPage />} />
        <Route path="/insights/review" element={<ReviewPage />} />
        <Route path="/settings" element={<SettingsPage />} />
      </Route>
    </Routes>
  )
}
