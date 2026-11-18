# Frontend

React (Vite, plain JavaScript, React Router), hand-written CSS, no component library. FastAPI serves the built
files from `frontend/dist`; the plain operations pages stay at `/ops` as a fallback.

```bash
npm install        # once
npm run dev        # http://localhost:5173, with /api and /ops forwarded to FastAPI on :8000
npm run build      # writes dist/, served by FastAPI at /
npm test           # render and behaviour tests (Vitest + jsdom)
```

| Path | What it is |
|---|---|
| `src/main.jsx`, `src/App.jsx` | Entry point; routes and the navigation for the current role |
| `src/identity.js` | Name and role, kept in this browser and sent with every request |
| `src/api.js` | The one place that calls the server: adds `X-User`/`X-Role`, turns errors into plain sentences |
| `src/components/` | Small shared pieces: dialog, confirm button, error note, money |
| `src/pages/` | One file per screen |
| `src/styles.css` | All styling |
| `src/test/` | Vitest tests and their fixtures |
