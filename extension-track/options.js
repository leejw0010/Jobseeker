import { getSettings, saveSettings } from "./settings.js";

const form = document.getElementById("form");
const s = await getSettings();
form.apiUrl.value = s.apiUrl;
form.webUrl.value = s.webUrl;
form.onsubmit = async (e) => {
  e.preventDefault();
  await saveSettings({ apiUrl: form.apiUrl.value.trim(), webUrl: form.webUrl.value.trim() });
  document.getElementById("saved").hidden = false;
};
