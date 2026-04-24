import type { WSProgressMessage } from '../types'

export function connectJobWS(
  jobId: number,
  onMessage: (msg: WSProgressMessage) => void,
  onClose?: () => void,
): WebSocket {
  const protocol = window.location.protocol === 'https:' ? 'wss:' : 'ws:'
  const ws = new WebSocket(`${protocol}//${window.location.host}/ws/jobs/${jobId}`)

  ws.onmessage = (event) => {
    try {
      const data = JSON.parse(event.data) as WSProgressMessage
      onMessage(data)
    } catch {
      // ignore parse errors
    }
  }

  ws.onclose = () => {
    onClose?.()
    // Reconnect after 3 seconds
    setTimeout(() => {
      connectJobWS(jobId, onMessage, onClose)
    }, 3000)
  }

  // Send periodic pings to keep alive
  const pingInterval = setInterval(() => {
    if (ws.readyState === WebSocket.OPEN) {
      ws.send('ping')
    } else {
      clearInterval(pingInterval)
    }
  }, 30000)

  return ws
}
