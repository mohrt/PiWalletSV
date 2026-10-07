"""Keep PiWallet Pay out of the site nav until it launches.

publish.sh sets PIWALLETSV_SHOW_PAY=1 for the dev mirror only, which fills
``extra.show_piwallet_pay``. Markdown pages gate their own mentions with
``{% if show_piwallet_pay %}``.
"""


def on_nav(nav, config, files):
    if not config["extra"].get("show_piwallet_pay"):
        nav.items = [item for item in nav.items if item.title != "PiWallet Pay"]
    return nav
