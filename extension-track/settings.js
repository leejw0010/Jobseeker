// 확장 설정(chrome.storage.sync). 옵션 페이지에서 바꿀 수 있다.
export const DEFAULTS = {
  apiUrl: "http://localhost:8000",
  webUrl: "http://localhost:5173",
};

export async function getSettings() {
  const saved = await chrome.storage.sync.get(Object.keys(DEFAULTS));
  return { ...DEFAULTS, ...saved };
}

export async function saveSettings(values) {
  await chrome.storage.sync.set(values);
}
