/* Theme toggle — dark (default) <-> light (cream + blue).
   Applied ASAP so there's no flash, then a floating button is added. */
(function () {
  var KEY = "camview-theme";
  // apply saved choice immediately (before the button exists) to avoid a flash
  try {
    if (localStorage.getItem(KEY) === "light") {
      document.documentElement.classList.add("light");
    }
  } catch (e) {}

  function iconSun() {
    return '<svg class="i-sun" viewBox="0 0 24 24"><circle cx="12" cy="12" r="4"/>' +
      '<path d="M12 2v2M12 20v2M4.9 4.9l1.4 1.4M17.7 17.7l1.4 1.4M2 12h2M20 12h2M4.9 19.1l1.4-1.4M17.7 6.3l1.4-1.4"/></svg>';
  }
  function iconMoon() {
    return '<svg class="i-moon" viewBox="0 0 24 24"><path d="M21 12.8A9 9 0 1 1 11.2 3a7 7 0 0 0 9.8 9.8z"/></svg>';
  }

  function build() {
    if (document.querySelector(".themetoggle")) return;
    var btn = document.createElement("button");
    btn.className = "themetoggle";
    btn.type = "button";
    btn.title = "Switch light / dark theme";
    btn.setAttribute("aria-label", "Switch light or dark theme");
    btn.innerHTML = iconSun() + iconMoon();
    btn.addEventListener("click", function () {
      var isLight = document.documentElement.classList.toggle("light");
      try { localStorage.setItem(KEY, isLight ? "light" : "dark"); } catch (e) {}
    });
    document.body.appendChild(btn);
  }

  if (document.readyState === "loading") {
    document.addEventListener("DOMContentLoaded", build);
  } else {
    build();
  }
})();
