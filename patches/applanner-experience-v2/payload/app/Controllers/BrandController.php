<?php
namespace App\Controllers;

use App\Core\{Auth,Audit,CSRF,Database,HttpException,TenantContext,View};

final class BrandController
{
    private const FONTS=['Inter','Arial','Verdana','Tahoma','Trebuchet MS','Georgia','Times New Roman'];
    private const PAYMENT_METHODS=['pix'=>'Pix','cash'=>'Dinheiro','credit_card'=>'Cartão de crédito','debit_card'=>'Cartão de débito','bank_transfer'=>'Transferência bancária','payment_link'=>'Link de pagamento'];
    private const PUBLIC_SECTIONS=['services'=>'Serviços','professionals'=>'Profissionais','reviews'=>'Avaliações','products'=>'Produtos','memberships'=>'Assinaturas','packages'=>'Pacotes','loyalty'=>'Fidelidade','units'=>'Unidades e contato'];

    public function index():void
    {
        Auth::requireRole('owner');$q=Database::connection()->prepare('SELECT * FROM tenants WHERE id=:t AND deleted_at IS NULL');$q->execute(['t'=>TenantContext::id()]);$tenant=$q->fetch();if(!$tenant)HttpException::abort(404,'Estabelecimento não encontrado.');$tq=Database::connection()->prepare('SELECT locale,content_key,content_value FROM public_content_translations WHERE tenant_id=:t');$tq->execute(['t'=>$tenant['id']]);$translations=[];foreach($tq->fetchAll() as $row)$translations[$row['locale']][$row['content_key']]=$row['content_value'];
        View::render('settings/branding',['title'=>'Aparência do sistema','tenant'=>$tenant,'translations'=>$translations,'fonts'=>self::FONTS,'paymentMethods'=>self::PAYMENT_METHODS,'publicSections'=>self::PUBLIC_SECTIONS,'success'=>$_SESSION['branding_success']??null,'error'=>$_SESSION['branding_error']??null]);unset($_SESSION['branding_success'],$_SESSION['branding_error']);
    }

    public function update():void
    {
        Auth::requireRole('owner');CSRF::enforce();$tenantId=TenantContext::id();$pdo=Database::connection();$q=$pdo->prepare('SELECT logo_path,cover_path,public_layout,public_headline,public_subheadline,public_cta_label,public_announcement,public_accent_color,public_seo_title,public_seo_description,public_instagram,default_locale FROM tenants WHERE id=:t AND deleted_at IS NULL');$q->execute(['t'=>$tenantId]);$before=$q->fetch();if(!$before)HttpException::abort(404,'Estabelecimento não encontrado.');
        $defaults=['primary_color'=>'#3157d5','menu_color'=>'#17213b','menu_text_color'=>'#dce3f7','background_color'=>'#f4f6fb','text_color'=>'#17213b'];$colors=[];foreach($defaults as $key=>$default){$value=isset($_POST['restore_default'])?$default:(string)($_POST[$key]??$default);if(!preg_match('/^#[0-9a-f]{6}$/i',$value))HttpException::abort(422,'Uma das cores informadas é inválida.');$colors[$key]=strtolower($value);}
        $font=isset($_POST['restore_default'])?'Inter':(string)($_POST['font_family']??'Inter');if(!in_array($font,self::FONTS,true))HttpException::abort(422,'Fonte inválida.');$fontSize=isset($_POST['restore_default'])?15:max(12,min(20,(int)($_POST['font_size']??15)));$payments=array_values(array_intersect(array_keys(self::PAYMENT_METHODS),(array)($_POST['payment_methods']??[])));$sections=array_values(array_intersect(array_keys(self::PUBLIC_SECTIONS),(array)($_POST['public_sections']??[])));$logo=$before['logo_path'];$cover=$before['cover_path'];$created=[];
        try{
            if(!isset($_POST['restore_default'])&&!empty($_FILES['logo']['name'])){$logo=$this->upload($_FILES['logo'],$tenantId,'logo',2*1024*1024);$created[]=$logo;}
            if(!isset($_POST['restore_default'])&&!empty($_FILES['cover']['name'])){$cover=$this->upload($_FILES['cover'],$tenantId,'capa',5*1024*1024);$created[]=$cover;}
            if(isset($_POST['remove_logo']))$logo=null;if(isset($_POST['remove_cover']))$cover=null;
            $layouts=['editorial','minimal','bold'];$layout=(string)($_POST['public_layout']??'editorial');if(!in_array($layout,$layouts,true))$layout='editorial';$locale=(string)($_POST['default_locale']??'pt_BR');if(!in_array($locale,\App\Core\I18n::SUPPORTED,true))$locale='pt_BR';$accent=(string)($_POST['public_accent_color']??$colors['primary_color']);if(!preg_match('/^#[0-9a-f]{6}$/i',$accent))$accent=$colors['primary_color'];$clean=static fn(string $key,int $max):?string=>($v=mb_substr(trim(strip_tags((string)($_POST[$key]??''))),0,$max))!==''?$v:null;
            $requestedOrder=array_filter(explode(',',preg_replace('/[^a-z_,]/','',(string)($_POST['public_section_order']??''))));$order=array_values(array_unique(array_merge(array_intersect($requestedOrder,array_keys(self::PUBLIC_SECTIONS)),array_keys(self::PUBLIC_SECTIONS))));$public=['layout'=>$layout,'headline'=>$clean('public_headline',120),'subheadline'=>$clean('public_subheadline',300),'cta'=>$clean('public_cta_label',60),'announcement'=>$clean('public_announcement',160),'accent'=>strtolower($accent),'seo_title'=>$clean('public_seo_title',70),'seo_description'=>$clean('public_seo_description',180),'instagram'=>$clean('public_instagram',120),'locale'=>$locale,'order'=>$order];
            $pdo->prepare('UPDATE tenants SET logo_path=:logo,cover_path=:cover,primary_color=:primary,menu_color=:menu,menu_text_color=:menu_text,background_color=:background,text_color=:text,font_family=:font,font_size=:font_size,accepted_payment_methods=:payments,public_sections=:sections,public_section_order=:section_order,public_layout=:layout,public_headline=:headline,public_subheadline=:subheadline,public_cta_label=:cta,public_announcement=:announcement,public_accent_color=:accent,public_seo_title=:seo_title,public_seo_description=:seo_description,public_instagram=:instagram,default_locale=:locale,updated_at=NOW() WHERE id=:t')->execute(['logo'=>$logo,'cover'=>$cover,'primary'=>$colors['primary_color'],'menu'=>$colors['menu_color'],'menu_text'=>$colors['menu_text_color'],'background'=>$colors['background_color'],'text'=>$colors['text_color'],'font'=>$font,'font_size'=>$fontSize,'payments'=>json_encode($payments,JSON_UNESCAPED_UNICODE),'sections'=>json_encode($sections,JSON_UNESCAPED_UNICODE),'section_order'=>json_encode($order,JSON_UNESCAPED_UNICODE),'layout'=>$public['layout'],'headline'=>$public['headline'],'subheadline'=>$public['subheadline'],'cta'=>$public['cta'],'announcement'=>$public['announcement'],'accent'=>$public['accent'],'seo_title'=>$public['seo_title'],'seo_description'=>$public['seo_description'],'instagram'=>$public['instagram'],'locale'=>$public['locale'],'t'=>$tenantId]);
            foreach(['pt_PT','en','es'] as $translationLocale)foreach(['headline'=>120,'subheadline'=>300,'cta'=>60,'announcement'=>160] as $translationKey=>$max){$value=mb_substr(trim(strip_tags((string)($_POST['translation'][$translationLocale][$translationKey]??''))),0,$max);$pdo->prepare('INSERT INTO public_content_translations(tenant_id,locale,content_key,content_value,updated_at)VALUES(:t,:l,:k,:v,NOW()) ON DUPLICATE KEY UPDATE content_value=VALUES(content_value),updated_at=NOW()')->execute(['t'=>$tenantId,'l'=>$translationLocale,'k'=>$translationKey,'v'=>$value?:null]);}
            foreach(['logo_path'=>$before['logo_path'],'cover_path'=>$before['cover_path']] as $key=>$old){$new=$key==='logo_path'?$logo:$cover;if($old&&$old!==$new)$this->deleteOwned((string)$old,$tenantId);}
            Audit::log('TENANT_BRANDING_UPDATED','tenants',$tenantId,$before,['logo_path'=>$logo,'cover_path'=>$cover,'theme'=>$colors+['font_family'=>$font,'font_size'=>$fontSize],'public'=>$public,'payment_methods'=>$payments]);$_SESSION['branding_success']='Aparência e informações públicas atualizadas com sucesso.';
        }catch(\DomainException $e){foreach($created as $file)$this->deleteOwned($file,$tenantId);$_SESSION['branding_error']=$e->getMessage();}
        header('Location: /settings/branding');exit;
    }

    private function upload(array $file,int $tenantId,string $prefix,int $maxBytes):string
    {
        if(($file['error']??UPLOAD_ERR_NO_FILE)!==UPLOAD_ERR_OK)throw new \DomainException('Não foi possível receber a imagem.');$size=(int)($file['size']??0);if($size<1||$size>$maxBytes)throw new \DomainException('A imagem excede o tamanho permitido.');$tmp=(string)($file['tmp_name']??'');if(!is_uploaded_file($tmp))throw new \DomainException('Upload de imagem inválido.');$info=@getimagesize($tmp);$mime=(string)($info['mime']??'');$allowed=['image/jpeg'=>'jpg','image/png'=>'png','image/webp'=>'webp'];if(!isset($allowed[$mime])||($info[0]??0)<100||($info[1]??0)<100||($info[0]??0)>6000||($info[1]??0)>6000)throw new \DomainException('Envie JPG, PNG ou WebP entre 100 e 6000 pixels.');
        $base=dirname(__DIR__,2).'/public/uploads/tenants/'.$tenantId;if(!is_dir($base)&&!mkdir($base,0755,true)&&!is_dir($base))throw new \RuntimeException('Não foi possível preparar a pasta de imagens.');$name=$prefix.'-'.bin2hex(random_bytes(16)).'.'.$allowed[$mime];$dest=$base.'/'.$name;if(!move_uploaded_file($tmp,$dest))throw new \RuntimeException('Não foi possível salvar a imagem.');@chmod($dest,0644);return '/public/uploads/tenants/'.$tenantId.'/'.$name;
    }

    private function deleteOwned(string $webPath,int $tenantId):void
    {
        $prefix='/public/uploads/tenants/'.$tenantId.'/';if(!str_starts_with($webPath,$prefix))return;$base=realpath(dirname(__DIR__,2).'/public/uploads/tenants/'.$tenantId);$file=realpath(dirname(__DIR__,2).$webPath);if($base&&$file&&str_starts_with($file,$base.DIRECTORY_SEPARATOR)&&is_file($file))@unlink($file);
    }
}
