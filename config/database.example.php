<?php
return [
    'host' => getenv('LEGACY_MYSQL_HOST') ?: 'localhost',
    'port' => (int) (getenv('LEGACY_MYSQL_PORT') ?: 3306),
    'database' => getenv('LEGACY_MYSQL_DATABASE') ?: 'agenda_saas',
    'username' => getenv('LEGACY_MYSQL_USER') ?: '',
    'password' => getenv('LEGACY_MYSQL_PASSWORD') ?: '',
    'charset' => 'utf8mb4',
];
