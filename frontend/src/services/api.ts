import axios from 'axios'
import toast from 'react-hot-toast'

const api = axios.create({
  baseURL: '/api',
  timeout: 60_000,
})

// Lets the backend work out when the user's study day starts (04:00 local),
// for daily new-card / review limits.
api.interceptors.request.use((config) => {
  config.headers['X-Timezone-Offset'] = String(new Date().getTimezoneOffset())
  return config
})

api.interceptors.response.use(
  (res) => res,
  (err) => {
    const msg = err.response?.data?.detail || err.message || 'Something went wrong'
    toast.error(msg)
    return Promise.reject(err)
  }
)

export default api
