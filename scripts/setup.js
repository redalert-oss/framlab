const fs = require('node:fs');
const path = require('node:path');
const { spawnSync } = require('node:child_process');

const root = path.resolve(__dirname, '..');
const npmCommand = process.platform === 'win32' ? 'npm.cmd' : 'npm';

if (!fs.existsSync(path.join(root, 'node_modules', 'electron'))) {
  console.log('FrameLab dependencies are being installed...');
  const install = spawnSync(npmCommand, ['install'], {
    cwd: root,
    stdio: 'inherit',
    windowsHide: true,
  });
  if (install.status !== 0) process.exit(install.status || 1);
} else {
  console.log('FrameLab dependencies are already installed.');
}

const check = spawnSync(process.execPath, [path.join(__dirname, 'check.js')], {
  cwd: root,
  stdio: 'inherit',
  windowsHide: true,
});
process.exit(check.status || 0);
