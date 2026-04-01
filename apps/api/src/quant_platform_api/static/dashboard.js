import {
  activateNav,
  fetchCurrentUser,
  setStatus,
} from "/assets/shared.js";

activateNav("/");

async function loadDashboard() {
  const user = await fetchCurrentUser();
  const accountNode = document.querySelector("#home-account");
  const primaryAction = document.querySelector("#primary-cta");
  const secondaryAction = document.querySelector("#secondary-cta");
  const authHint = document.querySelector("#auth-hint");

  if (user) {
    accountNode.textContent = `${user.username} / ${user.role}`;
    primaryAction.textContent = "进入用户工作台";
    primaryAction.href = "/workspace";
    secondaryAction.textContent = "继续策略研究";
    secondaryAction.href = "/strategy";
    authHint.textContent = "已检测到登录状态，可直接进入工作台和各研究模块。";
    setStatus(`欢迎回来，${user.username}。`);
    return;
  }

  accountNode.textContent = "未登录";
  primaryAction.textContent = "登录后进入工作台";
  primaryAction.href = "/workspace";
  secondaryAction.textContent = "注册试用账户";
  secondaryAction.href = "/register";
  authHint.textContent = "首页可公开访问，进入工作台或任何研究模块时会先跳转到登录页。";
  setStatus("平台入口已就绪。");
}

loadDashboard().catch((error) => setStatus(error.message));
