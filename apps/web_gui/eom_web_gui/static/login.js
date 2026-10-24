const form = document.querySelector("#login-form");
const error = document.querySelector("#login-error");

form.addEventListener("submit", async (event) => {
  event.preventDefault();
  error.textContent = "";
  const submit = form.querySelector("button[type='submit']");
  submit.disabled = true;
  try {
    const response = await fetch("/studio/api/v1/session", {
      method: "POST",
      credentials: "same-origin",
      headers: {"Accept": "application/json", "Content-Type": "application/json"},
      body: JSON.stringify({
        username: form.elements.username.value,
        password: form.elements.password.value,
      }),
    });
    form.elements.password.value = "";
    if (!response.ok) {
      let problem = null;
      try { problem = await response.json(); } catch { /* The status remains authoritative. */ }
      const message = response.status === 401
        ? "사용자 이름 또는 비밀번호를 확인하세요."
        : response.status === 429
          ? "로그인 시도가 많아 잠시 제한되었습니다. 연속해서 누르지 말고 잠시 후 다시 시도하세요. 비밀번호를 재설정했는데도 계속되면 관리자에게 알려주세요."
          : "지금 로그인할 수 없습니다. 잠시 후 다시 시도하거나 관리자에게 알려주세요.";
      const reference = typeof problem?.request_id === "string" && /^webreq_[0-9a-f]{24}$/.test(problem.request_id)
        ? ` 문의 번호: ${problem.request_id}` : "";
      throw new Error(message + reference);
    }
    window.location.replace("/studio/");
  } catch (failure) {
    error.textContent = failure instanceof Error ? failure.message : "로그인할 수 없습니다.";
    submit.disabled = false;
  }
});
