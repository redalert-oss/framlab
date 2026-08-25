# FrameLab repository guide

## Goal

Run and maintain the local Electron photo-style editor. It uses the Codex installation and login already present on the user's computer; do not add an OpenAI API key flow unless the user explicitly requests one.

## First run

1. Run `npm run setup`.
2. If the check passes, run `npm start`.
3. Keep user images, generated outputs, login state, and local workspace data out of Git.

## Validation

- Run `npm run check` after environment or packaging changes.
- Run `node --check main.js` and `python3 -m py_compile server.py` after source changes.
- On macOS, build with `npm run build:mac` only when a distributable is requested.
- On Windows, build with `npm run build:win` only when a distributable is requested.

## Important paths

- `main.js`: Electron desktop process and local Python server launcher.
- `server.py`: local HTTP API and installed Codex app-server integration.
- `index.html`: application UI.
- `presets/`: default editable transformation prompts.
- `photo-edit-assets/`: original and style preview images.

## Safety

- Never commit `outputs/`, `.uploads/`, `workspace/`, `user-data/`, `.env*`, `node_modules/`, `.pnpm-store/`, or `dist/`.
- Do not commit tokens, cookies, Codex sessions, or user-supplied photos.
