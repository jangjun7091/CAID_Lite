# gui/ — Frontend (Three.js + SSE)

## Purpose
Browser-based GUI served as static files by FastAPI. Two separate pages:
- `/` — single-part modelling (3-pane: shelf / Three.js viewer / chat)
- `/assembly` — multi-part assembly (3-pane: parts shelf / Three.js / constraints)

## Files
```
static/index.html       — main page HTML
static/app.js           — main page JS: SSE, generate pipeline, shelf, catalog modal,
                          file import (POST /api/parts/import)
static/style.css        — design tokens (CSS vars), main-page element-specific .hidden rules
static/assembly.html    — assembly page HTML
static/app_assembly.js  — assembly JS: Three.js multi-mesh, face-pick raycasting, SSE,
                          assembly CRUD, NL constraints
static/assembly.css     — assembly page styles
```

## ⚠️ Critical: `.hidden` CSS

`style.css` defines `.hidden` **only for specific main-page elements** (not as a global rule).
`assembly.css` must define the global utility at the top:
```css
.hidden { display: none !important; }
/* viewport placeholder uses opacity-fade, so override: */
#asm-viewport-placeholder.hidden { display: flex !important; opacity: 0; }
```
Without this, elements like `#asm-status-overlay` (which has `display: flex` via ID rule)
will **not** be hidden by `class="hidden"` — causing the "Solving…" overlay to block the canvas.

## Cache busting
All JS/CSS assets use `?v=N` query params. When changing `app_assembly.js` or `assembly.css`,
increment N in `assembly.html`. `GET /assembly` and `GET /` serve HTML with
`Cache-Control: no-cache` (set in `server.py`) so browsers always get fresh asset URLs.

## face-pick interaction (app_assembly.js)

State machine variables (ES module scope, not on `window`):
```javascript
faceState = { step: 'idle'|'face_a_selected', partA: null, selectorA: null }
faceOverlays  // { [partId]: { '>X': THREE.Mesh, '<X': ..., ... } }
```
Key functions:
- `createFaceOverlays(partId, mesh)` — called after each STL load in `loadPartSTLs()`
- `destroyFaceOverlays(partId)` — called in `removeAsmPart()` and `clearScene()`
- `hitToSelector(hitPoint, mesh)` — maps raycast hit to CadQuery selector (">Z" etc.)
- `inferConstraintType(selA, selB)` — same axis → "Plane", different → "Axis"
- `cancelFacePick()` — ESC key, Cancel button, part removal, scene clear

DOM elements required by face-pick code:
`#face-pick-step`, `#face-pick-cancel`, `#con-type-auto`, `#con-param-auto`, `#con-form-error`

## SSE (both pages)
```javascript
const evtSource = new EventSource('/api/events');
// reconnect after 3s on error
// on reconnect: re-fetch active session to fix any stuck overlay/status
```
Event types handled in `app_assembly.js`:
`assembly.updated`, `assembly.solved`, `assembly.failed`, `part.ready`, `part.failed`, `part.status_changed`

## ES module note
`app_assembly.js` is `type="module"` — all top-level variables are module-scoped,
not accessible via `window.*` in devtools or eval contexts.
