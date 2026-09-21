<?php
declare(strict_types=1);
if (PHP_SAPI !== 'cli') { http_response_code(404); exit; }

$root = dirname(__DIR__);
$payload = $root . '/patches/applanner-arena-v2/payload';
$errors=[]; $warnings=[]; $oks=[];
$ok = static function(string $m) use (&$oks): void { $oks[]=$m; echo "[OK] {$m}\n"; };
$warn = static function(string $m) use (&$warnings): void { $warnings[]=$m; echo "[AVISO] {$m}\n"; };
$err = static function(string $m) use (&$errors): void { $errors[]=$m; echo "[ERRO] {$m}\n"; };

if (version_compare(PHP_VERSION,'8.1.0','<')) $err('PHP 8.1+ é obrigatório. Atual: '.PHP_VERSION); else $ok('PHP '.PHP_VERSION);
if (!is_file($root.'/storage/installed.lock')) $err('storage/installed.lock não encontrado; diretório não parece ser a instalação ativa.'); else $ok('Instalação ativa reconhecida');
if (!is_file($root.'/database/migrations/035_sports_courts_module.sql')) $err('Migration 035 de Quadras/Esportes não encontrada.'); else $ok('Migration 035 encontrada');
if (!is_dir($payload)) $err('Payload Arena V2 não encontrado.');

$files=[];
if (is_dir($payload)) {
  $it=new RecursiveIteratorIterator(new RecursiveDirectoryIterator($payload,FilesystemIterator::SKIP_DOTS));
  foreach($it as $f){ if(!$f->isFile())continue; $rel=str_replace('\\','/',substr($f->getPathname(),strlen($payload)+1)); $files[$rel]=$f->getPathname(); }
  ksort($files);
  if(count($files)<45) $err('Payload incompleto: apenas '.count($files).' arquivos.'); else $ok('Payload íntegro: '.count($files).' arquivos');
}

foreach(['database/migrations/037_applanner_arena_v1.sql','database/migrations/038_applanner_arena_v2_complete.sql'] as $rel){
  $f=$payload.'/'.$rel;
  if(!is_file($f)){ $err("Migration ausente: {$rel}"); continue; }
  $sql=(string)file_get_contents($f);
  if(preg_match('/\\b(DROP\\s+(DATABASE|TABLE)|TRUNCATE\\s+TABLE)\\b/i',$sql)) $err("Migration destrutiva detectada: {$rel}"); else $ok("Migration não destrutiva: {$rel}");
}

// Detecta nomes de FK duplicados entre as migrations finais do patch.
$constraints=[];
foreach(['037_applanner_arena_v1.sql','038_applanner_arena_v2_complete.sql'] as $name){
  $sql=(string)@file_get_contents($payload.'/database/migrations/'.$name);
  if(preg_match_all('/\\bCONSTRAINT\\s+([A-Za-z0-9_]+)/i',$sql,$m)){
    foreach($m[1] as $c){ $k=strtolower($c); $constraints[$k][]=$name; }
  }
}
foreach($constraints as $name=>$where){ if(count($where)>1) $err('Nome de foreign key repetido no patch: '.$name.' em '.implode(', ',$where)); }
if(!$errors) $ok('Nomes de foreign keys do patch sem colisão interna');

// Lint integral do payload antes de qualquer alteração.
foreach($files as $rel=>$src){
  if(!str_ends_with(strtolower($rel),'.php')) continue;
  $out=[];$code=0; exec(escapeshellarg(PHP_BINARY).' -l '.escapeshellarg($src).' 2>&1',$out,$code);
  if($code!==0){ $err('PHP inválido em '.$rel.': '.implode(' ',$out)); break; }
}
if(!$errors) $ok('Lint PHP do payload aprovado');

// Verificações funcionais estáticas mais importantes.
$index=(string)@file_get_contents($payload.'/index.php');
foreach([
  '/arena/reserva/{token}/card-payment',
  '/sports/commands/open',
  '/sports/classes/{id}/attendance',
  '/sports/tournaments/{id}/matches/{match}/score'
] as $route){ if(!str_contains($index,$route)) $err('Rota obrigatória ausente: '.$route); }
if(!$errors) $ok('Rotas críticas Arena V2 presentes');

$public=(string)@file_get_contents($payload.'/app/Views/public/sports.php');
if(stripos($public,'professional_id')!==false || stripos($public,'Escolha um profissional')!==false) $err('Fluxo público da Arena ainda contém conceito de profissional.'); else $ok('Fluxo público Arena sem profissional');

$settings=(string)@file_get_contents($payload.'/app/Views/arena/settings.php');
if(!str_contains($settings,'dynamic_pricing_enabled') || !str_contains($settings,'Preço dinâmico')) $err('Configuração de preço dinâmico ausente.'); else $ok('Preço dinâmico configurável/opt-in presente');

$cardJs=$payload.'/public/assets/js/arena-card-payment.js';
if(!is_file($cardJs)) $err('Componente de cartão Mercado Pago ausente.'); else $ok('Componente de cartão tokenizado presente');

// Checagem somente-leitura no banco: versão, migrations e colisões reais de FK.
if (getenv('APPLANNER_PREFLIGHT_SKIP_DB') === '1') {
  $warn('Checagem de banco ignorada por APPLANNER_PREFLIGHT_SKIP_DB=1 (somente para validação offline do pacote).');
} else try {
  spl_autoload_register(static function(string $class) use ($root): void {
    $prefix='App\\'; if(!str_starts_with($class,$prefix)) return;
    $file=$root.'/app/'.str_replace('\\','/',substr($class,strlen($prefix))).'.php'; if(is_file($file)) require_once $file;
  });
  $pdo=\App\Core\Database::connection();
  $version=(string)$pdo->query('SELECT VERSION()')->fetchColumn();
  $ok('Banco acessível: '.$version);
  $db=(string)$pdo->query('SELECT DATABASE()')->fetchColumn();
  if($db==='') $err('Nenhum database ativo.');

  // Mapeia FK -> tabela pretendida nas migrations do patch e compara com INFORMATION_SCHEMA.
  $intended=[];
  foreach(['037_applanner_arena_v1.sql','038_applanner_arena_v2_complete.sql'] as $name){
    $sql=(string)file_get_contents($payload.'/database/migrations/'.$name);
    if(preg_match_all('/CREATE\\s+TABLE\\s+IF\\s+NOT\\s+EXISTS\\s+`?([A-Za-z0-9_]+)`?\\s*\\((.*?)\\)\\s*ENGINE/is',$sql,$blocks,PREG_SET_ORDER)){
      foreach($blocks as $b){ if(preg_match_all('/\\bCONSTRAINT\\s+([A-Za-z0-9_]+)/i',$b[2],$cm)) foreach($cm[1] as $c) $intended[strtolower($c)]=$b[1]; }
    }
  }
  if($intended){
    $names=array_keys($intended); $ph=implode(',',array_fill(0,count($names),'?'));
    $st=$pdo->prepare("SELECT CONSTRAINT_NAME,TABLE_NAME FROM information_schema.REFERENTIAL_CONSTRAINTS WHERE CONSTRAINT_SCHEMA=? AND LOWER(CONSTRAINT_NAME) IN ($ph)");
    $st->execute(array_merge([$db],$names));
    foreach($st->fetchAll(PDO::FETCH_ASSOC) as $row){
      $n=strtolower((string)$row['CONSTRAINT_NAME']); $actual=(string)$row['TABLE_NAME']; $want=$intended[$n]??'';
      if($want!=='' && strcasecmp($actual,$want)!==0) $err("Colisão de FK no banco: {$row['CONSTRAINT_NAME']} já pertence a {$actual}; patch espera {$want}.");
    }
    if(!$errors) $ok('Sem colisão de foreign keys com o schema atual');
  }
} catch(Throwable $e){ $err('Falha na checagem somente-leitura do banco: '.$e->getMessage()); }

if($errors){ echo "\nPRE-FLIGHT: FALHOU (".count($errors)." erro(s)). Nenhuma alteração foi feita.\n"; exit(1); }
echo "\nPRE-FLIGHT: OK".($warnings?' com '.count($warnings).' aviso(s)':'').". Nenhuma alteração foi feita.\n";
