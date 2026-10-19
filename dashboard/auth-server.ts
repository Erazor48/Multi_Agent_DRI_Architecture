import { auth } from './src/lib/auth'

const server = Bun.serve({
  port: 3001,
  fetch(req) {
    return auth.handler(req)
  },
})

console.log(`[auth] http://localhost:${server.port}`)
