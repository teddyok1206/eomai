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
    if (!response.ok) throw new Error(response.status === 401 ? "사용자 이름 또는 비밀번호를 확인하세요." : "로그인할 수 없습니다.");
    window.location.replace("/studio/");
  } catch (failure) {
    error.textContent = failure instanceof Error ? failure.message : "로그인할 수 없습니다.";
    submit.disabled = false;
  }
});
