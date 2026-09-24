import React from 'react'
import ReactDOM from 'react-dom/client'
import App from './App.tsx'
import { TechnicianPortalApp } from './TechnicianPortalApp.tsx'
import { ErrorBoundary } from './components/ErrorBoundary.tsx'
import './index.css'

// /tecnico é o "sistema à parte" do técnico (login próprio por telefone+PIN, ver TechnicianPortalApp),
// completamente separado do app administrativo - decidido antes de montar nada.
const isTechnicianPortal = typeof window !== 'undefined' && window.location.pathname.startsWith('/tecnico');

ReactDOM.createRoot(document.getElementById('root')!).render(
  <React.StrictMode>
    <ErrorBoundary>
      {isTechnicianPortal ? <TechnicianPortalApp /> : <App />}
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
