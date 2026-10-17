(function () {
  var root = document.documentElement;
  var reduceMotion = window.matchMedia("(prefers-reduced-motion: reduce)");

  function currentTheme() {
    var set = root.getAttribute("data-theme");
    if (set) return set;
    return window.matchMedia("(prefers-color-scheme: dark)").matches ? "dark" : "light";
  }

  // The browser bar takes the page's paper colour, including a theme picked with the toggle.
  function syncThemeColor() {
    if (!root.getAttribute("data-theme")) return;
    var paper = getComputedStyle(root).getPropertyValue("--bg").trim();
    document.querySelectorAll('meta[name="theme-color"]').forEach(function (meta) {
      meta.setAttribute("content", paper);
    });
  }

  syncThemeColor();

  document.querySelectorAll("[data-theme-toggle]").forEach(function (button) {
    button.addEventListener("click", function () {
      // Switching theme stays on this page: use the plain crossfade, not the page arrival.
      root.removeAttribute("data-nav");
      var next = currentTheme() === "dark" ? "light" : "dark";
      function apply() {
        root.setAttribute("data-theme", next);
        syncThemeColor();
      }
      if (document.startViewTransition && !reduceMotion.matches) {
        document.startViewTransition(apply);
      } else {
        apply();
      }
      try {
        localStorage.setItem("theme", next);
      } catch (e) {}
    });
  });

  // The server's clock may be in another time zone, so greet by the viewer's clock.
  var greeting = document.querySelector("[data-greeting]");
  if (greeting) {
    var hour = new Date().getHours();
    greeting.textContent = hour < 12 ? "Good morning" : hour < 17 ? "Good afternoon" : "Good evening";
  }

  // Show/Hide buttons on password fields (hidden until this script runs).
  document.querySelectorAll("[data-password-toggle]").forEach(function (button) {
    var input = document.getElementById(button.getAttribute("aria-controls"));
    if (!input) return;
    button.hidden = false;
    button.addEventListener("click", function () {
      var show = input.type === "password";
      input.type = show ? "text" : "password";
      // A toggle button keeps one label; aria-pressed says whether it is on.
      button.setAttribute("aria-pressed", show ? "true" : "false");
    });
  });

  document.querySelectorAll("[data-print]").forEach(function (button) {
    button.hidden = false;
    button.addEventListener("click", function () {
      window.print();
    });
  });

  // After tapping an answer, show which one was picked while the page reloads.
  document.addEventListener("submit", function (event) {
    var form = event.target;
    if (!form.querySelector(".mark-buttons")) return;
    form.setAttribute("aria-busy", "true");
    if (event.submitter) event.submitter.setAttribute("data-pressed", "");
  });

  // Coming back with the Back button restores the page as it was left; clear the busy state.
  window.addEventListener("pageshow", function (event) {
    if (!event.persisted) return;
    document.querySelectorAll('form[aria-busy="true"]').forEach(function (form) {
      form.removeAttribute("aria-busy");
      form.querySelectorAll("[data-pressed]").forEach(function (button) {
        button.removeAttribute("data-pressed");
      });
    });
  });

  var search = document.querySelector("[data-topic-search]");
  if (search) {
    search.addEventListener("input", function () {
      var query = search.value.trim().toLowerCase();
      var rows = document.querySelectorAll("[data-topic]");
      var shown = 0;
      rows.forEach(function (row) {
        row.hidden = query !== "" && row.getAttribute("data-topic").indexOf(query) === -1;
        if (!row.hidden) shown += 1;
      });
      var empty = document.querySelector("[data-search-empty]");
      if (empty) empty.hidden = shown > 0;
    });
  }
})();
