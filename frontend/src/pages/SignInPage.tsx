import { useEffect, useState, type FormEvent } from 'react'
import { useDevSignIn, useProviders } from '../api/queries.ts'
import { browserTimeZone } from '../time.ts'

const OUTCOMES: Record<string, string> = {
  cancelled: 'Sign-in was cancelled.',
  failed: "Google sign-in didn't work. Please try again.",
}

function readOutcome(): string | null {
  return new URLSearchParams(window.location.search).get('signin')
}

function clearOutcome(): void {
  const params = new URLSearchParams(window.location.search)
  params.delete('signin')
  const query = params.toString()
  window.history.replaceState(null, '', window.location.pathname + (query ? `?${query}` : ''))
}

export function SignInPage() {
  const providers = useProviders()
  const [outcome] = useState(readOutcome)
  const zone = browserTimeZone()

  useEffect(() => {
    if (outcome !== null) clearOutcome()
  }, [outcome])

  const message = outcome === null ? null : (OUTCOMES[outcome] ?? null)
  const google = providers.data?.google ?? false
  const dev = providers.data?.dev ?? false

  return (
    <section className="sign-in">
      <h1>Prep reviews</h1>
      <p className="muted">Which NeetCode problems to redo today.</p>

      {message && (
        <p role="alert" className="error notice">
          {message}
        </p>
      )}

      {google && (
        <a className="google" href={`/api/auth/google/login?timezone=${encodeURIComponent(zone)}`}>
          Continue with Google
        </a>
      )}

      {dev && <DevSignIn zone={zone} />}

      {providers.isError && (
        <p role="alert" className="error notice">
          Couldn't reach the server: {providers.error.message}
        </p>
      )}
      {providers.isSuccess && !google && !dev && (
        <p className="muted notice">Sign-in isn't set up on this server yet.</p>
      )}

      <p className="muted notice">
        <a href="/privacy.html">Privacy policy</a>
      </p>
    </section>
  )
}

function DevSignIn({ zone }: { zone: string }) {
  const signIn = useDevSignIn()
  const [email, setEmail] = useState('')

  function submit(event: FormEvent<HTMLFormElement>) {
    event.preventDefault()
    signIn.mutate(email)
  }

  return (
    <form className="dev" onSubmit={submit}>
      <label htmlFor="email">Development sign-in</label>
      <div className="row">
        <input
          id="email"
          type="email"
          required
          placeholder="you@example.com"
          autoComplete="email"
          value={email}
          onChange={(event) => setEmail(event.target.value)}
        />
        <button type="submit" disabled={signIn.isPending}>
          Sign in
        </button>
      </div>
      <p className="muted">Only on dev servers. Your time zone: {zone}.</p>
      {signIn.isError && (
        <p role="alert" className="error">
          {signIn.error.message}
        </p>
      )}
    </form>
  )
}
