/**
 * app_assembly.js — Assembly workspace JavaScript
 *
 * Manages:
 *  - Assembly session CRUD (create, select, delete)
 *  - Part management (add from shelf / catalog / upload, remove)
 *  - Constraint CRUD (add / remove)
 *  - SSE subscription (assembly.updated / assembly.solved / assembly.failed)
 *  - Three.js multi-part 3D viewer
 *  - NL constraint parsing (Phase 2)
 */

import * as THREE from 'three';
import { OrbitControls } from 'three/addons/controls/OrbitControls.js';
import { STLLoader } from 'three/addons/loaders/STLLoader.js';

// ── State ─────────────────────────────────────────────────────────────────────

const state = {
  sessions: [],          // all AssemblySession dicts
  activeId: null,        // currently selected assembly id
  shelfParts: [],        // PartEntry dicts from /api/parts (status=ready)
  catalog: null,         // raw catalog data
  selectedCatalogType: null,
  meshes: {},            // part_id → THREE.Mesh  (for active assembly)
  explodeActive: false,
  wireframeActive: false,
};

// ── Face-pick state ───────────────────────────────────────────────────────────

const faceState = {
  step: 'idle',       // 'idle' | 'face_a_selected'
  partA: null,        // part id
  selectorA: null,    // '>Z' etc.
};

// partId → { '>X': THREE.Mesh overlay, ... }
const faceOverlays = {};

// ── Three.js setup ────────────────────────────────────────────────────────────

const canvas    = document.getElementById('asm-canvas');
const gizmoCanvas = document.getElementById('asm-gizmo-canvas');

const renderer  = new THREE.WebGLRenderer({ canvas, antialias: true });
renderer.setPixelRatio(window.devicePixelRatio);
renderer.shadowMap.enabled = true;
renderer.setClearColor(0x0f1117);

const scene = new THREE.Scene();
scene.add(new THREE.AmbientLight(0xffffff, 0.5));
const dirLight = new THREE.DirectionalLight(0xffffff, 1.0);
dirLight.position.set(5, 8, 5);
scene.add(dirLight);
const dirLight2 = new THREE.DirectionalLight(0xffffff, 0.4);
dirLight2.position.set(-5, -3, -5);
scene.add(dirLight2);

// Grid
const grid = new THREE.GridHelper(200, 20, 0x2a2f3e, 0x1f2330);
scene.add(grid);

const camera = new THREE.PerspectiveCamera(50, 1, 0.1, 5000);
camera.position.set(50, 50, 100);

const controls = new OrbitControls(camera, canvas);
controls.enableDamping = true;
controls.dampingFactor = 0.08;

// Gizmo renderer
const gizmoRenderer = new THREE.WebGLRenderer({ canvas: gizmoCanvas, alpha: true, antialias: true });
gizmoRenderer.setPixelRatio(window.devicePixelRatio);
gizmoRenderer.setSize(80, 80);
const gizmoScene  = new THREE.Scene();
const gizmoCamera = new THREE.OrthographicCamera(-1.5, 1.5, 1.5, -1.5, 0.1, 10);
gizmoCamera.position.set(0, 0, 5);

// Axis arrows for gizmo
const _axisGeom = new THREE.CylinderGeometry(0.05, 0.05, 1, 8);
function _makeAxis(color, dir) {
  const m = new THREE.Mesh(_axisGeom, new THREE.MeshBasicMaterial({ color }));
  m.quaternion.setFromUnitVectors(new THREE.Vector3(0, 1, 0), dir.clone().normalize());
  m.position.copy(dir.clone().multiplyScalar(0.5));
  return m;
}
gizmoScene.add(_makeAxis(0xff4444, new THREE.Vector3(1, 0, 0)));
gizmoScene.add(_makeAxis(0x44dd44, new THREE.Vector3(0, 1, 0)));
gizmoScene.add(_makeAxis(0x4488ff, new THREE.Vector3(0, 0, 1)));

function resizeViewport() {
  const vp = document.getElementById('asm-viewport');
  const w  = vp.clientWidth;
  const h  = vp.clientHeight;
  renderer.setSize(w, h, false);
  camera.aspect = w / h;
  camera.updateProjectionMatrix();
}
resizeViewport();
new ResizeObserver(resizeViewport).observe(document.getElementById('asm-viewport'));

function animate() {
  requestAnimationFrame(animate);
  controls.update();
  renderer.render(scene, camera);

  // Sync gizmo camera with main camera
  gizmoCamera.position.copy(camera.position).normalize().multiplyScalar(5);
  gizmoCamera.lookAt(0, 0, 0);
  gizmoRenderer.render(gizmoScene, gizmoCamera);
}
animate();

// ── Face overlay constants & helpers ─────────────────────────────────────────

// Each entry: selector → [euler_x, euler_y, euler_z], position axis, sign
// PlaneGeometry default normal is +Z; rotations below orient the normal outward.
const FACE_DEFS = [
  { sel: '>X', eu: [0, -Math.PI / 2, 0] },
  { sel: '<X', eu: [0,  Math.PI / 2, 0] },
  { sel: '>Y', eu: [-Math.PI / 2, 0, 0] },
  { sel: '<Y', eu: [ Math.PI / 2, 0, 0] },
  { sel: '>Z', eu: [0, 0, 0] },
  { sel: '<Z', eu: [Math.PI, 0, 0] },
];

function createFaceOverlays(partId, mesh) {
  if (faceOverlays[partId]) destroyFaceOverlays(partId);
  faceOverlays[partId] = {};

  const box = new THREE.Box3().setFromObject(mesh);
  const center = new THREE.Vector3();
  const size   = new THREE.Vector3();
  box.getCenter(center);
  box.getSize(size);

  FACE_DEFS.forEach(({ sel, eu }) => {
    const ax   = sel.slice(1);           // 'X' | 'Y' | 'Z'
    const sign = sel[0] === '>' ? 1 : -1;
    let planeW, planeH, pos;

    if (ax === 'X') {
      planeW = size.z; planeH = size.y;
      pos = new THREE.Vector3(center.x + sign * size.x / 2, center.y, center.z);
    } else if (ax === 'Y') {
      planeW = size.x; planeH = size.z;
      pos = new THREE.Vector3(center.x, center.y + sign * size.y / 2, center.z);
    } else {
      planeW = size.x; planeH = size.y;
      pos = new THREE.Vector3(center.x, center.y, center.z + sign * size.z / 2);
    }

    // Small offset along face normal to prevent z-fighting
    const normal = new THREE.Vector3(
      ax === 'X' ? sign : 0,
      ax === 'Y' ? sign : 0,
      ax === 'Z' ? sign : 0,
    );
    pos.addScaledVector(normal, 0.08);

    const geom = new THREE.PlaneGeometry(planeW, planeH);
    const mat  = new THREE.MeshBasicMaterial({
      color: 0xffffff,
      transparent: true,
      opacity: 0,
      depthTest: false,
      depthWrite: false,
      side: THREE.DoubleSide,
    });
    const overlay = new THREE.Mesh(geom, mat);
    overlay.position.copy(pos);
    overlay.rotation.set(...eu);
    overlay.renderOrder = 999;
    overlay.visible = false;
    scene.add(overlay);
    faceOverlays[partId][sel] = overlay;
  });
}

function destroyFaceOverlays(partId) {
  if (!faceOverlays[partId]) return;
  Object.values(faceOverlays[partId]).forEach(m => {
    scene.remove(m);
    m.geometry.dispose();
    m.material.dispose();
  });
  delete faceOverlays[partId];
}

function showFaceOverlay(partId, sel, color, opacity) {
  const ov = faceOverlays[partId]?.[sel];
  if (!ov) return;
  ov.material.color.setHex(color);
  ov.material.opacity = opacity;
  ov.visible = true;
}

function hideFaceOverlay(partId, sel) {
  const ov = faceOverlays[partId]?.[sel];
  if (ov) ov.visible = false;
}

function hideAllFaceOverlays() {
  Object.values(faceOverlays).forEach(faces =>
    Object.values(faces).forEach(m => { m.visible = false; })
  );
}

// ── Raycasting & face detection ───────────────────────────────────────────────

const raycaster = new THREE.Raycaster();

function mouseToNDC(event) {
  const rect = canvas.getBoundingClientRect();
  return new THREE.Vector2(
    ((event.clientX - rect.left) / rect.width)  *  2 - 1,
    ((event.clientY - rect.top)  / rect.height) * -2 + 1,
  );
}

function hitToSelector(hitPoint, mesh) {
  const box    = new THREE.Box3().setFromObject(mesh);
  const center = new THREE.Vector3();
  const size   = new THREE.Vector3();
  box.getCenter(center);
  box.getSize(size);

  const nx = size.x > 0.001 ? (hitPoint.x - center.x) / (size.x / 2) : 0;
  const ny = size.y > 0.001 ? (hitPoint.y - center.y) / (size.y / 2) : 0;
  const nz = size.z > 0.001 ? (hitPoint.z - center.z) / (size.z / 2) : 0;

  const ax  = Math.abs(nx), ay = Math.abs(ny), az = Math.abs(nz);
  if (az >= ax && az >= ay) return nz > 0 ? '>Z' : '<Z';
  if (ay >= ax)             return ny > 0 ? '>Y' : '<Y';
  return nx > 0 ? '>X' : '<X';
}

function inferConstraintType(selA, selB) {
  return selA.slice(1) === selB.slice(1) ? 'Plane' : 'Axis';
}

function getPartMeshes() {
  return Object.entries(state.meshes)
    .filter(([id]) => id !== '_assembled')
    .map(([id, mesh]) => ({ id, mesh }));
}

// Hover tracking
let _hoveredPart = null;
let _hoveredSel  = null;

canvas.addEventListener('mousemove', (e) => {
  // During face_a_selected, don't change hover
  if (faceState.step === 'face_a_selected') return;

  const ndc      = mouseToNDC(e);
  raycaster.setFromCamera(ndc, camera);
  const parts    = getPartMeshes();
  const hits     = raycaster.intersectObjects(parts.map(p => p.mesh));

  // Clear previous hover
  if (_hoveredPart) {
    hideFaceOverlay(_hoveredPart, _hoveredSel);
    _hoveredPart = null;
    _hoveredSel  = null;
  }

  if (hits.length > 0) {
    const hit   = hits[0];
    const entry = parts.find(p => p.mesh === hit.object);
    if (entry) {
      const sel = hitToSelector(hit.point, entry.mesh);
      showFaceOverlay(entry.id, sel, 0xffffff, 0.25);
      _hoveredPart = entry.id;
      _hoveredSel  = sel;
      canvas.style.cursor = 'crosshair';
    }
  } else {
    canvas.style.cursor = '';
  }
});

// Click: use mousedown/up delta to distinguish click from drag
let _mouseDownX = 0, _mouseDownY = 0;

canvas.addEventListener('mousedown', (e) => {
  _mouseDownX = e.clientX;
  _mouseDownY = e.clientY;
});

canvas.addEventListener('click', (e) => {
  const dx = e.clientX - _mouseDownX;
  const dy = e.clientY - _mouseDownY;
  if (dx * dx + dy * dy > 9) return; // drag → ignore
  handleFaceClick(e);
});

function handleFaceClick(e) {
  const ndc   = mouseToNDC(e);
  raycaster.setFromCamera(ndc, camera);
  const parts = getPartMeshes();
  const hits  = raycaster.intersectObjects(parts.map(p => p.mesh));
  if (hits.length === 0) return;

  const hit   = hits[0];
  const entry = parts.find(p => p.mesh === hit.object);
  if (!entry) return;

  const sel = hitToSelector(hit.point, entry.mesh);

  if (faceState.step === 'idle') {
    // Select face A
    if (_hoveredPart) {
      hideFaceOverlay(_hoveredPart, _hoveredSel);
      _hoveredPart = null; _hoveredSel = null;
    }
    faceState.step     = 'face_a_selected';
    faceState.partA    = entry.id;
    faceState.selectorA = sel;
    showFaceOverlay(entry.id, sel, 0x4488ff, 0.45);
    updateFacePickStatus();
    document.getElementById('face-pick-cancel').classList.remove('hidden');

  } else if (faceState.step === 'face_a_selected') {
    if (entry.id === faceState.partA) {
      // Clicked same part → cancel selection
      cancelFacePick();
      return;
    }
    // Select face B → submit constraint
    const selB  = sel;
    const typeEl = document.getElementById('con-type-auto');
    const type  = typeEl.value === 'auto'
      ? inferConstraintType(faceState.selectorA, selB)
      : typeEl.value;
    const param = parseFloat(document.getElementById('con-param-auto').value) || 0;

    // Flash face B green, then hide
    showFaceOverlay(entry.id, selB, 0x44dd44, 0.45);
    setTimeout(() => hideFaceOverlay(entry.id, selB), 300);

    // Clear face A overlay
    hideFaceOverlay(faceState.partA, faceState.selectorA);

    const pA = faceState.partA;
    const sA = faceState.selectorA;
    cancelFacePick();

    submitConstraint(pA, sA, entry.id, selB, type, param);
  }
}

async function submitConstraint(partA, selA, partB, selB, type, param) {
  const errEl = document.getElementById('con-form-error');
  errEl.classList.add('hidden');
  try {
    await api('POST', `/api/assembly/${state.activeId}/constraints`, {
      type, part_a: partA, selector_a: selA,
      part_b: partB, selector_b: selB, param,
    });
    const updated = await api('GET', `/api/assembly/${state.activeId}`);
    updateSession(updated);
    renderAssemblyUI();
  } catch (err) {
    errEl.textContent = err.message;
    errEl.classList.remove('hidden');
  }
}

function cancelFacePick() {
  if (faceState.partA) hideFaceOverlay(faceState.partA, faceState.selectorA);
  faceState.step      = 'idle';
  faceState.partA     = null;
  faceState.selectorA = null;
  _hoveredPart = null;
  _hoveredSel  = null;
  canvas.style.cursor = '';
  document.getElementById('face-pick-cancel')?.classList.add('hidden');
  updateFacePickStatus();
}

function updateFacePickStatus() {
  const el = document.getElementById('face-pick-step');
  if (!el) return;
  if (faceState.step === 'idle') {
    el.textContent = '① Click a face on any part';
    el.classList.remove('active');
  } else {
    const session  = activeSession();
    const partName = session?.parts.find(p => p.id === faceState.partA)?.name ?? 'Part A';
    el.textContent = `② ${partName} [${faceState.selectorA}] → click a face on Part B`;
    el.classList.add('active');
  }
}

document.getElementById('face-pick-cancel').addEventListener('click', cancelFacePick);

// ── View presets ──────────────────────────────────────────────────────────────

const VIEW_PRESETS = {
  iso:   new THREE.Vector3( 1,  1,  1),
  front: new THREE.Vector3( 0,  0,  1),
  top:   new THREE.Vector3( 0,  1,  0.001),
  right: new THREE.Vector3( 1,  0,  0),
};

function setView(name) {
  const dir = VIEW_PRESETS[name];
  if (!dir) return;
  const box = new THREE.Box3();
  scene.traverse(obj => { if (obj.isMesh && obj !== grid) box.expandByObject(obj); });
  const target = box.isEmpty() ? new THREE.Vector3() : box.getCenter(new THREE.Vector3());
  const size = box.isEmpty() ? 100 : box.getSize(new THREE.Vector3()).length();
  controls.target.copy(target);
  camera.position.copy(dir.clone().normalize().multiplyScalar(size * 1.8).add(target));
  camera.lookAt(target);
  controls.update();
}

document.querySelectorAll('.view-btn[data-view]').forEach(btn => {
  btn.addEventListener('click', () => setView(btn.dataset.view));
});

// Wireframe toggle
document.getElementById('asm-wireframe-btn').addEventListener('click', () => {
  state.wireframeActive = !state.wireframeActive;
  Object.values(state.meshes).forEach(mesh => {
    if (mesh.material) mesh.material.wireframe = state.wireframeActive;
  });
});

// Explode toggle
document.getElementById('asm-explode-btn').addEventListener('click', () => {
  state.explodeActive = !state.explodeActive;
  _applyExplode();
});

function _applyExplode() {
  const ids = Object.keys(state.meshes);
  ids.forEach((id, i) => {
    const mesh = state.meshes[id];
    if (!mesh) return;
    if (state.explodeActive) {
      // Move parts along their bounding box center direction from origin
      const box = new THREE.Box3().setFromObject(mesh);
      const center = box.getCenter(new THREE.Vector3());
      const offset = center.normalize().multiplyScalar(20 * (i + 1));
      mesh.position.add(offset);
    } else {
      // Reset to original positions (re-load STL or zero)
      mesh.position.set(0, 0, 0);
    }
  });
}

// ── SSE ───────────────────────────────────────────────────────────────────────

const connDot = document.getElementById('conn-status');
let evtSource = null;

function connectSSE() {
  evtSource = new EventSource('/api/events');
  evtSource.onopen = () => {
    connDot.className = 'status-dot connected';
    // After reconnect, refresh active session and fix any stuck overlay
    if (state.activeId) {
      api('GET', `/api/assembly/${state.activeId}`).then(session => {
        updateSession(session);
        renderAssemblyUI();
        if (session.status !== 'solving') hideStatusOverlay();
        if (session.status === 'solved' && session.exports?.stl) loadAssemblySTL(session);
      }).catch(() => {});
    }
  };
  evtSource.onerror = () => {
    connDot.className = 'status-dot disconnected';
    setTimeout(connectSSE, 3000);
  };
  evtSource.onmessage = (e) => {
    const evt = JSON.parse(e.data);
    handleSSE(evt);
  };
}

function handleSSE(evt) {
  const { type, data } = evt;

  // Part shelf updates (for available parts panel)
  if (type === 'part.ready' || type === 'part.failed' || type === 'part.status_changed') {
    loadShelfParts();
    return;
  }

  // Assembly events
  if (type === 'assembly.updated' || type === 'assembly.solved' || type === 'assembly.failed') {
    // Update our cached session
    const idx = state.sessions.findIndex(s => s.id === data.id);
    if (idx >= 0) {
      state.sessions[idx] = data;
    }
    renderAssemblyUI();

    if (type === 'assembly.solved' && data.id === state.activeId) {
      hideStatusOverlay();
      showResultInfo(`Solved in ${data.solve_time_s?.toFixed(2) ?? '?'}s`);
      updateDownloadLinks(data);
      loadAssemblySTL(data);
    }
    if (type === 'assembly.failed' && data.id === state.activeId) {
      hideStatusOverlay();
      showResultInfo(`Failed: ${data.error || 'unknown error'}`, true);
    }
  }

  // Catalog-generated part arrives → could also be used in assembly
  if (type === 'part.ready') {
    loadShelfParts();
  }
}

connectSSE();

// ── API helpers ───────────────────────────────────────────────────────────────

async function api(method, path, body) {
  const opts = { method, headers: {} };
  if (body !== undefined) {
    opts.headers['Content-Type'] = 'application/json';
    opts.body = JSON.stringify(body);
  }
  const res = await fetch(path, opts);
  if (!res.ok) {
    const detail = await res.json().then(j => j.detail || JSON.stringify(j)).catch(() => res.statusText);
    throw new Error(detail);
  }
  if (res.status === 204) return null;
  return res.json();
}

// ── Initialization ────────────────────────────────────────────────────────────

async function init() {
  await Promise.all([loadSessions(), loadShelfParts(), loadCatalog()]);
  renderAssemblyUI();
}

async function loadSessions() {
  try {
    state.sessions = await api('GET', '/api/assembly');
  } catch { state.sessions = []; }
}

async function loadShelfParts() {
  try {
    const parts = await api('GET', '/api/parts');
    state.shelfParts = parts.filter(p => p.status === 'ready');
    renderAvailableList();
  } catch { /* ignore */ }
}

async function loadCatalog() {
  try {
    state.catalog = await api('GET', '/api/catalog');
  } catch { state.catalog = null; }
}

// ── Assembly CRUD ─────────────────────────────────────────────────────────────

document.getElementById('asm-new-btn').addEventListener('click', async () => {
  try {
    const name = `Assembly ${state.sessions.length + 1}`;
    const session = await api('POST', '/api/assembly', { name });
    state.sessions.push(session);
    state.activeId = session.id;
    renderAssemblyUI();
  } catch (err) {
    alert('Failed to create assembly: ' + err.message);
  }
});

document.getElementById('asm-delete-btn').addEventListener('click', async () => {
  if (!state.activeId) return;
  if (!confirm('Delete this assembly?')) return;
  try {
    await api('DELETE', `/api/assembly/${state.activeId}`);
    state.sessions = state.sessions.filter(s => s.id !== state.activeId);
    state.activeId = state.sessions[0]?.id || null;
    clearScene();
    renderAssemblyUI();
  } catch (err) {
    alert('Delete failed: ' + err.message);
  }
});

document.getElementById('asm-select').addEventListener('change', (e) => {
  state.activeId = e.target.value || null;
  clearScene();
  renderAssemblyUI();
  // If session has STL, reload viewer
  const session = activeSession();
  if (session?.exports?.stl) loadAssemblySTL(session);
});

function activeSession() {
  return state.sessions.find(s => s.id === state.activeId) || null;
}

// ── Render functions ──────────────────────────────────────────────────────────

function renderAssemblyUI() {
  renderSessionSelector();
  renderAsmPartsList();
  renderAvailableList();
  renderConstraintsList();
}

function renderSessionSelector() {
  const sel = document.getElementById('asm-select');
  const empty = document.getElementById('asm-selector-empty');
  sel.innerHTML = '';
  if (state.sessions.length === 0) {
    empty.classList.remove('hidden');
    sel.classList.add('hidden');
    return;
  }
  empty.classList.add('hidden');
  sel.classList.remove('hidden');
  state.sessions.forEach(s => {
    const opt = document.createElement('option');
    opt.value = s.id;
    opt.textContent = s.name;
    if (s.id === state.activeId) opt.selected = true;
    sel.appendChild(opt);
  });
  if (!state.activeId && state.sessions.length > 0) {
    state.activeId = state.sessions[0].id;
    sel.value = state.activeId;
  }
}

function renderAsmPartsList() {
  const ul = document.getElementById('asm-parts-list');
  ul.innerHTML = '';
  const session = activeSession();
  if (!session || session.parts.length === 0) {
    ul.innerHTML = '<li class="shelf-empty">No parts in this assembly.</li>';
    return;
  }
  session.parts.forEach(part => {
    const li = document.createElement('li');
    li.className = 'asm-part-item';
    li.innerHTML = `
      <span class="asm-part-dot" style="background:${part.color}"></span>
      <span class="asm-part-name" title="${part.name}">${part.name}</span>
      <button class="asm-part-remove" title="Remove" data-pid="${part.id}">✕</button>
    `;
    ul.appendChild(li);
  });
  ul.querySelectorAll('.asm-part-remove').forEach(btn => {
    btn.addEventListener('click', () => removeAsmPart(btn.dataset.pid));
  });
}

function renderAvailableList() {
  const ul = document.getElementById('shelf-available-list');
  ul.innerHTML = '';
  if (state.shelfParts.length === 0) {
    ul.innerHTML = '<li class="shelf-empty">No ready parts on shelf.</li>';
    return;
  }
  const session = activeSession();
  const inAsmIds = new Set(session ? session.parts.map(p => p.part_ref_id) : []);
  state.shelfParts.forEach(part => {
    const inAsm = inAsmIds.has(part.id);
    const li = document.createElement('li');
    li.className = 'shelf-avail-item' + (inAsm ? ' in-asm' : '');
    li.innerHTML = `
      <span style="flex:1;overflow:hidden;text-overflow:ellipsis;white-space:nowrap" title="${part.name}">${part.name}</span>
      <span class="shelf-avail-badge">${inAsm ? 'In Asm' : 'Add'}</span>
    `;
    if (!inAsm) {
      li.addEventListener('click', () => addPartFromShelf(part.id));
    }
    ul.appendChild(li);
  });
}

function renderConstraintsList() {
  const ul = document.getElementById('constraints-list');
  ul.innerHTML = '';
  const session = activeSession();
  if (!session || session.constraints.length === 0) {
    ul.innerHTML = '<li class="shelf-empty">No constraints yet.</li>';
    return;
  }
  const partMap = Object.fromEntries(session.parts.map(p => [p.id, p.name]));
  session.constraints.forEach(con => {
    const li = document.createElement('li');
    li.className = 'con-item';
    const partA = partMap[con.part_a] || con.part_a.slice(0, 8);
    const partB = con.part_b ? (partMap[con.part_b] || con.part_b.slice(0, 8)) : 'World';
    const desc = con.part_b
      ? `${partA} [${con.selector_a}] ↔ ${partB} [${con.selector_b}]`
      : `${partA} → Fixed`;
    li.innerHTML = `
      <span class="con-type-badge">${con.type}</span>
      <span class="con-desc">${desc}</span>
      <button class="con-remove" title="Remove" data-cid="${con.id}">✕</button>
    `;
    ul.appendChild(li);
  });
  ul.querySelectorAll('.con-remove').forEach(btn => {
    btn.addEventListener('click', () => removeConstraint(btn.dataset.cid));
  });
}

function updateConstraintPartSelectors() {
  const session = activeSession();
  const parts = session ? session.parts : [];
  const selA = document.getElementById('con-part-a');
  const selB = document.getElementById('con-part-b');
  [selA, selB].forEach(sel => {
    const prev = sel.value;
    sel.innerHTML = '<option value="">— Select part —</option>';
    parts.forEach(p => {
      const opt = document.createElement('option');
      opt.value = p.id;
      opt.textContent = p.name;
      sel.appendChild(opt);
    });
    if (prev) sel.value = prev;
  });
}

// ── Part operations ───────────────────────────────────────────────────────────

async function addPartFromShelf(partRefId) {
  if (!state.activeId) {
    alert('Create or select an assembly first.');
    return;
  }
  try {
    await api('POST', `/api/assembly/${state.activeId}/parts/from-shelf`, { part_ref_id: partRefId });
    const updated = await api('GET', `/api/assembly/${state.activeId}`);
    updateSession(updated);
    renderAssemblyUI();
  } catch (err) {
    alert('Failed to add part: ' + err.message);
  }
}

async function removeAsmPart(partId) {
  if (!state.activeId) return;
  try {
    await api('DELETE', `/api/assembly/${state.activeId}/parts/${partId}`);
    const updated = await api('GET', `/api/assembly/${state.activeId}`);
    updateSession(updated);
    // Remove mesh and overlays from scene
    if (state.meshes[partId]) {
      scene.remove(state.meshes[partId]);
      delete state.meshes[partId];
    }
    destroyFaceOverlays(partId);
    if (faceState.partA === partId) cancelFacePick();
    renderAssemblyUI();
  } catch (err) {
    alert('Failed to remove part: ' + err.message);
  }
}

// Add from shelf button → open picker modal
document.getElementById('add-shelf-part-btn').addEventListener('click', () => {
  if (!state.activeId) { alert('Create or select an assembly first.'); return; }
  openShelfPicker();
});

document.getElementById('add-catalog-part-btn').addEventListener('click', () => {
  if (!state.activeId) { alert('Create or select an assembly first.'); return; }
  openCatalogPicker();
});

document.getElementById('upload-step-btn').addEventListener('click', () => {
  if (!state.activeId) { alert('Create or select an assembly first.'); return; }
  const input = document.createElement('input');
  input.type = 'file';
  input.accept = '.step,.stp';
  input.onchange = async () => {
    if (!input.files[0]) return;
    const fd = new FormData();
    fd.append('file', input.files[0]);
    try {
      const res = await fetch(`/api/assembly/${state.activeId}/parts/upload`, {
        method: 'POST', body: fd,
      });
      if (!res.ok) throw new Error((await res.json()).detail || res.statusText);
      const updated = await api('GET', `/api/assembly/${state.activeId}`);
      updateSession(updated);
      renderAssemblyUI();
    } catch (err) {
      alert('Upload failed: ' + err.message);
    }
  };
  input.click();
});

// ── Shelf picker modal ────────────────────────────────────────────────────────

function openShelfPicker() {
  const session = activeSession();
  const inAsmIds = new Set(session ? session.parts.map(p => p.part_ref_id) : []);
  const ul = document.getElementById('shelf-picker-list');
  ul.innerHTML = '';
  if (state.shelfParts.length === 0) {
    ul.innerHTML = '<li style="padding:12px 16px;color:var(--text-dim)">No ready parts on shelf.</li>';
  } else {
    state.shelfParts.forEach(part => {
      const inAsm = inAsmIds.has(part.id);
      const li = document.createElement('li');
      li.className = 'picker-item' + (inAsm ? ' in-asm' : '');
      li.innerHTML = `
        <span class="picker-item-name">${part.name}</span>
        <span class="picker-item-meta">${inAsm ? 'Already added' : 'Click to add'}</span>
      `;
      if (!inAsm) {
        li.addEventListener('click', async () => {
          closeModal('shelf-picker-modal');
          await addPartFromShelf(part.id);
        });
      }
      ul.appendChild(li);
    });
  }
  document.getElementById('shelf-picker-modal').classList.remove('hidden');
}

// ── Catalog picker modal ──────────────────────────────────────────────────────

function openCatalogPicker() {
  document.getElementById('catalog-picker-modal').classList.remove('hidden');
  if (state.catalog) renderCatalogPickerGrid('fastener');
}

function renderCatalogPickerGrid(cat) {
  const grid = document.getElementById('cp-grid');
  grid.innerHTML = '';
  if (!state.catalog) return;

  const ICONS = { bolt: '🔩', nut: '⬡', washer: '⭕', bearing: '⚙️', shaft: '⬜', key: '🔑', collar: '🔘', profile: '▬' };

  const items = Object.entries(state.catalog)
    .flatMap(([category, parts]) => parts.map(p => ({ ...p, _cat: category })))
    .filter(p => p.category === cat || (cat === 'fastener' && ['bolt', 'nut', 'washer'].includes(p.category))
                                    || (cat === 'bearing' && p.category === 'bearing')
                                    || (cat === 'shaft' && ['shaft', 'key', 'collar'].includes(p.category))
                                    || (cat === 'profile' && p.category === 'profile'));

  // Fallback: show all if no category filter match
  const toShow = items.length > 0 ? items : Object.values(state.catalog).flat();

  toShow.forEach(part => {
    const btn = document.createElement('button');
    btn.className = 'cat-item-btn';
    const icon = ICONS[part.category] || '🔧';
    const shortName = part.name.replace(/ISO\s+\d+\s+/, '').slice(0, 20);
    btn.innerHTML = `<span class="cat-item-icon">${icon}</span><span>${shortName}</span>`;
    btn.addEventListener('click', () => selectCatalogType(part));
    grid.appendChild(btn);
  });

  // hide config panel
  document.getElementById('cp-config-empty').classList.remove('hidden');
  document.getElementById('cp-config-panel').classList.add('hidden');
  state.selectedCatalogType = null;
}

function selectCatalogType(part) {
  state.selectedCatalogType = part;
  document.getElementById('cp-config-empty').classList.add('hidden');
  const panel = document.getElementById('cp-config-panel');
  panel.classList.remove('hidden');
  document.getElementById('cp-part-name').textContent = part.name;

  // Populate size selector
  const sizeSel = document.getElementById('cp-size-sel');
  sizeSel.innerHTML = '';
  (part.sizes || []).forEach(s => {
    const opt = document.createElement('option');
    opt.value = s;
    opt.textContent = s;
    sizeSel.appendChild(opt);
  });
  sizeSel.onchange = () => updateCatalogDimsTable(part, sizeSel.value);

  // Length row
  const lengthRow = document.getElementById('cp-length-row');
  lengthRow.classList.toggle('hidden', !part.has_length);

  updateCatalogDimsTable(part, sizeSel.value);
}

function updateCatalogDimsTable(part, size) {
  const table = document.getElementById('cp-dims-table');
  table.innerHTML = '';
  const dims = part.dims?.[size] || {};
  Object.entries(dims).forEach(([k, v]) => {
    const tr = document.createElement('tr');
    tr.innerHTML = `<td><b>${k}</b></td><td>${v}</td>`;
    table.appendChild(tr);
  });
}

document.getElementById('cp-tabs').addEventListener('click', (e) => {
  const btn = e.target.closest('.cat-btn');
  if (!btn) return;
  document.querySelectorAll('#cp-tabs .cat-btn').forEach(b => b.classList.remove('active'));
  btn.classList.add('active');
  renderCatalogPickerGrid(btn.dataset.cat);
});

document.getElementById('cp-insert-btn').addEventListener('click', async () => {
  const part = state.selectedCatalogType;
  if (!part) return;
  const size = document.getElementById('cp-size-sel').value;
  const lengthInp = document.getElementById('cp-length-inp');
  const length = part.has_length ? parseFloat(lengthInp.value) : null;
  const errEl = document.getElementById('cp-error');
  errEl.classList.add('hidden');

  const btn = document.getElementById('cp-insert-btn');
  btn.disabled = true;
  btn.textContent = 'Generating…';

  try {
    // 1. Generate catalog part on the main shelf
    const partEntry = await api('POST', '/api/catalog/insert', {
      type: part.id, size, length,
    });

    // 2. Poll until ready (max 30s)
    let ready = partEntry.status === 'ready';
    for (let i = 0; i < 60 && !ready; i++) {
      await new Promise(r => setTimeout(r, 500));
      const updated = await api('GET', `/api/parts/${partEntry.id}`);
      ready = updated.status === 'ready';
      if (updated.status === 'failed') {
        throw new Error(updated.error || 'Generation failed');
      }
    }
    if (!ready) throw new Error('Timed out waiting for part generation');

    // 3. Add to assembly
    closeModal('catalog-picker-modal');
    await api('POST', `/api/assembly/${state.activeId}/parts/from-catalog`, {
      part_ref_id: partEntry.id,
    });
    const updated = await api('GET', `/api/assembly/${state.activeId}`);
    updateSession(updated);
    renderAssemblyUI();
  } catch (err) {
    errEl.textContent = err.message;
    errEl.classList.remove('hidden');
  } finally {
    btn.disabled = false;
    btn.textContent = 'Generate & Add to Assembly';
  }
});

// ── Constraint operations ─────────────────────────────────────────────────────
// Constraints are now created via 3D face picking (see raycasting section above).
// submitConstraint() POSTs directly when two faces are selected.

async function removeConstraint(conId) {
  if (!state.activeId) return;
  try {
    await api('DELETE', `/api/assembly/${state.activeId}/constraints/${conId}`);
    const updated = await api('GET', `/api/assembly/${state.activeId}`);
    updateSession(updated);
    renderAssemblyUI();
  } catch (err) {
    alert('Failed to remove constraint: ' + err.message);
  }
}

// ── Solve ─────────────────────────────────────────────────────────────────────

document.getElementById('asm-solve-btn').addEventListener('click', async () => {
  if (!state.activeId) { alert('Create or select an assembly first.'); return; }
  const session = activeSession();
  if (!session || session.parts.length === 0) {
    alert('Add at least one part before solving.');
    return;
  }
  showStatusOverlay('Solving…');
  showResultInfo('');
  document.getElementById('asm-download-step').classList.add('hidden');
  document.getElementById('asm-download-stl').classList.add('hidden');
  try {
    await api('POST', `/api/assembly/${state.activeId}/solve`);
  } catch (err) {
    hideStatusOverlay();
    showResultInfo('Solve request failed: ' + err.message, true);
  }
});

// ── 3D viewer: load assembled STL ────────────────────────────────────────────

const stlLoader = new STLLoader();

function clearScene() {
  Object.values(state.meshes).forEach(m => scene.remove(m));
  state.meshes = {};
  // Destroy all face overlays
  Object.keys(faceOverlays).forEach(destroyFaceOverlays);
  cancelFacePick();
  document.getElementById('asm-viewport-placeholder').classList.remove('hidden');
}

function loadAssemblySTL(session) {
  if (!session.exports?.stl) return;
  clearScene();
  stlLoader.load(
    `/api/assembly/${session.id}/stl`,
    (geometry) => {
      geometry.computeVertexNormals();
      const mat = new THREE.MeshPhongMaterial({
        color: 0x7ec8e3,
        specular: 0x444444,
        shininess: 30,
        wireframe: state.wireframeActive,
      });
      const mesh = new THREE.Mesh(geometry, mat);
      scene.add(mesh);
      state.meshes['_assembled'] = mesh;
      document.getElementById('asm-viewport-placeholder').classList.add('hidden');
      setView('iso');
    },
    undefined,
    (err) => console.warn('STL load error:', err)
  );
}

// Also load individual STLs for parts in assembly (for multi-color preview)
async function loadPartSTLs(session) {
  clearScene();
  if (!session || session.parts.length === 0) return;

  const promises = session.parts.map(part => {
    if (!part.stl_path) return Promise.resolve();
    return new Promise((resolve) => {
      stlLoader.load(
        `/api/parts/${part.part_ref_id}/stl`,
        (geometry) => {
          geometry.computeVertexNormals();
          const hex = part.color.replace('#', '');
          const r = parseInt(hex.slice(0, 2), 16) / 255;
          const g = parseInt(hex.slice(2, 4), 16) / 255;
          const b = parseInt(hex.slice(4, 6), 16) / 255;
          const mat = new THREE.MeshPhongMaterial({
            color: new THREE.Color(r, g, b),
            specular: 0x444444,
            shininess: 30,
            wireframe: state.wireframeActive,
          });
          const mesh = new THREE.Mesh(geometry, mat);
          scene.add(mesh);
          state.meshes[part.id] = mesh;
          createFaceOverlays(part.id, mesh);
          resolve();
        },
        undefined,
        () => resolve()
      );
    });
  });

  await Promise.all(promises);
  if (Object.keys(state.meshes).length > 0) {
    document.getElementById('asm-viewport-placeholder').classList.add('hidden');
    setView('iso');
  }
}

// ── Status overlay & result info ──────────────────────────────────────────────

function showStatusOverlay(text) {
  const el = document.getElementById('asm-status-overlay');
  document.getElementById('asm-status-text').textContent = text;
  el.classList.remove('hidden');
}

function hideStatusOverlay() {
  document.getElementById('asm-status-overlay').classList.add('hidden');
}

function showResultInfo(text, isError = false) {
  const el = document.getElementById('asm-result-info');
  el.textContent = text;
  el.style.color = isError ? 'var(--red)' : 'var(--text-dim)';
}

function updateDownloadLinks(session) {
  const stepEl = document.getElementById('asm-download-step');
  const stlEl  = document.getElementById('asm-download-stl');
  if (session.exports?.step) {
    stepEl.href = `/api/assembly/${session.id}/step`;
    stepEl.classList.remove('hidden');
  }
  if (session.exports?.stl) {
    stlEl.href = `/api/assembly/${session.id}/stl`;
    stlEl.classList.remove('hidden');
  }
}

// ── Modal helpers ─────────────────────────────────────────────────────────────

function closeModal(id) {
  document.getElementById(id).classList.add('hidden');
}

document.querySelectorAll('.modal-close-btn[data-modal]').forEach(btn => {
  btn.addEventListener('click', () => closeModal(btn.dataset.modal));
});

document.querySelectorAll('.modal-overlay').forEach(overlay => {
  overlay.addEventListener('click', (e) => {
    if (e.target === overlay) overlay.classList.add('hidden');
  });
});

// Escape key closes modals and cancels face picking
window.addEventListener('keydown', (e) => {
  if (e.key === 'Escape') {
    document.querySelectorAll('.modal-overlay:not(.hidden)').forEach(m => m.classList.add('hidden'));
    cancelFacePick();
  }
  if (e.key === 'w' || e.key === 'W') {
    document.getElementById('asm-wireframe-btn').click();
  }
});

// ── NL Constraint (Phase 2) ───────────────────────────────────────────────────

document.getElementById('nl-constraint-btn').addEventListener('click', async () => {
  if (!state.activeId) { alert('Create or select an assembly first.'); return; }
  const input  = document.getElementById('nl-constraint-input');
  const status = document.getElementById('nl-constraint-status');
  const text   = input.value.trim();
  if (!text) return;

  status.textContent = 'Parsing…';
  status.className   = '';
  status.classList.remove('hidden');
  const btn = document.getElementById('nl-constraint-btn');
  btn.disabled = true;

  try {
    const result = await api('POST', `/api/assembly/${state.activeId}/nl-constrain`, { message: text });
    // result contains added constraints list
    const updated = await api('GET', `/api/assembly/${state.activeId}`);
    updateSession(updated);
    renderAssemblyUI();
    const n = result.added?.length || 0;
    status.textContent = `Added ${n} constraint${n !== 1 ? 's' : ''}.`;
    status.classList.add('ok');
    input.value = '';
  } catch (err) {
    status.textContent = err.message;
    status.classList.add('error');
  } finally {
    btn.disabled = false;
  }
});

// ── Helper: update session in state ──────────────────────────────────────────

function updateSession(updated) {
  const idx = state.sessions.findIndex(s => s.id === updated.id);
  if (idx >= 0) state.sessions[idx] = updated;
  else state.sessions.push(updated);
}

// ── Download links from action bar ───────────────────────────────────────────

// Restore download links for already-solved session on page load
function restoreSessionUI() {
  const session = activeSession();
  if (!session) return;
  if (session.status === 'solved' && session.exports?.step) {
    updateDownloadLinks(session);
    showResultInfo(`Solved in ${session.solve_time_s?.toFixed(2) ?? '?'}s`);
    loadAssemblySTL(session);
  } else if (session.parts.length > 0) {
    loadPartSTLs(session);
  }
}

// ── Boot ──────────────────────────────────────────────────────────────────────

init().then(() => {
  if (state.activeId) restoreSessionUI();
});
