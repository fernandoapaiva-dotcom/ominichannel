import { defineConfig } from 'vite'
import react from '@vitejs/plugin-react'
import { resolve } from 'path'

export default defineConfig({
  plugins: [react()],
  build: {
    rollupOptions: {
      // Três páginas de entrada compartilhando a mesma SPA (App.tsx decide o que mostrar pela
      // rota) - precisam ser entry points de verdade do Vite, não cópias estáticas de public/,
      // senão a tag <script> fica com o hash do bundle "congelado" do build em que foram criadas
      // e quebra (tela preta) assim que um build novo gera um hash diferente - achado em
      // produção em 07/10/2026 (app de foto da O.S. parou de abrir no celular).
      input: {
        main: resolve(__dirname, 'index.html'),
        fotoOs: resolve(__dirname, 'foto-os.html'),
        tecnico: resolve(__dirname, 'tecnico.html'),
      },
    },
  },
  server: {
    port: 3000,
    host: true,
    proxy: {
      '/api': {
        target: 'http://127.0.0.1:8000',
        changeOrigin: true,
        secure: false,
      },
      '/ws': {
        target: 'ws://127.0.0.1:8000',
        ws: true,
        changeOrigin: true
      }
    }
  }
})
