Copy-paste-ready markdown for `frontend/README.md` (point-wise).

```markdown
## Quick start
1. Install **Node 20+**
2. `cd frontend`
3. `npm install`
4. `npm run dev` → http://localhost:5173
5. `npm run build` → static files in `dist/`

## Core dependencies
| Package | Purpose |
|---------|---------|
| `react` | UI library |
| `react-dom` | React renderer |
| `@reduxjs/toolkit` | Redux store + slices |
| `react-redux` | React bindings for Redux |
| `@tanstack/react-query` | Data fetching & caching |
| `axios` | HTTP client |
| `socket.io-client` | Real-time WebSocket |

## State & Data flow
1. **Redux Toolkit**  
   - Slices: `recording`, `file`, `ui`, `project`, `summary`, `transcript`, `resource`.  
   - Typed hooks: `useAppDispatch()` / `useAppSelector()`.

2. **React Query (TanStack)**  
   - REST calls wrapped in `services/api.ts`.  
   - WebSocket updates push into `queryClient.setQueryData()` inside `services/socket.ts`.

## Folder layout
```
src/
├── components/   # React components
├── redux/        # store + slices + hooks
├── services/     # axios & socket.io
├── hooks/        # custom hooks
├── utils/        # helpers
├── styles/       # global styles
└── assets/       # images, fonts
```
```