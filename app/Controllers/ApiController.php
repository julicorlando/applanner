<?php
namespace App\Controllers;

use App\Core\Auth;
use App\Core\CSRF;
use App\Services\BehaviorEngine;
use App\Services\ModuleService;
use App\Core\Authorization;
use App\Core\TenantContext;

final class ApiController
{
    public function recalculateBehavior(): void
    {
        ModuleService::require('behavior');
        Authorization::require('customers.view');
        CSRF::enforce();
        header('Content-Type: application/json; charset=utf-8');

        $customerId = filter_var($_POST['customer_id'] ?? null, FILTER_VALIDATE_INT);
        if (!$customerId) {
            http_response_code(422);
            echo json_encode(['ok' => false, 'error' => 'customer_id inválido']);
            return;
        }

        $result = (new BehaviorEngine())->recalculateCustomer(TenantContext::id(), $customerId);
        echo json_encode(['ok' => true, 'profile' => $result], JSON_UNESCAPED_UNICODE);
    }

    public function opportunities(): void
    {
        ModuleService::require('behavior');
        Authorization::require('dashboard.view');
        header('Content-Type: application/json; charset=utf-8');
        $items = (new BehaviorEngine())->opportunities(TenantContext::id(), 5);
        echo json_encode(['ok' => true, 'items' => $items], JSON_UNESCAPED_UNICODE);
    }
}
