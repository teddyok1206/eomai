const form = document.querySelector("#login-form");
const error = document.querySelector("#login-error");

form.addEventListener("submit", async (event) => {
  event.preventDefault();
  error.textContent = "";
  const token = document.querySelector("#access-token").value;
  try {
    const response = await fetch("/observe/api/v1/session", {
      method: "POST",
      credentials: "same-origin",
      headers: { "Content-Type": "application/json", Accept: "application/json" },
      body: JSON.stringify({ token }),
    });
    if (!response.ok) {
      error.textContent = response.status === 429 ? "Too many attempts. Try again later." : "Access token not accepted.";
      return;
    }
    window.location.replace("/observe/");
  } catch (_) {
    error.textContent = "The console is unavailable.";
  }
});
