import { api, getNextPath, setStatus } from "/assets/shared.js";

document.querySelector("#register-form").addEventListener("submit", async (event) => {
  event.preventDefault();
  const username = document.querySelector("#username").value.trim();
  const contact = document.querySelector("#contact").value.trim();
  const password = document.querySelector("#password").value;

  try {
    setStatus("正在创建账户...");
    await api("/api/v1/auth/register", {
      method: "POST",
      body: JSON.stringify({ username, contact, password }),
    });
    setStatus("注册成功，正在跳转。");
    window.location.href = getNextPath("/workspace");
  } catch (error) {
    setStatus(error.message);
  }
});
