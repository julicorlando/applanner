<?php
namespace App\Core;

final class I18n
{
    public const SUPPORTED=['pt_BR','pt_PT','en','es'];
    private static string $locale='pt_BR';
    private static array $messages=[];

    public static function boot():void
    {
        $requested=str_replace('-','_',(string)($_GET['lang']??$_SESSION['locale']??$_COOKIE['applanner_locale']??'pt_BR'));
        if(!in_array($requested,self::SUPPORTED,true))$requested='pt_BR';
        self::$locale=$requested;$_SESSION['locale']=$requested;
        if(isset($_GET['lang']))setcookie('applanner_locale',$requested,['expires'=>time()+31536000,'path'=>'/','secure'=>!empty($_SERVER['HTTPS']),'httponly'=>false,'samesite'=>'Lax']);
        $file=__DIR__.'/../Lang/'.$requested.'.php';self::$messages=is_file($file)?(require $file):[];
    }

    public static function locale():string{return self::$locale;}
    public static function htmlLocale():string{return str_replace('_','-',self::$locale);}
    public static function t(string $key,array $replace=[],?string $fallback=null):string
    {
        $text=(string)(self::$messages[$key]??$fallback??$key);
        foreach($replace as $name=>$value)$text=str_replace('{'.$name.'}',(string)$value,$text);
        return $text;
    }
    public static function label(string $pt):string{return self::t('literal.'.$pt,[],$pt);}
    public static function options():array{return ['pt_BR'=>'Português (Brasil)','pt_PT'=>'Português (Portugal)','en'=>'English','es'=>'Español'];}
}
