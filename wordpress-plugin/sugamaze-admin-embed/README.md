# Sugamaze WhatsApp Bot Admin (WordPress embed)

Serves the bot's admin panel at `sugamaze.ca/whatsapp/admin` by embedding the
existing FastAPI admin page (already deployed on Render) in an iframe.

Login is still handled entirely by the backend (HTTP Basic Auth) — this
plugin does not add its own authentication. Anyone visiting the URL sees the
backend's own login prompt inside the iframe.

## Install

1. Zip this folder (`sugamaze-admin-embed`) or upload it as-is via FTP/SFTP
   to `wp-content/plugins/sugamaze-admin-embed/`.
2. In `wp-admin` → **Plugins**, find "Sugamaze WhatsApp Bot Admin" and
   **Activate** it.
3. Make sure **Settings → Permalinks** is set to anything other than
   "Plain" (e.g. "Post name") — the `/whatsapp/admin` URL depends on
   WordPress's rewrite rules, which plain permalinks don't support. If
   you're not sure, open Settings → Permalinks and just click **Save
   Changes** once (this also flushes the rewrite cache).
4. Visit `https://sugamaze.ca/whatsapp/admin` — you should see the admin
   panel's login prompt.

## If the backend URL ever changes

Edit the `SUGAMAZE_ADMIN_EMBED_URL` constant near the top of
`sugamaze-admin-embed.php` and update it to the new backend `/admin` URL,
then re-save/re-activate the plugin (or just re-upload the file — no
reactivation needed for this specific change).

## Uninstalling

Deactivating the plugin immediately removes the `/whatsapp/admin` route.
