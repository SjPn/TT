document.addEventListener("htmx:afterRequest", (event) => {
  const dialog = event.target.closest?.("dialog");
  if (dialog && event.detail.successful) {
    dialog.close();
    const form = dialog.querySelector("form");
    if (form) form.reset();
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
