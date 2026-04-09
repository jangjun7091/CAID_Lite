/**
 * CAID Lite — 3-pane GUI  (P1 update)
 *
 * Pane responsibilities:
 *   - Parts Shelf  : renders the parts list; handles selection
 *   - Viewport     : Three.js STL preview + grid + gizmo + view toolbar + download bar
 *   - Chat Panel   : prompt input, message history, SSE status updates
 *
 * Communication:
 *   - POST /api/chat          submit prompt
 *   - GET  /api/parts         initial shelf load
 *   - GET  /api/events        SSE stream (status, ready, failed)
 *   - GET  /api/parts/:id/stl streamed into STL loader
 *   - GET  /api/parts/:id/step|stl  download links
 *
 * P1 additions:
 *   - Reference grid + corner axis gizmo
 *   - View preset buttons (Iso / Front / Top / Right)
 *   - Wireframe toggle
 *   - Dimension badge (W × H × D mm)
 *   - Code view modal with syntax highlighting (highlight.js)
 */

import * as THREE from "three";
import { OrbitControls } from "three/addons/controls/OrbitControls.js";
import { STLLoader } from "three/addons/loaders/STLLoader.js";

// ── State ─────────────────────────────────────────────────────────────────────
const state = {
  parts: {},          // id → part dict
  activePart: null,   // currently selected part id
  refinePart: null,   // part id currently open in the Refine modal
  catalog: null,              // catalog data from GET /api/catalog
  catalogCat: "fastener",     // currently selected category tab
  catalogSelectedType: null,  // currently selected part type id (e.g. "iso4762")
};

// ── DOM refs ──────────────────────────────────────────────────────────────────
const $partsList       = document.getElementById("parts-list");
const $viewport        = document.getElementById("viewport");
const $placeholder     = document.getElementById("viewport-placeholder");
const $placeholderText = document.getElementById("placeholder-text");
const $canvas          = document.getElementById("three-canvas");
const $partInfo        = document.getElementById("part-info");
const $partInfoName    = document.getElementById("part-info-name");
const $partInfoMeta    = document.getElementById("part-info-meta");
const $downloadBar     = document.getElementById("download-bar");
const $dlStep          = document.getElementById("download-step");
const $dlStl           = document.getElementById("download-stl");
const $chatMessages    = document.getElementById("chat-messages");
const $chatForm        = document.getElementById("chat-form");
const $chatInput       = document.getElementById("chat-input");
const $sendBtn         = document.getElementById("send-btn");
const $connStatus      = document.getElementById("conn-status");

// P1 additions
const $viewToolbar     = document.getElementById("view-toolbar");
const $wireframeBtn    = document.getElementById("wireframe-btn");
const $gizmoCanvas     = document.getElementById("gizmo-canvas");
const $dimBadge        = document.getElementById("dim-badge");
const $dimText         = document.getElementById("dim-text");
const $codeBtn         = document.getElementById("code-btn");
const $codeModal       = document.getElementById("code-modal");
const $codeModalClose  = document.getElementById("code-modal-close");
const $codeModalTitle  = document.getElementById("code-modal-title");
const $codeContent     = document.getElementById("code-content");
const $codeCopyBtn     = document.getElementById("code-copy-btn");
const $errorPanel      = document.getElementById("error-panel");
const $errorPanelBody  = document.getElementById("error-panel-body");

// Catalog modal
const $catalogModal       = document.getElementById("catalog-modal");
const $catalogModalClose  = document.getElementById("catalog-modal-close");
const $catalogCatBtns     = document.querySelectorAll(".cat-btn");
const $catalogGrid        = document.getElementById("catalog-grid");
const $catalogConfigEmpty = document.getElementById("catalog-config-empty");
const $catalogConfigPanel = document.getElementById("catalog-config-panel");
const $configPartName     = document.getElementById("config-part-name");
const $catSizeSel         = document.getElementById("cat-size-sel");
const $catLengthRow       = document.getElementById("cat-length-row");
const $catLengthInp       = document.getElementById("cat-length-inp");
const $catDimsTable       = document.getElementById("cat-dims-table");
const $catalogInsertBtn   = document.getElementById("catalog-insert-btn");
const $catalogError       = document.getElementById("catalog-error");
const $catalogOpenBtn     = document.getElementById("catalog-open-btn");

// Refine modal
const $refineModal      = document.getElementById("refine-modal");
const $refineModalClose = document.getElementById("refine-modal-close");
const $refineModalTitle = document.getElementById("refine-modal-title");
const $refineFields     = document.getElementById("refine-fields");
const $refineApplyBtn   = document.getElementById("refine-apply-btn");
const $refineCancelBtn  = document.getElementById("refine-cancel-btn");
const $refineError      = document.getElementById("refine-error");

// ── Three.js — Main Renderer ──────────────────────────────────────────────────
const renderer = new THREE.WebGLRenderer({ canvas: $canvas, antialias: true });
renderer.setPixelRatio(window.devicePixelRatio);
renderer.setClearColor(0x0d1117);
renderer.shadowMap.enabled = true;

const scene  = new THREE.Scene();
const camera = new THREE.PerspectiveCamera(45, 1, 0.01, 100000);
const controls = new OrbitControls(camera, $canvas);
controls.enableDamping = true;
controls.dampingFactor = 0.08;

// Lighting
scene.add(new THREE.AmbientLight(0xffffff, 0.5));
const keyLight = new THREE.DirectionalLight(0xffffff, 1.0);
keyLight.position.set(1, 2, 1.5);
scene.add(keyLight);
const fillLight = new THREE.DirectionalLight(0x8ab4f8, 0.35);
fillLight.position.set(-1, -0.5, -1);
scene.add(fillLight);

// ── Grid ──────────────────────────────────────────────────────────────────────
const gridHelper = new THREE.GridHelper(2000, 40, 0x2a3044, 0x1a1f2e);
gridHelper.visible = false;
scene.add(gridHelper);

// ── Gizmo Renderer (separate small canvas, bottom-right) ─────────────────────
const gizmoRenderer = new THREE.WebGLRenderer({ canvas: $gizmoCanvas, alpha: true, antialias: true });
gizmoRenderer.setPixelRatio(Math.min(window.devicePixelRatio, 2));
gizmoRenderer.setSize(72, 72);

const gizmoScene  = new THREE.Scene();
const gizmoCamera = new THREE.PerspectiveCamera(50, 1, 0.1, 100);
gizmoCamera.position.set(0, 0, 3);

// Colored axis arrows: X=red, Y=green, Z=blue
function makeAxisLine(dir, hex) {
  const mat = new THREE.LineBasicMaterial({ color: hex, linewidth: 2 });
  const pts = [new THREE.Vector3(0, 0, 0), dir.clone().normalize().multiplyScalar(0.9)];
  return new THREE.Line(new THREE.BufferGeometry().setFromPoints(pts), mat);
}
gizmoScene.add(makeAxisLine(new THREE.Vector3(1, 0, 0), 0xe74c3c));  // X red
gizmoScene.add(makeAxisLine(new THREE.Vector3(0, 1, 0), 0x2ecc71));  // Y green
gizmoScene.add(makeAxisLine(new THREE.Vector3(0, 0, 1), 0x3498db));  // Z blue

// Small sphere at origin
const originMesh = new THREE.Mesh(
  new THREE.SphereGeometry(0.07, 8, 8),
  new THREE.MeshBasicMaterial({ color: 0xaaaaaa })
);
gizmoScene.add(originMesh);

// ── Mesh state ────────────────────────────────────────────────────────────────
let currentMesh     = null;
let baseMaterial    = null;    // stored solid material for wireframe toggle
let wireframeMode   = false;
let currentModelDiag = 200;   // bounding-box diagonal, updated on each STL load

function resizeRenderer() {
  const w = $viewport.clientWidth;
  const h = $viewport.clientHeight;
  renderer.setSize(w, h);
  camera.aspect = w / h;
  camera.updateProjectionMatrix();
}

function animate() {
  requestAnimationFrame(animate);
  controls.update();
  renderer.render(scene, camera);

  // Sync gizmo camera orientation with main camera
  const dir = camera.position.clone().sub(controls.target).normalize();
  gizmoCamera.position.copy(dir.multiplyScalar(3));
  gizmoCamera.up.copy(camera.up);
  gizmoCamera.lookAt(0, 0, 0);
  gizmoRenderer.render(gizmoScene, gizmoCamera);
}

const resizeObs = new ResizeObserver(resizeRenderer);
resizeObs.observe($viewport);
resizeRenderer();
animate();

// ── View presets ──────────────────────────────────────────────────────────────
function setView(name) {
  const d = currentModelDiag * 1.1;
  const presets = {
    iso:   { pos: [d * 0.65, d * 0.45, d * 0.85], up: [0, 1, 0] },
    front: { pos: [0,  0,   d],                   up: [0, 1, 0] },
    top:   { pos: [0,  d,   0.001],               up: [0, 0, -1] },
    right: { pos: [d,  0,   0],                   up: [0, 1, 0] },
    left:  { pos: [-d, 0,   0],                   up: [0, 1, 0] },
    back:  { pos: [0,  0,  -d],                   up: [0, 1, 0] },
  };
  const p = presets[name] ?? presets.iso;
  camera.position.set(...p.pos);
  camera.up.set(...p.up);
  controls.target.set(0, 0, 0);
  controls.update();
}

document.querySelectorAll(".view-btn[data-view]").forEach(btn => {
  btn.addEventListener("click", () => setView(btn.dataset.view));
});

// Keyboard shortcuts: F = fit / Home = iso, 1 = front, 7 = top, 3 = right
document.addEventListener("keydown", (e) => {
  if (e.target === $chatInput) return;     // don't steal chat shortcuts
  if ($codeModal && !$codeModal.classList.contains("hidden")) return;
  if ($refineModal && !$refineModal.classList.contains("hidden")) return;
  if ($catalogModal && !$catalogModal.classList.contains("hidden")) return;
  switch (e.key) {
    case "Home": case "f": case "F":  setView("iso");   break;
    case "1":                         setView("front");  break;
    case "7":                         setView("top");    break;
    case "3":                         setView("right");  break;
    case "w": case "W":               toggleWireframe(); break;
  }
});

// ── Wireframe toggle ──────────────────────────────────────────────────────────
function toggleWireframe() {
  if (!currentMesh) return;
  wireframeMode = !wireframeMode;
  if (wireframeMode) {
    currentMesh.material = new THREE.MeshBasicMaterial({
      color: 0x5b8af5, wireframe: true,
    });
    $wireframeBtn.classList.add("active");
  } else {
    currentMesh.material = baseMaterial.clone();
    $wireframeBtn.classList.remove("active");
  }
}

$wireframeBtn.addEventListener("click", toggleWireframe);

// ── STL loading ───────────────────────────────────────────────────────────────
const stlLoader = new STLLoader();

function loadSTL(partId) {
  if (currentMesh) {
    scene.remove(currentMesh);
    currentMesh.geometry.dispose();
    currentMesh.material.dispose();
    currentMesh = null;
  }
  wireframeMode = false;
  $wireframeBtn.classList.remove("active");

  $canvas.classList.remove("hidden");
  $placeholder.classList.add("hidden");

  stlLoader.load(
    `/api/parts/${partId}/stl`,
    (geometry) => {
      geometry.computeVertexNormals();

      baseMaterial = new THREE.MeshStandardMaterial({
        color: 0x5b8af5, metalness: 0.15, roughness: 0.55,
      });
      const mesh = new THREE.Mesh(geometry, baseMaterial);
      currentMesh = mesh;
      scene.add(mesh);

      // Fit camera
      const box   = new THREE.Box3().setFromObject(mesh);
      const size  = box.getSize(new THREE.Vector3());
      const diag  = box.getSize(new THREE.Vector3()).length();
      const center = box.getCenter(new THREE.Vector3());

      mesh.position.sub(center);    // center at world origin

      currentModelDiag = diag;
      camera.near = diag * 0.001;
      camera.far  = diag * 200;
      camera.updateProjectionMatrix();

      // Grid: snap to model bottom
      gridHelper.visible = true;
      gridHelper.position.y = -size.y / 2;

      // Show gizmo and toolbar
      $gizmoCanvas.classList.add("visible");
      $viewToolbar.classList.add("visible");

      setView("iso");
      updatePartInfo(partId);
    },
    undefined,
    (err) => {
      console.warn("STL load error:", err);
      showPlaceholder("Failed to load preview");
    }
  );
}

function showPlaceholder(msg = "Select a ready part to preview") {
  $canvas.classList.add("hidden");
  $placeholder.classList.remove("hidden");
  $placeholderText.textContent = msg;
  $partInfo.classList.remove("visible");
  $downloadBar.classList.remove("visible");
  $dimBadge.classList.add("hidden");
  $errorPanel.classList.add("hidden");
}

function showErrorPanel(errorText) {
  $placeholderText.textContent = "Generation failed";
  $errorPanelBody.textContent = errorText || "Unknown error";
  $errorPanel.classList.remove("hidden");
}

function updatePartInfo(partId) {
  const part = state.parts[partId];
  if (!part) return;

  $partInfoName.textContent = part.name;
  const lines = [];
  if (part.validation) {
    if (part.validation.volume != null) {
      lines.push(`Vol: ${part.validation.volume.toFixed(0)} mm³`);
    }
    if (part.validation.face_count != null) {
      lines.push(`Faces: ${part.validation.face_count}`);
    }
  }
  if (part.repair_iterations > 0) {
    lines.push(`Repaired: ${part.repair_iterations}×`);
  }
  $partInfoMeta.textContent = lines.join("   ");
  $partInfo.classList.add("visible");

  // Dimension badge
  if (part.validation && part.validation.bbox) {
    const [bx, by, bz] = part.validation.bbox.map(v => v.toFixed(1));
    $dimText.textContent = `${bx} × ${by} × ${bz} mm`;
    $dimBadge.classList.remove("hidden");
  } else {
    $dimBadge.classList.add("hidden");
  }

  $dlStep.href = `/api/parts/${partId}/step`;
  $dlStep.download = `${part.name}_${partId.slice(0, 8)}.step`;
  $dlStl.href  = `/api/parts/${partId}/stl`;
  $dlStl.download = `${part.name}_${partId.slice(0, 8)}.stl`;
  $downloadBar.classList.add("visible");
}

// ── Code Modal ────────────────────────────────────────────────────────────────
function openCodeModal(partId) {
  const part = state.parts[partId];
  if (!part || !part.code) return;

  $codeModalTitle.textContent = `CadQuery Code — ${part.name}`;

  // Reset highlight state, then apply
  $codeContent.textContent = part.code;
  $codeContent.removeAttribute("data-highlighted");
  $codeContent.className = "language-python";
  if (window.hljs) {
    hljs.highlightElement($codeContent);
  }
  $codeModal.classList.remove("hidden");
}

function closeCodeModal() {
  $codeModal.classList.add("hidden");
}

$codeBtn.addEventListener("click", () => {
  if (state.activePart) openCodeModal(state.activePart);
});
$codeModalClose.addEventListener("click", closeCodeModal);
$codeModal.addEventListener("click", (e) => { if (e.target === $codeModal) closeCodeModal(); });

$codeCopyBtn.addEventListener("click", () => {
  const part = state.activePart ? state.parts[state.activePart] : null;
  if (!part || !part.code) return;
  navigator.clipboard.writeText(part.code).then(() => {
    $codeCopyBtn.textContent = "Copied!";
    setTimeout(() => { $codeCopyBtn.textContent = "Copy"; }, 1800);
  }).catch(() => {
    $codeCopyBtn.textContent = "Failed";
    setTimeout(() => { $codeCopyBtn.textContent = "Copy"; }, 1800);
  });
});

// Escape closes modals
document.addEventListener("keydown", (e) => {
  if (e.key === "Escape") {
    closeCodeModal();
    closeRefineModal();
  }
});

// ── Catalog Modal ─────────────────────────────────────────────────────────────

// SVG icons for each part type (40×40 or similar viewBox, stroke-based line art)
const PART_ICONS = {
  // ── Fasteners ────────────────────────────────────────────────────────────
  iso4762: `<svg viewBox="0 0 32 60" fill="none" stroke="currentColor" stroke-width="1.8" stroke-linecap="round" stroke-linejoin="round">
    <rect x="8" y="2" width="16" height="12" rx="1.5"/>
    <polygon points="16,5.5 20,8 20,10 16,12.5 12,10 12,8" stroke-width="1.2"/>
    <rect x="13" y="14" width="6" height="42" rx="1"/>
  </svg>`,

  iso7380: `<svg viewBox="0 0 32 60" fill="none" stroke="currentColor" stroke-width="1.8" stroke-linecap="round" stroke-linejoin="round">
    <path d="M8,14 Q8,2 16,2 Q24,2 24,14 Z"/>
    <rect x="13" y="14" width="6" height="42" rx="1"/>
  </svg>`,

  iso10642: `<svg viewBox="0 0 32 60" fill="none" stroke="currentColor" stroke-width="1.8" stroke-linecap="round" stroke-linejoin="round">
    <path d="M8,16 L16,2 L24,16 Z"/>
    <line x1="8" y1="16" x2="24" y2="16"/>
    <rect x="13" y="16" width="6" height="40" rx="1"/>
  </svg>`,

  iso4026: `<svg viewBox="0 0 32 44" fill="none" stroke="currentColor" stroke-width="1.8" stroke-linecap="round" stroke-linejoin="round">
    <rect x="10" y="2" width="12" height="40" rx="3"/>
    <polygon points="16,5.5 19.5,8 19.5,11 16,13.5 12.5,11 12.5,8" stroke-width="1.2"/>
  </svg>`,

  iso4032: `<svg viewBox="0 0 40 40" fill="none" stroke="currentColor" stroke-width="1.8" stroke-linejoin="round">
    <polygon points="20,3 34,11 34,29 20,37 6,29 6,11"/>
    <circle cx="20" cy="20" r="8"/>
  </svg>`,

  iso7089: `<svg viewBox="0 0 40 40" fill="none" stroke="currentColor" stroke-width="1.8">
    <circle cx="20" cy="20" r="17"/>
    <circle cx="20" cy="20" r="8.5"/>
  </svg>`,

  // ── Bearings ─────────────────────────────────────────────────────────────
  iso15_6000: `<svg viewBox="0 0 40 40" fill="none" stroke="currentColor" stroke-width="1.8">
    <circle cx="20" cy="20" r="18"/>
    <circle cx="20" cy="20" r="12" stroke-width="1"/>
    <circle cx="20" cy="20" r="7"/>
    <circle cx="20" cy="8"  r="2.4" fill="currentColor" opacity="0.55" stroke="none"/>
    <circle cx="29" cy="13" r="2.4" fill="currentColor" opacity="0.55" stroke="none"/>
    <circle cx="29" cy="27" r="2.4" fill="currentColor" opacity="0.55" stroke="none"/>
    <circle cx="20" cy="32" r="2.4" fill="currentColor" opacity="0.55" stroke="none"/>
    <circle cx="11" cy="27" r="2.4" fill="currentColor" opacity="0.55" stroke="none"/>
    <circle cx="11" cy="13" r="2.4" fill="currentColor" opacity="0.55" stroke="none"/>
  </svg>`,

  iso15_6200: `<svg viewBox="0 0 40 40" fill="none" stroke="currentColor" stroke-width="1.8">
    <circle cx="20" cy="20" r="18"/>
    <circle cx="20" cy="20" r="11" stroke-width="1"/>
    <circle cx="20" cy="20" r="5"/>
    <circle cx="20" cy="9"  r="2.2" fill="currentColor" opacity="0.55" stroke="none"/>
    <circle cx="29.5" cy="14.5" r="2.2" fill="currentColor" opacity="0.55" stroke="none"/>
    <circle cx="29.5" cy="25.5" r="2.2" fill="currentColor" opacity="0.55" stroke="none"/>
    <circle cx="20" cy="31" r="2.2" fill="currentColor" opacity="0.55" stroke="none"/>
    <circle cx="10.5" cy="25.5" r="2.2" fill="currentColor" opacity="0.55" stroke="none"/>
    <circle cx="10.5" cy="14.5" r="2.2" fill="currentColor" opacity="0.55" stroke="none"/>
  </svg>`,

  // ── Shaft & Keys ─────────────────────────────────────────────────────────
  shaft_h6: `<svg viewBox="0 0 60 20" fill="none" stroke="currentColor" stroke-width="1.8" stroke-linecap="round">
    <rect x="2" y="4" width="56" height="12" rx="6"/>
  </svg>`,

  din705: `<svg viewBox="0 0 40 40" fill="none" stroke="currentColor" stroke-width="1.8">
    <circle cx="20" cy="20" r="17"/>
    <circle cx="20" cy="20" r="9"/>
    <rect x="18" y="2" width="4" height="7" rx="1" fill="currentColor" opacity="0.5" stroke="currentColor" stroke-width="1.2"/>
  </svg>`,

  din6885: `<svg viewBox="0 0 58 22" fill="none" stroke="currentColor" stroke-width="1.8" stroke-linecap="round">
    <rect x="3" y="3" width="52" height="16" rx="8"/>
    <line x1="11" y1="3" x2="11" y2="19" stroke-width="0.9" opacity="0.4"/>
    <line x1="47" y1="3" x2="47" y2="19" stroke-width="0.9" opacity="0.4"/>
  </svg>`,

  // ── Profiles ─────────────────────────────────────────────────────────────
  tslot: `<svg viewBox="0 0 40 40" fill="none" stroke="currentColor" stroke-width="1.5" stroke-linejoin="round">
    <path d="M4,4 L15,4 L15,8 L12,8 L12,14 L28,14 L28,8 L25,8 L25,4
             L36,4 L36,15 L32,15 L32,12 L26,12 L26,28 L32,28 L32,25 L36,25
             L36,36 L25,36 L25,32 L28,32 L28,26 L12,26 L12,32 L15,32 L15,36
             L4,36 L4,25 L8,25 L8,28 L14,28 L14,12 L8,12 L8,15 L4,15 Z"/>
    <circle cx="20" cy="20" r="3.5"/>
  </svg>`,
};

// Human-readable dimension labels
const DIM_LABELS = {
  d: "Ø Shank / Bore (d)", dk: "Ø Head (dk)", k: "Head Height (k)",
  s: "Socket / Key (s)", m: "Nut Height (m)", d1: "Ø Inner (d1)",
  d2: "Ø Outer (d2)", t: "Thickness (t)", pitch: "Thread Pitch",
  D: "Ø Outer (D)", B: "Width (B)", b: "Key Width (b)", h: "Key Height (h)",
  w: "Section (w)", slot_w: "Slot Opening", slot_d: "Slot Depth",
  center_d: "Center Bore",
};

async function initCatalog() {
  try {
    const r = await fetch("/api/catalog");
    state.catalog = await r.json();
  } catch (err) {
    console.warn("Failed to load catalog:", err);
  }
}

function openCatalogModal() {
  if (!state.catalog) return;
  $catalogError.classList.add("hidden");
  renderCatalogCategory(state.catalogCat);
  $catalogModal.classList.remove("hidden");
}

function closeCatalogModal() {
  $catalogModal.classList.add("hidden");
}

function renderCatalogCategory(cat) {
  state.catalogCat = cat;

  // Update active tab
  $catalogCatBtns.forEach(btn => {
    btn.classList.toggle("active", btn.dataset.cat === cat);
  });

  // Render icon grid
  const types = state.catalog[cat] || [];
  $catalogGrid.innerHTML = types.map(t => {
    const icon = PART_ICONS[t.id] || `<svg viewBox="0 0 40 40"><circle cx="20" cy="20" r="16" fill="none" stroke="currentColor" stroke-width="1.5"/></svg>`;
    const isSelected = t.id === state.catalogSelectedType;
    return `<div class="cat-card${isSelected ? " selected" : ""}" data-type="${escHtml(t.id)}" title="${escHtml(t.name)}">
      <div class="cat-card-icon">${icon}</div>
      <div class="cat-card-label">${escHtml(_shortName(t.name))}</div>
    </div>`;
  }).join("");

  // Attach click handlers
  $catalogGrid.querySelectorAll(".cat-card").forEach(card => {
    card.addEventListener("click", () => selectCatalogPart(card.dataset.type));
  });

  // If previously selected part is in this category, re-select it; else deselect
  const inCategory = types.some(t => t.id === state.catalogSelectedType);
  if (!inCategory) {
    state.catalogSelectedType = null;
    $catalogConfigEmpty.classList.remove("hidden");
    $catalogConfigPanel.classList.add("hidden");
  } else if (state.catalogSelectedType) {
    _showConfigPanel(state.catalogSelectedType);
  }
}

function selectCatalogPart(typeId) {
  state.catalogSelectedType = typeId;

  // Highlight selected card
  $catalogGrid.querySelectorAll(".cat-card").forEach(card => {
    card.classList.toggle("selected", card.dataset.type === typeId);
  });

  _showConfigPanel(typeId);
}

function _shortName(name) {
  // "ISO 4762 Socket Head Cap Screw" → "Socket Head\nCap Screw"
  // Keep under ~20 chars by taking last 2-3 words
  const words = name.split(" ");
  if (words.length <= 3) return name;
  // Drop leading standard prefix (ISO XXXX / DIN XXX)
  const idx = words.findIndex(w => !/^(ISO|DIN|Ball|Set|Plain|T-Slot|Shaft)$/i.test(w));
  return words.slice(Math.max(idx, 1)).join(" ");
}

function _showConfigPanel(typeId) {
  const cat = state.catalogCat;
  const types = state.catalog[cat] || [];
  const type = types.find(t => t.id === typeId);
  if (!type) return;

  $configPartName.textContent = type.name;

  // Size selector
  $catSizeSel.innerHTML = type.sizes
    .map(s => `<option value="${escHtml(s)}">${escHtml(s)}</option>`)
    .join("");

  // Length input
  if (type.has_length) {
    $catLengthRow.classList.remove("hidden");
    const defaults = type.default_lengths || [];
    const mid = defaults[Math.floor(defaults.length / 2)] || 20;
    $catLengthInp.value = mid;
  } else {
    $catLengthRow.classList.add("hidden");
  }

  // Dimension table for first size
  if (type.sizes.length > 0) {
    renderCatalogDims(typeId, type.sizes[0]);
  }

  $catalogConfigEmpty.classList.add("hidden");
  $catalogConfigPanel.classList.remove("hidden");
}

function renderCatalogDims(typeId, size) {
  const cat = state.catalogCat;
  const types = state.catalog[cat] || [];
  const type = types.find(t => t.id === typeId);
  if (!type) return;

  const dims = (type.dims || {})[size];
  if (!dims) { $catDimsTable.innerHTML = ""; return; }

  const rows = Object.entries(dims)
    .map(([k, v]) => `<tr><td class="dim-key">${escHtml(DIM_LABELS[k] || k)}</td><td class="dim-val">${v} mm</td></tr>`)
    .join("");

  $catDimsTable.innerHTML = `
    <thead><tr><th>Dimension</th><th>Value</th></tr></thead>
    <tbody>${rows}</tbody>`;
}

async function submitCatalogInsert() {
  const typeId = state.catalogSelectedType;
  if (!typeId) return;

  const cat = state.catalogCat;
  const types = state.catalog[cat] || [];
  const type = types.find(t => t.id === typeId);
  if (!type) return;

  const body = { type: typeId, size: $catSizeSel.value };
  if (type.has_length) {
    const len = parseFloat($catLengthInp.value);
    if (!len || len <= 0) {
      $catalogError.textContent = "Please enter a valid length (mm).";
      $catalogError.classList.remove("hidden");
      return;
    }
    body.length = len;
  }

  $catalogInsertBtn.disabled = true;
  $catalogInsertBtn.textContent = "Inserting…";
  $catalogError.classList.add("hidden");

  try {
    const res = await fetch("/api/catalog/insert", {
      method: "POST",
      headers: { "Content-Type": "application/json" },
      body: JSON.stringify(body),
    });

    if (!res.ok) {
      const err = await res.json().catch(() => ({}));
      $catalogError.textContent = err.detail || `Error ${res.status}`;
      $catalogError.classList.remove("hidden");
      return;
    }

    const part = await res.json();
    state.parts[part.id] = part;
    renderShelf();
    if (!state.activePart) {
      state.activePart = part.id;
      renderShelf();
      showPlaceholder("Part is generating…");
    }
    appendStatusMsg(`Inserting "${part.name}"…`);
    closeCatalogModal();
  } catch (err) {
    $catalogError.textContent = `Network error: ${err.message}`;
    $catalogError.classList.remove("hidden");
  } finally {
    $catalogInsertBtn.disabled = false;
    $catalogInsertBtn.textContent = "Insert Part";
  }
}

// Catalog event handlers
$catalogOpenBtn.addEventListener("click", openCatalogModal);
$catalogModalClose.addEventListener("click", closeCatalogModal);
$catalogModal.addEventListener("click", (e) => {
  if (e.target === $catalogModal) closeCatalogModal();
});
$catalogCatBtns.forEach(btn => {
  btn.addEventListener("click", () => renderCatalogCategory(btn.dataset.cat));
});
$catSizeSel.addEventListener("change", () => renderCatalogDims(state.catalogSelectedType, $catSizeSel.value));
$catalogInsertBtn.addEventListener("click", submitCatalogInsert);

// ── Refine Modal ──────────────────────────────────────────────────────────────
function openRefineModal(partId) {
  const part = state.parts[partId];
  if (!part || part.status !== "ready" || !part.design_plan) return;

  const constraints = part.design_plan.constraints || {};
  // numeric 값만 필터링 (load_class 같은 string, rib 같은 boolean 제외)
  const numericEntries = Object.entries(constraints)
    .filter(([, v]) => typeof v === "number");

  if (numericEntries.length === 0) {
    // fallback: chat 입력창에 프롬프트를 복사
    $chatInput.value = part.prompt;
    $chatInput.focus();
    return;
  }

  state.refinePart = partId;
  $refineModalTitle.textContent = `Edit Dimensions — ${part.name}`;
  $refineError.classList.add("hidden");
  $refineError.textContent = "";

  // 입력 필드 렌더링
  $refineFields.innerHTML = "";
  for (const [key, val] of numericEntries) {
    const unit = key.endsWith("_mm") ? "mm"
               : key.endsWith("_deg") ? "°"
               : "";
    const row = document.createElement("div");
    row.className = "refine-field-row";
    row.innerHTML =
      `<label class="refine-label">${escHtml(key)}</label>` +
      `<input type="number" class="refine-input" data-key="${escHtml(key)}"` +
      ` value="${val}" step="${Number.isInteger(val) ? 1 : 0.1}" min="0">` +
      `<span class="refine-unit">${escHtml(unit)}</span>`;
    $refineFields.appendChild(row);
  }

  $refineModal.classList.remove("hidden");
  // 첫 번째 입력 필드에 포커스
  const first = $refineFields.querySelector(".refine-input");
  if (first) first.focus();
}

function closeRefineModal() {
  $refineModal.classList.add("hidden");
  state.refinePart = null;
}

async function submitRefine() {
  const partId = state.refinePart;
  if (!partId) return;

  // 입력값 수집
  const constraints = {};
  $refineFields.querySelectorAll(".refine-input").forEach(input => {
    const key = input.dataset.key;
    const val = parseFloat(input.value);
    if (key && !isNaN(val)) constraints[key] = val;
  });

  $refineApplyBtn.disabled = true;
  $refineApplyBtn.textContent = "Regenerating…";
  $refineError.classList.add("hidden");

  try {
    const res = await fetch(`/api/parts/${partId}/refine`, {
      method: "POST",
      headers: { "Content-Type": "application/json" },
      body: JSON.stringify({ constraints }),
    });

    if (!res.ok) {
      const err = await res.json().catch(() => ({}));
      $refineError.textContent = err.detail || `Error ${res.status}`;
      $refineError.classList.remove("hidden");
      return;
    }

    const updatedPart = await res.json();
    state.parts[partId] = updatedPart;
    closeRefineModal();
    renderShelf();
    if (state.activePart === partId) {
      showPlaceholder("Part is regenerating…");
    }
    appendStatusMsg(`"${updatedPart.name}" — refining with updated dimensions`);
  } catch (err) {
    $refineError.textContent = `Network error: ${err.message}`;
    $refineError.classList.remove("hidden");
  } finally {
    $refineApplyBtn.disabled = false;
    $refineApplyBtn.textContent = "Apply & Regenerate";
  }
}

// Refine modal event handlers
$refineModalClose.addEventListener("click", closeRefineModal);
$refineCancelBtn.addEventListener("click", closeRefineModal);
$refineApplyBtn.addEventListener("click", submitRefine);
$refineModal.addEventListener("click", (e) => {
  if (e.target === $refineModal) closeRefineModal();
});
// Enter 키로 제출 (입력 필드 안에서)
$refineFields.addEventListener("keydown", (e) => {
  if (e.key === "Enter") { e.preventDefault(); submitRefine(); }
});

// ── Parts Shelf ───────────────────────────────────────────────────────────────
function renderShelf() {
  const parts = Object.values(state.parts)
    .sort((a, b) => new Date(a.created_at) - new Date(b.created_at));

  if (parts.length === 0) {
    $partsList.innerHTML = '<li class="shelf-empty">No parts yet. Submit a prompt to start.</li>';
    return;
  }

  $partsList.innerHTML = "";
  for (const part of parts) {
    const li = document.createElement("li");
    li.className = "part-item" + (part.id === state.activePart ? " active" : "");
    li.dataset.id = part.id;

    const time = new Date(part.created_at).toLocaleTimeString([], { hour: "2-digit", minute: "2-digit" });
    const spinnerHtml = isInProgress(part.status) ? `<span class="spinner"></span>` : "";
    const pipelineHtml = buildPipelineSteps(part);

    li.innerHTML = `
      <div class="part-name-row">
        <span class="part-name" title="Click to rename">${escHtml(part.name)}</span>
        <button class="refine-btn" data-id="${part.id}" title="Pre-fill chat with this prompt">Refine</button>
      </div>
      <span class="part-prompt">${escHtml(part.prompt)}</span>
      <div class="part-status-row">
        ${spinnerHtml}<span class="part-badge badge-${part.status}">${part.status}</span>
        <span class="part-time">${time}</span>
      </div>
      ${pipelineHtml}`;

    li.addEventListener("click", () => selectPart(part.id));

    const refineBtn = li.querySelector(".refine-btn");
    if (refineBtn) {
      if (part.status !== "ready" || !part.design_plan) {
        refineBtn.classList.add("hidden");   // 생성 중 또는 agents 비활성이면 숨김
      } else {
        refineBtn.classList.remove("hidden");
        refineBtn.addEventListener("click", (e) => {
          e.stopPropagation();
          openRefineModal(part.id);
        });
      }
    }

    li.querySelector(".part-name").addEventListener("click", (e) => {
      e.stopPropagation();
      startRename(part.id, li.querySelector(".part-name"));
    });

    $partsList.appendChild(li);
  }
}

/**
 * Build a mini pipeline-steps indicator for the part shelf.
 * Steps: Plan → Code → Run → Validate [→ Repair]
 */
function buildPipelineSteps(part) {
  const stages = ["Plan", "Code", "Run", "Validate"];
  const statusOrder = { generating: 1, validating: 3, repairing: 4, ready: 5 };
  const isFailed = part.status === "failed";
  const progress = statusOrder[part.status] ?? 0;

  const steps = stages.map((label, idx) => {
    const stepNum = idx + 1;
    let cls = "";
    if (isFailed) {
      // repair_iterations > 0 → all 4 steps done, repair badge shows error
      // otherwise → first 3 done, validate shows error (most common failure point)
      if (part.repair_iterations > 0) cls = "done";
      else                             cls = stepNum < 4 ? "done" : "error";
    } else if (stepNum < progress) {
      cls = "done";
    } else if (stepNum === progress) {
      cls = part.status === "ready" ? "done" : "active";
    }
    return `<span class="pipeline-step ${cls}">${label}</span>`;
  });

  if (part.repair_iterations > 0) {
    const repairCls = isFailed ? "error" : part.status === "ready" ? "done" : part.status === "repairing" ? "active" : "";
    steps.push(`<span class="pipeline-step ${repairCls}">Repair×${part.repair_iterations}</span>`);
  }

  return `<div class="pipeline-steps">${steps.join("")}</div>`;
}

function isInProgress(status) {
  return ["generating", "validating", "repairing"].includes(status);
}

function selectPart(id) {
  state.activePart = id;
  renderShelf();
  const part = state.parts[id];
  if (!part) return;

  if (part.status === "ready") {
    loadSTL(id);
  } else if (part.status === "failed") {
    showPlaceholder();
    showErrorPanel(part.error);
    $partInfo.classList.remove("visible");
    $downloadBar.classList.remove("visible");
  } else {
    showPlaceholder(`Part is ${part.status}…`);
    $partInfo.classList.remove("visible");
    $downloadBar.classList.remove("visible");
  }
}

// ── SSE ───────────────────────────────────────────────────────────────────────
function connectSSE() {
  const es = new EventSource("/api/events");

  es.onopen = () => {
    $connStatus.className = "status-dot connected";
    $connStatus.title = "Connected";
  };

  es.onerror = () => {
    $connStatus.className = "status-dot disconnected";
    $connStatus.title = "Disconnected — retrying…";
  };

  es.onmessage = (e) => {
    let event;
    try { event = JSON.parse(e.data); } catch { return; }

    const { type, data } = event;

    if (type === "connected") {
      fetchParts();
      return;
    }

    if (type === "part.status_changed") {
      const part = state.parts[data.id];
      if (part) {
        part.status = data.status;
        if (data.repair_iterations != null) part.repair_iterations = data.repair_iterations;
        renderShelf();
        if (state.activePart === data.id && data.status !== "ready") {
          showPlaceholder(`Part is ${data.status}…`);
        }
        appendStatusMsg(`"${part.name}" — ${data.status}`);
      }
      return;
    }

    if (type === "part.ready") {
      state.parts[data.id] = data;
      renderShelf();
      appendStatusMsg(`"${data.name}" ready ✓`);
      if (state.activePart === data.id) {
        loadSTL(data.id);
      } else if (!state.activePart) {
        selectPart(data.id);
      }
      return;
    }

    if (type === "part.failed") {
      state.parts[data.id] = data;
      renderShelf();
      appendStatusMsg(`"${data.name}" failed: ${data.error || "unknown error"}`, "error");
      if (state.activePart === data.id) {
        showPlaceholder();
        showErrorPanel(data.error);
      }
      return;
    }
  };
}

// ── Initial parts fetch ───────────────────────────────────────────────────────
async function fetchParts() {
  try {
    const r = await fetch("/api/parts");
    const parts = await r.json();
    for (const p of parts) state.parts[p.id] = p;
    renderShelf();
  } catch (err) {
    console.warn("fetchParts error:", err);
  }
}

// ── Chat ──────────────────────────────────────────────────────────────────────
$chatForm.addEventListener("submit", async (e) => {
  e.preventDefault();
  const msg = $chatInput.value.trim();
  if (!msg) return;

  $chatInput.value = "";
  $sendBtn.disabled = true;
  appendMessage("user", msg);

  try {
    const r = await fetch("/api/chat", {
      method: "POST",
      headers: { "Content-Type": "application/json" },
      body: JSON.stringify({ message: msg }),
    });

    if (!r.ok) {
      const err = await r.json().catch(() => ({}));
      appendMessage("error", `Error ${r.status}: ${err.detail || r.statusText}`);
    } else {
      const data = await r.json();
      state.parts[data.part_id] = {
        id: data.part_id, name: msg.slice(0, 40), prompt: msg,
        status: "generating", created_at: new Date().toISOString(),
        code: null, validation: null, exports: {}, repair_iterations: 0, error: null,
      };
      renderShelf();
      if (!state.activePart) {
        state.activePart = data.part_id;
        renderShelf();
        showPlaceholder("Part is generating…");
      }
    }
  } catch (err) {
    appendMessage("error", `Network error: ${err.message}`);
  } finally {
    $sendBtn.disabled = false;
    $chatInput.focus();
  }
});

// Enter = submit, Shift+Enter = newline
$chatInput.addEventListener("keydown", (e) => {
  if (e.key === "Enter" && !e.shiftKey) {
    e.preventDefault();
    $chatForm.dispatchEvent(new Event("submit"));
  }
});

// ── Chat helpers ──────────────────────────────────────────────────────────────
function appendMessage(role, text) {
  const div = document.createElement("div");
  div.className = `msg msg-${role}`;
  const label = role === "user" ? "You" : role === "error" ? "Error" : "System";
  div.innerHTML = `<span class="msg-role">${label}</span><div class="msg-body">${escHtml(text)}</div>`;
  $chatMessages.appendChild(div);
  $chatMessages.scrollTop = $chatMessages.scrollHeight;
}

function appendStatusMsg(text, variant = "status") {
  const div = document.createElement("div");
  div.className = `msg msg-${variant}`;
  div.innerHTML = `<div class="msg-body">${escHtml(text)}</div>`;
  $chatMessages.appendChild(div);
  $chatMessages.scrollTop = $chatMessages.scrollHeight;
}

// ── Part name inline rename ───────────────────────────────────────────────────
async function startRename(partId, nameEl) {
  const part = state.parts[partId];
  if (!part) return;

  const input = document.createElement("input");
  input.type = "text";
  input.value = part.name;
  input.className = "rename-input";
  nameEl.replaceWith(input);
  input.focus();
  input.select();

  async function commitRename() {
    const newName = input.value.trim();
    if (newName && newName !== part.name) {
      try {
        const res = await fetch(`/api/parts/${partId}`, {
          method: "PATCH",
          headers: { "Content-Type": "application/json" },
          body: JSON.stringify({ name: newName }),
        });
        if (res.ok) {
          const updated = await res.json();
          state.parts[partId] = { ...state.parts[partId], name: updated.name };
          if (state.activePart === partId) $partInfoName.textContent = updated.name;
        }
      } catch { /* network error — revert silently */ }
    }
    renderShelf();
  }

  input.addEventListener("blur", commitRename);
  input.addEventListener("keydown", (e) => {
    if (e.key === "Enter")  { e.preventDefault(); input.blur(); }
    if (e.key === "Escape") { input.value = part.name; input.blur(); }
  });
}

// ── Utilities ─────────────────────────────────────────────────────────────────
function escHtml(str) {
  return String(str)
    .replace(/&/g, "&amp;")
    .replace(/</g, "&lt;")
    .replace(/>/g, "&gt;")
    .replace(/"/g, "&quot;");
}

// ── Boot ──────────────────────────────────────────────────────────────────────
connectSSE();
initCatalog();
