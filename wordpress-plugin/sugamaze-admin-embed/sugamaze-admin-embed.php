<?php
/**
 * Plugin Name: Sugamaze WhatsApp Bot Admin
 * Description: Serves the WhatsApp bot's admin panel at sugamaze.ca/whatsapp/admin (embedded via iframe). Login is handled by the bot's own backend — this plugin only provides the URL.
 * Version: 1.0.0
 * Author: Sugamaze
 */

if (!defined('ABSPATH')) {
    exit; // No direct access.
}

// Change this if the bot's backend ever moves to a different host.
define('SUGAMAZE_ADMIN_EMBED_URL', 'https://sugamaze-whatsapp-bot.onrender.com/admin');

/**
 * Register the /whatsapp/admin/ URL as a WordPress rewrite rule.
 * Requires "Pretty" permalinks to be enabled (Settings > Permalinks in
 * wp-admin) — plain "?p=123" permalinks won't route this correctly.
 */
function sugamaze_admin_embed_rewrite_rule() {
    add_rewrite_rule('^whatsapp/admin/?$', 'index.php?sugamaze_admin_embed=1', 'top');
}
add_action('init', 'sugamaze_admin_embed_rewrite_rule');

function sugamaze_admin_embed_query_vars($vars) {
    $vars[] = 'sugamaze_admin_embed';
    return $vars;
}
add_filter('query_vars', 'sugamaze_admin_embed_query_vars');

/**
 * When the request matches our rewrite rule, bypass the theme entirely and
 * output a full-page iframe pointing at the bot's own admin panel. The
 * iframe will show the backend's own login prompt (HTTP Basic Auth) —
 * WordPress itself does not gate access to this page, since the backend
 * already protects it.
 */
function sugamaze_admin_embed_render() {
    if (!get_query_var('sugamaze_admin_embed')) {
        return;
    }

    $target_url = esc_url(SUGAMAZE_ADMIN_EMBED_URL);
    ?>
<!DOCTYPE html>
<html lang="en">
<head>
<meta charset="UTF-8">
<title>Sugamaze Bot Admin</title>
<meta name="viewport" content="width=device-width, initial-scale=1">
<style>
    html, body { margin: 0; padding: 0; height: 100%; background: #fdf5f8; }
    iframe { display: block; width: 100%; height: 100vh; border: none; }
</style>
</head>
<body>
<iframe src="<?php echo $target_url; ?>" title="Sugamaze Bot Admin" allow="clipboard-write"></iframe>
</body>
</html>
    <?php
    exit;
}
add_action('template_redirect', 'sugamaze_admin_embed_render');

/**
 * Flush rewrite rules on activation/deactivation so the /whatsapp/admin/
 * URL starts (and stops) working immediately, without needing a manual
 * visit to Settings > Permalinks.
 */
function sugamaze_admin_embed_activate() {
    sugamaze_admin_embed_rewrite_rule();
    flush_rewrite_rules();
}
register_activation_hook(__FILE__, 'sugamaze_admin_embed_activate');

function sugamaze_admin_embed_deactivate() {
    flush_rewrite_rules();
}
register_deactivation_hook(__FILE__, 'sugamaze_admin_embed_deactivate');
