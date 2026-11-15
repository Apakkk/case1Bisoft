// City suggestions for inputs marked data-city-suggest (see views/templates/_city_input.html).
// Fetches a server-rendered <li> list after a short pause in typing, then handles the keyboard
// (Up/Down move, Enter picks, Escape closes) and the ARIA combobox state. Listeners sit on the
// document, so inputs inside forms that HTMX swaps in later work without re-binding.
// Picking from the list is optional: whatever is typed is still submitted as before.
(() => {
  "use strict";

  const DELAY_MS = 250;
  const INPUT = "input[data-city-suggest]";
  const state = new WeakMap(); // input -> { timer, controller }

  const cityInput = (target) => (target instanceof HTMLInputElement && target.matches(INPUT) ? target : null);
  const listOf = (input) => document.getElementById(input.getAttribute("aria-controls"));
  const optionsOf = (input) => Array.from(listOf(input)?.querySelectorAll('[role="option"]') ?? []);
  const isOpen = (input) => input.getAttribute("aria-expanded") === "true";

  function slot(input) {
    if (!state.has(input)) state.set(input, { timer: 0, controller: null });
    return state.get(input);
  }

  // Stop a scheduled or running request for this input.
  function cancel(input) {
    const s = slot(input);
    clearTimeout(s.timer);
    s.controller?.abort();
    s.controller = null;
    input.closest(".city-box")?.removeAttribute("data-loading");
  }

  function close(input) {
    const list = listOf(input);
    if (list) {
      list.hidden = true;
      list.replaceChildren();
    }
    input.setAttribute("aria-expanded", "false");
    input.removeAttribute("aria-activedescendant");
  }

  function activeIndex(input) {
    return optionsOf(input).findIndex((option) => option.getAttribute("aria-selected") === "true");
  }

  function activate(input, index) {
    const options = optionsOf(input);
    options.forEach((option, i) => option.setAttribute("aria-selected", String(i === index)));
    const active = options[index];
    if (!active) return input.removeAttribute("aria-activedescendant");
    input.setAttribute("aria-activedescendant", active.id);
    active.scrollIntoView({ block: "nearest" });
  }

  function choose(input, option) {
    input.value = option.dataset.value;
    cancel(input);
    close(input);
    input.dispatchEvent(new Event("change", { bubbles: true }));
  }

  async function load(input) {
    cancel(input);
    const query = input.value.trim();
    if (!query) return close(input);

    const s = slot(input);
    const controller = new AbortController();
    const box = input.closest(".city-box");
    s.controller = controller;
    box?.setAttribute("data-loading", "");
    try {
      const url = `${input.dataset.citySuggest}?q=${encodeURIComponent(query)}`;
      const response = await fetch(url, { signal: controller.signal, headers: { Accept: "text/html" } });
      if (!response.ok) throw new Error(`HTTP ${response.status}`);
      const html = await response.text();
      if (document.activeElement !== input) return; // the user already moved on
      const list = listOf(input);
      list.innerHTML = html;
      optionsOf(input).forEach((option, i) => (option.id = `${list.id}-${i}`));
      list.hidden = false;
      input.setAttribute("aria-expanded", "true");
      input.removeAttribute("aria-activedescendant");
    } catch (error) {
      if (error.name !== "AbortError") close(input); // suggestions are a help, never a blocker
    } finally {
      if (s.controller === controller) {
        s.controller = null;
        box?.removeAttribute("data-loading");
      }
    }
  }

  document.addEventListener("input", (event) => {
    const input = cityInput(event.target);
    if (!input) return;
    cancel(input); // an answer for older letters must not show up late
    slot(input).timer = setTimeout(() => load(input), DELAY_MS);
  });

  document.addEventListener("keydown", (event) => {
    const input = cityInput(event.target);
    if (!input) return;
    const options = optionsOf(input);
    switch (event.key) {
      case "ArrowDown":
      case "ArrowUp": {
        event.preventDefault();
        if (!isOpen(input)) return void load(input);
        if (!options.length) return;
        const step = event.key === "ArrowDown" ? 1 : -1;
        const current = activeIndex(input);
        const next = current < 0 ? (step > 0 ? 0 : options.length - 1) : (current + step + options.length) % options.length;
        return activate(input, next);
      }
      case "Enter": {
        if (!isOpen(input)) return; // closed list: Enter submits the form as usual
        event.preventDefault(); // open list: never submit by accident
        const current = activeIndex(input);
        if (current >= 0) return choose(input, options[current]);
        cancel(input);
        return close(input);
      }
      case "Escape":
        if (!isOpen(input)) return;
        event.preventDefault();
        cancel(input);
        return close(input);
      case "Tab":
        cancel(input);
        return close(input);
    }
  });

  // mousedown (not click) so the input keeps focus and does not close the list first.
  document.addEventListener("mousedown", (event) => {
    const list = event.target instanceof Element ? event.target.closest(".city-list") : null;
    if (!list) return;
    event.preventDefault();
    const option = event.target.closest('[role="option"]');
    const input = document.querySelector(`[aria-controls="${list.id}"]`);
    if (option && input) choose(input, option);
  });

  document.addEventListener("focusout", (event) => {
    const input = cityInput(event.target);
    if (!input) return;
    cancel(input);
    close(input);
  });

  // A list that opens after the form was sent would only get in the way.
  document.addEventListener("submit", (event) => {
    event.target.querySelectorAll?.(INPUT).forEach((input) => {
      cancel(input);
      close(input);
    });
  });
})();
