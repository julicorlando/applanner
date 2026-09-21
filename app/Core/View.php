<?php
namespace App\Core;

final class View
{
    public static function render(string $view, array $data = []): void
    {
        extract($data, EXTR_SKIP);
        $viewFile = __DIR__ . '/../Views/' . $view . '.php';
        if (!is_file($viewFile)) {
            throw new \RuntimeException("View não encontrada: {$view}");
        }
        require __DIR__ . '/../Views/layout.php';
    }
}
