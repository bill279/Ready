import React, { useEffect, useRef } from 'react'

const BACKEND = import.meta.env.VITE_BACKEND_URL || ''
import { Mic, MicOff, Zap, Globe, Mail, Calendar, AlertCircle, CheckCircle } from 'lucide-react'
import { useRealtimeSession } from './useRealtimeSession'

const TOOL_ICONS = {
  web_search: Globe,
  send_email: Mail,
  list_emails: Mail,
  list_calendar_events: Calendar,
  create_calendar_event: Calendar,
}

const TOOL_LABELS = {
  web_search: 'Searching the web',
  send_email: 'Sending email',
  list_emails: 'Reading inbox',
  list_calendar_events: 'Checking calendar',
  create_calendar_event: 'Creating event',
}

function StatusDot({ state }) {
  if (state === 'idle') return null
  if (state === 'connecting') return (
    <div className="flex items-center gap-2 text-slate-400 text-sm">
      <div className="w-2 h-2 rounded-full bg-yellow-400 animate-pulse" />
      Connecting...
    </div>
  )
  if (state === 'listening') return (
    <div className="flex items-center gap-2 text-slate-400 text-sm">
      <div className="w-2 h-2 rounded-full bg-green-400 animate-pulse" />
      Listening
    </div>
  )
  if (state === 'speaking') return (
    <div className="flex items-center gap-2 text-slate-400 text-sm">
      <div className="flex gap-0.5 items-end h-6">
        {[...Array(6)].map((_, i) => (
          <div key={i} className="w-1 bg-indigo-400 rounded-full wave-bar" style={{ height: '4px' }} />
        ))}
      </div>
      Speaking
    </div>
  )
  if (state === 'thinking') return (
    <div className="flex items-center gap-2 text-slate-400 text-sm">
      <div className="w-2 h-2 rounded-full bg-purple-400 animate-pulse" />
      Thinking
    </div>
  )
  return null
}

function Message({ msg }) {
  const isUser = msg.role === 'user'
  return (
    <div className={`flex ${isUser ? 'justify-end' : 'justify-start'} mb-3`}>
      <div className={`max-w-[85%] px-4 py-2.5 rounded-2xl text-sm leading-relaxed ${
        isUser
          ? 'bg-indigo-600 text-white rounded-br-sm'
          : 'bg-slate-800 text-slate-100 rounded-bl-sm'
      }`}>
        {msg.text}
        {msg.streaming && <span className="inline-block w-1 h-4 ml-1 bg-current animate-pulse rounded" />}
      </div>
    </div>
  )
}

export default function App() {
  const { state, transcript, toolActivity, outlookConnected, connect, disconnect, interrupt } = useRealtimeSession()
  const bottomRef = useRef(null)
  const isActive = state !== 'idle'

  useEffect(() => {
    bottomRef.current?.scrollIntoView({ behavior: 'smooth' })
  }, [transcript])

  // Handle OAuth callback from Azure — /auth/callback?code=...
  useEffect(() => {
    const path = window.location.pathname
    const params = new URLSearchParams(window.location.search)
    const code = params.get('code')
    if (path === '/auth/callback' && code) {
      window.history.replaceState({}, '', '/')
      fetch(`${BACKEND}/auth/outlook/exchange`, {
        method: 'POST',
        headers: { 'Content-Type': 'application/json' },
        body: JSON.stringify({ code }),
      })
        .then(r => r.json())
        .then(data => {
          if (data.status === 'connected') window.location.reload()
        })
        .catch(console.error)
    }
  }, [])

  return (
    <div className="flex flex-col h-full max-w-2xl mx-auto">
      {/* Header */}
      <div className="flex items-center justify-between px-4 py-4 border-b border-slate-800">
        <div className="flex items-center gap-2">
          <Zap size={20} className="text-indigo-400" />
          <span className="font-semibold text-slate-100">Executive Assistant</span>
        </div>
        <div className="flex items-center gap-3">
          <StatusDot state={state} />
          {!outlookConnected ? (
            <a
              href={`${BACKEND}/auth/outlook`}
              className="flex items-center gap-1.5 text-xs text-slate-400 hover:text-slate-200 transition-colors border border-slate-700 hover:border-slate-500 px-2.5 py-1.5 rounded-lg"
            >
              <AlertCircle size={12} className="text-yellow-400" />
              Connect Outlook
            </a>
          ) : (
            <div className="flex items-center gap-1.5 text-xs text-slate-500">
              <CheckCircle size={12} className="text-green-400" />
              Outlook
            </div>
          )}
        </div>
      </div>

      {/* Transcript */}
      <div className="flex-1 overflow-y-auto px-4 py-4 space-y-1">
        {transcript.length === 0 && (
          <div className="flex flex-col items-center justify-center h-full text-center gap-4 text-slate-500">
            <Mic size={40} className="text-slate-700" />
            <div>
              <p className="text-slate-300 font-medium mb-1">Ready when you are</p>
              <p className="text-sm">Tap the button and start talking.<br />Ask me anything or tell me to check your email.</p>
            </div>
            <div className="grid grid-cols-2 gap-2 mt-4 w-full max-w-sm">
              {[
                "What's in my inbox?",
                "Search latest AI news",
                "Schedule a meeting tomorrow",
                "Send an email to...",
              ].map(s => (
                <div key={s} className="text-xs bg-slate-800 text-slate-400 px-3 py-2 rounded-lg">{s}</div>
              ))}
            </div>
          </div>
        )}
        {transcript.map(msg => <Message key={msg.id} msg={msg} />)}

        {/* Tool activity */}
        {toolActivity && (
          <div className="flex justify-start mb-3">
            <div className="flex items-center gap-2 bg-slate-800 text-slate-400 text-xs px-3 py-2 rounded-full border border-slate-700">
              {(() => {
                const Icon = TOOL_ICONS[toolActivity.tool] || Zap
                return <Icon size={12} className="text-purple-400 animate-pulse" />
              })()}
              {TOOL_LABELS[toolActivity.tool] || toolActivity.tool}...
            </div>
          </div>
        )}

        <div ref={bottomRef} />
      </div>

      {/* Controls */}
      <div className="px-4 py-6 border-t border-slate-800 flex flex-col items-center gap-3">
        <button
          onClick={isActive ? (state === 'speaking' ? interrupt : disconnect) : connect}
          className={`w-20 h-20 rounded-full flex items-center justify-center transition-all duration-200 ${
            isActive
              ? state === 'speaking'
                ? 'bg-purple-600 hover:bg-purple-700 pulse-ring'
                : 'bg-red-600 hover:bg-red-700'
              : 'bg-indigo-600 hover:bg-indigo-700'
          }`}
        >
          {isActive ? (
            state === 'speaking'
              ? <div className="flex gap-1 items-end h-8">
                  {[...Array(4)].map((_, i) => (
                    <div key={i} className="w-1.5 bg-white rounded-full wave-bar" />
                  ))}
                </div>
              : <MicOff size={28} className="text-white" />
          ) : (
            <Mic size={28} className="text-white" />
          )}
        </button>
        <p className="text-xs text-slate-600">
          {!isActive ? 'Tap to start' :
           state === 'speaking' ? 'Tap to interrupt' :
           'Tap to stop'}
        </p>
      </div>
    </div>
  )
}
