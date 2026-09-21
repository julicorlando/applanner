<?php
namespace App\Services;

final class EmailMarketingTemplateService
{
    public function build(array $payload):array
    {
        $message=trim((string)($payload['message']??''));$referralUrl=trim((string)($payload['referral_url']??''));
        $unsubscribeUrl=trim((string)($payload['unsubscribe_url']??''));$referrer=trim((string)($payload['referrer_name']??'Equipe ApPlanner'));
        $imageUrl=trim((string)($payload['image_url']??''));$imageAlt=trim((string)($payload['image_alt']??'Card promocional ApPlanner'));
        $cardLink=trim((string)($payload['card_link_url']??''));if($cardLink===''&&$referralUrl!=='')$cardLink=$referralUrl;

        $referralText=$referralUrl!==''?"\n\nConheça o ApPlanner e comece seu teste:\n{$referralUrl}\n\nIndicação: {$referrer}":'';
        $imageText=$imageUrl!==''?"\n\nCard da campanha: {$imageUrl}":'';
        $text=$message.$imageText.$referralText."\n\n---\nVocê recebeu esta mensagem por estar na lista de contatos do ApPlanner."
            .($unsubscribeUrl!==''?"\nNão deseja mais receber novidades? Acesse: {$unsubscribeUrl}":'');

        $esc=static fn(string $v):string=>htmlspecialchars($v,ENT_QUOTES|ENT_SUBSTITUTE,'UTF-8');
        $messageHtml=$message!==''?nl2br($esc($message),false):'';
        $image='';
        if($imageUrl!==''){
            $img='<img src="'.$esc($imageUrl).'" alt="'.$esc($imageAlt).'" width="640" style="display:block;width:100%;max-width:640px;height:auto;border:0;outline:none;text-decoration:none;border-radius:12px;">';
            $image=$cardLink!==''?'<a href="'.$esc($cardLink).'" target="_blank" style="text-decoration:none;">'.$img.'</a>':$img;
            $image='<tr><td style="padding:0 24px 22px;">'.$image.'</td></tr>';
        }
        $cta='';
        if($referralUrl!==''){
            $cta='<tr><td style="padding:0 24px 24px;text-align:center;"><a href="'.$esc($referralUrl).'" target="_blank" style="display:inline-block;background:#111827;color:#fff;text-decoration:none;padding:13px 22px;border-radius:8px;font-family:Arial,sans-serif;font-size:15px;font-weight:700;">Conhecer o ApPlanner</a><div style="font-family:Arial,sans-serif;font-size:12px;color:#6b7280;margin-top:10px;">Indicação: '.$esc($referrer).'</div></td></tr>';
        }
        $unsubscribe=$unsubscribeUrl!==''?'<a href="'.$esc($unsubscribeUrl).'" style="color:#6b7280;text-decoration:underline;">Descadastrar</a>':'';
        $messageRow=$messageHtml!==''?'<tr><td style="padding:26px 24px 18px;font-family:Arial,sans-serif;font-size:15px;line-height:1.65;color:#1f2937;">'.$messageHtml.'</td></tr>':'';
        $html='<!doctype html><html><head><meta charset="UTF-8"><meta name="viewport" content="width=device-width,initial-scale=1"></head><body style="margin:0;padding:0;background:#f3f4f6;"><table role="presentation" width="100%" cellspacing="0" cellpadding="0" border="0" style="background:#f3f4f6;"><tr><td align="center" style="padding:24px 12px;"><table role="presentation" width="100%" cellspacing="0" cellpadding="0" border="0" style="width:100%;max-width:688px;background:#fff;border-radius:14px;overflow:hidden;">'
            .$messageRow.$image.$cta
            .'<tr><td style="padding:18px 24px;background:#f9fafb;border-top:1px solid #e5e7eb;font-family:Arial,sans-serif;font-size:11px;line-height:1.5;color:#6b7280;text-align:center;">Você recebeu esta mensagem por estar na lista de contatos do ApPlanner.'
            .($unsubscribe!==''?'<br>'.$unsubscribe:'').'</td></tr></table></td></tr></table></body></html>';
        return ['text'=>$text,'html'=>$html];
    }
}
