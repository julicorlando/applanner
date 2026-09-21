<?php
namespace App\Services;

final class SmtpProvider
{
    public function send(array $config,string $to,string $subject,string $body):void
    {
        $this->deliver($config,$to,$subject,"MIME-Version: 1.0\r\nContent-Type: text/plain; charset=UTF-8\r\nContent-Transfer-Encoding: 8bit",$body);
    }

    public function sendHtml(array $config,string $to,string $subject,string $textBody,string $htmlBody):void
    {
        $boundary='applanner-alt-'.bin2hex(random_bytes(12));
        $headers="MIME-Version: 1.0\r\nContent-Type: multipart/alternative; boundary=\"{$boundary}\"";
        $body="--{$boundary}\r\nContent-Type: text/plain; charset=UTF-8\r\nContent-Transfer-Encoding: 8bit\r\n\r\n{$textBody}\r\n"
            ."--{$boundary}\r\nContent-Type: text/html; charset=UTF-8\r\nContent-Transfer-Encoding: 8bit\r\n\r\n{$htmlBody}\r\n--{$boundary}--";
        $this->deliver($config,$to,$subject,$headers,$body);
    }

    private function deliver(array $config,string $to,string $subject,string $mimeHeaders,string $body):void
    {
        $host=(string)($config['host']??'');$port=(int)($config['port']??0);
        if(!preg_match('/^[a-z0-9.-]+$/i',$host)||$port<1||$port>65535)throw new \RuntimeException('SMTP inválido.');
        $prefix=($config['encryption']??'tls')==='ssl'?'ssl://':'';
        $socket=@stream_socket_client($prefix.$host.':'.$port,$errorNumber,$errorMessage,15);
        if(!$socket)throw new \RuntimeException('SMTP indisponível (conexão recusada ou tempo esgotado).');
        stream_set_timeout($socket,15);
        $readResponse=function()use($socket):string{$response='';do{$line=fgets($socket,4096);if($line===false)break;$response.=$line;}while(strlen($line)>=4&&$line[3]==='-');return $response;};
        $command=function(string $line,array $accepted,string $stage)use($socket,$readResponse):void{if(fwrite($socket,$line."\r\n")===false)throw new \RuntimeException('Falha de comunicação SMTP em '.$stage.'.');$response=$readResponse();$code=(int)substr($response,0,3);if(!in_array($code,$accepted,true))throw new \RuntimeException('SMTP recusou '.$stage.' (código '.($code?:'sem resposta').').');};
        try{
            $greeting=$readResponse();if((int)substr($greeting,0,3)!==220)throw new \RuntimeException('Servidor SMTP não apresentou uma saudação válida.');
            $command('EHLO applanner.com.br',[250],'identificação EHLO');
            if(($config['encryption']??'')==='tls'){$command('STARTTLS',[220],'início do TLS');if(!stream_socket_enable_crypto($socket,true,STREAM_CRYPTO_METHOD_TLS_CLIENT))throw new \RuntimeException('TLS SMTP falhou.');$command('EHLO applanner.com.br',[250],'identificação após TLS');}
            if(($config['username']??'')!==''){$command('AUTH LOGIN',[334],'autenticação');$command(base64_encode((string)$config['username']),[334],'usuário');$command(base64_encode((string)($config['password']??'')),[235],'senha');}
            $from=(string)($config['from_email']??'');if(!filter_var($from,FILTER_VALIDATE_EMAIL)||!filter_var($to,FILTER_VALIDATE_EMAIL))throw new \RuntimeException('E-mail inválido.');
            $command('MAIL FROM:<'.$from.'>',[250],'remetente');$command('RCPT TO:<'.$to.'>',[250,251],'destinatário');$command('DATA',[354],'conteúdo da mensagem');
            $fromName=trim((string)($config['from_name']??'ApPlanner'));$encodedSubject='=?UTF-8?B?'.base64_encode($subject).'?=';$encodedName='=?UTF-8?B?'.base64_encode($fromName).'?=';
            $replyTo=trim((string)($config['reply_to']??''));$headers="Subject: {$encodedSubject}\r\nFrom: {$encodedName} <{$from}>\r\nTo: {$to}\r\n";
            if($replyTo!==''&&filter_var($replyTo,FILTER_VALIDATE_EMAIL))$headers.="Reply-To: {$replyTo}\r\n";
            $headers.=$mimeHeaders."\r\n";$message=$headers."\r\n".$body;$safe=preg_replace('/^\./m','..',$message);
            if(fwrite($socket,$safe."\r\n.\r\n")===false)throw new \RuntimeException('Falha ao transmitir a mensagem SMTP.');
            $response=$readResponse();$code=(int)substr($response,0,3);if($code!==250)throw new \RuntimeException('SMTP rejeitou a mensagem (código '.($code?:'sem resposta').').');
            $command('QUIT',[221],'encerramento');
        }finally{fclose($socket);}
    }
}
