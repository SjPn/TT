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

document.addEventListener("DOMContentLoaded", () => {
  const flash = document.body?.dataset?.flash;
  if (flash && FLASH_MESSAGES[flash]) showToast(FLASH_MESSAGES[flash]);
});

document.addEventListener("change", (event) => {
  const input = event.target;
  if (!input?.matches?.("input[data-preview]")) return;
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
});
