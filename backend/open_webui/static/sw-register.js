// Registro do Service Worker para YuIA PWA
// Este script registra e gerencia o service worker

if ('serviceWorker' in navigator) {
  window.addEventListener('load', () => {
    registerServiceWorker();
  });
}

async function registerServiceWorker() {
  try {
    const registration = await navigator.serviceWorker.register('/sw.js', {
      scope: '/'
    });

    console.log('[SW] Service Worker registrado com sucesso:', registration.scope);

    // Verifica atualizações a cada hora
    setInterval(() => {
      registration.update();
    }, 60 * 60 * 1000);

    // Listener para atualizações do SW
    registration.addEventListener('updatefound', () => {
      const newWorker = registration.installing;
      console.log('[SW] Nova versão do Service Worker encontrada');

      newWorker.addEventListener('statechange', () => {
        if (newWorker.state === 'installed' && navigator.serviceWorker.controller) {
          // Novo SW instalado mas antigo ainda controlando
          showUpdateNotification(registration);
        }
      });
    });

    // Listener para quando o SW tomar controle
    navigator.serviceWorker.addEventListener('controllerchange', () => {
      console.log('[SW] Service Worker atualizado, recarregando...');
      window.location.reload();
    });

  } catch (error) {
    console.error('[SW] Erro ao registrar Service Worker:', error);
  }
}

function showUpdateNotification(registration) {
  // Notifica o usuário sobre atualização disponível
  const shouldUpdate = confirm(
    'Uma nova versão do YuIA está disponível. Deseja atualizar agora?'
  );

  if (shouldUpdate && registration.waiting) {
    // Envia mensagem para o SW pular a espera
    registration.waiting.postMessage({ type: 'SKIP_WAITING' });
  }
}

// Função para limpar cache (útil para debug)
window.clearAppCache = async function() {
  if ('serviceWorker' in navigator) {
    const registration = await navigator.serviceWorker.getRegistration();
    if (registration && registration.active) {
      registration.active.postMessage({ type: 'CLEAR_CACHE' });
      console.log('[SW] Comando de limpeza de cache enviado');
      setTimeout(() => window.location.reload(), 1000);
    }
  }
};

// Detecta se o app está instalado como PWA
window.isPWA = function() {
  return window.matchMedia('(display-mode: standalone)').matches ||
         window.navigator.standalone === true ||
         document.referrer.includes('android-app://');
};

// Log do status
console.log('[SW] Script de registro carregado');
console.log('[SW] Rodando como PWA:', window.isPWA());
