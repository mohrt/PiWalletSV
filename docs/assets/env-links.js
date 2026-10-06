/**
 * Rewrite prod links when the docs site is served from the dev mirror.
 * Build-time PIWALLETSV_COMPANION_URL is the primary fix for the companion;
 * this catches dev deploys that forgot to set it, and points PiWallet Pay
 * links at its dev site.
 */
(function () {
  if (location.hostname !== "dev.piwalletsv.com") {
    return;
  }
  const rewrites = [
    ["https://app.piwalletsv.com", "https://app.dev.piwalletsv.com"],
    ["https://piwalletpay.com", "https://dev.piwalletpay.com"],
  ];
  rewrites.forEach(function (pair) {
    const from = pair[0];
    const to = pair[1];
    document.querySelectorAll('a[href^="' + from + '"]').forEach(function (a) {
      a.href = a.href.replace(from, to);
    });
  });
})();
