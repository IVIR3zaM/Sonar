// A home-screen app has its own cookie jar, so Google sign-in there would end in a
// session Safari never sees. In standalone display the Google button asks for a
// one-time code page instead; in a normal browser it is left alone.
(function () {
  var link = document.getElementById("google-sign-in");
  if (!link) return;

  var standalone =
    navigator.standalone === true ||
    window.matchMedia("(display-mode: standalone)").matches;
  if (standalone) link.setAttribute("href", "/auth/google?mode=code");
})();
