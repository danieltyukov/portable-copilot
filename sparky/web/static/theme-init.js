/* Applies the theme picked with the header button before the page paints,
   so it never flashes the other theme. Loaded in the head without defer;
   app.js does everything else. */
try {
  var saved = localStorage.getItem("sparky-theme");
  if (saved === "light" || saved === "dark") document.documentElement.setAttribute("data-theme", saved);
} catch (e) { /* storage blocked: follow the system setting */ }
