<?php
/**
 * Plugin Name:       ZSG Auth
 * Plugin URI:        https://zeroshopgem.ir
 * Description:       سیستم احراز هویت اختصاصی Zero Shop Gem — ورود/ثبت‌نام با موبایل و OTP.
 * Version:           0.1.0-alpha
 * Requires at least: 6.7
 * Requires PHP:      8.1
 * Author:            Zero Shop Gem
 * Text Domain:       zsg-auth
 * License:           GPL-2.0-or-later
 *
 * @package ZSG\Auth
 */
declare(strict_types=1);

if ( ! defined( 'ABSPATH' ) ) { exit; }

define( 'ZSG_AUTH_VERSION',        '0.1.0-alpha' );
define( 'ZSG_AUTH_SCHEMA_VERSION', '1' );
define( 'ZSG_AUTH_FILE',           __FILE__ );
define( 'ZSG_AUTH_PATH',           plugin_dir_path( __FILE__ ) );
define( 'ZSG_AUTH_URL',            plugin_dir_url( __FILE__ ) );
define( 'ZSG_AUTH_BASENAME',       plugin_basename( __FILE__ ) );

require_once ZSG_AUTH_PATH . 'src/Core/Autoloader.php';
\ZSG\Auth\Core\Autoloader::register();

register_activation_hook( __FILE__, [ '\ZSG\Auth\Core\Activator', 'activate' ] );
register_deactivation_hook( __FILE__, [ '\ZSG\Auth\Core\Deactivator', 'deactivate' ] );

add_action( 'plugins_loaded', static function (): void {
    \ZSG\Auth\Core\Plugin::instance()->boot();
}, 5 );
