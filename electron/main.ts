import { app, BrowserWindow, ipcMain, Tray, Menu, nativeImage, dialog } from 'electron'
import { join } from 'path'
import { spawn, ChildProcess } from 'child_process'
import { WebSocket } from 'ws'
import fs from 'fs'

let mainWindow: BrowserWindow | null = null
let tray: Tray | null = null
let pythonProcess: ChildProcess | null = null
let wsConnection: WebSocket | null = null
let pythonPort = 0
let backendConnected = false

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
    const scriptPath = getPythonScriptPath()

    if (!fs.existsSync(scriptPath)) {
      console.error('Python backend not found at:', scriptPath)
      reject(new Error('Python backend not found'))
      return
    }

    const backendDir = join(scriptPath, '..')

    pythonProcess = spawn(getPythonExecutable(), [scriptPath], {
      cwd: backendDir,
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
  createTray()

  app.on('activate', () => {
    if (BrowserWindow.getAllWindows().length === 0) createWindow()
  })
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
