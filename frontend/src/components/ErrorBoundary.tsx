import { Component, type ReactNode } from 'react'

interface Props {
  children: ReactNode
}

interface State {
  error: Error | null
}

export default class ErrorBoundary extends Component<Props, State> {
  state: State = { error: null }

  static getDerivedStateFromError(error: Error): State {
    return { error }
  }

  componentDidCatch(error: Error, info: { componentStack: string }) {
    console.error('Unhandled render error:', error, info.componentStack)
  }

  render() {
    if (this.state.error) {
      return (
        <div className="min-h-screen flex items-center justify-center p-6">
          <div className="max-w-sm w-full text-center space-y-4">
            <p className="text-lg font-semibold text-gray-800">Something went wrong</p>
            <p className="text-sm text-gray-500">
              An unexpected error occurred while rendering this page.
            </p>
            <button
              onClick={() => window.location.reload()}
              className="btn-primary text-sm"
            >
              Reload page
            </button>
          </div>
        </div>
      )
    }

    return this.props.children
  }
}
