import { createRootRoute, Outlet } from '@tanstack/react-router'
import { Meta, Scripts } from '@tanstack/react-start'
import { ConvexProvider, ConvexReactClient } from 'convex/react'
import '~/styles/globals.css'

const convexUrl = import.meta.env.VITE_CONVEX_URL as string | undefined
const convex = convexUrl ? new ConvexReactClient(convexUrl) : null

export const Route = createRootRoute({
  head: () => ({
    meta: [
      { charSet: 'utf-8' },
      { name: 'viewport', content: 'width=device-width, initial-scale=1' },
      { title: 'DRI Dashboard' },
    ],
  }),
  component: function Root() {
    const body = (
      <html lang="en">
        <head>
          <Meta />
        </head>
        <body className="min-h-screen bg-zinc-950 text-zinc-50 antialiased">
          <Outlet />
          <Scripts />
        </body>
      </html>
    )

    if (convex) {
      return <ConvexProvider client={convex}>{body}</ConvexProvider>
    }
    return body
  },
})
