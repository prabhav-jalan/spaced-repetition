import { isUnauthorized } from './api/client.ts'
import { useMe } from './api/queries.ts'
import type { Me } from './api/types.ts'
import { ErrorNote } from './components/ErrorNote.tsx'
import { CatalogPage } from './pages/CatalogPage.tsx'
import { SettingsPage } from './pages/SettingsPage.tsx'
import { SignInPage } from './pages/SignInPage.tsx'
import { TodayPage } from './pages/TodayPage.tsx'
import { Link, usePath } from './router.tsx'

export default function App() {
  const me = useMe()

  if (me.isPending) {
    return (
      <main className="shell">
        <p className="muted">Loading…</p>
      </main>
    )
  }
  if (me.isError) {
    return (
      <main className="shell">
        {isUnauthorized(me.error) ? <SignInPage /> : <ErrorNote error={me.error} />}
      </main>
    )
  }
  return <SignedIn me={me.data} />
}

function SignedIn({ me }: { me: Me }) {
  const path = usePath()
  const due = me.totals.due_today

  return (
    <>
      <header className="topbar">
        <nav className="shell nav" aria-label="Main">
          <span className="brand">Prep reviews</span>
          <Link to="/">{due > 0 ? `Today (${due})` : 'Today'}</Link>
          <Link to="/catalog">Catalog</Link>
          <Link to="/settings">Settings</Link>
        </nav>
      </header>
      <main className="shell">
        {path === '/catalog' ? (
          <CatalogPage />
        ) : path === '/settings' ? (
          <SettingsPage me={me} />
        ) : (
          <TodayPage />
        )}
      </main>
    </>
  )
}
