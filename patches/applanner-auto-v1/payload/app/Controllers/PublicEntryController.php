<?php
namespace App\Controllers;

use App\Core\Database;

/**
 * Entrada pública compatível com links legados /a/{slug}.
 *
 * Negócios com o módulo Quadras e Esportes habilitado são enviados para a
 * experiência pública própria em /arena/{slug}. Os demais estabelecimentos
 * continuam utilizando o fluxo público tradicional.
 */
final class PublicEntryController
{
    public function show(string $slug): void
    {
        $sportsSlug = $this->sportsCanonicalSlug($slug);

        if ($sportsSlug !== null) {
            header('Location: /arena/' . rawurlencode($sportsSlug), true, 302);
            exit;
        }

        $autoSlug = $this->autoCanonicalSlug($slug);
        if ($autoSlug !== null) {
            header('Location: /auto/' . rawurlencode($autoSlug), true, 302);
            exit;
        }

        (new PublicBookingController())->show($slug);
    }

    private function sportsCanonicalSlug(string $slug): ?string
    {
        $pdo = Database::connection();
        $query = $pdo->prepare(<<<'SQL'
SELECT t.public_slug, t.public_short_code
FROM tenants t
JOIN subscriptions s
  ON s.id = (
      SELECT MAX(s2.id)
      FROM subscriptions s2
      WHERE s2.tenant_id = t.id
  )
JOIN modules m
  ON m.slug = 'sports_courts'
 AND m.active = 1
LEFT JOIN plan_modules pm
  ON pm.plan_id = s.plan_id
 AND pm.module_id = m.id
LEFT JOIN tenant_modules tm
  ON tm.tenant_id = t.id
 AND tm.module_id = m.id
LEFT JOIN sports_settings ss
  ON ss.tenant_id = t.id
WHERE (t.public_slug = :slug OR t.public_short_code = :short_slug)
  AND t.status IN ('trial', 'active')
  AND t.deleted_at IS NULL
  AND COALESCE(tm.enabled, pm.enabled, 0) = 1
  AND COALESCE(ss.public_enabled, 1) = 1
LIMIT 1
SQL);
        $query->execute([
            'slug' => $slug,
            'short_slug' => $slug,
        ]);

        $tenant = $query->fetch();
        if (!$tenant) {
            return null;
        }

        $canonical = trim((string)($tenant['public_slug'] ?: $tenant['public_short_code']));
        return $canonical !== '' ? $canonical : null;
    }
    private function autoCanonicalSlug(string $slug): ?string
    {
        $q=Database::connection()->prepare("SELECT t.public_slug,t.public_short_code,t.category FROM tenants t LEFT JOIN auto_settings a ON a.tenant_id=t.id WHERE (t.public_slug=:s OR t.public_short_code=:s2) AND t.status IN('trial','active') AND t.deleted_at IS NULL AND COALESCE(a.public_enabled,1)=1 LIMIT 1");
        $q->execute(['s'=>$slug,'s2'=>$slug]);$t=$q->fetch();
        if(!$t || !\App\Services\AutoTenantService::isAutoCategory($t['category']??'')) return null;
        $canonical=trim((string)($t['public_slug']?:$t['public_short_code']));
        return $canonical!==''?$canonical:null;
    }

}
