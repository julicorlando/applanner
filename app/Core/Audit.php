<?php
namespace App\Core;

final class Audit
{
    public static function log(string $action, ?string $entityType = null, ?int $entityId = null, ?array $before = null, ?array $after = null): void
    {
        try {
            $pdo = Database::connection();
            $u = Auth::user();
            $tenantId=$u['tenant_id']??null;$userId=$u['id']??null;
            if(Auth::isSupportImpersonating()){
                $meta=Auth::supportMeta()??[];
                $after=($after??[])+[
                    '_support_access'=>true,
                    '_support_actor_id'=>(int)($meta['actor_id']??0),
                    '_support_ticket_id'=>(int)($meta['ticket_id']??0),
                    '_support_access_session_id'=>(int)($meta['access_session_id']??0),
                    '_effective_user_id'=>(int)($u['id']??0),
                ];
                if(!empty($meta['actor_id']))$userId=(int)$meta['actor_id'];
            }
            $stmt = $pdo->prepare(
                "INSERT INTO audit_logs
                (tenant_id, user_id, action, entity_type, entity_id, ip_address, user_agent, before_json, after_json, created_at)
                VALUES (:tenant_id, :user_id, :action, :entity_type, :entity_id, :ip, :ua, :before_json, :after_json, NOW())"
            );
            $stmt->execute([
                'tenant_id' => $tenantId,
                'user_id' => $userId,
                'action' => $action,
                'entity_type' => $entityType,
                'entity_id' => $entityId,
                'ip' => $_SERVER['REMOTE_ADDR'] ?? null,
                'ua' => substr($_SERVER['HTTP_USER_AGENT'] ?? '', 0, 500),
                'before_json' => $before ? json_encode($before, JSON_UNESCAPED_UNICODE) : null,
                'after_json' => $after ? json_encode($after, JSON_UNESCAPED_UNICODE) : null,
            ]);
        } catch (\Throwable $e) {
            // Auditoria não pode derrubar a aplicação.
        }
    }
}
