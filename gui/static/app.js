/**
 * CAID Lite — 3-pane GUI
 *
 * Pane responsibilities:
 *   - Parts Shelf  : renders the parts list; handles selection
 *   - Viewport     : three.js STL preview + download bar
 *   - Chat Panel   : prompt input, message history, SSE status updates
 *
 * Communication:
 *   - POST /api/chat          submit prompt
 *   - GET  /api/parts         initial shelf load
 *   - GET  /api/events        SSE stream (status, ready, failed)
 *   - GET  /api/parts/:id/stl streamed into STL loader
 *   - GET  /api/parts/:id/step|stl  download links
 */

import * as THREE from "three";
import { OrbitControls } from "three/addons/controls/OrbitControls.js";
import { STLLoader } from "three/addons/loaders/STLLoader.js";

// ── State ─────────────────────────────────────────────────────────────────────
const state = {
  parts: {},          // id → part dict
  activePart: null,   // currently selected part id
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

// ── Three.js setup ────────────────────────────────────────────────────────────
const renderer = new THREE.WebGLRenderer({ canvas: $canvas, antialias: true });
renderer.setPixelRatio(window.devicePixelRatio);
renderer.setClearColor(0x0f1117);
renderer.shadowMap.enabled = true;

const scene  = new THREE.Scene();
const camera = new THREE.PerspectiveCamera(45, 1, 0.01, 10000);
const controls = new OrbitControls(camera, $canvas);
controls.enableDamping = true;
controls.dampingFactor = 0.08;

// Lighting
scene.add(new THREE.AmbientLight(0xffffff, 0.45));
const key = new THREE.DirectionalLight(0xffffff, 1.0);
key.position.set(1, 2, 1.5);
scene.add(key);
const fill = new THREE.DirectionalLight(0x8ab4f8, 0.4);
fill.position.set(-1, -0.5, -1);
scene.add(fill);

let currentMesh = null;

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
}

const resizeObs = new ResizeObserver(resizeRenderer);
resizeObs.observe($viewport);
resizeRenderer();
animate();

// ── STL loading ───────────────────────────────────────────────────────────────
const stlLoader = new STLLoader();

function loadSTL(partId) {
  if (currentMesh) {
    scene.remove(currentMesh);
    currentMesh.geometry.dispose();
    currentMesh.material.dispose();
    currentMesh = null;
  }

  $canvas.classList.remove("hidden");
  $placeholder.classList.add("hidden");

  stlLoader.load(
    `/api/parts/${partId}/stl`,
    (geometry) => {
      geometry.computeVertexNormals();
      const material = new THREE.MeshStandardMaterial({
        color: 0x5b8af5, metalness: 0.2, roughness: 0.55,
      });
      const mesh = new THREE.Mesh(geometry, material);
      currentMesh = mesh;
      scene.add(mesh);

      // Fit camera to geometry
      const box = new THREE.Box3().setFromObject(mesh);
      const center = box.getCenter(new THREE.Vector3());
      const size = box.getSize(new THREE.Vector3()).length();
      mesh.position.sub(center);  // center at origin
      camera.position.set(size * 0.6, size * 0.4, size * 0.8);
      camera.near = size * 0.001;
      camera.far  = size * 100;
      camera.updateProjectionMatrix();
      controls.target.set(0, 0, 0);
      controls.update();

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
}

function updatePartInfo(partId) {
  const part = state.parts[partId];
  if (!part) return;

  $partInfoName.textContent = part.name;
  const lines = [];
  if (part.validation) {
    if (part.validation.volume != null) {
      lines.push(`Volume: ${part.validation.volume.toFixed(1)} mm³`);
    }
    if (part.validation.face_count != null) {
      lines.push(`Faces: ${part.validation.face_count}`);
    }
    if (part.validation.bbox) {
      const [x, y, z] = part.validation.bbox.map(v => v.toFixed(1));
      lines.push(`BBox: ${x} × ${y} × ${z} mm`);
    }
  }
  if (part.repair_iterations > 0) {
    lines.push(`Repairs: ${part.repair_iterations}`);
  }
  $partInfoMeta.textContent = lines.join("\n");
  $partInfo.classList.add("visible");

  $dlStep.href = `/api/parts/${partId}/step`;
  $dlStep.download = `${part.name}_${partId.slice(0, 8)}.step`;
  $dlStl.href = `/api/parts/${partId}/stl`;
  $dlStl.download = `${part.name}_${partId.slice(0, 8)}.stl`;
  $downloadBar.classList.add("visible");
}

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

    li.innerHTML = `
      <span class="part-name">${escHtml(part.name)}</span>
      <span class="part-prompt">${escHtml(part.prompt)}</span>
      <div class="part-status-row">
        ${spinnerHtml}<span class="part-badge badge-${part.status}">${part.status}</span>
        <span class="part-time">${time}</span>
      </div>`;

    li.addEventListener("click", () => selectPart(part.id));
    $partsList.appendChild(li);
  }
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
    showPlaceholder("Generation failed — see chat for details");
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
    // Browser auto-reconnects EventSource; clean up and let it retry
  };

  es.onmessage = (e) => {
    let event;
    try { event = JSON.parse(e.data); } catch { return; }

    const { type, data } = event;

    if (type === "connected") {
      // Initial handshake; load current parts
      fetchParts();
      return;
    }

    if (type === "part.status_changed") {
      const part = state.parts[data.id];
      if (part) {
        part.status = data.status;
        renderShelf();
        // If this part is currently selected, update placeholder text
        if (state.activePart === data.id && data.status !== "ready") {
          showPlaceholder(`Part is ${data.status}…`);
        }
        appendStatusMsg(`Part "${part.name}" — ${data.status}`);
      }
      return;
    }

    if (type === "part.ready") {
      state.parts[data.id] = data;
      renderShelf();
      appendStatusMsg(`"${data.name}" ready`);
      // Auto-select if this is the first ready part or already selected
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
        showPlaceholder("Generation failed");
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
    for (const p of parts) {
      state.parts[p.id] = p;
    }
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
      // Part will arrive via SSE; add it to state immediately as "generating"
      state.parts[data.part_id] = {
        id: data.part_id, name: msg.slice(0, 40), prompt: msg,
        status: "generating", created_at: new Date().toISOString(),
        validation: null, exports: {}, repair_iterations: 0, error: null,
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
