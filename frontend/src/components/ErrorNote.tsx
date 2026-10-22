export function ErrorNote({ error }: { error: Error }) {
  return (
    <p role="alert" className="error">
      Something went wrong: {error.message}
    </p>
  )
}
