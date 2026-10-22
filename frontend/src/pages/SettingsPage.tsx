import { useMemo, useState, type FormEvent } from 'react'
import { useSignOut, useUpdateMe } from '../api/queries.ts'
import type { Me } from '../api/types.ts'
import { allTimeZones, browserTimeZone, longDay } from '../time.ts'

export function SettingsPage({ me }: { me: Me }) {
  const update = useUpdateMe()
  const signOut = useSignOut()
  const [zone, setZone] = useState(me.timezone)
  const [emails, setEmails] = useState(me.email_enabled)
  const zones = useMemo(allTimeZones, [])
  const detected = browserTimeZone()

  function saveZone(event: FormEvent<HTMLFormElement>) {
    event.preventDefault()
    update.mutate({ timezone: zone.trim() })
  }

  function saveEmails(enabled: boolean) {
    setEmails(enabled)
    update.mutate({ email_enabled: enabled }, { onError: () => setEmails(!enabled) })
  }

  return (
    <section>
      <header className="page-head">
        <h1>Settings</h1>
        <p className="muted">Signed in as {me.email}</p>
      </header>

      <form className="setting" onSubmit={saveZone}>
        <label htmlFor="time-zone">Time zone</label>
        <p className="muted">
          Your day starts at midnight here. It's {longDay(me.local_date)} in {me.timezone}.
        </p>
        <div className="row">
          <input
            id="time-zone"
            list="time-zones"
            value={zone}
            onChange={(event) => setZone(event.target.value)}
            autoComplete="off"
            spellCheck={false}
          />
          <button type="submit" disabled={update.isPending || zone.trim() === me.timezone}>
            Save
          </button>
        </div>
        <datalist id="time-zones">
          {zones.map((name) => (
            <option key={name} value={name} />
          ))}
        </datalist>
        {detected !== me.timezone && (
          <button type="button" className="link-button" onClick={() => setZone(detected)}>
            Use this device's time zone ({detected})
          </button>
        )}
        {update.isError && update.variables?.timezone !== undefined && (
          <p role="alert" className="error">
            {update.error.message}
          </p>
        )}
      </form>

      <div className="setting">
        <label className="check">
          <input
            type="checkbox"
            checked={emails}
            onChange={(event) => saveEmails(event.target.checked)}
          />
          Email me at 8 a.m. on days with reviews due
        </label>
        {update.isError && update.variables?.email_enabled !== undefined && (
          <p role="alert" className="error">
            {update.error.message}
          </p>
        )}
      </div>

      <div className="setting">
        <button type="button" onClick={() => signOut.mutate()} disabled={signOut.isPending}>
          Sign out
        </button>
      </div>
    </section>
  )
}
