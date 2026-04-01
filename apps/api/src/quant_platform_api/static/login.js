import { api, getNextPath, setStatus } from "/assets/shared.js";

document.querySelector("#login-form").addEventListener("submit", async (event) => {
  event.preventDefault();
  const username = document.querySelector("#username").value.trim();
  const password = document.querySelector("#password").value;

  try {
    setStatus("正在登录...");
    await api("/api/v1/auth/login", {
      method: "POST",
      body: JSON.stringify({ username, password }),
    });
    setStatus("登录成功，正在跳转。");
    window.location.href = getNextPath("/workspace");
  } catch (error) {
    setStatus(error.message);
  }
});
