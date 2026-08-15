const state = {
  snapshot: null,
  paused: false,
  pendingSnapshot: null,
  selectedNodeId: null,
  streamConnected: false,
};

const listeners = new Set();

export function getState() {
  return state;
}

export function subscribe(listener) {
  listeners.add(listener);
  return () => listeners.delete(listener);
}

function notify() {
  for (const listener of listeners) listener(state);
}

export function receiveSnapshot(snapshot) {
  if (state.paused) {
    state.pendingSnapshot = snapshot;
  } else {
    state.snapshot = snapshot;
    state.pendingSnapshot = null;
  }
  notify();
}

export function togglePaused() {
  state.paused = !state.paused;
  if (!state.paused && state.pendingSnapshot) {
    state.snapshot = state.pendingSnapshot;
    state.pendingSnapshot = null;
  }
  notify();
}

export function selectNode(nodeId) {
  state.selectedNodeId = nodeId;
  notify();
}

export function setStreamConnected(connected) {
  state.streamConnected = connected;
  notify();
}
