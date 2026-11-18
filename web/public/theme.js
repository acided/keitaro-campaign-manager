// Set the theme before the first paint: saved choice, else the system preference.
(function () {
  let theme = null;
  try {
    theme = localStorage.getItem("theme");
  } catch {}
  if (theme !== "light" && theme !== "dark") {
    theme = matchMedia("(prefers-color-scheme: dark)").matches ? "dark" : "light";
  }
  document.documentElement.dataset.theme = theme;
})();
