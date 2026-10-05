import React from 'react'
import ReactDOM from 'react-dom/client'
import App from './App.tsx'
import { TechnicianPortalApp } from './TechnicianPortalApp.tsx'
import { FotoLauncherApp } from './FotoLauncherApp.tsx'
import { ErrorBoundary } from './components/ErrorBoundary.tsx'
import './index.css'

// /tecnico é o "sistema à parte" do técnico (login próprio por telefone+PIN, ver TechnicianPortalApp),
// completamente separado do app administrativo - decidido antes de montar nada. /foto-os é outro
// "sistema à parte" (pedido em 05/10/2026): atalho instalável só pra registrar foto/arquivo de uma
// O.S., sem abrir o resto do sistema - ver FotoLauncherApp.
const pathname = typeof window !== 'undefined' ? window.location.pathname : '';
const isTechnicianPortal = pathname.startsWith('/tecnico');
const isFotoLauncher = pathname.startsWith('/foto-os');

ReactDOM.createRoot(document.getElementById('root')!).render(
  <React.StrictMode>
    <ErrorBoundary>
      {isFotoLauncher ? <FotoLauncherApp /> : isTechnicianPortal ? <TechnicianPortalApp /> : <App />}
    </ErrorBoundary>
  </React.StrictMode>,
)

// Registra o Service Worker para suporte a PWA, notificações e badges na tela inicial
if ('serviceWorker' in navigator) {
  window.addEventListener('load', () => {
    navigator.serviceWorker.register('/sw.js').catch((err) => {
      console.debug('ServiceWorker registration error:', err);
    });
  });
}
