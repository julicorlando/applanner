<?php
namespace App\Core;

final class HttpException
{
    public static function abort(int $status, string $message): never
    {
        http_response_code($status);
        $titles = [
            400 => 'Requisição inválida',
            401 => 'Não autenticado',
            403 => 'Acesso negado',
            404 => 'Página não encontrada',
            409 => 'Conflito',
            419 => 'Sessão expirada',
            422 => 'Dados inválidos',
            429 => 'Muitas tentativas',
            500 => 'Erro interno',
            503 => 'Serviço indisponível',
        ];
        $view = __DIR__ . '/../Views/errors/' . $status . '.php';
        if (!is_file($view)) {
            $view = __DIR__ . '/../Views/errors/generic.php';
            View::render('errors/generic', [
                'title' => $titles[$status] ?? "Erro {$status}",
                'message' => $message,
                'status' => $status,
            ]);
        } else {
            View::render("errors/{$status}", [
                'title' => $titles[$status] ?? "Erro {$status}",
                'message' => $message,
                'status' => $status,
            ]);
        }
        exit;
    }
}
