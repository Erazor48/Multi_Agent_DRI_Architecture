import { describe, it, expect, vi, beforeEach } from 'vitest'

const mockFetch = vi.fn()
vi.stubGlobal('fetch', mockFetch)

function makeOkResponse(data: unknown) {
  return {
    ok: true,
    status: 200,
    json: () => Promise.resolve(data),
  }
}

function makeErrorResponse(status: number, detail: string) {
  return {
    ok: false,
    status,
    json: () => Promise.resolve({ detail }),
  }
}

beforeEach(() => mockFetch.mockReset())

describe('listCompanies', () => {
  it('calls /api/companies with X-User-ID header', async () => {
    const companies = [{ id: '1', name: 'Acme' }]
    mockFetch.mockResolvedValueOnce(makeOkResponse(companies))

    const { listCompanies } = await import('../src/lib/dri-api')
    const result = await listCompanies('user-abc')

    expect(mockFetch).toHaveBeenCalledWith(
      'http://localhost:8000/api/companies',
      expect.objectContaining({
        headers: expect.objectContaining({ 'X-User-ID': 'user-abc' }),
      }),
    )
    expect(result).toEqual(companies)
  })

  it('throws with server detail on HTTP error', async () => {
    mockFetch.mockResolvedValueOnce(makeErrorResponse(404, 'Not found'))

    const { listCompanies } = await import('../src/lib/dri-api')
    await expect(listCompanies('user-abc')).rejects.toThrow('Not found')
  })
})

describe('getCompany', () => {
  it('calls /api/companies/:id', async () => {
    const company = { id: 'c1', name: 'Acme' }
    mockFetch.mockResolvedValueOnce(makeOkResponse(company))

    const { getCompany } = await import('../src/lib/dri-api')
    const result = await getCompany('c1', 'user-abc')

    expect(mockFetch).toHaveBeenCalledWith(
      'http://localhost:8000/api/companies/c1',
      expect.anything(),
    )
    expect(result).toEqual(company)
  })
})

describe('approveAction', () => {
  it('POSTs to approve endpoint with note', async () => {
    const action = { status: 'approved', type: 'email' }
    mockFetch.mockResolvedValueOnce(makeOkResponse(action))

    const { approveAction } = await import('../src/lib/dri-api')
    await approveAction('c1', 1, 'looks good', 'user-abc')

    expect(mockFetch).toHaveBeenCalledWith(
      'http://localhost:8000/api/companies/c1/approvals/1/approve',
      expect.objectContaining({
        method: 'POST',
        body: JSON.stringify({ note: 'looks good' }),
      }),
    )
  })
})

describe('streamPost (SSE parsing)', () => {
  it('yields parsed status and result events', async () => {
    const sseData =
      'data: {"type":"status","message":"Loading"}\n\n' +
      'data: {"type":"result","text":"Done"}\n\n'

    const encoder = new TextEncoder()
    const stream = new ReadableStream({
      start(controller) {
        controller.enqueue(encoder.encode(sseData))
        controller.close()
      },
    })

    mockFetch.mockResolvedValueOnce({ ok: true, status: 200, body: stream })

    const { streamPost } = await import('../src/lib/dri-api')
    const events: unknown[] = []
    for await (const event of streamPost('/api/test', {}, 'user-abc')) {
      events.push(event)
    }

    expect(events).toHaveLength(2)
    expect(events[0]).toEqual({ type: 'status', message: 'Loading' })
    expect(events[1]).toEqual({ type: 'result', text: 'Done' })
  })

  it('handles events split across multiple chunks', async () => {
    const part1 = 'data: {"type":"status","mess'
    const part2 = 'age":"Chunk"}\n\ndata: {"type":"result","text":"OK"}\n\n'
    const encoder = new TextEncoder()

    const stream = new ReadableStream({
      start(controller) {
        controller.enqueue(encoder.encode(part1))
        controller.enqueue(encoder.encode(part2))
        controller.close()
      },
    })

    mockFetch.mockResolvedValueOnce({ ok: true, status: 200, body: stream })

    const { streamPost } = await import('../src/lib/dri-api')
    const events: unknown[] = []
    for await (const event of streamPost('/api/test', {}, 'user-abc')) {
      events.push(event)
    }

    expect(events).toHaveLength(2)
    expect(events[0]).toEqual({ type: 'status', message: 'Chunk' })
  })

  it('throws on non-ok response', async () => {
    mockFetch.mockResolvedValueOnce({ ok: false, status: 500, body: null })

    const { streamPost } = await import('../src/lib/dri-api')
    await expect(async () => {
      for await (const _ of streamPost('/api/test', {}, 'user-abc')) { /* noop */ }
    }).rejects.toThrow('HTTP 500')
  })
})
