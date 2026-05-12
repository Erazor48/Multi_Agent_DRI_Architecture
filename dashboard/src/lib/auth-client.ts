import { createAuthClient } from 'better-auth/react'

const baseURL =
  typeof window !== 'undefined'
    ? window.location.origin
    : (import.meta.env.VITE_APP_URL ?? 'http://localhost:3000')

export const authClient = createAuthClient({ baseURL })

export const { useSession, signIn, signUp, signOut } = authClient
