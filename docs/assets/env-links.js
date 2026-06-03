/**
 * Rewrite prod companion links when the docs site is served from the dev
 * mirror. Build-time PIWALLETSV_COMPANION_URL is the primary fix; this
 * catches dev deploys that forgot to set it.
 */
(function () {
  if (location.hostname !== "dev.piwalletsv.com") {
    return;
  }
  const from = "https://app.piwalletsv.com";
  const to = "https://app.dev.piwalletsv.com";
  document.querySelectorAll('a[href^="' + from + '"]').forEach(function (a) {
    a.href = a.href.replace(from, to);
  });
})();
