# Validação PWA

Implementado: manifest same-origin, `display: standalone`, ícones 180/192/512, metadados Safari, instalação assistida, safe areas, Service Worker versionado e atualização por ação do usuário.

O Service Worker intercepta somente arquivos estáticos versionados; não intercepta navegação, APIs, administração, pagamentos, mídia ou respostas privadas. Testes Node: 20 passaram. A instalação real precisa ser repetida após redeploy no Safari do iPhone e Chrome Android.
