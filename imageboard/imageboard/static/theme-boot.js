(function () {
  var allowed = ["rorisu", "macos", "win98", "classic"];
  var stored = null;
  try {
    stored = window.localStorage.getItem("paradise.theme");
  } catch (error) {
    stored = null;
  }
  var theme = allowed.indexOf(stored) === -1 ? "rorisu" : stored;
  document.documentElement.setAttribute("data-theme", theme);
})();
