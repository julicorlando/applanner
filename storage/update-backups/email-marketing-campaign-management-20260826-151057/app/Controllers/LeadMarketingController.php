<?php
namespace App\Controllers;

use App\Core\{Auth,Audit,CSRF,Database,Encryption,HttpException,View};
use App\Services\{EmailMarketingCardService,PlatformSetting,SmtpProvider};

final class LeadMarketingController
{
    private const SMTP_KEY='platform.lead_marketing_smtp';
    private function master():void{Auth::requireRole('master');}

    public function index():void
    {
        $this->master();header('Cache-Control: no-store, private');$pdo=Database::connection();$smtp=PlatformSetting::secret(self::SMTP_KEY);unset($smtp['password']);
        $stats=['active'=>(int)$pdo->query("SELECT COUNT(*) FROM marketing_leads WHERE status='active'")->fetchColumn(),'unsubscribed'=>(int)$pdo->query("SELECT COUNT(*) FROM marketing_leads WHERE status='unsubscribed'")->fetchColumn(),'sent'=>(int)$pdo->query("SELECT COUNT(*) FROM marketing_deliveries WHERE status='sent'")->fetchColumn(),'failed'=>(int)$pdo->query("SELECT COUNT(*) FROM marketing_deliveries WHERE status='failed'")->fetchColumn()];
        $platformUsers=$pdo->query("SELECT DISTINCT u.id,u.name,u.email,r.slug role_slug FROM users u JOIN user_roles ur ON ur.user_id=u.id JOIN roles r ON r.id=ur.role_id WHERE u.tenant_id IS NULL AND u.status='active' AND r.slug IN('master','support','commercial') ORDER BY u.name")->fetchAll();
        $profileInsert=$pdo->prepare("INSERT IGNORE INTO marketing_referral_profiles(user_id,referral_code,active,created_at,updated_at)VALUES(:u,:code,1,NOW(),NOW())");foreach($platformUsers as $staff)$profileInsert->execute(['u'=>$staff['id'],'code'=>bin2hex(random_bytes(8))]);
        $staff=$pdo->query("SELECT DISTINCT u.id,u.name,u.email,r.slug role_slug,rp.referral_code,(SELECT COUNT(*) FROM marketing_referral_visits rv WHERE rv.referrer_user_id=u.id) clicks,(SELECT COUNT(*) FROM marketing_referral_visits rv WHERE rv.referrer_user_id=u.id AND rv.converted_tenant_id IS NOT NULL) conversions FROM users u JOIN user_roles ur ON ur.user_id=u.id JOIN roles r ON r.id=ur.role_id JOIN marketing_referral_profiles rp ON rp.user_id=u.id AND rp.active=1 WHERE u.tenant_id IS NULL AND u.status='active' AND r.slug IN('master','support','commercial') ORDER BY u.name")->fetchAll();
        $leads=$pdo->query("SELECT * FROM marketing_leads ORDER BY id DESC LIMIT 300")->fetchAll();
        $campaigns=$pdo->query("SELECT c.*,u.name author_name,ru.name referrer_name,cr.referrer_user_id,(SELECT COUNT(*) FROM marketing_referral_visits rv WHERE rv.campaign_id=c.id) visit_count FROM marketing_campaigns c JOIN users u ON u.id=c.created_by LEFT JOIN marketing_campaign_referrers cr ON cr.campaign_id=c.id LEFT JOIN users ru ON ru.id=cr.referrer_user_id WHERE c.deleted_at IS NULL ORDER BY c.id DESC LIMIT 80")->fetchAll();
        $editCampaign=null;$editId=filter_var($_GET['edit_campaign']??null,FILTER_VALIDATE_INT);
        if($editId){$q=$pdo->prepare("SELECT c.*,cr.referrer_user_id FROM marketing_campaigns c LEFT JOIN marketing_campaign_referrers cr ON cr.campaign_id=c.id WHERE c.id=:id AND c.deleted_at IS NULL LIMIT 1");$q->execute(['id'=>$editId]);$editCampaign=$q->fetch()?:null;}
        View::render('master/lead-marketing',['title'=>'E-mail marketing','smtp'=>$smtp,'smtpConfigured'=>!empty($smtp['host'])&&!empty($smtp['from_email']),'stats'=>$stats,'leads'=>$leads,'campaigns'=>$campaigns,'staff'=>$staff,'editCampaign'=>$editCampaign]);
    }

    public function saveSmtp():void
    {
        $this->master();CSRF::enforce();$old=PlatformSetting::secret(self::SMTP_KEY);$cfg=['from_name'=>trim((string)($_POST['from_name']??'')),'from_email'=>mb_strtolower(trim((string)($_POST['from_email']??''))),'reply_to'=>mb_strtolower(trim((string)($_POST['reply_to']??''))),'host'=>trim((string)($_POST['host']??'')),'port'=>(int)($_POST['port']??587),'encryption'=>(string)($_POST['encryption']??'tls'),'username'=>trim((string)($_POST['username']??'')),'password'=>(string)($_POST['password']??'')];
        if($cfg['password']==='')$cfg['password']=$old['password']??'';if(mb_strlen($cfg['from_name'])<2||!filter_var($cfg['from_email'],FILTER_VALIDATE_EMAIL)||($cfg['reply_to']!==''&&!filter_var($cfg['reply_to'],FILTER_VALIDATE_EMAIL))||!preg_match('/^[a-z0-9.-]+$/i',$cfg['host'])||$cfg['port']<1||$cfg['port']>65535||!in_array($cfg['encryption'],['tls','ssl','none'],true)||$cfg['password']==='')HttpException::abort(422,'Configuração SMTP inválida.');PlatformSetting::setSecret(self::SMTP_KEY,$cfg);Audit::log('LEAD_MARKETING_SMTP_UPDATED','settings');header('Location: /master/email-marketing?smtp=ok');exit;
    }

    public function testSmtp():void
    {
        $this->master();CSRF::enforce();$to=mb_strtolower(trim((string)($_POST['test_email']??'')));if(!filter_var($to,FILTER_VALIDATE_EMAIL))HttpException::abort(422,'Informe um e-mail válido para o teste.');$smtp=PlatformSetting::secret(self::SMTP_KEY);if(empty($smtp['host'])||empty($smtp['password']))HttpException::abort(422,'Salve o SMTP antes de testar.');try{(new SmtpProvider())->send($smtp,$to,'Teste de e-mail marketing — ApPlanner',"Olá!\n\nO SMTP exclusivo de e-mail marketing do ApPlanner está funcionando corretamente.\n\nEste foi apenas um teste.");Audit::log('LEAD_MARKETING_SMTP_TESTED','settings',null,null,['to'=>$to]);header('Location: /master/email-marketing?smtp_test=ok');}catch(\Throwable $e){Audit::log('LEAD_MARKETING_SMTP_TEST_FAILED','settings',null,null,['to'=>$to,'error'=>mb_substr($e->getMessage(),0,180)]);header('Location: /master/email-marketing?smtp_error='.rawurlencode($e->getMessage()));}exit;
    }

    public function addLead():void{$this->master();CSRF::enforce();$added=$this->storeLead(trim((string)($_POST['name']??'')),(string)($_POST['email']??''),'manual');Audit::log('MARKETING_LEAD_ADDED','marketing_leads',$added);header('Location: /master/email-marketing?leads=1');exit;}

    public function addList():void
    {
        $this->master();CSRF::enforce();$lines=preg_split('/\R/u',(string)($_POST['list']??''));if(count($lines)>5000)HttpException::abort(422,'A lista deve ter no máximo 5.000 linhas por importação.');$count=0;foreach($lines as $line){$line=trim($line);if($line==='')continue;$parts=str_getcsv($line,str_contains($line,';')?';':',');if(count($parts)===1&&filter_var(trim($parts[0]),FILTER_VALIDATE_EMAIL)){$name=strstr(trim($parts[0]),'@',true)?:'Contato';$email=$parts[0];}else{$name=trim((string)($parts[0]??''));$email=(string)($parts[1]??'');}if($this->storeLead($name,$email,'list',false))$count++;}Audit::log('MARKETING_LEAD_LIST_IMPORTED','marketing_leads',null,null,['count'=>$count]);header('Location: /master/email-marketing?leads='.$count);exit;
    }

    public function importCsv():void
    {
        $this->master();CSRF::enforce();$file=$_FILES['csv']??[];if(($file['error']??UPLOAD_ERR_NO_FILE)!==UPLOAD_ERR_OK||(int)($file['size']??0)>5*1024*1024)HttpException::abort(422,'CSV inválido ou maior que 5 MB.');$handle=fopen($file['tmp_name'],'rb');if(!$handle)HttpException::abort(422,'Não foi possível ler o CSV.');$first=fgets($handle);rewind($handle);$delimiter=substr_count((string)$first,';')>substr_count((string)$first,',')?';':',';$count=0;$row=0;while(($data=fgetcsv($handle,0,$delimiter))!==false){$row++;if($row>5001)break;$name=trim((string)($data[0]??''));$email=trim((string)($data[1]??''));if($row===1&&mb_strtolower($name)==='nome'&&mb_strtolower($email)==='email')continue;if($this->storeLead($name,$email,'csv',false))$count++;}fclose($handle);Audit::log('MARKETING_LEAD_CSV_IMPORTED','marketing_leads',null,null,['count'=>$count]);header('Location: /master/email-marketing?leads='.$count);exit;
    }

    public function exportCsv():void
    {
        $this->master();$rows=Database::connection()->query('SELECT name,email FROM marketing_leads ORDER BY name,email')->fetchAll();header('Content-Type: text/csv; charset=UTF-8');header('Content-Disposition: attachment; filename="contatos-marketing-'.date('Y-m-d').'.csv"');$out=fopen('php://output','wb');fwrite($out,"\xEF\xBB\xBF");fputcsv($out,['nome','email'],';');foreach($rows as $r){$name=preg_match('/^[=+\-@]/',(string)$r['name'])?"'".$r['name']:$r['name'];fputcsv($out,[$name,$r['email']],';');}fclose($out);exit;
    }

    public function updateLead(string $id):void{$this->master();CSRF::enforce();$status=(string)($_POST['status']??'');if(!in_array($status,['active','unsubscribed','bounced'],true))HttpException::abort(422,'Status inválido.');$q=Database::connection()->prepare("UPDATE marketing_leads SET status=:s,unsubscribed_at=IF(:s2='unsubscribed',NOW(),NULL),updated_at=NOW() WHERE id=:id");$q->execute(['s'=>$status,'s2'=>$status,'id'=>(int)$id]);Audit::log('MARKETING_LEAD_STATUS_UPDATED','marketing_leads',(int)$id,null,['status'=>$status]);header('Location: /master/email-marketing');exit;}

    public function send():void
    {
        $this->master();CSRF::enforce();$smtp=PlatformSetting::secret(self::SMTP_KEY);
        if(empty($smtp['host'])||empty($smtp['password']))HttpException::abort(422,'Configure o SMTP de marketing antes do disparo.');

        $subject=trim((string)($_POST['subject']??''));$body=trim((string)($_POST['body']??''));
        $imageAlt=trim((string)($_POST['image_alt']??''));$cardLink=trim((string)($_POST['card_link_url']??''));
        $referrerId=filter_var($_POST['referrer_user_id']??null,FILTER_VALIDATE_INT);
        $hasUpload=(int)(($_FILES['card_image']['error']??UPLOAD_ERR_NO_FILE))!==UPLOAD_ERR_NO_FILE;

        if(mb_strlen($subject)<4||!$referrerId)HttpException::abort(422,'Informe assunto e responsável pela indicação.');
        if(mb_strlen($body)<20&&!$hasUpload)HttpException::abort(422,'Informe uma mensagem com pelo menos 20 caracteres ou envie um card.');
        if($cardLink!==''&&!filter_var($cardLink,FILTER_VALIDATE_URL))HttpException::abort(422,'O link do card é inválido.');
        if(mb_strlen($imageAlt)>190)HttpException::abort(422,'O texto alternativo do card deve ter até 190 caracteres.');

        $pdo=Database::connection();$ref=$pdo->prepare("SELECT rp.referral_code,u.name FROM marketing_referral_profiles rp JOIN users u ON u.id=rp.user_id JOIN user_roles ur ON ur.user_id=u.id JOIN roles r ON r.id=ur.role_id WHERE rp.user_id=:u AND rp.active=1 AND u.tenant_id IS NULL AND u.status='active' AND r.slug IN('master','support','commercial') LIMIT 1");
        $ref->execute(['u'=>$referrerId]);$referrer=$ref->fetch();if(!$referrer)HttpException::abort(422,'Indicador inválido.');
        $leads=$pdo->query("SELECT id,name,email,unsubscribe_token FROM marketing_leads WHERE status='active' ORDER BY id LIMIT 5000")->fetchAll();if(!$leads)HttpException::abort(422,'Não há contatos ativos para receber a campanha.');
        $app=require __DIR__.'/../../config/app.php';$base=rtrim((string)($app['url']??'https://applanner.com.br'),'/');

        $stored=null;if($hasUpload){try{$stored=(new EmailMarketingCardService())->store($_FILES['card_image']??[],$base);}catch(\Throwable $e){HttpException::abort(422,$e->getMessage());}}
        $imageAlt=$imageAlt!==''?$imageAlt:'Card promocional ApPlanner';

        $pdo->beginTransaction();
        try{
            $pdo->prepare("INSERT INTO marketing_campaigns(subject,body,image_path,image_url,image_alt,card_link_url,status,total_count,created_by,created_at,queued_at)VALUES(:s,:b,:path,:url,:alt,:link,'queued',:total,:u,NOW(),NOW())")->execute(['s'=>$subject,'b'=>$body,'path'=>$stored['path']??null,'url'=>$stored['url']??null,'alt'=>$stored?$imageAlt:null,'link'=>$cardLink!==''?$cardLink:null,'total'=>count($leads),'u'=>Auth::user()['id']]);
            $campaignId=(int)$pdo->lastInsertId();$pdo->prepare("INSERT INTO marketing_campaign_referrers(campaign_id,referrer_user_id,created_at)VALUES(:c,:u,NOW())")->execute(['c'=>$campaignId,'u'=>$referrerId]);
            $delivery=$pdo->prepare("INSERT INTO marketing_deliveries(campaign_id,lead_id,status,created_at,updated_at)VALUES(:c,:l,'queued',NOW(),NOW())");
            $job=$pdo->prepare("INSERT INTO jobs(tenant_id,type,payload_encrypted,status,attempts,available_at,created_at,updated_at)VALUES(NULL,'marketing.lead_email',:p,'queued',0,:available,NOW(),NOW())");
            foreach($leads as $i=>$lead){
                $delivery->execute(['c'=>$campaignId,'l'=>$lead['id']]);$deliveryId=(int)$pdo->lastInsertId();
                $referralUrl=$base.'/indicacao/'.$referrer['referral_code'].'?c='.$campaignId.'&l='.(int)$lead['id'];
                $message=str_replace(['{nome}','{email}','{link_indicacao}'],[$lead['name'],$lead['email'],$referralUrl],$body);
                $payload=Encryption::encrypt(['campaign_id'=>$campaignId,'delivery_id'=>$deliveryId,'lead_id'=>(int)$lead['id'],'to'=>$lead['email'],'subject'=>$subject,'message'=>$message,'image_url'=>$stored['url']??null,'image_alt'=>$stored?$imageAlt:null,'card_link_url'=>$cardLink!==''?$cardLink:null,'referral_url'=>$referralUrl,'referrer_name'=>$referrer['name'],'unsubscribe_url'=>$base.'/email/descadastrar/'.$lead['unsubscribe_token']]);
                $available=date('Y-m-d H:i:s',time()+intdiv($i,20)*60);$job->execute(['p'=>$payload,'available'=>$available]);
            }
            $pdo->prepare("UPDATE marketing_campaigns SET status='sending' WHERE id=:id")->execute(['id'=>$campaignId]);$pdo->commit();
            Audit::log('MARKETING_CAMPAIGN_QUEUED','marketing_campaigns',$campaignId,null,['recipients'=>count($leads),'referrer_user_id'=>$referrerId,'has_card'=>$stored!==null,'card_dimensions'=>$stored?[$stored['width'],$stored['height']]:null]);
        }catch(\Throwable $e){if($pdo->inTransaction())$pdo->rollBack();if($stored)(new EmailMarketingCardService())->delete($stored['path']??null);throw $e;}
        header('Location: /master/email-marketing?campaign=queued');exit;
    }


    public function updateCampaign(string $id):void
    {
        $this->master();CSRF::enforce();$campaignId=(int)$id;$pdo=Database::connection();$campaign=$this->campaign($pdo,$campaignId);
        $subject=trim((string)($_POST['subject']??''));$body=trim((string)($_POST['body']??''));$imageAlt=trim((string)($_POST['image_alt']??''));$cardLink=trim((string)($_POST['card_link_url']??''));$referrerId=(int)($_POST['referrer_user_id']??0);$referrer=$this->referrer($pdo,$referrerId);
        if(mb_strlen($subject)<4)HttpException::abort(422,'Informe um assunto válido.');
        if(mb_strlen($body)<20&&empty($campaign['image_url'])&&($_FILES['card_image']['error']??UPLOAD_ERR_NO_FILE)===UPLOAD_ERR_NO_FILE)HttpException::abort(422,'Informe uma mensagem ou mantenha/envie um card.');
        if($cardLink!==''&&!filter_var($cardLink,FILTER_VALIDATE_URL))HttpException::abort(422,'O link do card é inválido.');if(mb_strlen($imageAlt)>190)HttpException::abort(422,'O texto alternativo deve ter até 190 caracteres.');
        $app=require __DIR__.'/../../config/app.php';$base=rtrim((string)($app['url']??'https://applanner.com.br'),'/');$oldImagePath=(string)($campaign['image_path']??'');$imagePath=$oldImagePath;$imageUrl=(string)($campaign['image_url']??'');$removeImage=!empty($_POST['remove_card']);$stored=null;
        if($removeImage){$imagePath='';$imageUrl='';$imageAlt='';}
        if((int)(($_FILES['card_image']['error']??UPLOAD_ERR_NO_FILE))!==UPLOAD_ERR_NO_FILE){try{$stored=(new EmailMarketingCardService())->store($_FILES['card_image']??[],$base);}catch(\Throwable $e){HttpException::abort(422,$e->getMessage());}$imagePath=(string)$stored['path'];$imageUrl=(string)$stored['url'];$imageAlt=$imageAlt!==''?$imageAlt:'Card promocional ApPlanner';}elseif($imageUrl!==''&&$imageAlt==='')$imageAlt=(string)($campaign['image_alt']??'Card promocional ApPlanner');
        $pdo->beginTransaction();try{$pdo->prepare("UPDATE marketing_campaigns SET subject=:s,body=:b,image_path=:path,image_url=:url,image_alt=:alt,card_link_url=:link,updated_at=NOW() WHERE id=:id AND deleted_at IS NULL")->execute(['s'=>$subject,'b'=>$body,'path'=>$imagePath!==''?$imagePath:null,'url'=>$imageUrl!==''?$imageUrl:null,'alt'=>$imageUrl!==''?$imageAlt:null,'link'=>$cardLink!==''?$cardLink:null,'id'=>$campaignId]);$pdo->prepare("INSERT INTO marketing_campaign_referrers(campaign_id,referrer_user_id,created_at)VALUES(:c,:u,NOW()) ON DUPLICATE KEY UPDATE referrer_user_id=VALUES(referrer_user_id)")->execute(['c'=>$campaignId,'u'=>$referrerId]);$campaign=array_merge($campaign,['subject'=>$subject,'body'=>$body,'image_path'=>$imagePath,'image_url'=>$imageUrl,'image_alt'=>$imageAlt,'card_link_url'=>$cardLink,'referrer_user_id'=>$referrerId]);$updatedJobs=$this->rewriteQueuedJobs($pdo,$campaign,$referrer);$pdo->commit();}catch(\Throwable $e){if($pdo->inTransaction())$pdo->rollBack();if($stored)(new EmailMarketingCardService())->delete($stored['path']??null);throw $e;}
        if(($removeImage||$stored)&&$oldImagePath!==''&&$oldImagePath!==$imagePath)(new EmailMarketingCardService())->delete($oldImagePath);Audit::log('MARKETING_CAMPAIGN_UPDATED','marketing_campaigns',$campaignId,null,['referrer_user_id'=>$referrerId,'queued_jobs_updated'=>$updatedJobs]);header('Location: /master/email-marketing?campaign_action=updated');exit;
    }

    public function changeCampaignReferrer(string $id):void
    {
        $this->master();CSRF::enforce();$campaignId=(int)$id;$pdo=Database::connection();$campaign=$this->campaign($pdo,$campaignId);$referrerId=(int)($_POST['referrer_user_id']??0);$referrer=$this->referrer($pdo,$referrerId);$pdo->beginTransaction();try{$pdo->prepare("INSERT INTO marketing_campaign_referrers(campaign_id,referrer_user_id,created_at)VALUES(:c,:u,NOW()) ON DUPLICATE KEY UPDATE referrer_user_id=VALUES(referrer_user_id)")->execute(['c'=>$campaignId,'u'=>$referrerId]);$campaign['referrer_user_id']=$referrerId;$updated=$this->rewriteQueuedJobs($pdo,$campaign,$referrer);$pdo->commit();}catch(\Throwable $e){if($pdo->inTransaction())$pdo->rollBack();throw $e;}Audit::log('MARKETING_CAMPAIGN_REFERRER_UPDATED','marketing_campaigns',$campaignId,null,['referrer_user_id'=>$referrerId,'queued_jobs_updated'=>$updated]);header('Location: /master/email-marketing?campaign_action=referrer');exit;
    }

    public function campaignStatus(string $id):void
    {
        $this->master();CSRF::enforce();$campaignId=(int)$id;$pdo=Database::connection();$this->campaign($pdo,$campaignId);$active=(int)($_POST['active']??0)===1;
        if($active){$pdo->prepare("UPDATE marketing_campaigns SET active=1,updated_at=NOW() WHERE id=:id")->execute(['id'=>$campaignId]);Audit::log('MARKETING_CAMPAIGN_REACTIVATED','marketing_campaigns',$campaignId);header('Location: /master/email-marketing?campaign_action=reactivated');exit;}
        $pdo->beginTransaction();try{$cancelled=$this->cancelQueuedJobs($pdo,$campaignId);$pdo->prepare("UPDATE marketing_campaigns SET active=0,status=IF(status='completed','completed','cancelled'),updated_at=NOW() WHERE id=:id")->execute(['id'=>$campaignId]);$this->refreshCampaign($pdo,$campaignId);$pdo->commit();}catch(\Throwable $e){if($pdo->inTransaction())$pdo->rollBack();throw $e;}Audit::log('MARKETING_CAMPAIGN_INACTIVATED','marketing_campaigns',$campaignId,null,['queued_jobs_cancelled'=>$cancelled]);header('Location: /master/email-marketing?campaign_action=inactive');exit;
    }

    public function deleteCampaign(string $id):void
    {
        $this->master();CSRF::enforce();$campaignId=(int)$id;$pdo=Database::connection();$campaign=$this->campaign($pdo,$campaignId);$vis=$pdo->prepare("SELECT COUNT(*) FROM marketing_referral_visits WHERE campaign_id=:id");$vis->execute(['id'=>$campaignId]);$visits=(int)$vis->fetchColumn();$sent=(int)($campaign['sent_count']??0);$pdo->beginTransaction();try{$cancelled=$this->cancelQueuedJobs($pdo,$campaignId);if($sent===0&&$visits===0){$pdo->prepare("DELETE FROM marketing_campaigns WHERE id=:id")->execute(['id'=>$campaignId]);$hard=true;}else{$pdo->prepare("UPDATE marketing_campaigns SET active=0,deleted_at=NOW(),status=IF(status='completed','completed','cancelled'),updated_at=NOW() WHERE id=:id")->execute(['id'=>$campaignId]);$hard=false;}$pdo->commit();}catch(\Throwable $e){if($pdo->inTransaction())$pdo->rollBack();throw $e;}if($hard&&!empty($campaign['image_path']))(new EmailMarketingCardService())->delete($campaign['image_path']);Audit::log('MARKETING_CAMPAIGN_DELETED','marketing_campaigns',$campaignId,null,['hard_delete'=>$hard,'sent'=>$sent,'visits'=>$visits,'queued_jobs_cancelled'=>$cancelled]);header('Location: /master/email-marketing?campaign_action=deleted');exit;
    }

    private function campaign(\PDO $pdo,int $id):array
    {
        $q=$pdo->prepare("SELECT c.*,cr.referrer_user_id FROM marketing_campaigns c LEFT JOIN marketing_campaign_referrers cr ON cr.campaign_id=c.id WHERE c.id=:id AND c.deleted_at IS NULL LIMIT 1");$q->execute(['id'=>$id]);$row=$q->fetch();if(!$row)HttpException::abort(404,'Campanha não encontrada.');return $row;
    }

    private function referrer(\PDO $pdo,int $id):array
    {
        $q=$pdo->prepare("SELECT rp.referral_code,u.name,u.id FROM marketing_referral_profiles rp JOIN users u ON u.id=rp.user_id JOIN user_roles ur ON ur.user_id=u.id JOIN roles r ON r.id=ur.role_id WHERE rp.user_id=:u AND rp.active=1 AND u.tenant_id IS NULL AND u.status='active' AND r.slug IN('master','support','commercial') LIMIT 1");$q->execute(['u'=>$id]);$row=$q->fetch();if(!$row)HttpException::abort(422,'Indicador inválido.');return $row;
    }

    private function rewriteQueuedJobs(\PDO $pdo,array $campaign,array $referrer):int
    {
        $app=require __DIR__.'/../../config/app.php';$base=rtrim((string)($app['url']??'https://applanner.com.br'),'/');$jobs=$pdo->query("SELECT id,payload_encrypted FROM jobs WHERE tenant_id IS NULL AND type='marketing.lead_email' AND status='queued' ORDER BY id")->fetchAll();$updated=0;$leadStmt=$pdo->prepare("SELECT id,name,email,unsubscribe_token FROM marketing_leads WHERE id=:id LIMIT 1");$update=$pdo->prepare("UPDATE jobs SET payload_encrypted=:p,updated_at=NOW() WHERE id=:id AND status='queued'");
        foreach($jobs as $job){try{$p=Encryption::decrypt($job['payload_encrypted']);}catch(\Throwable){continue;}if((int)($p['campaign_id']??0)!==(int)$campaign['id'])continue;$leadStmt->execute(['id'=>(int)($p['lead_id']??0)]);$lead=$leadStmt->fetch();if(!$lead)continue;$referralUrl=$base.'/indicacao/'.$referrer['referral_code'].'?c='.(int)$campaign['id'].'&l='.(int)$lead['id'];$message=str_replace(['{nome}','{email}','{link_indicacao}'],[$lead['name'],$lead['email'],$referralUrl],(string)$campaign['body']);$p=array_merge($p,['to'=>$lead['email'],'subject'=>(string)$campaign['subject'],'message'=>$message,'image_url'=>$campaign['image_url']??null,'image_alt'=>$campaign['image_alt']??null,'card_link_url'=>$campaign['card_link_url']??null,'referral_url'=>$referralUrl,'referrer_name'=>$referrer['name'],'unsubscribe_url'=>$base.'/email/descadastrar/'.$lead['unsubscribe_token']]);$update->execute(['p'=>Encryption::encrypt($p),'id'=>$job['id']]);$updated+=$update->rowCount();}
        return $updated;
    }

    private function cancelQueuedJobs(\PDO $pdo,int $campaignId):int
    {
        $jobs=$pdo->query("SELECT id,payload_encrypted FROM jobs WHERE tenant_id IS NULL AND type='marketing.lead_email' AND status='queued' ORDER BY id")->fetchAll();$cancelled=0;$jobDone=$pdo->prepare("UPDATE jobs SET status='completed',payload_encrypted='',locked_at=NULL,last_error=NULL,updated_at=NOW() WHERE id=:id AND status='queued'");$delivery=$pdo->prepare("UPDATE marketing_deliveries SET status='skipped',error_message='Campanha inativada/cancelada pelo Master.',updated_at=NOW() WHERE id=:id AND status='queued'");foreach($jobs as $job){try{$p=Encryption::decrypt($job['payload_encrypted']);}catch(\Throwable){continue;}if((int)($p['campaign_id']??0)!==$campaignId)continue;if(!empty($p['delivery_id']))$delivery->execute(['id'=>(int)$p['delivery_id']]);$jobDone->execute(['id'=>$job['id']]);$cancelled+=$jobDone->rowCount();}return $cancelled;
    }

    private function refreshCampaign(\PDO $pdo,int $campaignId):void
    {
        $q=$pdo->prepare("SELECT SUM(status='sent') sent,SUM(status='failed') failed,SUM(status='skipped') skipped,COUNT(*) total FROM marketing_deliveries WHERE campaign_id=:c");$q->execute(['c'=>$campaignId]);$s=$q->fetch();$done=(int)$s['sent']+(int)$s['failed']+(int)$s['skipped']>=(int)$s['total'];$pdo->prepare("UPDATE marketing_campaigns SET sent_count=:sent,failed_count=:failed,status=IF(active=0,'cancelled',IF(:done=1,'completed','sending')),completed_at=IF(active=1 AND :done2=1,NOW(),completed_at),updated_at=NOW() WHERE id=:id")->execute(['sent'=>(int)$s['sent'],'failed'=>(int)$s['failed'],'done'=>$done?1:0,'done2'=>$done?1:0,'id'=>$campaignId]);
    }

    public function referral(string $code):void
    {
        if(!preg_match('/^[a-f0-9]{16}$/',$code))HttpException::abort(404,'Indicação inválida.');$pdo=Database::connection();$q=$pdo->prepare("SELECT rp.user_id FROM marketing_referral_profiles rp JOIN users u ON u.id=rp.user_id JOIN user_roles ur ON ur.user_id=u.id JOIN roles r ON r.id=ur.role_id WHERE rp.referral_code=:code AND rp.active=1 AND u.status='active' AND u.tenant_id IS NULL AND r.slug IN('master','support','commercial') LIMIT 1");$q->execute(['code'=>$code]);$referrerId=(int)$q->fetchColumn();if(!$referrerId)HttpException::abort(404,'Indicação inválida.');$campaignId=filter_var($_GET['c']??null,FILTER_VALIDATE_INT)?:null;$leadId=filter_var($_GET['l']??null,FILTER_VALIDATE_INT)?:null;if($campaignId){$valid=$pdo->prepare('SELECT 1 FROM marketing_campaign_referrers WHERE campaign_id=:c AND referrer_user_id=:u');$valid->execute(['c'=>$campaignId,'u'=>$referrerId]);if(!$valid->fetchColumn())$campaignId=null;}if($leadId){$valid=$pdo->prepare('SELECT 1 FROM marketing_leads WHERE id=:id');$valid->execute(['id'=>$leadId]);if(!$valid->fetchColumn())$leadId=null;}$token=bin2hex(random_bytes(32));$ip=(string)($_SERVER['REMOTE_ADDR']??'');$pdo->prepare("INSERT INTO marketing_referral_visits(referrer_user_id,campaign_id,lead_id,visit_token_hash,ip_hash,user_agent,clicked_at)VALUES(:u,:c,:l,:token,:ip,:ua,NOW())")->execute(['u'=>$referrerId,'c'=>$campaignId,'l'=>$leadId,'token'=>hash('sha256',$token),'ip'=>$ip!==''?hash('sha256',$ip):null,'ua'=>mb_substr((string)($_SERVER['HTTP_USER_AGENT']??''),0,500)]);setcookie('ap_ref',$token,['expires'=>time()+2592000,'path'=>'/','secure'=>!empty($_SERVER['HTTPS'])&&$_SERVER['HTTPS']!=='off','httponly'=>true,'samesite'=>'Lax']);header('Location: /cadastro?indicacao='.$code);exit;
    }

    public function unsubscribe(string $token):void
    {
        if(!preg_match('/^[a-f0-9]{64}$/',$token))HttpException::abort(404,'Link inválido.');$q=Database::connection()->prepare("UPDATE marketing_leads SET status='unsubscribed',unsubscribed_at=NOW(),updated_at=NOW() WHERE unsubscribe_token=:t");$q->execute(['t'=>$token]);View::render('marketing/unsubscribed',['title'=>'Descadastro confirmado','publicLayout'=>true]);
    }

    private function storeLead(string $name,string $email,string $source,bool $strict=true):int
    {
        $email=mb_strtolower(trim($email));$name=trim($name);if(!filter_var($email,FILTER_VALIDATE_EMAIL)){if($strict)HttpException::abort(422,'E-mail inválido.');return 0;}if($name==='')$name=strstr($email,'@',true)?:'Contato';$pdo=Database::connection();$q=$pdo->prepare("INSERT INTO marketing_leads(name,email,status,source,unsubscribe_token,consent_at,created_at,updated_at)VALUES(:n,:e,'active',:s,:t,NULL,NOW(),NOW()) ON DUPLICATE KEY UPDATE name=IF(status='active',VALUES(name),name),updated_at=NOW()");$q->execute(['n'=>mb_substr($name,0,160),'e'=>$email,'s'=>$source,'t'=>bin2hex(random_bytes(32))]);return (int)($pdo->lastInsertId()?:$pdo->query('SELECT LAST_INSERT_ID()')->fetchColumn());
    }
}
