import { app, BrowserWindow, ipcMain, Tray, Menu, nativeImage, dialog, shell } from 'electron'
import { join } from 'path'
import { spawn, ChildProcess } from 'child_process'
import { WebSocket } from 'ws'
import fs from 'fs'
import { autoUpdater } from 'electron-updater'

let mainWindow: BrowserWindow | null = null
let tray: Tray | null = null
let pythonProcess: ChildProcess | null = null
let wsConnection: WebSocket | null = null
let pythonPort = 0
let backendConnected = false
let isQuitting = false

function sendBackendStatus(): void {
  mainWindow?.webContents.send('backend:status', { connected: backendConnected })
}

const DEV = !app.isPackaged

function getPythonScriptPath(): string {
  if (app.isPackaged) {
    return join(process.resourcesPath, 'backend', 'main.py')
  }
  return join(__dirname, '..', '..', 'backend', 'main.py')
}

function getPythonExecutable(): string {
  const isWin = process.platform === 'win32'
  const exeName = isWin ? 'python.exe' : 'python3'

  if (app.isPackaged) {
    // Preferred: self-contained native backend built by build-backend.sh (PyInstaller)
    const frozenName = isWin ? 'syncflow-backend.exe' : 'syncflow-backend'
    const frozenPath = join(process.resourcesPath, 'backend-bin', frozenName)
    if (fs.existsSync(frozenPath)) return frozenPath
    // Legacy: venv bundled next to backend source (pre-1.0 layouts)
    const packagedPath = join(process.resourcesPath, 'backend', 'venv', isWin ? 'Scripts' : 'bin', exeName)
    if (fs.existsSync(packagedPath)) return packagedPath
    return exeName
  }

  const venvPath = join(__dirname, '..', '..', 'backend', 'venv', isWin ? 'Scripts' : 'bin', exeName)
  if (fs.existsSync(venvPath)) return venvPath
  return exeName
}

function startPythonBackend(): Promise<number> {
  return new Promise((resolve, reject) => {
    const exe = getPythonExecutable()
    const isFrozen = /syncflow-backend(\.exe)?$/.test(exe)
    const args: string[] = []
    let cwd: string

    if (isFrozen) {
      cwd = join(exe, '..')
    } else {
      const scriptPath = getPythonScriptPath()
      if (!fs.existsSync(scriptPath)) {
        console.error('Python backend not found at:', scriptPath)
        reject(new Error('Python backend not found'))
        return
      }
      args.push(scriptPath)
      cwd = join(scriptPath, '..')
    }

    pythonProcess = spawn(exe, args, {
      cwd,
      stdio: ['pipe', 'pipe', 'pipe'],
      env: { ...process.env, PYTHONUNBUFFERED: '1' },
    })

    let resolved = false

    pythonProcess.stdout?.on('data', (data: Buffer) => {
      const output = data.toString()
      console.log('[Python]', output)

      const portMatch = output.match(/SYNCFLOW_PORT:(\d+)/)
      if (portMatch && !resolved) {
        resolved = true
        pythonPort = parseInt(portMatch[1], 10)
        resolve(pythonPort)
      }
    })

    pythonProcess.stderr?.on('data', (data: Buffer) => {
      console.error('[Python ERR]', data.toString())
    })

    pythonProcess.on('close', (code) => {
      console.log(`Python process exited with code ${code}`)
    })

    pythonProcess.on('error', (err) => {
      console.error('Failed to start Python:', err)
      if (!resolved) {
        resolved = true
        reject(err)
      }
    })

    setTimeout(() => {
      if (!resolved) {
        resolved = true
        pythonPort = 18973
        resolve(pythonPort)
      }
    }, 5000)
  })
}

function connectToPython(port: number): Promise<void> {
  return new Promise((resolve, reject) => {
    const ws = new WebSocket(`ws://127.0.0.1:${port}`)
    wsConnection = ws

    ws.on('open', () => {
      console.log('Connected to Python backend')
      backendConnected = true
      sendBackendStatus()
      resolve()
    })

    ws.on('message', (data) => {
      try {
        const msg = JSON.parse(data.toString())
        mainWindow?.webContents.send('ws:message', msg)
      } catch (e) {
        console.error('Invalid WS message:', e)
      }
    })

    ws.on('close', () => {
      console.log('Disconnected from Python backend')
      if (wsConnection === ws) {
        wsConnection = null
      }
      backendConnected = false
      sendBackendStatus()
      setTimeout(() => {
        if (pythonProcess && !pythonProcess.killed) {
          connectToPython(port).catch(console.error)
        }
      }, 3000)
    })

    ws.on('error', (err) => {
      console.error('WS error:', err.message)
      reject(err)
    })
  })
}

function createWindow(): void {
  const isWin = process.platform === 'win32'
  const isLinux = process.platform === 'linux'

  mainWindow = new BrowserWindow({
    width: 1280,
    height: 800,
    minWidth: 900,
    minHeight: 600,
    frame: false,
    ...(isLinux ? {} : { titleBarStyle: 'hidden' as const }),
    backgroundColor: '#0A1628',
    webPreferences: {
      preload: join(__dirname, '../preload/index.js'),
      contextIsolation: true,
      nodeIntegration: false,
      sandbox: true,
      webviewTag: false,
    },
    icon: join(__dirname, '..', '..', 'build', 'icon.png'),
  })

  if (DEV) {
    mainWindow.loadURL('http://localhost:5173')
  } else {
    mainWindow.loadFile(join(__dirname, '../renderer/index.html'))
  }

  mainWindow.webContents.on('did-finish-load', sendBackendStatus)

  // Close hides to tray; real quit happens from the tray menu / before-quit
  mainWindow.on('close', (event) => {
    if (!isQuitting) {
      event.preventDefault()
      mainWindow?.hide()
    }
  })

  mainWindow.on('closed', () => {
    mainWindow = null
  })
}

function createTray(): void {
  const iconPath = join(__dirname, '..', '..', 'build', 'tray-icon.png')

  let trayIcon: ReturnType<typeof nativeImage.createEmpty>
  if (fs.existsSync(iconPath)) {
    trayIcon = nativeImage.createFromPath(iconPath).resize({ width: 16, height: 16 })
  } else {
    trayIcon = nativeImage.createEmpty()
  }

  tray = new Tray(trayIcon)
  tray.setToolTip('SyncFlow')

  const contextMenu = Menu.buildFromTemplate([
    {
      label: 'Open SyncFlow',
      click: () => mainWindow?.show(),
    },
    {
      label: 'Send files',
      click: () => {
        mainWindow?.show()
        mainWindow?.focus()
        mainWindow?.webContents.send('tray:send-files')
      },
    },
    {
      label: 'Quit',
      click: () => {
        if (pythonProcess && !pythonProcess.killed) {
          pythonProcess.kill()
        }
        app.quit()
      },
    },
  ])

  tray.setContextMenu(contextMenu)
  tray.on('click', () => {
    if (mainWindow) {
      if (mainWindow.isVisible()) {
        mainWindow.focus()
      } else {
        mainWindow.show()
      }
    }
  })
}

// Auto-update: silent background check (startup + every 6h) against the
// GitHub releases feed; downloads in background, asks once to restart.
// Dev runs are untouched (no app-update.yml outside packaged builds).
function setupAutoUpdater(): void {
  if (!app.isPackaged) return
  autoUpdater.autoDownload = true
  autoUpdater.on('checking-for-update', () => {
    console.log('[Updater] checking for updates')
  })
  autoUpdater.on('update-not-available', () => {
    console.log('[Updater] already up to date')
  })
  autoUpdater.on('update-available', () => {
    console.log('[Updater] update available — downloading in background')
  })
  autoUpdater.on('update-downloaded', (event) => {
    const notes = typeof event.releaseNotes === 'string' ? event.releaseNotes : ''
    const opts = {
      type: 'info' as const,
      title: 'Update ready',
      message: `Version ${event.version} is ready to install.`,
      detail:
        notes.trim()
          ? notes.slice(0, 500)
          : 'Restart now to switch to the new version, or keep working and update later.',
      buttons: ['Restart now', 'Later'],
      defaultId: 0,
      cancelId: 1,
    }
    const done = (r: { response: number }): void => {
      if (r.response === 0) {
        isQuitting = true
        if (pythonProcess && !pythonProcess.killed) pythonProcess.kill()
        app.quit()
      }
    }
    if (mainWindow) {
      void dialog.showMessageBox(mainWindow, opts).then(done)
    } else {
      void dialog.showMessageBox(opts).then(done)
    }
  })
  autoUpdater.on('error', (err) => {
    console.log('[Updater]', (err as Error).message)
  })
  const check = (): void => {
    autoUpdater.checkForUpdates().catch((err) => {
      console.log('[Updater] check failed:', (err as Error).message)
    })
  }
  setTimeout(check, 15_000)
  setInterval(check, 6 * 60 * 60 * 1000)
}

app.on('before-quit', () => {
  isQuitting = true
})

app.whenReady().then(async () => {
  // Renderer may only ever load our own UI — block any navigation away
  // (e.g. crafted content redirecting the app window) and popups.
  app.on('web-contents-created', (_event, contents) => {
    contents.setWindowOpenHandler(() => ({ action: 'deny' }))
    contents.on('will-navigate', (event, url) => {
      const isDevUI =
        url.startsWith('http://localhost:5173') || url.startsWith('http://127.0.0.1:5173')
      if (!DEV || !isDevUI) event.preventDefault()
    })
  })

  try {
    const port = await startPythonBackend()
    console.log(`Python backend started on port ${port}`)
    await connectToPython(port)
  } catch (err) {
    console.error('Failed to start Python backend:', err)
  }

  createWindow()
  console.log('[Boot] window created')
  createTray()
  console.log('[Boot] tray created')
  setupAutoUpdater()
  console.log('[Boot] updater armed')

  app.on('activate', () => {
    if (BrowserWindow.getAllWindows().length === 0) createWindow()
  })
}).catch((err) => {
  console.error('[Boot] whenReady failed:', err)
})

app.on('window-all-closed', () => {
  if (pythonProcess && !pythonProcess.killed) {
    pythonProcess.kill()
  }
  if (process.platform !== 'darwin') app.quit()
})

ipcMain.on('window:minimize', () => mainWindow?.minimize())
ipcMain.on('window:maximize', () => {
  if (mainWindow?.isMaximized()) {
    mainWindow.unmaximize()
  } else {
    mainWindow?.maximize()
  }
})
ipcMain.on('window:close', () => mainWindow?.close())
ipcMain.on('backend:status:request', () => sendBackendStatus())
ipcMain.on('window:focus', () => {
  mainWindow?.show()
  mainWindow?.focus()
})

// File-manager actions — every path is confined to the user's home directory
function confineToHome(target: string): string | null {
  try {
    const expanded = target.startsWith('~')
      ? join(app.getPath('home'), target.slice(1))
      : target
    const real = fs.realpathSync(expanded)
    const home = fs.realpathSync(app.getPath('home'))
    if (real !== home && !real.startsWith(home + require('path').sep)) return null
    return real
  } catch {
    return null
  }
}

ipcMain.handle('shell:open', (_event, target: unknown) => {
  if (typeof target !== 'string' || !target) return 'Invalid path'
  const real = confineToHome(target)
  if (!real) return 'Path must be inside your home directory'
  return shell.openPath(real)
})

ipcMain.handle('shell:reveal', (_event, target: unknown) => {
  if (typeof target !== 'string' || !target) return false
  const real = confineToHome(target)
  if (!real) return false
  shell.showItemInFolder(real)
  return true
})

// Sync-folder scanner: top-level files changed since `lastSync` (mtimeMs).
// Used by the Sync page to decide what to push to a peer.
const MAX_SCAN_FILES = 1000

ipcMain.handle('sync:scan', (_event, folderPath: unknown, lastSync: unknown) => {
  if (typeof folderPath !== 'string' || !folderPath) return { error: 'Invalid folder' }
  const real = confineToHome(folderPath)
  if (!real) return { error: 'Folder must be inside your home directory' }
  let stat: import('fs').Stats
  try {
    stat = fs.statSync(real)
  } catch {
    return { error: 'Folder does not exist' }
  }
  if (!stat.isDirectory()) return { error: 'Not a folder' }
  const since = typeof lastSync === 'number' && lastSync > 0 ? lastSync : 0
  try {
    const entries = fs.readdirSync(real, { withFileTypes: true })
    const files: { path: string; name: string; size: number }[] = []
    for (const entry of entries) {
      if (files.length >= MAX_SCAN_FILES) break
      if (!entry.isFile()) continue
      const full = join(real, entry.name)
      try {
        const s = fs.statSync(full)
        if (s.mtimeMs > since) files.push({ path: full, name: entry.name, size: s.size })
      } catch {
        continue
      }
    }
    return { files }
  } catch (e) {
    return { error: String((e as Error).message || e) }
  }
})

ipcMain.handle('ws:send', (_event, msg) => {
  if (wsConnection && wsConnection.readyState === WebSocket.OPEN) {
    wsConnection.send(JSON.stringify(msg))
    return true
  }
  return false
})

ipcMain.handle('dialog:openFiles', async () => {
  if (!mainWindow) return []
  const result = await dialog.showOpenDialog(mainWindow, {
    properties: ['openFile', 'multiSelections'],
    title: 'Select Files to Send',
  })
  if (result.canceled) return []

  return result.filePaths.map((fp) => {
    try {
      const stat = fs.statSync(fp)
      return {
        path: fp,
        name: require('path').basename(fp),
        size: stat.size,
        type: '',
      }
    } catch {
      return { path: fp, name: fp, size: 0, type: '' }
    }
  })
})

ipcMain.handle('dialog:openDirectory', async () => {
  if (!mainWindow) return null
  const result = await dialog.showOpenDialog(mainWindow, {
    properties: ['openDirectory'],
    title: 'Select Folder',
  })
  if (result.canceled || !result.filePaths.length) return null
  return result.filePaths[0]
})

ipcMain.handle('app:getPath', (_event, name: string) => {
  return app.getPath(name as any)
})
