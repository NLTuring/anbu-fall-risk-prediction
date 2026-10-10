"use strict";
const el = id => document.getElementById(id);
let token = "", generation = 0, timer = null, objectURL = null, controller = null;
let mutation = false;
const labels = {no_model:"No model",not_loaded:"Model not loaded",loading:"Model loading",
  ready:"Model ready",no_people:"No people detected",people_detected:"People detected",model_error:"MODEL ERROR"};
function clearFrame() {
  el("frame").hidden = true;
  el("frame").removeAttribute("src");
  if (objectURL) URL.revokeObjectURL(objectURL);
  objectURL = null;
  el("caption").textContent = "No fresh live frame";
}
function cancel() {
  generation++;
  clearTimeout(timer);
  if (controller) controller.abort();
  controller = null;
}
function buttons() {
  el("start").disabled = !token || mutation;
  el("stop").disabled = !token || mutation;
  el("logout").disabled = !token || mutation;
  el("login").disabled = !!token || mutation;
}
async function request(path, method = "GET") {
  const own = new AbortController();
  controller = own;
  const timeout = setTimeout(() => own.abort(), 8000);
  try {
    const response = await fetch(path, {method, headers:{Authorization:`Bearer ${token}`},
      cache:"no-store", credentials:"omit", signal:own.signal});
    if (!response.ok) {
      const error = new Error(response.status === 401 ? "Authentication failed" : `Request failed (${response.status})`);
      error.status = response.status;
      throw error;
    }
    // Consume body before allowing another request, also covered by timeout.
    if (path === "/api/frame") return {blob:await response.blob(),
      model:response.headers.get("X-Pose-State"), people:response.headers.get("X-People-Count"),
      sequence:response.headers.get("X-Frame-Sequence")};
    return await response.json();
  } finally {
    clearTimeout(timeout);
    if (controller === own) controller = null;
  }
}
function disconnect() {
  cancel(); token = ""; el("token").value = ""; clearFrame(); buttons();
  el("status").textContent = "Disconnected. Camera may still be running; reconnect to stop it.";
}
async function poll(g) {
  if (!token || g !== generation || mutation) return;
  try {
    const status = await request("/api/status");
    if (g !== generation) return;
    el("status").textContent = JSON.stringify(status, null, 2);
    el("message").textContent = `${status.camera} · ${labels[status.model] || status.model}`;
    if (status.frame_fresh && status.camera === "running") {
      const frame = await request("/api/frame");
      if (g !== generation) return;
      const next = URL.createObjectURL(frame.blob);
      const previous = objectURL;
      objectURL = next;
      el("frame").src = next;
      el("frame").hidden = false;
      if (previous) URL.revokeObjectURL(previous);
      el("caption").textContent = `Frame ${frame.sequence} · ${labels[frame.model] || frame.model} · people: ${frame.people}`;
    } else clearFrame();
  } catch (error) {
    if (g !== generation) return;
    clearFrame();
    el("message").textContent = error.message;
    if (error.status === 401) { disconnect(); return; }
  }
  // One status request then one frame request, never overlapping; at most 5 polls/sec.
  if (g === generation && token) timer = setTimeout(() => poll(g), 200);
}
el("login").onclick = () => {
  token = el("token").value;
  el("token").value = "";
  if (token.length < 32) { token = ""; el("message").textContent = "Token must be at least 32 characters"; return; }
  cancel(); buttons(); poll(generation);
};
el("logout").onclick = disconnect;
async function control(action) {
  if (!token || mutation) return;
  mutation = true; cancel(); clearFrame(); buttons();
  try {
    const status = await request(`/api/camera/${action}`, "POST");
    el("status").textContent = JSON.stringify(status, null, 2);
  } catch (error) {
    el("message").textContent = `${error.message}. Camera state is uncertain; check status.`;
    if (error.status === 401) disconnect();
  } finally {
    mutation = false; buttons();
    if (token) poll(generation);
  }
}
el("start").onclick = () => control("start");
el("stop").onclick = () => control("stop");
document.addEventListener("visibilitychange", () => {
  if (mutation) return;
  cancel(); clearFrame();
  if (!document.hidden && token) poll(generation);
});
window.addEventListener("pagehide", () => { cancel(); token = ""; clearFrame(); });
