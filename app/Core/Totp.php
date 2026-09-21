<?php
namespace App\Core;

final class Totp
{
    private const ALPHABET='ABCDEFGHIJKLMNOPQRSTUVWXYZ234567';
    public static function secret(): string { $raw=random_bytes(20); $out=''; $bits=0;$buffer=0; foreach(str_split($raw) as $c){$buffer=($buffer<<8)|ord($c);$bits+=8;while($bits>=5){$bits-=5;$out.=self::ALPHABET[($buffer>>$bits)&31];}} return $out; }
    public static function verify(string $secret,string $code,int $window=1): bool { return self::verifyStep($secret,$code,$window)!==null; }
    public static function verifyStep(string $secret,string $code,int $window=1): ?int { $code=preg_replace('/\D/','',$code); if(strlen($code)!==6)return null; $step=intdiv(time(),30); for($i=-$window;$i<=$window;$i++){ $candidate=$step+$i;if(hash_equals(self::code($secret,$candidate),$code))return $candidate;} return null; }
    private static function code(string $secret,int $counter): string { $key=self::decode($secret); $bin=pack('N2',($counter>>32)&0xffffffff,$counter&0xffffffff);$hash=hash_hmac('sha1',$bin,$key,true);$offset=ord($hash[19])&15;$value=((ord($hash[$offset])&127)<<24)|(ord($hash[$offset+1])<<16)|(ord($hash[$offset+2])<<8)|ord($hash[$offset+3]);return str_pad((string)($value%1000000),6,'0',STR_PAD_LEFT); }
    private static function decode(string $value): string { $value=strtoupper(preg_replace('/[^A-Z2-7]/','',$value));$buffer=0;$bits=0;$out='';foreach(str_split($value) as $c){$pos=strpos(self::ALPHABET,$c);if($pos===false)continue;$buffer=($buffer<<5)|$pos;$bits+=5;if($bits>=8){$bits-=8;$out.=chr(($buffer>>$bits)&255);}}return $out; }
}
