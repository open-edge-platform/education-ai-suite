
This folder contains the React UI for the Smart Classroom Application.

## Quick start
1. Install **Node 20.19+ or 22.12+** (per `package.json` engines) — on Linux run `../setup.sh` (uses `scripts/node-setup.sh`)
2. `npm install`
3. `npm run dev` 
4. `npm run build` → static files in `dist/`

## Core dependencies

| Package               | Purpose                                   |
|-----------------------|-------------------------------------------|
| `react` / `react-dom` | UI library and renderer                   |
| `@reduxjs/toolkit`    | Redux store + slices                      |
| `react-redux`         | React bindings for Redux                  |
| `axios`               | HTTP client                               |
| `react-i18next`       | Translations (`src/i18n/`)                |
| `video.js` / `react-player` | Video playback                      |
| `jsmind`              | Mind map rendering                        |
| `pdfjs-dist`          | PDF preview                               |

## State & data flow

1. **Redux Toolkit**  
   - Slices: `ui`, `transcript`, `summary`, `mindmap`, `resource`, `classStatistics`,
     `mediaValidation`, `featureConfig`  
   - Typed hooks: `useAppDispatch()` / `useAppSelector()`

2. **Data fetching**  
   - REST calls wrapped in `services/api.ts` (axios + `fetch` for streamed responses)  
   - Long-running pipelines are followed by polling and server-sent events, not sockets  

