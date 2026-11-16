// Distance boxes on the carrier form (data-nonnegative, type="number" min="0"): only digits and one decimal point
// get in. The browser already refuses letters in a number box but still lets "-", "+" and "e" through; those keys
// are blocked here, and a pasted value is kept only if it is a plain non-negative number. The server checks again.
(() => {
  "use strict";

  const BLOCKED = new Set(["-", "+", "e", "E"]);
  const PLAIN = /^\d+([.,]\d+)?$/;

  document.addEventListener("keydown", (event) => {
    if (event.target.matches?.("[data-nonnegative]") && BLOCKED.has(event.key)) event.preventDefault();
  });

  document.addEventListener("paste", (event) => {
    if (!event.target.matches?.("[data-nonnegative]")) return;
    const text = (event.clipboardData?.getData("text") || "").trim();
    if (!PLAIN.test(text)) event.preventDefault();
  });
})();
