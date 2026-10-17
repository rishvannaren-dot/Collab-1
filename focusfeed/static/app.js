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

  var search = document.querySelector("[data-topic-search]");
  if (search) {
    search.addEventListener("input", function () {
      var query = search.value.trim().toLowerCase();
      document.querySelectorAll("[data-topic]").forEach(function (row) {
        row.hidden = query !== "" && row.getAttribute("data-topic").indexOf(query) === -1;
      });
    });
  }
})();
