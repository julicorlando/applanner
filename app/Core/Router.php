<?php
namespace App\Core;

final class Router
{
    private array $routes = [];

    public function get(string $path, array $handler): void { $this->add('GET', $path, $handler); }
    public function post(string $path, array $handler): void { $this->add('POST', $path, $handler); }

    private function add(string $method, string $path, array $handler): void
    {
        $this->routes[$method][$path] = $handler;
    }

    public function dispatch(string $method, string $uri): void
    {
        $path = parse_url($uri, PHP_URL_PATH) ?: '/';
        $path = rtrim($path, '/') ?: '/';

        $handler = $this->routes[$method][$path] ?? null;
        $params=[];
        if(!$handler){foreach($this->routes[$method]??[] as $route=>$candidate){if(!str_contains($route,'{'))continue;$quoted=preg_quote($route,'#');$pattern='#^'.preg_replace('/\\\\\{([a-z_]+)\\\\\}/','(?P<$1>[a-z0-9-]+)',$quoted).'$#i';if(preg_match($pattern,$path,$matches)){foreach($matches as $k=>$v)if(is_string($k))$params[$k]=$v;$handler=$candidate;break;}}}
        if (!$handler) {
            http_response_code(404);
            View::render('dashboard/404', ['title' => 'Página não encontrada']);
            return;
        }

        [$class, $action] = $handler;
        (new $class())->{$action}(...array_values($params));
    }
}
