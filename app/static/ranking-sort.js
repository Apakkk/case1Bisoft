// Rules page: reorder the ranking by dragging a row's grip (pointer events: mouse, touch and pen) or with
// ↑ / ↓ on a focused grip. The row moves with its hidden "ranking" input; when the order changed, the form
// gets a "reordered" event and HTMX posts the draft, so the server re-renders numbering and the save state.
// Listeners sit on document because every edit swaps the whole form.
(() => {
  "use strict";

  let drag = null; // { grip, row, body, before: original order }
  let refocus = null; // key of the row whose grip gets focus back after the swap

  const keys = (body) => [...body.children].map((row) => row.dataset.key).join(",");

  function changed(body, before) {
    if (keys(body) === before) return;
    body.closest("form").dispatchEvent(new Event("reordered", { bubbles: true }));
  }

  document.addEventListener("pointerdown", (event) => {
    const grip = event.target.closest("[data-grip]");
    if (!grip || event.button !== 0) return;
    const row = grip.closest("tr");
    event.preventDefault();
    grip.setPointerCapture(event.pointerId);
    drag = { grip, row, body: row.parentElement, before: keys(row.parentElement), order: [...row.parentElement.children] };
    row.classList.add("dragging");
  });

  document.addEventListener("pointermove", (event) => {
    if (!drag) return;
    const { row, body } = drag;
    // The first other row whose middle is below the pointer: the dragged row goes before it.
    const next = [...body.children].find(
      (other) => other !== row && event.clientY < other.getBoundingClientRect().top + other.offsetHeight / 2,
    ) || null;
    if (next !== row.nextElementSibling) body.insertBefore(row, next);
  });

  function finish(cancel) {
    if (!drag) return;
    const { row, body, before, order } = drag;
    drag = null;
    row.classList.remove("dragging");
    if (cancel) {
      order.forEach((r) => body.appendChild(r));
      return;
    }
    refocus = row.dataset.key;
    changed(body, before);
  }

  document.addEventListener("pointerup", () => finish(false));
  document.addEventListener("pointercancel", () => finish(true));

  document.addEventListener("keydown", (event) => {
    if (drag && event.key === "Escape") return finish(true);
    const grip = event.target.closest("[data-grip]");
    if (!grip || (event.key !== "ArrowUp" && event.key !== "ArrowDown")) return;
    event.preventDefault();
    const row = grip.closest("tr");
    const body = row.parentElement;
    const before = keys(body);
    if (event.key === "ArrowUp" && row.previousElementSibling) body.insertBefore(row, row.previousElementSibling);
    if (event.key === "ArrowDown" && row.nextElementSibling) body.insertBefore(row.nextElementSibling, row);
    grip.focus();
    refocus = row.dataset.key;
    changed(body, before);
  });

  document.addEventListener("htmx:afterSettle", () => {
    if (!refocus) return;
    const grip = document.querySelector(`#ranking-editor tr[data-key="${refocus}"] [data-grip]`);
    refocus = null;
    if (grip) grip.focus({ preventScroll: true });
  });
})();
