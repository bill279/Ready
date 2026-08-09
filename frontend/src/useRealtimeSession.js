import { useRef, useState, useCallback, useEffect } from 'react'
import { getSessionId } from './session'

const BACKEND = import.meta.env.VITE_BACKEND_URL || ''
const WS_URL = BACKEND.replace(/^http/, 'ws') + '/ws/realtime'
const SAMPLE_RATE = 24000

export function useRealtimeSession() {
  const wsRef = useRef(null)
  const audioContextRef = useRef(null)
  const mediaStreamRef = useRef(null)
  const processorRef = useRef(null)
  const audioQueueRef = useRef([])
  const isPlayingRef = useRef(false)
  const sourceRef = useRef(null)

  const [state, setState] = useState('idle') // idle | connecting | listening | speaking | thinking
  const [transcript, setTranscript] = useState([])
  const [toolActivity, setToolActivity] = useState(null)
  const [outlookConnected, setOutlookConnected] = useState(false)

  const addMessage = useCallback((role, text) => {
    setTranscript(prev => {
      const last = prev[prev.length - 1]
      if (last && last.role === role && last.streaming) {
        return [...prev.slice(0, -1), { ...last, text: last.text + text }]
      }
      return [...prev, { role, text, id: Date.now(), streaming: role === 'assistant' }]
    })
  }, [])

  const finalizeMessage = useCallback((role) => {
    setTranscript(prev => prev.map((m, i) =>
      i === prev.length - 1 && m.role === role ? { ...m, streaming: false } : m
    ))
  }, [])

  const playAudioChunk = useCallback(async (base64Audio) => {
    if (!audioContextRef.current) {
      audioContextRef.current = new AudioContext({ sampleRate: SAMPLE_RATE })
    }
    const ctx = audioContextRef.current
    const raw = atob(base64Audio)
    const pcm = new Int16Array(raw.length / 2)
    for (let i = 0; i < pcm.length; i++) {
      pcm[i] = (raw.charCodeAt(i * 2) | (raw.charCodeAt(i * 2 + 1) << 8))
    }
    const float32 = new Float32Array(pcm.length)
    for (let i = 0; i < pcm.length; i++) float32[i] = pcm[i] / 32768

    const buffer = ctx.createBuffer(1, float32.length, SAMPLE_RATE)
    buffer.getChannelData(0).set(float32)
    audioQueueRef.current.push(buffer)

    if (!isPlayingRef.current) playNextChunk(ctx)
  }, [])

  const playNextChunk = (ctx) => {
    if (audioQueueRef.current.length === 0) {
      isPlayingRef.current = false
      return
    }
    isPlayingRef.current = true
    setState('speaking')
    const buffer = audioQueueRef.current.shift()
    const source = ctx.createBufferSource()
    source.buffer = buffer
    source.connect(ctx.destination)
    sourceRef.current = source
    source.onended = () => playNextChunk(ctx)
    source.start()
  }

  const stopAudio = useCallback(() => {
    audioQueueRef.current = []
    if (sourceRef.current) {
      try { sourceRef.current.stop() } catch {}
    }
    isPlayingRef.current = false
  }, [])

  const checkOutlook = useCallback(async () => {
    try {
      const r = await fetch(`${BACKEND}/auth/status?session=${encodeURIComponent(getSessionId())}`)
      const data = await r.json()
      setOutlookConnected(data.outlook_connected)
    } catch {}
  }, [])

  // Reflect the real connection state in the header before the user taps connect.
  useEffect(() => { checkOutlook() }, [checkOutlook])

  const connect = useCallback(async () => {
    setState('connecting')

    await checkOutlook()

    const ws = new WebSocket(`${WS_URL}?session=${encodeURIComponent(getSessionId())}`)
    wsRef.current = ws

    ws.onopen = () => {
      setState('listening')
      startMic(ws)
    }

    ws.onmessage = async (event) => {
      const msg = JSON.parse(event.data)
      handleServerEvent(msg)
    }

    ws.onclose = () => {
      setState('idle')
      stopMic()
    }

    ws.onerror = () => setState('idle')
  }, [checkOutlook])

  const handleServerEvent = useCallback((event) => {
    const t = event.type

    if (t === 'input_audio_buffer.speech_started') {
      stopAudio()
      setState('listening')
    }
    if (t === 'conversation.item.input_audio_transcription.completed') {
      addMessage('user', event.transcript)
    }
    if (t === 'response.audio_transcript.delta') {
      addMessage('assistant', event.delta)
      setState('speaking')
    }
    if (t === 'response.audio_transcript.done') {
      finalizeMessage('assistant')
    }
    if (t === 'response.audio.delta') {
      playAudioChunk(event.delta)
    }
    if (t === 'response.audio.done') {
      setTimeout(() => {
        if (audioQueueRef.current.length === 0 && !isPlayingRef.current) {
          setState('listening')
        }
      }, 500)
    }
    if (t === 'response.function_call_arguments.done') {
      setState('thinking')
      setToolActivity({ tool: event.name, status: 'running' })
    }
    if (t === 'response.done') {
      setToolActivity(null)
      if (state !== 'speaking') setState('listening')
    }
    if (t === 'error') {
      console.error('OpenAI error:', event)
      setState('listening')
    }
  }, [addMessage, finalizeMessage, playAudioChunk, stopAudio, state])

  const startMic = async (ws) => {
    try {
      const stream = await navigator.mediaDevices.getUserMedia({ audio: true })
      mediaStreamRef.current = stream
      const ctx = new AudioContext({ sampleRate: SAMPLE_RATE })
      audioContextRef.current = ctx

      const source = ctx.createMediaStreamSource(stream)
      const processor = ctx.createScriptProcessor(4096, 1, 1)
      processorRef.current = processor

      processor.onaudioprocess = (e) => {
        if (ws.readyState !== WebSocket.OPEN) return
        const float32 = e.inputBuffer.getChannelData(0)
        const pcm = new Int16Array(float32.length)
        for (let i = 0; i < float32.length; i++) {
          pcm[i] = Math.max(-32768, Math.min(32767, float32[i] * 32768))
        }
        const b64 = btoa(String.fromCharCode(...new Uint8Array(pcm.buffer)))
        ws.send(JSON.stringify({ type: 'input_audio_buffer.append', audio: b64 }))
      }

      source.connect(processor)
      processor.connect(ctx.destination)
    } catch (err) {
      console.error('Mic error:', err)
      setState('idle')
    }
  }

  const stopMic = () => {
    if (mediaStreamRef.current) {
      mediaStreamRef.current.getTracks().forEach(t => t.stop())
      mediaStreamRef.current = null
    }
    if (processorRef.current) {
      processorRef.current.disconnect()
      processorRef.current = null
    }
  }

  const disconnect = useCallback(() => {
    if (wsRef.current) wsRef.current.close()
    stopMic()
    stopAudio()
    setState('idle')
  }, [stopAudio])

  const interrupt = useCallback(() => {
    stopAudio()
    if (wsRef.current?.readyState === WebSocket.OPEN) {
      wsRef.current.send(JSON.stringify({ type: 'response.cancel' }))
    }
  }, [stopAudio])

  return { state, transcript, toolActivity, outlookConnected, connect, disconnect, interrupt }
}
