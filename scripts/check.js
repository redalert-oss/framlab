const fs = require('node:fs');
const os = require('node:os');
const path = require('node:path');
const { spawnSync } = require('node:child_process');

const root = path.resolve(__dirname, '..');
const requiredFiles = [
  'main.js',
  'server.py',
  'index.html',
  'presets/03-felt-mini.txt',
  'presets/04-watercolor.txt',
  'presets/06-pinterest-doodle.txt',
  'presets/07-vintage-poster.txt',
  'photo-edit-assets/00-original.jpg',
  'photo-edit-assets/03-felt-mini.jpg',
  'photo-edit-assets/04-watercolor.jpg',
  'photo-edit-assets/06-pinterest-doodle.jpg',
  'photo-edit-assets/07-vintage-poster.jpg',
];

function commandWorks(command, args = []) {
  const result = spawnSync(command, [...args, '--version'], { encoding: 'utf8', windowsHide: true });
  return result.status === 0;
}

function findPython() {
  const candidates = process.platform === 'win32'
    ? [{ command: 'py', args: ['-3'] }, { command: 'python', args: [] }, { command: 'python3', args: [] }]
    : [{ command: 'python3', args: [] }, { command: 'python', args: [] }];
  return candidates.find(({ command, args }) => commandWorks(command, args));
}

function findCodex() {
  if (process.env.FRAME_LAB_CODEX && fs.existsSync(process.env.FRAME_LAB_CODEX)) {
    return process.env.FRAME_LAB_CODEX;
  }
  if (commandWorks('codex')) return 'codex';
  const candidates = process.platform === 'darwin'
    ? [
        '/Applications/ChatGPT.app/Contents/Resources/codex',
        '/Applications/Codex.app/Contents/Resources/codex',
      ]
    : [];
  if (process.platform === 'win32') {
    const localAppData = process.env.LOCALAPPDATA || path.join(os.homedir(), 'AppData', 'Local');
    const binRoot = path.join(localAppData, 'OpenAI', 'Codex', 'bin');
    if (fs.existsSync(binRoot)) {
      for (const entry of fs.readdirSync(binRoot, { withFileTypes: true })) {
        if (entry.isDirectory()) candidates.push(path.join(binRoot, entry.name, 'codex.exe'));
      }
      candidates.push(path.join(binRoot, 'codex.exe'));
    }
  }
  return candidates.find((candidate) => fs.existsSync(candidate)) || '';
}

const missing = requiredFiles.filter((file) => !fs.existsSync(path.join(root, file)));
const python = findPython();
const codex = findCodex();
const imagegenSkill = path.join(os.homedir(), '.codex', 'skills', '.system', 'imagegen', 'SKILL.md');

console.log(`FrameLab root: ${root}`);
console.log(`Node.js: ${process.version}`);
console.log(`Python 3: ${python ? `${python.command} ${python.args.join(' ')}`.trim() : 'NOT FOUND'}`);
console.log(`Codex: ${codex || 'NOT FOUND'}`);
console.log(`ImageGen skill: ${fs.existsSync(imagegenSkill) ? imagegenSkill : 'NOT FOUND'}`);
console.log(`Project files: ${missing.length ? `MISSING (${missing.join(', ')})` : 'OK'}`);
console.log(`Electron dependencies: ${fs.existsSync(path.join(root, 'node_modules', 'electron')) ? 'OK' : 'NOT INSTALLED'}`);

if (!python || !codex || !fs.existsSync(imagegenSkill) || missing.length) {
  process.exitCode = 1;
}
