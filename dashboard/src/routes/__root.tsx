import { createRootRoute, HeadContent, Outlet, Scripts } from '@tanstack/react-router'
import { ConvexProvider, ConvexReactClient } from 'convex/react'
import '~/styles/globals.css'

const convexUrl = import.meta.env.VITE_CONVEX_URL as string | undefined
const convex = convexUrl ? new ConvexReactClient(convexUrl) : null

function NotFound() {
  return (
    <div className="min-h-screen bg-zinc-950 flex items-center justify-center">
      <div className="text-center">
        <p className="text-zinc-400 text-lg">Page not found.</p>
        <a href="/" className="text-zinc-50 underline text-sm mt-2 inline-block">
          Go home
        </a>
      </div>
    </div>
  )
}

export const Route = createRootRoute({
  notFoundComponent: NotFound,
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
          <HeadContent />
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
