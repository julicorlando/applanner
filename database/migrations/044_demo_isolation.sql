-- ApPlanner - Demo Isolation / Clean Homologation
-- Marca tenants de demonstração para excluí-los de métricas, billing e automações de produção.

ALTER TABLE tenants
  ADD COLUMN IF NOT EXISTS is_demo TINYINT(1) NOT NULL DEFAULT 0 AFTER deleted_at;

ALTER TABLE tenants
  ADD INDEX IF NOT EXISTS idx_tenants_demo (is_demo,status,deleted_at);

UPDATE tenants
SET is_demo=1, updated_at=NOW()
WHERE slug IN ('auto-prime-demonstracao','studio-aurora-demonstracao','arena-applanner-demo')
   OR public_slug IN ('applanner-auto-demo','arena-applanner-demo')
   OR LOWER(name) LIKE '%demonstra%';
