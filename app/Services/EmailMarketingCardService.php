<?php
namespace App\Services;

final class EmailMarketingCardService
{
    private const MAX_BYTES=5242880;
    private const MAX_WIDTH=6000;
    private const MAX_HEIGHT=6000;
    private const MAX_PIXELS=24000000;

    public function store(array $file,string $baseUrl):?array
    {
        $error=(int)($file['error']??UPLOAD_ERR_NO_FILE);
        if($error===UPLOAD_ERR_NO_FILE)return null;
        if($error!==UPLOAD_ERR_OK)throw new \RuntimeException('Falha no upload do card de marketing.');
        $size=(int)($file['size']??0);
        if($size<1||$size>self::MAX_BYTES)throw new \RuntimeException('O card deve ter no máximo 5 MB.');
        $tmp=(string)($file['tmp_name']??'');
        if($tmp===''||!is_uploaded_file($tmp))throw new \RuntimeException('Upload do card inválido.');

        $info=@getimagesize($tmp);
        if(!$info||empty($info[0])||empty($info[1]))throw new \RuntimeException('O arquivo enviado não é uma imagem válida.');
        $width=(int)$info[0];$height=(int)$info[1];
        if($width>self::MAX_WIDTH||$height>self::MAX_HEIGHT||($width*$height)>self::MAX_PIXELS)
            throw new \RuntimeException('A imagem é grande demais. Reduza as dimensões antes do envio.');

        $mime=(new \finfo(FILEINFO_MIME_TYPE))->file($tmp)?:'';
        $map=['image/jpeg'=>'jpg','image/png'=>'png','image/webp'=>'webp'];
        if(!isset($map[$mime]))throw new \RuntimeException('Formato não permitido. Use JPG, PNG ou WebP.');

        $ym=date('Y/m');$relative='public/uploads/email-marketing/'.$ym;$root=dirname(__DIR__,2);$dir=$root.'/'.$relative;
        if(!is_dir($dir)&&!mkdir($dir,0755,true)&&!is_dir($dir))throw new \RuntimeException('Não foi possível criar a pasta do card.');
        $name=date('YmdHis').'-'.bin2hex(random_bytes(10)).'.'.$map[$mime];$path=$dir.'/'.$name;
        if(!move_uploaded_file($tmp,$path))throw new \RuntimeException('Não foi possível salvar o card.');
        @chmod($path,0644);
        return ['path'=>$relative.'/'.$name,'url'=>rtrim($baseUrl,'/').'/'.$relative.'/'.$name,'mime'=>$mime,'width'=>$width,'height'=>$height,'bytes'=>$size];
    }

    public function delete(?string $relativePath):void
    {
        $relative=trim((string)$relativePath);
        if($relative===''||!str_starts_with($relative,'public/uploads/email-marketing/'))return;
        $root=realpath(dirname(__DIR__,2));if(!$root)return;
        $candidate=$root.'/'.$relative;$allowed=realpath($root.'/public/uploads/email-marketing');$dir=realpath(dirname($candidate));
        if(!$dir||!$allowed||!str_starts_with($dir,$allowed))return;
        if(is_file($candidate))@unlink($candidate);
    }
}
