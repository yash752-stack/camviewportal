/* The gate's interaction.

   Pick a product from the ring and the band slides in carrying that product's
   identity and the sign-in. Products not yet on this interface still open the
   band — they say so plainly and disable the button, rather than being
   unclickable for no visible reason.

   Progressive: with JS off the ring is still readable and the form is still in
   the DOM, so the page degrades to a plain sign-in rather than a dead end. */
(function () {
  var stage = document.getElementById("stage");
  var band  = document.getElementById("band");
  if (!stage || !band) return;

  var hubKick = document.getElementById("hubKick");
  var hubName = document.getElementById("hubName");
  var hubIcon = document.getElementById("hubIcon");
  var bDisc   = document.getElementById("bDisc");
  var bName   = document.getElementById("bName");
  var bTag    = document.getElementById("bTag");
  var bSoon   = document.getElementById("bSoon");
  var bProd   = document.getElementById("bProduct");
  var form    = document.getElementById("bForm");
  var submit  = form ? form.querySelector(".gbtn") : null;
  var ring    = document.getElementById("ring");
  var nodes   = Array.prototype.slice.call(document.querySelectorAll(".node"));

  var hubDefault = { kick: hubKick.textContent, name: hubName.textContent };

  function preview(node) {
    hubIcon.innerHTML = node.querySelector(".disc").innerHTML;
    hubIcon.classList.add("show");
    hubName.textContent = node.dataset.name;
    hubKick.textContent = node.dataset.live === "1" ? "Ready" : "Not on this interface yet";
  }

  function restore() {
    if (stage.classList.contains("picked")) return;
    hubIcon.classList.remove("show");
    hubIcon.innerHTML = "";
    hubName.textContent = hubDefault.name;
    hubKick.textContent = hubDefault.kick;
  }

  function open(node) {
    nodes.forEach(function (n) { n.classList.toggle("on", n === node); });
    if (ring) ring.classList.add("chosen");
    var live = node.dataset.live === "1";

    bDisc.innerHTML = node.querySelector(".disc").innerHTML;
    bDisc.style.background = getComputedStyle(node).getPropertyValue("--tint");
    bName.textContent = node.dataset.name;
    bTag.textContent  = node.dataset.tag;
    bProd.value = node.dataset.slug;

    bSoon.hidden = live;
    if (submit) {
      submit.disabled = !live;
      submit.firstChild.nodeValue = live ? "Sign in " : "Unavailable ";
    }
    form.querySelectorAll("input[name=username],input[name=password]")
        .forEach(function (i) { i.disabled = !live; });

    preview(node);
    stage.classList.add("picked");
    band.setAttribute("aria-hidden", "false");
    if (live) {
      var first = form.querySelector("input[name=username]");
      if (first) setTimeout(function () { first.focus(); }, 340);
    }
  }

  function close() {
    stage.classList.remove("picked");
    band.setAttribute("aria-hidden", "true");
    nodes.forEach(function (n) { n.classList.remove("on"); });
    if (ring) ring.classList.remove("chosen");
    restore();
  }

  nodes.forEach(function (node) {
    node.addEventListener("click", function () { open(node); });
    node.addEventListener("mouseenter", function () { preview(node); });
    node.addEventListener("mouseleave", restore);
    node.addEventListener("focus", function () { preview(node); });
    node.addEventListener("blur", restore);
  });

  var back = document.getElementById("bback");
  if (back) back.addEventListener("click", close);
  document.addEventListener("keydown", function (e) {
    if (e.key === "Escape" && stage.classList.contains("picked")) close();
  });

  /* A failed sign-in re-renders with .picked already set, so reopen the band on
     whichever product was being signed into. */
  if (stage.classList.contains("picked")) {
    var want = bProd.value;
    var match = nodes.filter(function (n) { return n.dataset.slug === want; })[0] || nodes[1];
    if (match) open(match);
  }
})();
