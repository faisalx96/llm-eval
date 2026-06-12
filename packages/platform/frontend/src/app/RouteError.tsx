import { isRouteErrorResponse, Link, useNavigate, useRouteError } from 'react-router-dom'
import { ApiError } from '@/api/client'
import styles from './RouteError.module.css'

function describe(error: unknown): { title: string; detail: string } {
  if (isRouteErrorResponse(error)) {
    if (error.status === 404) {
      return { title: 'Page not found', detail: 'This page does not exist or has moved.' }
    }
    return { title: `Error ${error.status}`, detail: error.statusText || 'Something went wrong.' }
  }
  if (error instanceof ApiError) {
    return {
      title: 'Request failed',
      detail:
        typeof error.detail === 'string'
          ? error.detail
          : `The server responded with status ${error.status}.`,
    }
  }
  if (error instanceof Error) {
    return { title: 'Something went wrong', detail: error.message }
  }
  return { title: 'Something went wrong', detail: 'An unexpected error occurred.' }
}

/** Friendly route-level error card with a retry action. */
export default function RouteError() {
  const error = useRouteError()
  const navigate = useNavigate()
  const { title, detail } = describe(error)
  const notFound = isRouteErrorResponse(error) && error.status === 404

  return (
    <section className={styles.wrap}>
      <div className={styles.card} role="alert">
        <h1 className={styles.title}>{title}</h1>
        <p className={styles.detail}>{detail}</p>
        <div className={styles.actions}>
          {!notFound && (
            <button
              type="button"
              className={styles.retry}
              onClick={() => {
                // History reload: re-runs loaders and re-imports the chunk.
                navigate(0)
              }}
            >
              Retry
            </button>
          )}
          <Link to="/" className={styles.home}>
            All projects
          </Link>
        </div>
      </div>
    </section>
  )
}
