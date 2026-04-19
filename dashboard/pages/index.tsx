import { useState, useEffect } from 'react'

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
  role: string
  content: string
}

interface CallState {
  status: string
  caller_number: string
  conversation: ConversationMessage[]
  current_clinic: Clinic | null
  claude_analysis: {
    action?: string
    user_zip?: string
    monthly_income?: number
    language?: string
    candidates?: Clinic[]
  }
}

export default function Dashboard() {
  const [activeCalls, setActiveCalls] = useState<any[]>([])
  const [selectedCallSid, setSelectedCallSid] = useState<string | null>(null)
  const [callState, setCallState] = useState<CallState | null>(null)
  const [error, setError] = useState<string | null>(null)

  // Poll for active calls
  useEffect(() => {
    const fetchActiveCalls = async () => {
      try {
        const response = await fetch('http://localhost:8000/active-calls')
        const data = await response.json()
        setActiveCalls(data.calls || [])

        // Auto-select first call if none selected
        if (!selectedCallSid && data.calls && data.calls.length > 0) {
          setSelectedCallSid(data.calls[0].call_sid)
        }
      } catch (err) {
        console.error('Error fetching active calls:', err)
        setError('Failed to connect to backend')
      }
    }

    fetchActiveCalls()
    const interval = setInterval(fetchActiveCalls, 2000)
    return () => clearInterval(interval)
  }, [selectedCallSid])

  // Poll for call state
  useEffect(() => {
    if (!selectedCallSid) return

    const fetchCallState = async () => {
      try {
        const response = await fetch(`http://localhost:8000/call-state/${selectedCallSid}`)
        const data = await response.json()
        if (!data.error) {
          setCallState(data)
          setError(null)
        }
      } catch (err) {
        console.error('Error fetching call state:', err)
        setError('Failed to fetch call details')
      }
    }

    fetchCallState()
    const interval = setInterval(fetchCallState, 1000)
    return () => clearInterval(interval)
  }, [selectedCallSid])

  const formatPhoneNumber = (phone: string) => {
    if (!phone) return 'N/A'
    return phone.replace(/(\d{3})(\d{3})(\d{4})/, '($1) $2-$3')
  }

  const getStatusColor = (status: string) => {
    switch (status) {
      case 'connected': return 'text-green-500'
      case 'connecting': return 'text-yellow-500'
      case 'transferred': return 'text-blue-500'
      case 'sms_sent': return 'text-purple-500'
      case 'disconnected': return 'text-red-500'
      default: return 'text-gray-500'
    }
  }

  const getActionIcon = (action: string) => {
    switch (action) {
      case 'ask_followup': return '❓'
      case 'present_clinic': return '🏥'
      case 'transfer_call': return '📞'
      case 'send_sms': return '📱'
      case 'call_911': return '🚨'
      default: return '💬'
    }
  }

  return (
    <div className="min-h-screen bg-gray-100 p-8">
      <div className="max-w-6xl mx-auto">
        <h1 className="text-3xl font-bold mb-8 text-center">ClearPath Live Dashboard</h1>

        {error && (
          <div className="bg-red-100 border border-red-400 text-red-700 px-4 py-3 rounded mb-4">
            {error}
          </div>
        )}

        <div className="grid grid-cols-1 lg:grid-cols-3 gap-8">
          {/* Active Calls Panel */}
          <div className="bg-white rounded-lg shadow p-6">
            <h2 className="text-xl font-semibold mb-4">📞 Active Calls</h2>
            {activeCalls.length === 0 ? (
              <p className="text-gray-500">No active calls</p>
            ) : (
              <div className="space-y-2">
                {activeCalls.map((call) => (
                  <div
                    key={call.call_sid}
                    className={`p-3 rounded cursor-pointer transition-colors ${
                      selectedCallSid === call.call_sid
                        ? 'bg-blue-100 border-2 border-blue-500'
                        : 'bg-gray-50 hover:bg-gray-100'
                    }`}
                    onClick={() => setSelectedCallSid(call.call_sid)}
                  >
                    <div className="font-medium">{call.caller}</div>
                    <div className={`text-sm ${getStatusColor(call.status)}`}>
                      {call.status.replace('_', ' ')}
                    </div>
                  </div>
                ))}
              </div>
            )}
          </div>

          {/* Conversation Panel */}
          <div className="bg-white rounded-lg shadow p-6">
            <h2 className="text-xl font-semibold mb-4">💬 Conversation</h2>
            {!callState ? (
              <p className="text-gray-500">Select a call to view conversation</p>
            ) : (
              <div className="space-y-3 max-h-96 overflow-y-auto">
                {callState.conversation.length === 0 ? (
                  <p className="text-gray-500">Conversation starting...</p>
                ) : (
                  callState.conversation.map((msg, idx) => (
                    <div key={idx} className="flex gap-2">
                      <div className="font-semibold text-sm">
                        {msg.role === 'user' ? '👤' : '🤖'}
                      </div>
                      <div className="flex-1 text-sm">
                        <div className={`${msg.role === 'user' ? 'text-blue-700' : 'text-green-700'}`}>
                          {msg.content}
                        </div>
                      </div>
                    </div>
                  ))
                )}
              </div>
            )}
          </div>

          {/* Analysis Panel */}
          <div className="bg-white rounded-lg shadow p-6">
            <h2 className="text-xl font-semibold mb-4">🧠 Claude Analysis</h2>
            {!callState?.claude_analysis ? (
              <p className="text-gray-500">No analysis available</p>
            ) : (
              <div className="space-y-4">
                <div className="grid grid-cols-2 gap-4 text-sm">
                  <div>
                    <span className="font-medium">Action:</span>
                    <div className="flex items-center gap-1">
                      {getActionIcon(callState.claude_analysis.action || '')}
                      {callState.claude_analysis.action || 'N/A'}
                    </div>
                  </div>
                  <div>
                    <span className="font-medium">ZIP:</span>
                    <div>{callState.claude_analysis.user_zip || 'N/A'}</div>
                  </div>
                  <div>
                    <span className="font-medium">Income:</span>
                    <div>
                      {callState.claude_analysis.monthly_income
                        ? `$${callState.claude_analysis.monthly_income}/month`
                        : 'N/A'
                      }
                    </div>
                  </div>
                  <div>
                    <span className="font-medium">Language:</span>
                    <div>{callState.claude_analysis.language || 'N/A'}</div>
                  </div>
                </div>

                {/* Clinic Rankings */}
                {callState.claude_analysis.candidates && callState.claude_analysis.candidates.length > 0 && (
                  <div>
                    <h3 className="font-medium mb-2">🏥 Clinic Rankings</h3>
                    <div className="space-y-2 text-sm">
                      {callState.claude_analysis.candidates.slice(0, 3).map((clinic, idx) => (
                        <div key={idx} className="p-2 bg-gray-50 rounded">
                          <div className="font-medium">
                            {idx + 1}. {clinic.name}
                          </div>
                          <div className="text-gray-600">
                            {clinic.distance_miles ? `${clinic.distance_miles} miles` : 'Distance unknown'}
                            {clinic.score && ` • Score: ${clinic.score}`}
                          </div>
                        </div>
                      ))}
                    </div>
                  </div>
                )}

                {/* Selected Clinic */}
                {callState.current_clinic && (
                  <div>
                    <h3 className="font-medium mb-2">✅ Selected Clinic</h3>
                    <div className="p-3 bg-green-50 border border-green-200 rounded">
                      <div className="font-medium text-green-800">
                        {callState.current_clinic.name}
                      </div>
                      <div className="text-sm text-green-700">
                        {callState.current_clinic.address}
                      </div>
                      <div className="text-sm text-green-700">
                        {formatPhoneNumber(callState.current_clinic.phone)}
                      </div>
                      {callState.current_clinic.distance_miles && (
                        <div className="text-sm text-green-700">
                          {callState.current_clinic.distance_miles} miles away
                        </div>
                      )}
                      {callState.current_clinic.reason && (
                        <div className="text-sm text-green-600 mt-2 italic">
                          "{callState.current_clinic.reason}"
                        </div>
                      )}
                    </div>
                  </div>
                )}
              </div>
            )}
          </div>
        </div>

        {/* Call Status Bar */}
        {callState && (
          <div className="mt-8 bg-white rounded-lg shadow p-4">
            <div className="flex items-center justify-between">
              <div className="flex items-center gap-4">
                <span className="font-medium">Call Status:</span>
                <span className={`font-bold ${getStatusColor(callState.status)}`}>
                  {callState.status.replace('_', ' ').toUpperCase()}
                </span>
              </div>
              <div className="text-sm text-gray-600">
                Caller: {callState.caller_number}
              </div>
            </div>
          </div>
        )}
      </div>

      <style jsx>{`
        .min-h-screen {
          font-family: -apple-system, BlinkMacSystemFont, 'Segoe UI', Roboto, 'Helvetica Neue', Arial, sans-serif;
        }
      `}</style>
    </div>
  )
}