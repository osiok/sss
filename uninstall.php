<?php
declare(strict_types=1);
if ( ! defined( 'WP_UNINSTALL_PLUGIN' ) ) { exit; }

$allow_delete = (bool) get_option( 'zsg_auth_delete_on_uninstall', false );
if ( ! $allow_delete ) { return; }

global $wpdb;
$prefix = $wpdb->prefix . 'zsg_auth_';
foreach ( [ 'otp','limits','sessions','devices','passkeys','logs','challenges' ] as $t ) {
    $wpdb->query( "DROP TABLE IF EXISTS {$prefix}{$t}" ); // phpcs:ignore
}
$options = $wpdb->get_col( "SELECT option_name FROM {$wpdb->options} WHERE option_name LIKE 'zsg\\_auth\\_%'" );
foreach ( $options as $opt ) { delete_option( $opt ); }
