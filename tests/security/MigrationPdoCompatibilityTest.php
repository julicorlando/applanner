<?php
$sql=file_get_contents(dirname(__DIR__,2).'/database/migrations/010_corrective_commercial_architecture.sql');$ok=!preg_match('/\bDELIMITER\b/i',$sql)&&str_contains($sql,'CREATE TRIGGER tenants_public_identity_before_insert');echo ($ok?'PASS':'FAIL')." PDO-compatible migration\n";exit($ok?0:1);
