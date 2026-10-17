(function () {
  var root = document.documentElement;

  function currentTheme() {
    var set = root.getAttribute("data-theme");
    if (set) return set;
    return window.matchMedia("(prefers-color-scheme: dark)").matches ? "dark" : "light";
  }

  document.querySelectorAll("[data-theme-toggle]").forEach(function (button) {
    button.addEventListener("click", function () {
      var next = currentTheme() === "dark" ? "light" : "dark";
      root.setAttribute("data-theme", next);
      try {
        localStorage.setItem("theme", next);
      } catch (e) {}
    });
  });

  // The server's clock may be in another time zone, so greet by the viewer's clock.
  var greeting = document.querySelector("[data-greeting]");
  if (greeting) {
    var hour = new Date().getHours();
    var word = hour < 12 ? "Good morning" : hour < 17 ? "Good afternoon" : "Good evening";
    greeting.textContent = word + ",";
  }

  // Show/Hide buttons on password fields (hidden until this script runs).
  document.querySelectorAll("[data-password-toggle]").forEach(function (button) {
    var input = document.getElementById(button.getAttribute("aria-controls"));
    if (!input) return;
    button.hidden = false;
    button.addEventListener("click", function () {
      var show = input.type === "password";
      input.type = show ? "text" : "password";
      button.setAttribute("aria-pressed", show ? "true" : "false");
      button.setAttribute("aria-label", show ? "Hide password" : "Show password");
    });
  });

  document.querySelectorAll("[data-print]").forEach(function (button) {
    button.hidden = false;
    button.addEventListener("click", function () {
      window.print();
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
