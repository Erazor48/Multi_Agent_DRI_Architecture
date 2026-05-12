import { createFileRoute, redirect } from '@tanstack/react-router'
import { authClient } from '~/lib/auth-client'

export const Route = createFileRoute('/')({
  beforeLoad: async () => {
    const session = await authClient.getSession()
    if (!session.data) throw redirect({ to: '/login' })
    throw redirect({ to: '/companies' })
  },
  component: () => null,
})
