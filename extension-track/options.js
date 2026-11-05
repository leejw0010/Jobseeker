import { getSettings, hostPermissionWarning, saveSettings } from "./settings.js";

const form = document.getElementById("form");
const warning = document.getElementById("warning");
const showWarning = (apiUrl) => {
  const msg = hostPermissionWarning(apiUrl, chrome.runtime.getManifest());
  warning.hidden = !msg;
  warning.textContent = msg ?? "";
};
const s = await getSettings();
form.apiUrl.value = s.apiUrl;
form.webUrl.value = s.webUrl;
form.loginUrl.value = s.loginUrl;
showWarning(s.apiUrl);
form.onsubmit = async (e) => {
  e.preventDefault();
  const apiUrl = form.apiUrl.value.trim();
  await saveSettings({ apiUrl, webUrl: form.webUrl.value.trim(), loginUrl: form.loginUrl.value.trim() });
  showWarning(apiUrl);
  document.getElementById("saved").hidden = false;
};
