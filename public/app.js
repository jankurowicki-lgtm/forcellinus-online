const $ = (selector) => document.querySelector(selector);
const state = { meta: null, entry: null, indexCache: new Map(), chunkCache: new Map() };
const storage = {
  get(key, fallback = []) {
    try { return JSON.parse(localStorage.getItem(key)) ?? fallback; } catch { return fallback; }
  },
  set(key, value) { localStorage.setItem(key, JSON.stringify(value)); }
};

function normalizeLemma(value) {
  return value.trim().toLowerCase().normalize("NFD")
    .replace(/\p{Diacritic}/gu, "")
    .replaceAll("æ", "ae").replaceAll("œ", "oe")
    .replaceAll("j", "i").replaceAll("v", "u")
    .replace(/[^a-z]/g, "");
}

function decodeOcrEntities(value) {
  const textarea = document.createElement("textarea");
  textarea.innerHTML = value;
  return textarea.value;
}

function formatEntryText(value) {
  return decodeOcrEntities(value)
    .normalize("NFC")
    .replace(/[\u00ad\u200b\ufeff]/g, "")
    .replace(/(\p{L})-\s*\n\s*(?=\p{Ll})/gu, "$1")
    .replace(/\s*\n+\s*/g, " ")
    .replace(/[ \t]{2,}/g, " ")
    .trim();
}

function bucketFor(key) { return (key.slice(0, 2) || "_").padEnd(2, "_"); }
function setStatus(message) { $("#status").textContent = message; }

async function getJson(path) {
  const response = await fetch(path);
  if (!response.ok) throw new Error(`${response.status} ${response.statusText}`);
  return response.json();
}

async function findEntry(query) {
  const key = normalizeLemma(query);
  if (!key) return null;
  const bucket = bucketFor(key);
  if (!state.indexCache.has(bucket)) {
    state.indexCache.set(bucket, await getJson(`./data/index/${bucket}.json`));
  }
  const ref = state.indexCache.get(bucket)[key];
  if (!ref) return null;
  if (!state.chunkCache.has(ref.file)) {
    state.chunkCache.set(ref.file, await getJson(`./data/chunks/${ref.file}`));
  }
  return state.chunkCache.get(ref.file).find((item) => item.id === ref.id) ?? null;
}

function updateList(id, items, removable = false) {
  const list = $(id);
  list.replaceChildren();
  for (const lemma of items) {
    const li = document.createElement("li");
    const open = document.createElement("button");
    open.type = "button";
    open.textContent = lemma;
    open.addEventListener("click", () => search(lemma));
    li.append(open);
    if (removable) {
      const remove = document.createElement("button");
      remove.type = "button";
      remove.className = "remove";
      remove.textContent = "×";
      remove.ariaLabel = `Usuń ${lemma}`;
      remove.addEventListener("click", () => {
        const next = storage.get("saved").filter((item) => item !== lemma);
        storage.set("saved", next);
        updateList("#saved-list", next, true);
        syncSaveButton();
      });
      li.append(remove);
    }
    list.append(li);
  }
}

function remember(lemma) {
  const history = [lemma, ...storage.get("history").filter((item) => item !== lemma)].slice(0, 12);
  storage.set("history", history);
  updateList("#history-list", history);
}

function syncSaveButton() {
  const saved = storage.get("saved");
  const active = state.entry && saved.includes(state.entry.lemma);
  $("#save-entry").textContent = active ? "★" : "☆";
  $("#save-entry").ariaPressed = String(Boolean(active));
}

async function search(rawQuery) {
  const query = rawQuery.trim();
  if (!query) return;
  $("#lemma").value = query;
  setStatus("Quaeritur…");
  try {
    const entry = await findEntry(query);
    if (!entry) {
      state.entry = null;
      $("#result").hidden = true;
      setStatus(`Nie znaleziono hasła „${query}” w tej bazie OCR.`);
      return;
    }
    state.entry = entry;
    $("#entry-title").textContent = entry.lemma;
    $("#entry-text").textContent = formatEntryText(entry.text);
    $("#source-link").href = state.meta.sources[entry.source].page_url;
    $("#result").hidden = false;
    remember(entry.lemma);
    syncSaveButton();
    setStatus(`Inventa: ${entry.lemma}`);
    history.replaceState(null, "", `#${encodeURIComponent(entry.lemma)}`);
    $("#result").scrollIntoView({ behavior: "smooth", block: "start" });
  } catch (error) {
    console.error(error);
    setStatus("Nie udało się odczytać danych. Spróbuj ponownie po odzyskaniu połączenia.");
  }
}

$("#search-form").addEventListener("submit", (event) => {
  event.preventDefault();
  search($("#lemma").value);
});

$("#save-entry").addEventListener("click", () => {
  if (!state.entry) return;
  const saved = storage.get("saved");
  const next = saved.includes(state.entry.lemma)
    ? saved.filter((item) => item !== state.entry.lemma)
    : [state.entry.lemma, ...saved];
  storage.set("saved", next);
  updateList("#saved-list", next, true);
  syncSaveButton();
});

$("#clear-history").addEventListener("click", () => {
  storage.set("history", []);
  updateList("#history-list", []);
});

const savedTheme = localStorage.getItem("theme");
if (savedTheme) document.documentElement.dataset.theme = savedTheme;
$("#theme-toggle").addEventListener("click", () => {
  const theme = document.documentElement.dataset.theme === "dark" ? "light" : "dark";
  document.documentElement.dataset.theme = theme;
  localStorage.setItem("theme", theme);
});

async function init() {
  updateList("#history-list", storage.get("history"));
  updateList("#saved-list", storage.get("saved"), true);
  try {
    state.meta = await getJson("./data/meta.json");
    const scope = state.meta.import_status === "full" ? "pełny import" : "uczciwie oznaczona baza próbna";
    $("#dataset-note").textContent = `Baza: ${scope}; ${state.meta.article_count.toLocaleString("pl-PL")} artykułów wydobytych z OCR.`;
    setStatus(`Paratum — ${state.meta.article_count.toLocaleString("pl-PL")} artykułów OCR.`);
    if (location.hash.length > 1) search(decodeURIComponent(location.hash.slice(1)));
  } catch (error) {
    console.error(error);
    setStatus("Dane słownika nie zostały zbudowane.");
  }
  if ("serviceWorker" in navigator) navigator.serviceWorker.register("./sw.js");
}

init();
