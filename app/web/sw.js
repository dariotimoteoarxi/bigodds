// Service worker mínimo para o Bigodds se instalar como app no telemóvel.
// Não guarda nada em cache: as apostas e os dados são sempre pedidos à rede (são privados e mudam a cada minuto).
self.addEventListener('install', () => self.skipWaiting());
self.addEventListener('activate', e => e.waitUntil(self.clients.claim()));
self.addEventListener('fetch', e => {
  if (e.request.mode !== 'navigate') return;  // só a página: sem rede, mostra um aviso em vez do dinossauro do Chrome
  e.respondWith(fetch(e.request).catch(() => new Response(
    '<!doctype html><meta charset="utf-8"><meta name="viewport" content="width=device-width,initial-scale=1">' +
    '<body style="background:#06120D;color:#F3F1E8;font:16px system-ui;display:grid;place-items:center;height:100vh;margin:0;text-align:center">' +
    '<div><h2>Sem ligação</h2><p>O Bigodds precisa de internet. Tenta outra vez daqui a pouco.</p></div>',
    { headers: { 'Content-Type': 'text/html; charset=utf-8' } })));
});
