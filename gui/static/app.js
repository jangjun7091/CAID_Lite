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
