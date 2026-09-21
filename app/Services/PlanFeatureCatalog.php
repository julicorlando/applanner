<?php
namespace App\Services;

final class PlanFeatureCatalog
{
    private const FEATURES = [
        'products'=>['Cadastro de produtos','PDV / frente de caixa','Venda de produtos'],
        'stock'=>['Controle de estoque','Movimentações e alerta de estoque mínimo'],
        'finance'=>['Financeiro do estabelecimento','Controle de caixa','Receitas, despesas e formas de pagamento'],
        'behavior'=>['Inteligência de retorno e relacionamento'],
        'whatsapp'=>['Comunicação por WhatsApp'],
        'multiunit'=>['Gestão de múltiplas unidades'],
        'packages'=>['Pacotes e mensalidades'],
        'loyalty'=>['Programa de fidelidade'],
        'waitlist'=>['Lista de espera inteligente'],
        'custom_domain'=>['Domínio personalizado'],
        'medical_records'=>['Prontuários'],
        'odontology'=>['Recursos de odontologia'],
        'api'=>['Acesso à API'],
    ];
    public static function forSlug(string $slug,?string $fallback=null):array{return self::FEATURES[$slug]??($fallback!==null&&$fallback!==''?[$fallback]:[]);}
    public static function forModules(array $modules):array{$result=[];foreach($modules as $module){foreach(self::forSlug((string)($module['slug']??''),(string)($module['name']??'')) as $feature){if(!in_array($feature,$result,true))$result[]=$feature;}}return $result;}
}
