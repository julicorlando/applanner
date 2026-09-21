<?php
declare(strict_types=1);
if(PHP_SAPI!=='cli'){http_response_code(404);exit;}
fwrite(STDERR,"A criação automática de empresa-demo foi desativada durante a homologação comercial.\n");
fwrite(STDERR,"Nenhum tenant foi criado ou alterado.\n");
exit(2);
