// Carrier form: "+" (or Enter in the box) adds each typed container size as a ticked checkbox, so several sizes can
// be added one after another. A size already listed is ticked, never duplicated. Listeners sit on document because
// the form arrives by HTMX. Without this script a typed size is still saved: the server reads the box.
(() => {
  "use strict";

  const MAX_FT = 99;

  function add(picker) {
    const input = picker.querySelector("[data-size-input]");
    const error = picker.querySelector("[data-size-error]");
    const tokens = input.value.replace(/\s*(feet|ft|')/gi, "").split(/[,;\s]+/).filter(Boolean);
    if (!tokens.length) {
      input.focus();
      return;
    }
    const bad = tokens.filter((t) => !/^\d{1,2}$/.test(t) || Number(t) < 1 || Number(t) > MAX_FT);
    if (bad.length) {
      error.textContent = `1 ile ${MAX_FT} arasında tam sayı girin (${bad.join(", ")}).`;
      error.hidden = false;
      input.setAttribute("aria-invalid", "true");
      input.focus();
      return;
    }
    for (const size of new Set(tokens.map(Number))) tick(picker, size);
    input.value = "";
    error.hidden = true;
    input.removeAttribute("aria-invalid");
    input.focus();
  }

  function tick(picker, size) {
    const boxes = [...picker.querySelectorAll('input[name="container_sizes"]')];
    const existing = boxes.find((box) => Number(box.value) === size);
    if (existing) {
      existing.checked = true;
      return;
    }
    const label = document.createElement("label");
    const box = Object.assign(document.createElement("input"), { type: "checkbox", name: "container_sizes", value: String(size), checked: true });
    label.append(box, ` ${size}`);
    // Keep the boxes in size order; a larger size goes before the "+" box.
    const next = boxes.find((b) => Number(b.value) > size);
    const anchor = next ? next.closest("label") : picker.querySelector(".size-add");
    anchor.before(label);
  }

  document.addEventListener("click", (event) => {
    const button = event.target.closest("[data-size-add]");
    if (button) add(button.closest("[data-size-picker]"));
  });

  document.addEventListener("keydown", (event) => {
    if (event.key !== "Enter" || !event.target.matches("[data-size-input]")) return;
    event.preventDefault(); // Enter adds the size instead of submitting the form
    add(event.target.closest("[data-size-picker]"));
  });
})();
