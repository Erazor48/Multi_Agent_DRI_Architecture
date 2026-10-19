import { createFileRoute, useNavigate } from '@tanstack/react-router'
import { useEffect } from 'react'
import { authClient } from '~/lib/auth-client'

export const Route = createFileRoute('/')({
  component: IndexPage,
})

function IndexPage() {
  const navigate = useNavigate()
  const { data: session, isPending } = authClient.useSession()

  useEffect(() => {
    if (!isPending) {
      navigate({ to: session ? '/companies' : '/login' })
    }
  }, [isPending, session])

  return (
    <div className="min-h-screen bg-zinc-950 flex items-center justify-center">
      <p className="text-zinc-400">Loading…</p>
    </div>
  )
}
