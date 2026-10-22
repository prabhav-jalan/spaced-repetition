import { useState, type FormEvent } from 'react'
import { ApiError } from '../api/client.ts'
import { useDevSignIn } from '../api/queries.ts'
import { browserTimeZone } from '../time.ts'

export function SignInPage() {
  const signIn = useDevSignIn()
  const [email, setEmail] = useState('')

  function submit(event: FormEvent<HTMLFormElement>) {
    event.preventDefault()
    signIn.mutate(email)
  }

  const unavailable = signIn.error instanceof ApiError && signIn.error.status === 404
  return (
    <section className="sign-in">
      <h1>Prep reviews</h1>
      <p className="muted">Which NeetCode problems to redo today.</p>
      <form onSubmit={submit}>
        <label htmlFor="email">Email</label>
        <div className="row">
          <input
            id="email"
            type="email"
            required
            autoComplete="email"
            value={email}
            onChange={(event) => setEmail(event.target.value)}
          />
          <button type="submit" disabled={signIn.isPending}>
            Sign in
          </button>
        </div>
        <p className="muted">Development sign-in. Your time zone: {browserTimeZone()}.</p>
        {signIn.isError && (
          <p role="alert" className="error">
            {unavailable ? "Sign-in isn't available on this server yet." : signIn.error.message}
          </p>
        )}
      </form>
    </section>
  )
}
