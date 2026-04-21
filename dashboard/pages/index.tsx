import { useState, useEffect, useRef } from 'react'

interface Clinic {
  name: string
  address: string
  phone: string
  distance_miles?: number
  reason?: string
  lat?: number
  lng?: number
}

interface ConversationMessage {
  id?: string
  role: string
  content: string
  timestamp?: number
  isOptimistic?: boolean
}

interface CallState {
  status: string
  caller_number: string
  conversation: ConversationMessage[]
  current_clinic: Clinic | null
  calculating?: boolean
  claude_analysis: {
    action?: string
    user_zip?: string
    monthly_income?: number
    language?: string
    candidates?: Clinic[]
  }
  created_at?: number
  last_activity?: number
  total_messages?: number
  session_metadata?: {
    user_location?: string
    service_needed?: string
    eligibility_status?: string
    clinic_preferences?: string[]
  }
}

interface ActiveCall {
  call_sid: string
  caller: string
  status: string
}

export default function Dashboard() {
  const [activeCalls, setActiveCalls] = useState<ActiveCall[]>([])
  const [selectedCallSid, setSelectedCallSid] = useState<string | null>(null)
  const [callState, setCallState] = useState<CallState | null>(null)
  const [error, setError] = useState<string | null>(null)
  const [wsConnected, setWsConnected] = useState(false)
  const [showClearModal, setShowClearModal] = useState(false)
  const [clearing, setClearing] = useState(false)
  const [callingOut, setCallingOut] = useState(false)
  const [notification, setNotification] = useState<{type: 'success' | 'error', message: string} | null>(null)
  const [lastPolled, setLastPolled] = useState<number>(0)
  const [isAgentTyping, setIsAgentTyping] = useState(false)
  const pollingRef = useRef<NodeJS.Timeout | null>(null)
  const wsRef = useRef<WebSocket | null>(null)
  const reconnectTimeoutRef = useRef<NodeJS.Timeout | null>(null)
  const messagesEndRef = useRef<HTMLDivElement>(null)
  const conversationRef = useRef<HTMLDivElement>(null)

  // WebSocket connection for real-time updates
  useEffect(() => {
    const connectWebSocket = () => {
      try {
        console.log('[DEBUG] Connecting to dashboard WebSocket...')
        const ws = new WebSocket('ws://localhost:8000/dashboard')
        wsRef.current = ws

        ws.onopen = () => {
          console.log('[DEBUG] Dashboard WebSocket connected')
          setWsConnected(true)
          setError(null)

          // Send ping to keep connection alive
          ws.send(JSON.stringify({ type: 'ping' }))
        }

        ws.onmessage = (event) => {
          try {
            const data = JSON.parse(event.data)
            console.log('[DEBUG] Received WebSocket update:', data.type, data)

            switch (data.type) {
              case 'pong':
                // Heartbeat response
                break

              case 'call_connected':
                console.log('[DEBUG] Call connected:', data.call_sid)
                // Update active calls if this is a new call
                setActiveCalls(prev => {
                  const exists = prev.find(call => call.call_sid === data.call_sid)
                  if (!exists) {
                    const newCall: ActiveCall = {
                      call_sid: data.call_sid,
                      caller: data.caller_number || 'Unknown',
                      status: 'connected'
                    }
                    return [...prev, newCall]
                  }
                  return prev.map(call =>
                    call.call_sid === data.call_sid
                      ? { ...call, status: 'connected' }
                      : call
                  )
                })

                // Auto-select if no call selected
                if (!selectedCallSid) {
                  setSelectedCallSid(data.call_sid)
                }
                break

              case 'conversation_update':
                console.log('[DEBUG] Conversation update for:', data.call_sid)
                if (data.call_sid === selectedCallSid) {
                  // Batch all updates together for immediate rendering
                  setCallState(prev => {
                    if (!prev) return null

                    // Merge new messages efficiently
                    let updatedConversation = prev.conversation || []
                    if (data.latest_messages && Array.isArray(data.latest_messages)) {
                      const existingIds = new Set(updatedConversation.map(msg => msg.id).filter(Boolean))
                      const newMessages = data.latest_messages.filter(msg =>
                        !msg.id || !existingIds.has(msg.id)
                      )
                      updatedConversation = [...updatedConversation, ...newMessages]
                    }

                    return {
                      ...prev,
                      conversation: updatedConversation,
                      calculating: data.calculating || false,
                      claude_analysis: data.claude_analysis || prev.claude_analysis || {},
                      session_metadata: data.session_metadata || prev.session_metadata,
                      total_messages: data.total_messages || prev.total_messages || 0,
                      last_activity: data.timestamp || prev.last_activity,
                      current_clinic: data.clinic || prev.current_clinic
                    }
                  })
                }
                break

              case 'call_status_change':
                console.log('[DEBUG] Call status change:', data.status, 'for:', data.call_sid)
                // Update call status
                setActiveCalls(prev =>
                  prev.map(call =>
                    call.call_sid === data.call_sid
                      ? { ...call, status: data.status }
                      : call
                  )
                )

                if (data.call_sid === selectedCallSid) {
                  setCallState(prev => prev ? {
                    ...prev,
                    status: data.status,
                    current_clinic: data.clinic || prev.current_clinic
                  } : null)
                }
                break

              case 'sessions_cleared':
                console.log('[DEBUG] Sessions cleared:', data.cleared_count)
                setActiveCalls([])
                setCallState(null)
                setSelectedCallSid(null)
                setNotification({
                  type: 'success',
                  message: `Cleared ${data.cleared_count} sessions successfully`
                })
                setTimeout(() => setNotification(null), 3000)
                break
            }
          } catch (err) {
            console.error('[ERROR] Failed to parse WebSocket message:', err)
          }
        }

        ws.onclose = () => {
          console.log('[DEBUG] Dashboard WebSocket disconnected')
          setWsConnected(false)
          wsRef.current = null

          // Reconnect after 3 seconds
          if (!reconnectTimeoutRef.current) {
            reconnectTimeoutRef.current = setTimeout(() => {
              reconnectTimeoutRef.current = null
              connectWebSocket()
            }, 3000)
          }
        }

        ws.onerror = (error) => {
          console.error('[ERROR] Dashboard WebSocket error:', error)
          setError('WebSocket connection failed')
        }

      } catch (err) {
        console.error('[ERROR] Failed to create WebSocket:', err)
        setError(`WebSocket connection failed: ${err.message}`)
      }
    }

    connectWebSocket()

    // Cleanup on unmount
    return () => {
      if (wsRef.current) {
        wsRef.current.close()
        wsRef.current = null
      }
      if (reconnectTimeoutRef.current) {
        clearTimeout(reconnectTimeoutRef.current)
        reconnectTimeoutRef.current = null
      }
    }
  }, [])

  // Initial data loading when call is selected (fallback if WebSocket hasn't provided data)
  useEffect(() => {
    if (!selectedCallSid) {
      console.log('[DEBUG] No call selected, clearing call state')
      setCallState(null)
      return
    }

    // Only fetch if we don't already have call state data (WebSocket should provide this)
    if (!callState) {
      const fetchInitialCallState = async () => {
        try {
          console.log(`[DEBUG] Fetching initial call state for: ${selectedCallSid}`)
          const response = await fetch(`http://localhost:8000/call-state/${selectedCallSid}`)

          if (!response.ok) {
            throw new Error(`HTTP ${response.status}: ${response.statusText}`)
          }

          const data = await response.json()
          console.log('[DEBUG] Initial call state response:', data)

          if (data.error) {
            console.log('[DEBUG] Call state error:', data.error)
            setError(`Call not found: ${data.error}`)
            setCallState(null)
          } else {
            setCallState(data)
            setError(null)
          }
        } catch (err) {
          console.error('[ERROR] Failed to fetch initial call state:', err)
          setError(`Failed to fetch call details: ${err.message}`)
        }
      }

      fetchInitialCallState()
    }
  }, [selectedCallSid])

  // Initial active calls loading (fallback if WebSocket hasn't provided data)
  useEffect(() => {
    if (activeCalls.length === 0 && wsConnected) {
      const fetchInitialActiveCalls = async () => {
        try {
          console.log('[DEBUG] Fetching initial active calls...')
          const response = await fetch('http://localhost:8000/active-calls')

          if (!response.ok) {
            throw new Error(`HTTP ${response.status}: ${response.statusText}`)
          }

          const data = await response.json()
          console.log('[DEBUG] Initial active calls response:', data)
          setActiveCalls(data.calls || [])

          // Auto-select first call if none selected
          if (!selectedCallSid && data.calls && data.calls.length > 0) {
            console.log('[DEBUG] Auto-selecting first call:', data.calls[0].call_sid)
            setSelectedCallSid(data.calls[0].call_sid)
          }
        } catch (err) {
          console.error('[ERROR] Failed to fetch initial active calls:', err)
        }
      }

      fetchInitialActiveCalls()
    }
  }, [wsConnected])

  // Hybrid polling system - silent backup for WebSocket
  useEffect(() => {
    if (!selectedCallSid) {
      if (pollingRef.current) {
        clearInterval(pollingRef.current)
        pollingRef.current = null
      }
      return
    }

    const pollForUpdates = async () => {
      if (!selectedCallSid) return

      try {
        const response = await fetch(`http://localhost:8000/call-state/${selectedCallSid}`)
        if (!response.ok) return

        const data = await response.json()
        if (data.error) return

        const currentTime = Date.now()
        const dataTime = (data.last_activity || 0) * 1000

        // Only update if we have newer data than our last poll
        if (dataTime > lastPolled) {
          setLastPolled(dataTime)

          // Smart merge - only if WebSocket hasn't provided this data already
          setCallState(prev => {
            if (!prev) return data

            const prevTime = (prev.last_activity || 0) * 1000
            if (dataTime <= prevTime) return prev // WebSocket is ahead

            // Merge conversations intelligently
            let mergedConversation = prev.conversation || []
            if (data.conversation && data.conversation.length > mergedConversation.length) {
              mergedConversation = data.conversation
            }

            return {
              ...prev,
              ...data,
              conversation: mergedConversation
            }
          })
        }
      } catch (err) {
        // Silent fail - don't log polling errors
      }
    }

    // Start immediate poll, then every 1.5 seconds
    pollForUpdates()
    pollingRef.current = setInterval(pollForUpdates, 1500)

    return () => {
      if (pollingRef.current) {
        clearInterval(pollingRef.current)
        pollingRef.current = null
      }
    }
  }, [selectedCallSid, lastPolled])

  // Optimistic UI updates for instant feedback
  const addOptimisticMessage = (role: 'user' | 'assistant', content: string) => {
    const optimisticMessage: ConversationMessage = {
      id: `opt_${Date.now()}_${Math.random()}`,
      role,
      content,
      timestamp: Date.now() / 1000,
      isOptimistic: true
    }

    setCallState(prev => prev ? {
      ...prev,
      conversation: [...(prev.conversation || []), optimisticMessage]
    } : null)
  }

  // Handle optimistic updates from WebSocket messages
  useEffect(() => {
    if (!wsRef.current) return

    const ws = wsRef.current
    const handleOptimisticUpdate = (event: MessageEvent) => {
      try {
        const data = JSON.parse(event.data)

        // Show typing indicator when user speaks and agent is processing
        if (data.type === 'user_message_received') {
          setIsAgentTyping(true)
          // Optionally add optimistic user message if not already shown
        }

        // Hide typing when agent response arrives
        if (data.type === 'conversation_update' && data.latest_messages) {
          setIsAgentTyping(false)

          // Clear optimistic messages that are now confirmed
          setCallState(prev => prev ? {
            ...prev,
            conversation: (prev.conversation || []).map(msg =>
              msg.isOptimistic ? { ...msg, isOptimistic: false } : msg
            )
          } : prev)
        }
      } catch (e) {
        // Silent fail
      }
    }

    ws.addEventListener('message', handleOptimisticUpdate)
    return () => ws.removeEventListener('message', handleOptimisticUpdate)
  }, [wsRef.current])

  // Auto-scroll to bottom when new messages arrive
  useEffect(() => {
    if (messagesEndRef.current) {
      messagesEndRef.current.scrollIntoView({ behavior: 'smooth' })
    }
  }, [callState?.conversation?.length, callState?.calculating])

  const getCurrentState = (): 'no-call' | 'connecting' | 'connected' | 'ended' => {
    if (!activeCalls.length || !callState) return 'no-call'
    if (callState.status === 'connecting') return 'connecting'
    if (callState.status === 'connected' || callState.status === 'in_progress') return 'connected'
    return 'ended'
  }

  const getEndedStatusColor = (status: string) => {
    switch (status) {
      case 'transferred': return '#22c55e'  // green
      case 'sms_sent': return '#8b5cf6'    // purple
      case 'disconnected': return '#ef4444' // red
      case 'completed': return '#3b82f6'   // blue
      default: return '#6b7280'            // gray
    }
  }

  const getEndedStatusText = (status: string) => {
    switch (status) {
      case 'transferred': return '📞 Call transferred to clinic'
      case 'sms_sent': return '📱 Clinic details sent via SMS'
      case 'disconnected': return '❌ Call disconnected'
      case 'completed': return '✅ Call completed successfully'
      default: return `📋 Call ${status}`
    }
  }

  const formatPhoneNumber = (phone: string) => {
    if (!phone) return 'N/A'
    return phone.replace(/(\d{3})(\d{3})(\d{4})/, '($1) $2-$3')
  }

  // Outbound call functionality
  const handleOutboundCall = async () => {
    setCallingOut(true)
    try {
      const response = await fetch('http://localhost:8000/outbound-call', {
        method: 'POST'
      })

      if (!response.ok) {
        const errorData = await response.json()
        throw new Error(errorData.error || 'Failed to create outbound call')
      }

      const result = await response.json()
      console.log('[DEBUG] Outbound call successful:', result)

      setNotification({
        type: 'success',
        message: `Outbound call initiated to ${result.to_number}`
      })
      setTimeout(() => setNotification(null), 3000)

    } catch (error) {
      console.error('[ERROR] Failed to create outbound call:', error)
      setNotification({
        type: 'error',
        message: `Failed to create outbound call: ${error.message}`
      })
      setTimeout(() => setNotification(null), 5000)
    }
    setCallingOut(false)
  }

  // Clear sessions functionality
  const handleClearSessions = async () => {
    setClearing(true)
    try {
      const response = await fetch('http://localhost:8000/clear-sessions', {
        method: 'DELETE'
      })

      if (!response.ok) {
        const errorData = await response.json()
        throw new Error(errorData.message || 'Failed to clear sessions')
      }

      const result = await response.json()
      console.log('[DEBUG] Clear sessions successful:', result)

      // WebSocket will handle state clearing, but add fallback
      if (!wsConnected) {
        setActiveCalls([])
        setCallState(null)
        setSelectedCallSid(null)
        setNotification({
          type: 'success',
          message: `Cleared ${result.details.total_cleared} sessions successfully`
        })
        setTimeout(() => setNotification(null), 3000)
      }

    } catch (error) {
      console.error('[ERROR] Failed to clear sessions:', error)
      setNotification({
        type: 'error',
        message: `Failed to clear sessions: ${error.message}`
      })
      setTimeout(() => setNotification(null), 5000)
    }
    setClearing(false)
    setShowClearModal(false)
  }

  const currentState = getCurrentState()

  return (
    <div style={{
      minHeight: '100vh',
      backgroundColor: '#0f172a',
      color: '#ffffff',
      fontFamily: '-apple-system, BlinkMacSystemFont, "Segoe UI", Roboto, sans-serif',
      position: 'relative'
    }}>
      {/* Header */}
      <div style={{
        backgroundColor: '#1e293b',
        padding: '1rem 2rem',
        borderBottom: '1px solid #334155',
        display: 'flex',
        alignItems: 'center',
        justifyContent: 'space-between'
      }}>
        <h1 style={{
          fontSize: '1.5rem',
          fontWeight: 'bold',
          margin: 0,
          color: '#ffffff'
        }}>
          Call2Well
        </h1>
        <div style={{
          fontSize: '0.875rem',
          color: '#94a3b8',
          display: 'flex',
          alignItems: 'center',
          gap: '1rem'
        }}>

          {/* Clear button */}
          <button
            onClick={() => setShowClearModal(true)}
            disabled={clearing || (activeCalls.length === 0 && !callState)}
            style={{
              background: clearing ? '#6b7280' : 'linear-gradient(135deg, #dc2626, #b91c1c)',
              border: '1px solid #dc2626',
              borderRadius: '0.5rem',
              padding: '0.5rem 0.75rem',
              fontSize: '0.75rem',
              color: '#ffffff',
              cursor: clearing ? 'not-allowed' : 'pointer',
              opacity: clearing || (activeCalls.length === 0 && !callState) ? 0.5 : 1,
              display: 'flex',
              alignItems: 'center',
              gap: '0.375rem',
              transition: 'all 0.2s ease',
              boxShadow: '0 2px 4px rgba(220, 38, 38, 0.2)'
            }}
            onMouseEnter={(e) => {
              if (!clearing && (activeCalls.length > 0 || callState)) {
                e.currentTarget.style.transform = 'translateY(-1px)'
                e.currentTarget.style.boxShadow = '0 4px 8px rgba(220, 38, 38, 0.3)'
              }
            }}
            onMouseLeave={(e) => {
              e.currentTarget.style.transform = 'translateY(0)'
              e.currentTarget.style.boxShadow = '0 2px 4px rgba(220, 38, 38, 0.2)'
            }}
          >
            {clearing ? '⏳' : '🗑️'}
            {clearing ? 'Clearing...' : 'Clear All'}
          </button>

          <span style={{
            opacity: currentState === 'no-call' ? 0.6 : 1,
            transition: 'opacity 0.3s ease'
          }}>
            Live Dashboard
          </span>
          <div style={{
            fontSize: '0.75rem',
            color: error ? '#ef4444' : wsConnected ? '#22c55e' : '#f59e0b'
          }}>
            {error ? '🔴 Error' : wsConnected ? (activeCalls.length > 0 ? '🟢 Live' : '🟢 Ready') : '🟡 Connecting...'}
          </div>
        </div>
      </div>


      {/* Main Content */}
      <div style={{
        padding: '2rem',
        display: 'flex',
        justifyContent: 'center',
        alignItems: 'center',
        minHeight: 'calc(100vh - 80px)'
      }}>
        <div style={{
          width: '100%',
          maxWidth: '800px'
        }}>
          {/* No Call State */}
          {currentState === 'no-call' && (
            <div style={{
              textAlign: 'center',
              opacity: 0,
              animation: 'shimmerIn 2s ease-in-out forwards'
            }}>
              <div style={{
                fontSize: '4rem',
                marginBottom: '1rem'
              }}>
                📵
              </div>
              <p style={{
                fontSize: '1.25rem',
                color: '#94a3b8',
                margin: 0
              }}>
                Waiting for incoming call…
              </p>
            </div>
          )}

          {/* Connecting State */}
          {currentState === 'connecting' && (
            <div style={{
              textAlign: 'center',
              position: 'relative'
            }}>
              <div style={{
                position: 'relative',
                display: 'inline-block'
              }}>
                {/* Ripple rings */}
                <div style={{
                  position: 'absolute',
                  top: '50%',
                  left: '50%',
                  transform: 'translate(-50%, -50%)',
                  width: '200px',
                  height: '200px'
                }}>
                  <div style={{
                    position: 'absolute',
                    top: 0,
                    left: 0,
                    right: 0,
                    bottom: 0,
                    borderRadius: '50%',
                    border: '3px solid #22c55e',
                    animation: 'ripple 2s linear infinite'
                  }} />
                  <div style={{
                    position: 'absolute',
                    top: 0,
                    left: 0,
                    right: 0,
                    bottom: 0,
                    borderRadius: '50%',
                    border: '3px solid #22c55e',
                    animation: 'ripple 2s linear infinite',
                    animationDelay: '0.5s'
                  }} />
                  <div style={{
                    position: 'absolute',
                    top: 0,
                    left: 0,
                    right: 0,
                    bottom: 0,
                    borderRadius: '50%',
                    border: '3px solid #22c55e',
                    animation: 'ripple 2s linear infinite',
                    animationDelay: '1s'
                  }} />
                </div>

                {/* Phone emoji */}
                <div style={{
                  fontSize: '6rem',
                  animation: 'shake 0.5s ease-in-out infinite alternate',
                  position: 'relative',
                  zIndex: 10
                }}>
                  📞
                </div>
              </div>
            </div>
          )}

          {/* Connected State */}
          {currentState === 'connected' && (
            <div style={{
              display: 'flex',
              flexDirection: 'column',
              height: '70vh'
            }}>
              {/* Meta chips */}
              <div style={{
                display: 'flex',
                gap: '0.5rem',
                marginBottom: '1rem',
                flexWrap: 'wrap'
              }}>
                {callState?.session_metadata?.user_location && (
                  <div style={{
                    backgroundColor: '#1e293b',
                    border: '1px solid #334155',
                    borderRadius: '1rem',
                    padding: '0.25rem 0.75rem',
                    fontSize: '0.875rem',
                    color: '#94a3b8'
                  }}>
                    📍 {callState.session_metadata.user_location}
                  </div>
                )}
                {callState?.claude_analysis?.language && (
                  <div style={{
                    backgroundColor: '#1e293b',
                    border: '1px solid #334155',
                    borderRadius: '1rem',
                    padding: '0.25rem 0.75rem',
                    fontSize: '0.875rem',
                    color: '#94a3b8'
                  }}>
                    🌐 {callState.claude_analysis.language}
                  </div>
                )}
                {callState?.session_metadata?.service_needed && (
                  <div style={{
                    backgroundColor: '#1e293b',
                    border: '1px solid #334155',
                    borderRadius: '1rem',
                    padding: '0.25rem 0.75rem',
                    fontSize: '0.875rem',
                    color: '#94a3b8'
                  }}>
                    🏥 {callState.session_metadata.service_needed.replace('_', ' ')}
                  </div>
                )}
                {callState?.claude_analysis?.monthly_income && (
                  <div style={{
                    backgroundColor: '#1e293b',
                    border: '1px solid #334155',
                    borderRadius: '1rem',
                    padding: '0.25rem 0.75rem',
                    fontSize: '0.875rem',
                    color: '#94a3b8'
                  }}>
                    💰 ${callState.claude_analysis.monthly_income}/mo
                  </div>
                )}
                {callState?.session_metadata?.eligibility_status && (
                  <div style={{
                    backgroundColor: '#1e293b',
                    border: '1px solid #334155',
                    borderRadius: '1rem',
                    padding: '0.25rem 0.75rem',
                    fontSize: '0.875rem',
                    color: callState.session_metadata.eligibility_status === 'medicaid_eligible' ? '#22c55e' :
                          callState.session_metadata.eligibility_status === 'fqhc_eligible' ? '#3b82f6' : '#94a3b8'
                  }}>
                    {callState.session_metadata.eligibility_status === 'medicaid_eligible' ? '✅ Medicaid Eligible' :
                     callState.session_metadata.eligibility_status === 'fqhc_eligible' ? '✅ FQHC Eligible' :
                     '💳 Sliding Scale Only'}
                  </div>
                )}
              </div>

              {/* Chat messages */}
              <div
                ref={conversationRef}
                style={{
                  flex: 1,
                  overflowY: 'auto',
                  padding: '1rem 0',
                  display: 'flex',
                  flexDirection: 'column',
                  gap: '1rem',
                  scrollBehavior: 'smooth'
                }}>
                {callState?.conversation?.map((msg, idx) => (
                  <div key={msg.id || idx} style={{
                    display: 'flex',
                    justifyContent: msg.role === 'user' ? 'flex-end' : 'flex-start',
                    opacity: 0,
                    animation: `fadeInSlide${msg.role === 'user' ? 'Right' : 'Left'} 0.5s ease-out forwards`,
                    animationDelay: `${Math.min(idx * 0.1, 1)}s`
                  }}>
                    <div style={{
                      maxWidth: '80%',
                      padding: '0.875rem 1.25rem',
                      borderRadius: msg.role === 'user' ? '1.5rem 1.5rem 0.5rem 1.5rem' : '1.5rem 1.5rem 1.5rem 0.5rem',
                      backgroundColor: msg.role === 'user' ? '#3b82f6' : '#374151',
                      color: '#ffffff',
                      fontSize: '0.95rem',
                      lineHeight: '1.5',
                      boxShadow: '0 2px 8px rgba(0, 0, 0, 0.1)',
                      position: 'relative',
                      // Optimistic message styling
                      opacity: msg.isOptimistic ? 0.7 : 1,
                      border: msg.isOptimistic ? '2px dashed rgba(255, 255, 255, 0.3)' : 'none',
                      transition: 'all 0.3s ease'
                    }}>
                      {msg.role === 'assistant' && (
                        <div style={{
                          fontSize: '0.8rem',
                          opacity: 0.7,
                          marginBottom: '0.25rem',
                          color: '#cbd5e1',
                          display: 'flex',
                          alignItems: 'center',
                          gap: '0.5rem'
                        }}>
                          🤖 Call2Well
                          {msg.isOptimistic && <span style={{ fontSize: '0.7rem', opacity: 0.5 }}>⏳</span>}
                        </div>
                      )}
                      {msg.role === 'user' && msg.isOptimistic && (
                        <div style={{
                          fontSize: '0.8rem',
                          opacity: 0.7,
                          marginBottom: '0.25rem',
                          color: '#bfdbfe',
                          display: 'flex',
                          alignItems: 'center',
                          gap: '0.5rem'
                        }}>
                          <span style={{ fontSize: '0.7rem', opacity: 0.5 }}>⏳</span>
                        </div>
                      )}
                      {msg.content}
                      {msg.timestamp && (
                        <div style={{
                          fontSize: '0.75rem',
                          opacity: 0.6,
                          marginTop: '0.25rem',
                          color: msg.role === 'user' ? '#bfdbfe' : '#9ca3af'
                        }}>
                          {new Date(msg.timestamp * 1000).toLocaleTimeString([], { hour: '2-digit', minute: '2-digit' })}
                        </div>
                      )}
                    </div>
                  </div>
                ))}

                {/* Invisible scroll anchor */}
                <div ref={messagesEndRef} style={{ height: 1 }} />

                {/* Real-time typing indicator */}
                {isAgentTyping && (
                  <div style={{
                    display: 'flex',
                    justifyContent: 'flex-start',
                    animation: 'fadeInSlideLeft 0.3s ease-out'
                  }}>
                    <div style={{
                      padding: '0.875rem 1.25rem',
                      borderRadius: '1.5rem 1.5rem 1.5rem 0.5rem',
                      background: 'linear-gradient(135deg, #374151, #4b5563)',
                      border: '2px solid #6b7280',
                      color: '#f3f4f6',
                      fontSize: '0.95rem',
                      display: 'flex',
                      alignItems: 'center',
                      gap: '0.75rem',
                      boxShadow: '0 4px 12px rgba(0, 0, 0, 0.15)',
                      position: 'relative',
                      maxWidth: '80%'
                    }}>
                      <div style={{
                        fontSize: '1.1rem',
                        animation: 'pulse 2s ease-in-out infinite'
                      }}>
                        🔍
                      </div>

                      <div>
                        <div style={{
                          fontSize: '0.8rem',
                          opacity: 0.7,
                          marginBottom: '0.25rem',
                          color: '#d1d5db'
                        }}>
                          🤖 Call2Well
                        </div>
                        <div style={{
                          display: 'flex',
                          alignItems: 'center',
                          gap: '0.5rem'
                        }}>
                          <span>Thinking</span>
                          <div style={{
                            display: 'flex',
                            gap: '0.2rem'
                          }}>
                            <div style={{
                              width: '4px',
                              height: '4px',
                              borderRadius: '50%',
                              backgroundColor: '#10b981',
                              animation: 'bounce 1.4s ease-in-out infinite both'
                            }} />
                            <div style={{
                              width: '4px',
                              height: '4px',
                              borderRadius: '50%',
                              backgroundColor: '#10b981',
                              animation: 'bounce 1.4s ease-in-out infinite both',
                              animationDelay: '0.16s'
                            }} />
                            <div style={{
                              width: '4px',
                              height: '4px',
                              borderRadius: '50%',
                              backgroundColor: '#10b981',
                              animation: 'bounce 1.4s ease-in-out infinite both',
                              animationDelay: '0.32s'
                            }} />
                          </div>
                        </div>
                      </div>

                      {/* Subtle progress indicator */}
                      <div style={{
                        position: 'absolute',
                        bottom: 0,
                        left: 0,
                        right: 0,
                        height: '2px',
                        backgroundColor: 'rgba(16, 185, 129, 0.2)',
                        borderRadius: '0 0 1.5rem 0.5rem',
                        overflow: 'hidden'
                      }}>
                        <div style={{
                          width: '40%',
                          height: '100%',
                          backgroundColor: '#10b981',
                          animation: 'slideProgress 2s ease-in-out infinite'
                        }} />
                      </div>
                    </div>
                  </div>
                )}

                {/* Enhanced typing indicator */}
                {callState?.calculating && (
                  <div style={{
                    display: 'flex',
                    justifyContent: 'flex-start',
                    animation: 'fadeInSlideLeft 0.3s ease-out'
                  }}>
                    <div style={{
                      padding: '1rem 1.25rem',
                      borderRadius: '1.5rem 1.5rem 1.5rem 0.5rem',
                      background: 'linear-gradient(135deg, #374151, #4b5563)',
                      border: '1px solid #6b7280',
                      color: '#f3f4f6',
                      fontSize: '0.95rem',
                      display: 'flex',
                      alignItems: 'center',
                      gap: '0.75rem',
                      boxShadow: '0 4px 12px rgba(0, 0, 0, 0.15)',
                      position: 'relative'
                    }}>
                      <div style={{
                        fontSize: '1.1rem',
                        animation: 'pulse 2s ease-in-out infinite'
                      }}>
                        🔍
                      </div>

                      <div>
                        <div style={{
                          fontSize: '0.8rem',
                          opacity: 0.7,
                          marginBottom: '0.25rem',
                          color: '#d1d5db'
                        }}>
                          🤖 Call2Well
                        </div>
                        <div style={{
                          display: 'flex',
                          alignItems: 'center',
                          gap: '0.5rem'
                        }}>
                          <span>Analyzing your situation</span>
                          <div style={{
                            display: 'flex',
                            gap: '0.2rem'
                          }}>
                            <div style={{
                              width: '4px',
                              height: '4px',
                              borderRadius: '50%',
                              backgroundColor: '#10b981',
                              animation: 'bounce 1.4s ease-in-out infinite both'
                            }} />
                            <div style={{
                              width: '4px',
                              height: '4px',
                              borderRadius: '50%',
                              backgroundColor: '#10b981',
                              animation: 'bounce 1.4s ease-in-out infinite both',
                              animationDelay: '0.16s'
                            }} />
                            <div style={{
                              width: '4px',
                              height: '4px',
                              borderRadius: '50%',
                              backgroundColor: '#10b981',
                              animation: 'bounce 1.4s ease-in-out infinite both',
                              animationDelay: '0.32s'
                            }} />
                          </div>
                        </div>
                      </div>

                      {/* Subtle progress indicator */}
                      <div style={{
                        position: 'absolute',
                        bottom: 0,
                        left: 0,
                        right: 0,
                        height: '2px',
                        backgroundColor: 'rgba(16, 185, 129, 0.2)',
                        borderRadius: '0 0 1.5rem 0.5rem',
                        overflow: 'hidden'
                      }}>
                        <div style={{
                          width: '40%',
                          height: '100%',
                          backgroundColor: '#10b981',
                          animation: 'slideInRight 2s ease-in-out infinite'
                        }} />
                      </div>
                    </div>
                  </div>
                )}
              </div>

              {/* Enhanced Clinic Card */}
              {callState?.current_clinic && !callState?.calculating && (
                <div style={{
                  background: 'linear-gradient(135deg, #065f46, #047857)',
                  border: '2px solid #10b981',
                  borderRadius: '1rem',
                  padding: '1.5rem',
                  marginTop: '1rem',
                  animation: 'slideUp 0.5s ease-out',
                  boxShadow: '0 8px 32px rgba(16, 185, 129, 0.2)',
                  position: 'relative',
                  overflow: 'hidden'
                }}>
                  {/* Success pulse background */}
                  <div style={{
                    position: 'absolute',
                    top: 0,
                    right: 0,
                    width: '100px',
                    height: '100px',
                    background: 'radial-gradient(circle, rgba(16, 185, 129, 0.3), transparent 70%)',
                    animation: 'pulse 3s ease-in-out infinite'
                  }} />

                  <div style={{
                    display: 'flex',
                    alignItems: 'center',
                    marginBottom: '1rem'
                  }}>
                    <div style={{
                      fontSize: '2rem',
                      marginRight: '0.75rem'
                    }}>
                      🎯
                    </div>
                    <div>
                      <h3 style={{
                        margin: '0',
                        fontSize: '1.25rem',
                        fontWeight: 'bold',
                        color: '#ffffff'
                      }}>
                        {callState.current_clinic.name}
                      </h3>
                      <p style={{
                        margin: '0.25rem 0 0 0',
                        fontSize: '0.875rem',
                        color: '#6ee7b7',
                        fontWeight: '500'
                      }}>
                        ✨ Top Match
                      </p>
                    </div>
                  </div>

                  <div style={{
                    display: 'grid',
                    gap: '0.75rem',
                    marginBottom: '1rem'
                  }}>
                    <div style={{
                      display: 'flex',
                      alignItems: 'center',
                      gap: '0.5rem'
                    }}>
                      <span style={{ fontSize: '1.1rem' }}>📍</span>
                      <span style={{
                        fontSize: '0.9rem',
                        color: '#d1fae5'
                      }}>
                        {callState.current_clinic.address}
                      </span>
                    </div>

                    <div style={{
                      display: 'flex',
                      alignItems: 'center',
                      gap: '0.5rem'
                    }}>
                      <span style={{ fontSize: '1.1rem' }}>📞</span>
                      <span style={{
                        fontSize: '0.9rem',
                        color: '#d1fae5',
                        fontWeight: '500'
                      }}>
                        {formatPhoneNumber(callState.current_clinic.phone)}
                      </span>
                    </div>

                    {callState.current_clinic.distance_miles && (
                      <div style={{
                        display: 'flex',
                        alignItems: 'center',
                        gap: '0.5rem'
                      }}>
                        <span style={{ fontSize: '1.1rem' }}>🚗</span>
                        <span style={{
                          fontSize: '0.9rem',
                          color: '#d1fae5'
                        }}>
                          {callState.current_clinic.distance_miles} miles away
                        </span>
                      </div>
                    )}

                    {callState.current_clinic.cost_estimate && (
                      <div style={{
                        display: 'flex',
                        alignItems: 'center',
                        gap: '0.5rem'
                      }}>
                        <span style={{ fontSize: '1.1rem' }}>💰</span>
                        <span style={{
                          fontSize: '0.9rem',
                          color: '#6ee7b7',
                          fontWeight: '600'
                        }}>
                          Est. cost: {callState.current_clinic.cost_estimate}
                        </span>
                      </div>
                    )}
                  </div>

                  {callState.current_clinic.reason && (
                    <div style={{
                      borderTop: '1px solid rgba(16, 185, 129, 0.3)',
                      paddingTop: '1rem',
                      marginTop: '1rem'
                    }}>
                      <div style={{
                        display: 'flex',
                        alignItems: 'flex-start',
                        gap: '0.5rem'
                      }}>
                        <span style={{ fontSize: '1rem', marginTop: '0.1rem' }}>💡</span>
                        <div>
                          <p style={{
                            margin: '0 0 0.25rem 0',
                            fontSize: '0.8rem',
                            color: '#a7f3d0',
                            fontWeight: '500',
                            textTransform: 'uppercase',
                            letterSpacing: '0.025em'
                          }}>
                            Why this clinic?
                          </p>
                          <p style={{
                            margin: '0',
                            fontSize: '0.9rem',
                            color: '#ecfdf5',
                            fontStyle: 'italic',
                            lineHeight: '1.5'
                          }}>
                            "{callState.current_clinic.reason}"
                          </p>
                        </div>
                      </div>
                    </div>
                  )}
                </div>
              )}
            </div>
          )}

          {/* Call Ended State */}
          {currentState === 'ended' && callState && (
            <div>
              {/* Keep chat visible */}
              <div style={{
                display: 'flex',
                flexDirection: 'column',
                height: '60vh',
                marginBottom: '2rem'
              }}>
                <div style={{
                  flex: 1,
                  overflowY: 'auto',
                  padding: '1rem 0',
                  display: 'flex',
                  flexDirection: 'column',
                  gap: '1rem'
                }}>
                  {callState.conversation?.map((msg, idx) => (
                    <div key={idx} style={{
                      display: 'flex',
                      justifyContent: msg.role === 'user' ? 'flex-end' : 'flex-start'
                    }}>
                      <div style={{
                        maxWidth: '70%',
                        padding: '0.75rem 1rem',
                        borderRadius: '1rem',
                        backgroundColor: msg.role === 'user' ? '#3b82f6' : '#374151',
                        color: '#ffffff',
                        fontSize: '0.95rem',
                        lineHeight: '1.4'
                      }}>
                        {msg.content}
                      </div>
                    </div>
                  ))}
                </div>

                {/* Final clinic card if present */}
                {callState.current_clinic && (
                  <div style={{
                    backgroundColor: '#065f46',
                    border: '1px solid #10b981',
                    borderRadius: '0.75rem',
                    padding: '1rem',
                    marginTop: '1rem'
                  }}>
                    <h3 style={{
                      margin: '0 0 0.5rem 0',
                      fontSize: '1.125rem',
                      fontWeight: 'bold',
                      color: '#ffffff'
                    }}>
                      🏥 {callState.current_clinic.name}
                    </h3>
                    <p style={{
                      margin: '0 0 0.25rem 0',
                      fontSize: '0.875rem',
                      color: '#a7f3d0'
                    }}>
                      📍 {callState.current_clinic.address}
                    </p>
                    <p style={{
                      margin: '0',
                      fontSize: '0.875rem',
                      color: '#a7f3d0'
                    }}>
                      📞 {formatPhoneNumber(callState.current_clinic.phone)}
                    </p>
                  </div>
                )}
              </div>

              {/* Status banner */}
              <div style={{
                position: 'fixed',
                bottom: 0,
                left: 0,
                right: 0,
                backgroundColor: getEndedStatusColor(callState.status),
                color: '#ffffff',
                padding: '1rem 2rem',
                fontSize: '1.125rem',
                fontWeight: 'bold',
                textAlign: 'center',
                zIndex: 1000,
                animation: 'slideUp 0.5s ease-out'
              }}>
                {getEndedStatusText(callState.status)}
              </div>
            </div>
          )}
        </div>
      </div>

      <style jsx global>{`
        @keyframes shimmerIn {
          0% {
            opacity: 0;
            transform: translateY(20px);
          }
          100% {
            opacity: 1;
            transform: translateY(0);
          }
        }

        @keyframes shake {
          0% {
            transform: translateX(0);
          }
          25% {
            transform: translateX(-2px) rotate(-2deg);
          }
          50% {
            transform: translateX(0);
          }
          75% {
            transform: translateX(2px) rotate(2deg);
          }
          100% {
            transform: translateX(0);
          }
        }

        @keyframes ripple {
          0% {
            transform: scale(0.8);
            opacity: 1;
          }
          100% {
            transform: scale(2.5);
            opacity: 0;
          }
        }

        @keyframes slideInLeft {
          from {
            opacity: 0;
            transform: translateX(-20px);
          }
          to {
            opacity: 1;
            transform: translateX(0);
          }
        }

        @keyframes slideInRight {
          from {
            opacity: 0;
            transform: translateX(20px);
          }
          to {
            opacity: 1;
            transform: translateX(0);
          }
        }

        @keyframes slideUp {
          from {
            opacity: 0;
            transform: translateY(20px);
          }
          to {
            opacity: 1;
            transform: translateY(0);
          }
        }

        @keyframes bounce {
          0%, 80%, 100% {
            transform: scale(0);
          }
          40% {
            transform: scale(1);
          }
        }

        @keyframes pulse {
          0%, 100% {
            opacity: 0.6;
            transform: scale(1);
          }
          50% {
            opacity: 1;
            transform: scale(1.1);
          }
        }

        @keyframes fadeInSlideLeft {
          from {
            opacity: 0;
            transform: translateX(-30px);
          }
          to {
            opacity: 1;
            transform: translateX(0);
          }
        }

        @keyframes fadeInSlideRight {
          from {
            opacity: 0;
            transform: translateX(30px);
          }
          to {
            opacity: 1;
            transform: translateX(0);
          }
        }

        body {
          margin: 0;
          padding: 0;
          overflow-x: hidden;
        }

        * {
          box-sizing: border-box;
        }

        @keyframes fadeIn {
          from { opacity: 0; }
          to { opacity: 1; }
        }

        @keyframes slideInFromTop {
          from {
            opacity: 0;
            transform: translateY(-20px) scale(0.9);
          }
          to {
            opacity: 1;
            transform: translateY(0) scale(1);
          }
        }

        @keyframes slideProgress {
          0% {
            transform: translateX(-100%);
          }
          50% {
            transform: translateX(0%);
          }
          100% {
            transform: translateX(100%);
          }
        }
      `}</style>

      {/* Confirmation Modal */}
      {showClearModal && (
        <div style={{
          position: 'fixed',
          top: 0,
          left: 0,
          right: 0,
          bottom: 0,
          backgroundColor: 'rgba(0, 0, 0, 0.7)',
          display: 'flex',
          alignItems: 'center',
          justifyContent: 'center',
          zIndex: 1000,
          animation: 'fadeIn 0.2s ease-out'
        }}>
          <div style={{
            backgroundColor: '#1e293b',
            border: '1px solid #334155',
            borderRadius: '0.75rem',
            padding: '2rem',
            maxWidth: '400px',
            width: '90%',
            animation: 'slideInFromTop 0.3s ease-out',
            boxShadow: '0 20px 50px rgba(0, 0, 0, 0.5)'
          }}>
            <div style={{
              textAlign: 'center',
              marginBottom: '1.5rem'
            }}>
              <div style={{
                fontSize: '3rem',
                marginBottom: '0.5rem'
              }}>
                ⚠️
              </div>
              <h3 style={{
                fontSize: '1.25rem',
                fontWeight: 'bold',
                color: '#ffffff',
                margin: '0 0 0.5rem 0'
              }}>
                Clear All Sessions
              </h3>
              <p style={{
                color: '#94a3b8',
                fontSize: '0.875rem',
                margin: '0',
                lineHeight: '1.5'
              }}>
                This will permanently delete all call sessions and conversation history.
                <br />
                <strong style={{ color: '#ef4444' }}>This action cannot be undone.</strong>
              </p>
            </div>

            <div style={{
              backgroundColor: '#0f172a',
              border: '1px solid #334155',
              borderRadius: '0.5rem',
              padding: '1rem',
              marginBottom: '1.5rem'
            }}>
              <div style={{
                display: 'flex',
                alignItems: 'center',
                justifyContent: 'space-between',
                fontSize: '0.875rem',
                color: '#cbd5e1'
              }}>
                <span>Total Sessions:</span>
                <span style={{ fontWeight: '600' }}>{activeCalls.length + (callState ? 1 : 0)}</span>
              </div>
              <div style={{
                display: 'flex',
                alignItems: 'center',
                justifyContent: 'space-between',
                fontSize: '0.875rem',
                color: '#cbd5e1',
                marginTop: '0.25rem'
              }}>
                <span>Active Calls:</span>
                <span style={{ fontWeight: '600', color: '#22c55e' }}>
                  {activeCalls.filter(call => ['connecting', 'connected'].includes(call.status)).length}
                </span>
              </div>
            </div>

            <div style={{
              display: 'flex',
              gap: '0.75rem',
              justifyContent: 'flex-end'
            }}>
              <button
                onClick={() => setShowClearModal(false)}
                disabled={clearing}
                style={{
                  background: 'transparent',
                  border: '1px solid #6b7280',
                  borderRadius: '0.5rem',
                  padding: '0.75rem 1.5rem',
                  fontSize: '0.875rem',
                  color: '#d1d5db',
                  cursor: 'pointer',
                  transition: 'all 0.2s ease'
                }}
                onMouseEnter={(e) => {
                  e.currentTarget.style.backgroundColor = '#374151'
                }}
                onMouseLeave={(e) => {
                  e.currentTarget.style.backgroundColor = 'transparent'
                }}
              >
                Cancel
              </button>
              <button
                onClick={handleClearSessions}
                disabled={clearing}
                style={{
                  background: clearing ? '#6b7280' : 'linear-gradient(135deg, #dc2626, #b91c1c)',
                  border: '1px solid #dc2626',
                  borderRadius: '0.5rem',
                  padding: '0.75rem 1.5rem',
                  fontSize: '0.875rem',
                  color: '#ffffff',
                  cursor: clearing ? 'not-allowed' : 'pointer',
                  display: 'flex',
                  alignItems: 'center',
                  gap: '0.5rem',
                  transition: 'all 0.2s ease'
                }}
              >
                {clearing ? '⏳' : '🗑️'}
                {clearing ? 'Clearing...' : 'Clear All Sessions'}
              </button>
            </div>
          </div>
        </div>
      )}

      {/* Notification Toast */}
      {notification && (
        <div style={{
          position: 'fixed',
          top: '2rem',
          right: '2rem',
          backgroundColor: notification.type === 'success' ? '#065f46' : '#7f1d1d',
          border: `1px solid ${notification.type === 'success' ? '#10b981' : '#dc2626'}`,
          borderRadius: '0.75rem',
          padding: '1rem 1.25rem',
          color: '#ffffff',
          fontSize: '0.875rem',
          display: 'flex',
          alignItems: 'center',
          gap: '0.75rem',
          zIndex: 1001,
          animation: 'slideInFromTop 0.3s ease-out',
          maxWidth: '400px',
          boxShadow: '0 10px 25px rgba(0, 0, 0, 0.3)'
        }}>
          <div style={{ fontSize: '1.25rem' }}>
            {notification.type === 'success' ? '✅' : '❌'}
          </div>
          <div style={{ flex: 1, lineHeight: '1.4' }}>
            {notification.message}
          </div>
          <button
            onClick={() => setNotification(null)}
            style={{
              background: 'transparent',
              border: 'none',
              color: 'inherit',
              fontSize: '1.25rem',
              cursor: 'pointer',
              opacity: 0.7,
              transition: 'opacity 0.2s ease'
            }}
            onMouseEnter={(e) => { e.currentTarget.style.opacity = '1' }}
            onMouseLeave={(e) => { e.currentTarget.style.opacity = '0.7' }}
          >
            ×
          </button>
        </div>
      )}
    </div>
  )
}