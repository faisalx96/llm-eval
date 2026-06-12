import { Outlet } from 'react-router-dom'
import { AppShell } from '@/app/AppShell'

/**
 * Root route element: wraps every routed page in the application shell
 * (sidebar + topbar). The shell resolves its own context (global vs
 * project) from the current route.
 */
export default function App() {
  return (
    <AppShell>
      <Outlet />
    </AppShell>
  )
}
