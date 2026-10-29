// SPDX-FileCopyrightText: (C) 2026 Intel Corporation
// SPDX-License-Identifier: Apache-2.0

// Single source of truth for every filesystem location the Electron service
// manager touches. Nothing else in electron/services/ may build paths by hand.

const fs = require('fs');
const path = require('path');

// ui/electron/services -> ui/electron -> ui -> smart-classroom/Windows
const BUNDLED_HOME = path.resolve(__dirname, '..', '..', '..');

function isSmartClassroomHome(dir) {
  return !!dir && fs.existsSync(path.join(dir, 'main.py')) && fs.existsSync(path.join(dir, 'config.yaml'));
}

// Packaged builds ship the backend source under <resources>/backend (see
// electron-builder.yml). Prefer that when present so the installed app finds
// its source tree without a manual override; otherwise fall back to the
// source-tree location used during development.
function home() {
  const override = process.env.SMART_CLASSROOM_HOME;
  if (isSmartClassroomHome(override)) return path.resolve(override);
  return packagedHome() ?? BUNDLED_HOME;
}

// <install>/resources is the real on-disk resource dir (unlike __dirname,
// which sits inside app.asar once packaged). Guard with isSmartClassroomHome so
// dev (where process.resourcesPath is Electron's own dir, with no backend/ tree)
// naturally falls back to the source tree.
function packagedHome() {
  if (typeof process.resourcesPath !== 'string') return null;
  const candidate = path.join(process.resourcesPath, 'backend');
  return isSmartClassroomHome(candidate) ? candidate : null;
}

const isWindows = process.platform === 'win32';

// Writable state lives under the user's app-data dir in packaged installs so
// the read-only backend tree under <resources>/backend stays clean (venvs are
// created, logs written, config copied/edited at runtime). Returns the user-data
// root in a packaged app, and null in dev so everything stays with the source
// tree, preserving current behaviour.
function userDataDir() {
  if (!packagedHome()) return null;
  const override = process.env.SMART_CLASSROOM_USERDATA;
  if (override) return path.resolve(override);
  return process.env.LOCALAPPDATA
    ? path.join(process.env.LOCALAPPDATA, 'SmartClassroom')
    : packagedHome(); // last resort: stay inside the packaged tree
}

// The backend venv is a sibling of the app root in dev
// (smart-classroom/smartclassroom); in a packaged install it sits under the
// user-data dir.
function venvDir() {
  const base = userDataDir() ?? path.dirname(home());
  return path.join(base, 'smartclassroom');
}

function venvPython(dir = venvDir()) {
  return isWindows ? path.join(dir, 'Scripts', 'python.exe') : path.join(dir, 'bin', 'python');
}

// Read-only source locations, always under the backend tree.
function layoutServiceDir() {
  return path.join(home(), 'components', 'grading', 'providers', 'layout_detection_service');
}

// A writable copy of config.yaml under the user-data dir (seeded once from the
// shipped default) so Setup can edit it; in dev it points at the source tree.
function configFile() {
  const data = userDataDir();
  return data ? path.join(data, 'config.yaml') : path.join(home(), 'config.yaml');
}

// Seed the user-data dir: create it and copy the default config on first run.
// Also expose the user-data root to child processes so the Python backend and
// every service it spawns write their state there instead of the read-only
// backend tree. No-op in dev (where there is nothing to seed).
let ensured = false;
function ensureUserData() {
  if (ensured) return true;
  const data = userDataDir();
  if (!data) return true;
  try {
    fs.mkdirSync(data, { recursive: true });
    if (typeof process.env.SMART_CLASSROOM_USERDATA !== 'string') {
      process.env.SMART_CLASSROOM_USERDATA = data;
    }
    const target = path.join(data, 'config.yaml');
    if (!fs.existsSync(target)) {
      const src = path.join(home(), 'config.yaml');
      if (fs.existsSync(src)) fs.copyFileSync(src, target);
    }
    ensured = true;
    return true;
  } catch (e) {
    console.error('[paths] failed to initialise user data dir:', e);
    return false;
  }
}

const paths = {
  isWindows,
  home,
  userDataDir,
  ensureUserData,
  venvDir,
  venvPython,
  layoutServiceDir,
  configFile,
  proxyConfigFile: () => {
    const d = userDataDir();
    return d ? path.join(d, '.proxy-config') : path.join(home(), '.proxy-config');
  },
  requirementsFile: () => path.join(home(), 'requirements.txt'),
  dlStreamerScript: () => path.join(home(), 'Scripts', 'check_dlstreamer.ps1'),
  convertVenvDir: () => (userDataDir()
    ? path.join(userDataDir(), 'venv_convert')
    : path.join(layoutServiceDir(), 'venv_convert')),
  convertRequirementsFile: () => path.join(layoutServiceDir(), 'requirements_convert.txt'),
  layoutIrModel: () => (userDataDir()
    ? path.join(userDataDir(), 'models', 'detection_model', 'PP-DocLayoutV2-ov', 'fp16', 'model.xml')
    : path.join(home(), 'models', 'detection_model', 'PP-DocLayoutV2-ov', 'fp16', 'model.xml')),
  // Logs captured by the manager itself; distinct from the app's own
  // monitoring/logs and monitoring/executionlogs trees.
  managerLogDir: () => (userDataDir()
    ? path.join(userDataDir(), 'logs', 'manager')
    : path.join(home(), 'logs', 'manager')),
  configBackupDir: () => (userDataDir()
    ? path.join(userDataDir(), 'logs', 'config-backups')
    : path.join(home(), 'logs', 'config-backups')),
};

module.exports = paths;