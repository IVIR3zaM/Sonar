// The payoff ticks sit on a log scale, so the slider must snap to them; a native
// step range cannot do that. Without this script every step card stays visible.
(function () {
  var slider = document.getElementById("payoff-slider");
  var cards = Array.prototype.slice.call(document.querySelectorAll("[data-step]"));
  if (!slider || !cards.length) return;

  var ticks = Array.prototype.slice.call(document.querySelectorAll("[data-tick]"));
  var positions = cards.map(function (card) { return Number(card.getAttribute("data-position")); });
  var current = 0;

  function select(index) {
    current = Math.max(0, Math.min(cards.length - 1, index));
    cards.forEach(function (card, i) { card.hidden = i !== current; });
    ticks.forEach(function (tick, i) {
      if (i === current) tick.setAttribute("data-selected", "");
      else tick.removeAttribute("data-selected");
    });
    slider.value = positions[current];
    var payNow = cards[current].querySelector("[data-part=pay-now]");
    slider.setAttribute("aria-valuetext", payNow.textContent.trim());
  }

  function nearest(value) {
    var best = 0;
    positions.forEach(function (position, i) {
      if (Math.abs(position - value) < Math.abs(positions[best] - value)) best = i;
    });
    return best;
  }

  var moves = { ArrowLeft: -1, ArrowDown: -1, PageDown: -1, ArrowRight: 1, ArrowUp: 1, PageUp: 1 };

  slider.addEventListener("input", function () { select(nearest(Number(slider.value))); });
  slider.addEventListener("keydown", function (event) {
    var target;
    if (event.key in moves) target = current + moves[event.key];
    else if (event.key === "Home") target = 0;
    else if (event.key === "End") target = cards.length - 1;
    else return;
    event.preventDefault();
    select(target);
  });

  document.getElementById("payoff-slider-block").hidden = false;
  select(0);
})();
