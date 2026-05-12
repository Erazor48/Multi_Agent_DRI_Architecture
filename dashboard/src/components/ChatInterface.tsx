import { useState, useRef, useEffect } from 'react'
import { chat, task } from '~/lib/dri-api'

interface Message {
  id: string
  role: 'user' | 'assistant'
  content: string
  statusLog?: string[]
}

interface Props {
  companyId: string
  userId: string
}

export function ChatInterface({ companyId, userId }: Props) {
  const [messages, setMessages] = useState<Message[]>([])
  const [input, setInput] = useState('')
  const [mode, setMode] = useState<'chat' | 'task'>('chat')
  const [streaming, setStreaming] = useState(false)
  const [statusLog, setStatusLog] = useState<string[]>([])
  const bottomRef = useRef<HTMLDivElement>(null)
  const textareaRef = useRef<HTMLTextAreaElement>(null)

  useEffect(() => {
    bottomRef.current?.scrollIntoView({ behavior: 'smooth' })
  }, [messages, statusLog])

  async function handleSend(e: React.FormEvent) {
    e.preventDefault()
    const text = input.trim()
    if (!text || streaming) return

    const userMsg: Message = { id: Date.now().toString(), role: 'user', content: text }
    setMessages(prev => [...prev, userMsg])
    setInput('')
    setStreaming(true)
    setStatusLog([])

    const log: string[] = []

    try {
      let response = ''
      const stream = mode === 'chat'
        ? chat(companyId, text, userId)
        : task(companyId, text, userId)

      for await (const event of stream) {
        if (event.type === 'status' && event.message) {
          log.push(event.message)
          setStatusLog([...log])
        } else if (event.type === 'result' && event.text) {
          response = event.text
        } else if (event.type === 'error') {
          response = `Error: ${event.message ?? 'Unknown error'}`
        }
      }

      setMessages(prev => [
        ...prev,
        {
          id: (Date.now() + 1).toString(),
          role: 'assistant',
          content: response,
          statusLog: log,
        },
      ])
    } catch (err) {
      setMessages(prev => [
        ...prev,
        {
          id: (Date.now() + 1).toString(),
          role: 'assistant',
          content: `Error: ${err instanceof Error ? err.message : 'Failed to connect to backend'}`,
        },
      ])
    } finally {
      setStreaming(false)
      setStatusLog([])
    }
  }

  function handleKeyDown(e: React.KeyboardEvent<HTMLTextAreaElement>) {
    if (e.key === 'Enter' && !e.shiftKey) {
      e.preventDefault()
      handleSend(e as unknown as React.FormEvent)
    }
  }

  return (
    <div className="flex flex-col h-full" style={{ minHeight: '60vh' }}>
      {/* Mode toggle */}
      <div className="flex gap-2 mb-4">
        {(['chat', 'task'] as const).map(m => (
          <button
            key={m}
            onClick={() => setMode(m)}
            className={`px-3 py-1.5 text-xs font-medium rounded-lg transition-colors ${
              mode === m
                ? 'bg-zinc-700 text-zinc-50'
                : 'text-zinc-400 hover:text-zinc-300'
            }`}
          >
            {m === 'chat' ? 'Chat with CEO' : 'Assign Task'}
          </button>
        ))}
      </div>

      {/* Messages */}
      <div className="flex-1 overflow-y-auto space-y-4 mb-4 pr-1">
        {messages.length === 0 && (
          <p className="text-zinc-500 text-sm text-center py-8">
            {mode === 'chat'
              ? 'Start a conversation with the CEO.'
              : 'Assign a task to the company.'}
          </p>
        )}

        {messages.map(msg => (
          <div
            key={msg.id}
            className={`flex ${msg.role === 'user' ? 'justify-end' : 'justify-start'}`}
          >
            <div
              className={`max-w-[80%] rounded-xl px-4 py-3 text-sm leading-relaxed whitespace-pre-wrap ${
                msg.role === 'user'
                  ? 'bg-zinc-700 text-zinc-50'
                  : 'bg-zinc-900 border border-zinc-800 text-zinc-200'
              }`}
            >
              {msg.content}
            </div>
          </div>
        ))}

        {/* Live status log while streaming */}
        {streaming && statusLog.length > 0 && (
          <div className="bg-zinc-900 border border-zinc-800 rounded-xl px-4 py-3">
            <div className="space-y-1 font-mono text-xs text-zinc-400">
              {statusLog.map((m, i) => (
                <p key={i}>→ {m}</p>
              ))}
              <p className="text-zinc-600 animate-pulse">Working…</p>
            </div>
          </div>
        )}

        <div ref={bottomRef} />
      </div>

      {/* Input */}
      <form onSubmit={handleSend} className="flex gap-3 items-end">
        <textarea
          ref={textareaRef}
          value={input}
          onChange={e => setInput(e.target.value)}
          onKeyDown={handleKeyDown}
          placeholder={mode === 'chat' ? 'Message the CEO… (Enter to send)' : 'Describe the task…'}
          rows={2}
          disabled={streaming}
          className="flex-1 px-3 py-2 bg-zinc-800 border border-zinc-700 rounded-lg text-zinc-50 placeholder-zinc-500 focus:outline-none focus:border-zinc-500 resize-none text-sm disabled:opacity-50"
        />
        <button
          type="submit"
          disabled={streaming || !input.trim()}
          className="px-4 py-2 bg-zinc-50 text-zinc-900 rounded-lg font-medium hover:bg-zinc-200 disabled:opacity-40 transition-colors text-sm shrink-0"
        >
          {streaming ? '…' : 'Send'}
        </button>
      </form>
    </div>
  )
}
