<?php
return [
    'name' => 'ApPlanner',
    'version' => '4.3.0',
    'url' => getenv('PUBLIC_BASE_URL') ?: 'https://example.com',
    'env' => 'production',
    'debug' => false,
    'timezone' => 'America/Recife',
    'session_name' => 'agenda_saas_session',
    'app_key' => getenv('LEGACY_APP_KEY') ?: '',
    'system_email' => '',
];
