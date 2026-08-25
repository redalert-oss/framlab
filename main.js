const { app, BrowserWindow, dialog, Menu, shell } = require('electron');
const net = require('node:net');
const path = require('node:path');
const fs = require('node:fs');
const { spawn, spawnSync } = require('node:child_process');

let mainWindow = null;
let serverProcess = null;
let quitting = false;

function applicationRoot() {
  return app.isPackaged ? path.join(process.resourcesPath, 'app') : __dirname;
}

function findPython() {
  const absoluteCandidates = process.platform === 'win32'
    ? [
        process.env.LOCALAPPDATA && path.join(process.env.LOCALAPPDATA, 'Programs', 'Python', 'Python313', 'python.exe'),
        process.env.LOCALAPPDATA && path.join(process.env.LOCALAPPDATA, 'Programs', 'Python', 'Python312', 'python.exe'),
        process.env.LOCALAPPDATA && path.join(process.env.LOCALAPPDATA, 'Programs', 'Python', 'Python311', 'python.exe'),
      ].filter(Boolean)
    : ['/usr/bin/python3', '/opt/homebrew/bin/python3', '/usr/local/bin/python3'];
  const absolute = absoluteCandidates.find((candidate) => fs.existsSync(candidate));
  if (absolute) return { command: absolute, args: [] };

  const commands = process.platform === 'win32'
    ? [{ command: 'py', args: ['-3'] }, { command: 'python', args: [] }, { command: 'python3', args: [] }]
    : [{ command: 'python3', args: [] }, { command: 'python', args: [] }];
  return commands.find(({ command, args }) => {
    const result = spawnSync(command, [...args, '--version'], { windowsHide: true, encoding: 'utf8' });
    return result.status === 0;
  }) || null;
}

function reservePort() {
  return new Promise((resolve, reject) => {
    const probe = net.createServer();
    probe.unref();
    probe.on('error', reject);
    probe.listen(0, '127.0.0.1', () => {
      const { port } = probe.address();
      probe.close(() => resolve(port));
    });
  });
}

async function waitForServer(url, attempts = 100) {
  for (let index = 0; index < attempts; index += 1) {
    if (serverProcess?.exitCode !== null) {
      throw new Error('FrameLab 내부 서버가 시작되지 않았습니다.');
    }
    try {
      const response = await fetch(`${url}/api/status`);
      if (response.ok) return response.json();
    } catch (_) {}
    await new Promise((resolve) => setTimeout(resolve, 100));
  }
  throw new Error('FrameLab 내부 서버 연결 시간이 초과됐습니다.');
}

function startServer(port) {
  const python = findPython();
  if (!python) {
    throw new Error('Python 3 실행 환경을 찾지 못했습니다. Python 3을 설치한 뒤 다시 실행해주세요.');
  }
  const root = applicationRoot();
  const serverPath = path.join(root, 'server.py');
  const dataDir = path.join(app.getPath('userData'), 'workspace');
  fs.mkdirSync(dataDir, { recursive: true });
  serverProcess = spawn(python.command, [...python.args, serverPath], {
    cwd: root,
    env: {
      ...process.env,
      PYTHONUNBUFFERED: '1',
      PHOTO_EDIT_HOST: '127.0.0.1',
      PHOTO_EDIT_PORT: String(port),
      FRAME_LAB_DATA_DIR: dataDir,
    },
    stdio: ['ignore', 'pipe', 'pipe'],
  });
  serverProcess.stdout.on('data', (chunk) => console.log(`[FrameLab] ${chunk}`));
  serverProcess.stderr.on('data', (chunk) => console.error(`[FrameLab] ${chunk}`));
  serverProcess.on('exit', (code) => {
    if (!quitting && code !== 0) {
      dialog.showErrorBox('FrameLab 서버 오류', `내부 서버가 종료됐습니다. 종료 코드: ${code}`);
    }
  });
}

function createMenu() {
  const isMac = process.platform === 'darwin';
  const template = [
    {
      label: isMac ? 'FrameLab' : '파일',
      submenu: [
        ...(isMac ? [{ role: 'about' }, { type: 'separator' }] : []),
        {
          label: '결과 폴더 열기',
          click: () => shell.openPath(path.join(app.getPath('userData'), 'workspace', 'outputs')),
        },
        {
          label: '프롬프트 폴더 열기',
          click: () => shell.openPath(path.join(app.getPath('userData'), 'workspace', 'presets')),
        },
        { type: 'separator' },
        ...(isMac ? [
          { role: 'hide' },
          { role: 'hideOthers' },
          { role: 'unhide' },
          { type: 'separator' },
        ] : []),
        { role: 'quit' },
      ],
    },
    { label: '편집', submenu: [{ role: 'undo' }, { role: 'redo' }, { type: 'separator' }, { role: 'cut' }, { role: 'copy' }, { role: 'paste' }, { role: 'selectAll' }] },
    { label: '보기', submenu: [{ role: 'reload' }, { role: 'toggleDevTools' }, { type: 'separator' }, { role: 'resetZoom' }, { role: 'zoomIn' }, { role: 'zoomOut' }, { type: 'separator' }, { role: 'togglefullscreen' }] },
    { label: '윈도우', submenu: [{ role: 'minimize' }, ...(isMac ? [{ role: 'zoom' }, { role: 'front' }] : [{ role: 'close' }])] },
  ];
  Menu.setApplicationMenu(Menu.buildFromTemplate(template));
}

async function createWindow() {
  const port = await reservePort();
  const url = `http://127.0.0.1:${port}`;
  startServer(port);
  const status = await waitForServer(url);
  if (!status.ready) {
    throw new Error('설치된 Codex 또는 ImageGen 스킬을 찾지 못했습니다.');
  }
  mainWindow = new BrowserWindow({
    width: 1440,
    height: 960,
    minWidth: 980,
    minHeight: 720,
    backgroundColor: '#0f1115',
    title: 'FrameLab',
    show: false,
    webPreferences: {
      contextIsolation: true,
      nodeIntegration: false,
      sandbox: true,
    },
  });
  mainWindow.once('ready-to-show', () => mainWindow.show());
  mainWindow.webContents.setWindowOpenHandler(() => ({ action: 'deny' }));
  await mainWindow.loadURL(url);
}

app.whenReady().then(async () => {
  createMenu();
  try {
    await createWindow();
  } catch (error) {
    dialog.showErrorBox('FrameLab을 시작할 수 없습니다', error.message);
    app.quit();
  }
});

app.on('activate', () => {
  if (BrowserWindow.getAllWindows().length === 0) createWindow();
});

app.on('window-all-closed', () => app.quit());

app.on('before-quit', () => {
  quitting = true;
  if (serverProcess && serverProcess.exitCode === null) serverProcess.kill('SIGTERM');
});
