import React from 'react'
import ReactDOM from 'react-dom/client'
import { IS_COMPANION, installBridge } from './lib/bridge'
import { initDeepLinks } from './lib/deepLink'
import App from './App'
import './index.css'

// Phase 1: outside Electron there is no preload — install the WebSocket
// transport shim before React mounts so every window.electronAPI call works.
if (IS_COMPANION) {
  installBridge()
  // QR deep link: system camera opened syncflow://pair?... (native only)
  void initDeepLinks()
}

ReactDOM.createRoot(document.getElementById('root')!).render(
  <React.StrictMode>
    <App />
  </React.StrictMode>
)
