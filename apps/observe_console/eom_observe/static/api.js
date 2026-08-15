const API_ROOT = "/observe/api/v1";

export async function apiGet(path) {
  const response = await fetch(`${API_ROOT}${path}`, {
    credentials: "same-origin",
    headers: { Accept: "application/json" },
  });
  if (response.status === 401) {
    window.location.assign("/observe/login");
    throw new Error("authentication required");
  }
  if (!response.ok) {
    throw new Error(`request failed (${response.status})`);
  }
  return response.json();
}

export async function logout() {
  await fetch(`${API_ROOT}/logout`, {
    method: "POST",
    credentials: "same-origin",
    headers: { Accept: "application/json" },
  });
  window.location.assign("/observe/login");
}

export function streamUrl() {
  return `${API_ROOT}/stream`;
}
