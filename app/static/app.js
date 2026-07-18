document.addEventListener("htmx:afterRequest", (event) => {
  const dialog = event.target.closest?.("dialog");
  if (dialog && event.detail.successful) {
    dialog.close();
    const form = dialog.querySelector("form");
    if (form) form.reset();
    form?.querySelectorAll(".photo-preview").forEach((box) => {
      box.innerHTML = "";
      box.hidden = true;
    });
  }
});

document.addEventListener("click", (event) => {
  const dialog = event.target.closest("dialog");
  if (!dialog) return;
  const rect = dialog.getBoundingClientRect();
  const inDialog =
    event.clientX >= rect.left &&
    event.clientX <= rect.right &&
    event.clientY >= rect.top &&
    event.clientY <= rect.bottom;
  if (!inDialog) dialog.close();
});

const FLASH_MESSAGES = {
  created: "Задача создана",
  saved: "Изменения сохранены",
  deleted: "Задача удалена",
  project: "Проект создан",
  project_saved: "Проект сохранён",
  project_deleted: "Проект удалён",
  profile: "Профиль сохранён",
};

function showToast(text) {
  const el = document.getElementById("toast");
  if (!el || !text) return;
  el.textContent = text;
  el.hidden = false;
  clearTimeout(showToast._t);
  showToast._t = setTimeout(() => {
    el.hidden = true;
  }, 2800);
}

function isTypingTarget(el) {
  if (!el) return false;
  const tag = (el.tagName || "").toLowerCase();
  return tag === "input" || tag === "textarea" || tag === "select" || el.isContentEditable;
}

function openNewIssue() {
  const dialog = document.getElementById("new-issue");
  if (!dialog) return;
  dialog.showModal();
  dialog.querySelector("[name=title]")?.focus();
}

function renderPhotoPreview(input) {
  const box = input.parentElement?.querySelector(".photo-preview");
  if (!box) return;
  box.innerHTML = "";
  const files = [...(input.files || [])].filter((f) => f.type.startsWith("image/"));
  if (!files.length) {
    box.hidden = true;
    return;
  }
  box.hidden = false;
  files.slice(0, 8).forEach((file) => {
    const url = URL.createObjectURL(file);
    const img = document.createElement("img");
    img.src = url;
    img.alt = file.name;
    img.onload = () => URL.revokeObjectURL(url);
    box.appendChild(img);
  });
}

function mergeImageFiles(input, newFiles) {
  if (!input || !newFiles.length) return 0;
  const dt = new DataTransfer();
  const existing = [...(input.files || [])];
  existing.forEach((f) => dt.items.add(f));
  let added = 0;
  for (const file of newFiles) {
    if (!file.type.startsWith("image/")) continue;
    if (dt.files.length >= 8) break;
    dt.items.add(file);
    added += 1;
  }
  input.files = dt.files;
  renderPhotoPreview(input);
  return added;
}

function filesFromClipboard(clipboardData) {
  if (!clipboardData) return [];
  const out = [];
  const items = clipboardData.items ? [...clipboardData.items] : [];
  items.forEach((item, i) => {
    if (item.kind !== "file" || !item.type.startsWith("image/")) return;
    const file = item.getAsFile();
    if (!file) return;
    const ext = (file.type.split("/")[1] || "png").replace("jpeg", "jpg");
    const named =
      file.name && file.name !== "image.png"
        ? file
        : new File([file], `paste-${Date.now()}-${i}.${ext}`, { type: file.type });
    out.push(named);
  });
  if (!out.length && clipboardData.files?.length) {
    [...clipboardData.files].forEach((file, i) => {
      if (!file.type.startsWith("image/")) return;
      const ext = (file.type.split("/")[1] || "png").replace("jpeg", "jpg");
      out.push(
        new File([file], `paste-${Date.now()}-${i}.${ext}`, { type: file.type })
      );
    });
  }
  return out;
}

document.addEventListener("DOMContentLoaded", () => {
  const flash = document.body?.dataset?.flash;
  if (flash && FLASH_MESSAGES[flash]) showToast(FLASH_MESSAGES[flash]);
});

document.addEventListener("keydown", (e) => {
  if (e.key === "Escape") {
    const open = document.querySelector("dialog[open]");
    if (open) open.close();
    return;
  }

  if (isTypingTarget(e.target) && !(e.target?.matches?.("[data-quick-title]") && e.key === "Enter")) {
    if (e.target?.matches?.("[data-quick-title]") && e.key === "Enter") {
      e.preventDefault();
      e.target.form?.requestSubmit();
    }
    return;
  }

  if (e.metaKey || e.ctrlKey || e.altKey) return;

  if (e.key === "/") {
    const search = document.querySelector(".filters input[type=search], input.search");
    if (search) {
      e.preventDefault();
      search.focus();
      search.select?.();
    }
    return;
  }

  if (e.key === "c" || e.key === "C" || e.key === "n" || e.key === "N") {
    if (document.getElementById("new-issue")) {
      e.preventDefault();
      openNewIssue();
    }
  }
});

document.addEventListener("change", (event) => {
  const input = event.target;
  if (!input?.matches?.("input[data-preview]")) return;
  renderPhotoPreview(input);
});

document.addEventListener("paste", (event) => {
  const target = event.target;
  const form = target?.closest?.("form");
  if (!form) return;
  const input = form.querySelector('input[type=file][name=photos][data-preview]');
  if (!input) return;

  const images = filesFromClipboard(event.clipboardData);
  if (!images.length) return;

  event.preventDefault();
  const added = mergeImageFiles(input, images);
  if (added) {
    showToast(added === 1 ? "Фото из буфера добавлено" : `Добавлено фото: ${added}`);
  }
});
