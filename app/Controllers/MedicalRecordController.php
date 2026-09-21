<?php
namespace App\Controllers;

use App\Core\{Auth,Authorization,CSRF,Database,TenantContext,View,Audit,Encryption,HttpException};
use App\Services\ModuleService;

final class MedicalRecordController
{
    public function index():void
    {
        ModuleService::require('medical_records');Authorization::require('medical_records.view');$t=TenantContext::id();$pid=$this->professional($t);$pdo=Database::connection();
        $q=$pdo->prepare("SELECT c.id,c.name,c.phone,c.email,MAX(a.starts_at) last_appointment,COUNT(a.id) appointments_count FROM customers c JOIN appointments a ON a.customer_id=c.id AND a.tenant_id=c.tenant_id WHERE c.tenant_id=:t AND a.professional_id=:p AND c.status='active' GROUP BY c.id,c.name,c.phone,c.email ORDER BY last_appointment DESC,c.name LIMIT 500");$q->execute(['t'=>$t,'p'=>$pid]);
        View::render('medical/index',['title'=>'Prontuários','patients'=>$q->fetchAll()]);
    }

    public function show(string $id):void
    {
        ModuleService::require('medical_records');Authorization::require('medical_records.view');$t=TenantContext::id();$pid=$this->professional($t);$patientId=(int)$id;$pdo=Database::connection();$this->relationship($pdo,$t,$pid,$patientId);
        $q=$pdo->prepare('SELECT id,name,phone,email,birth_date FROM customers WHERE id=:id AND tenant_id=:t');$q->execute(['id'=>$patientId,'t'=>$t]);$patient=$q->fetch();if(!$patient)HttpException::abort(404,'Paciente não encontrado.');
        $r=$pdo->prepare('SELECT mre.*,p.name professional_name FROM medical_record_entries mre JOIN professionals p ON p.id=mre.professional_id AND p.tenant_id=mre.tenant_id WHERE mre.tenant_id=:t AND mre.customer_id=:c ORDER BY mre.created_at DESC,mre.id DESC');$r->execute(['t'=>$t,'c'=>$patientId]);$records=[];foreach($r->fetchAll() as $row){try{$payload=Encryption::decrypt($row['content_encrypted']);$row['content']=(string)($payload['content']??'');}catch(\Throwable){$row['content']='[Conteúdo indisponível]';}$records[]=$row;}
        $a=$pdo->prepare("SELECT a.id,a.starts_at,s.name service_name FROM appointments a JOIN services s ON s.id=a.service_id AND s.tenant_id=a.tenant_id WHERE a.tenant_id=:t AND a.customer_id=:c AND a.professional_id=:p ORDER BY a.starts_at DESC LIMIT 100");$a->execute(['t'=>$t,'c'=>$patientId,'p'=>$pid]);
        View::render('medical/show',['title'=>'Prontuário de '.$patient['name'],'patient'=>$patient,'records'=>$records,'appointments'=>$a->fetchAll()]);
    }

    public function store(string $id):void
    {
        ModuleService::require('medical_records');Authorization::require('medical_records.create');CSRF::enforce();$t=TenantContext::id();$pid=$this->professional($t);$patientId=(int)$id;$pdo=Database::connection();$this->relationship($pdo,$t,$pid,$patientId);
        $type=(string)($_POST['record_type']??'evolution');if(!in_array($type,['evolution','anamnesis','procedure','observation','follow_up'],true))$type='evolution';$title=trim((string)($_POST['title']??''));$content=trim((string)($_POST['content']??''));$appointmentId=filter_var($_POST['appointment_id']??null,FILTER_VALIDATE_INT)?:null;if(strlen($title)<3||strlen($content)<5)HttpException::abort(422,'Preencha o título e o conteúdo do registro.');if($appointmentId){$a=$pdo->prepare('SELECT 1 FROM appointments WHERE id=:id AND tenant_id=:t AND customer_id=:c AND professional_id=:p');$a->execute(['id'=>$appointmentId,'t'=>$t,'c'=>$patientId,'p'=>$pid]);if(!$a->fetchColumn())HttpException::abort(422,'Atendimento inválido.');}
        $encrypted=Encryption::encrypt(['content'=>$content]);$pdo->prepare('INSERT INTO medical_record_entries(tenant_id,customer_id,professional_id,appointment_id,record_type,title,content_encrypted,created_by,created_at)VALUES(:t,:c,:p,:a,:type,:title,:content,:u,NOW())')->execute(['t'=>$t,'c'=>$patientId,'p'=>$pid,'a'=>$appointmentId,'type'=>$type,'title'=>$title,'content'=>$encrypted,'u'=>Auth::user()['id']]);$rid=(int)$pdo->lastInsertId();Audit::log('MEDICAL_RECORD_CREATED','medical_record_entries',$rid,null,['customer_id'=>$patientId,'record_type'=>$type]);header('Location: /clinical/patients/'.$patientId);exit;
    }

    private function professional(int $tenantId):int
    {
        if((Auth::user()['role']??'')!=='professional')HttpException::abort(403,'Prontuários são acessados pelo portal do profissional autorizado.');$q=Database::connection()->prepare('SELECT id FROM professionals WHERE tenant_id=:t AND user_id=:u AND active=1');$q->execute(['t'=>$tenantId,'u'=>Auth::user()['id']]);$id=(int)$q->fetchColumn();if(!$id)HttpException::abort(403,'Seu acesso não está vinculado a um profissional ativo.');return $id;
    }

    private function relationship(\PDO $pdo,int $tenantId,int $professionalId,int $patientId):void
    {
        $q=$pdo->prepare("SELECT 1 FROM appointments WHERE tenant_id=:t AND customer_id=:c AND professional_id=:p AND status IN('confirmed','in_progress','completed') LIMIT 1");$q->execute(['t'=>$tenantId,'c'=>$patientId,'p'=>$professionalId]);if(!$q->fetchColumn())HttpException::abort(403,'Você não possui vínculo assistencial com este paciente.');
    }
}
