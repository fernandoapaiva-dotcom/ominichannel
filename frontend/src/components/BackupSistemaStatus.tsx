import React, { useEffect, useState } from 'react';
import { RefreshCw } from 'lucide-react';
import { apiFetch } from '../services/api';

// Admin > Integrações: status do backup do RAG (treino dos manuais) e do sistema (código + .env) no
// Google Drive - backend em app/services/sistema_backup_drive_service.py.

interface Item { em?: string; ok?: boolean; detalhe?: string; ultimo_sucesso?: string; tamanho_mb?: number }

const quando = (iso?: string) => (iso ? new Date(iso.endsWith('Z') ? iso : `${iso}Z`).toLocaleString('pt-BR') : '');

const Linha: React.FC<{ titulo: string; item: Item }> = ({ titulo, item }) => (
  <div style={{ fontSize: '12px', marginTop: '6px' }}>
    <span style={{ fontWeight: 600, color: 'var(--text-main)' }}>{titulo}: </span>
    {!item.em ? (
      <span style={{ color: 'var(--text-muted)' }}>ainda não rodou</span>
    ) : (
      <>
        <span style={{ fontWeight: 600, color: item.ok ? '#34d399' : '#f87171' }}>
          {item.ok ? '● ' : '○ '}{quando(item.em)}
        </span>
        {!item.ok && item.ultimo_sucesso && <span style={{ color: 'var(--text-muted)' }}> (último com sucesso: {quando(item.ultimo_sucesso)})</span>}
        {item.detalhe && <div style={{ color: 'var(--text-muted)', marginTop: '2px' }}>{item.detalhe}</div>}
      </>
    )}
  </div>
);

export const BackupSistemaStatus: React.FC<{ conectado?: boolean }> = ({ conectado }) => {
  const [st, setSt] = useState<{ rag: Item; sistema: Item; em_andamento: boolean } | null>(null);
  const [msg, setMsg] = useState<string | null>(null);

  const carregar = async () => {
    try { setSt(await apiFetch('/settings/backup-sistema/status')); } catch { /* painel continua sem o status */ }
  };
  useEffect(() => { carregar(); }, []);
  useEffect(() => {
    if (!st?.em_andamento) return;
    const t = setInterval(carregar, 15000);
    return () => clearInterval(t);
  }, [st?.em_andamento]);

  const rodar = async () => {
    try {
      const r = await apiFetch('/settings/backup-sistema/rodar-agora', { method: 'POST' });
      setMsg(r.mensagem);
      carregar();
    } catch (e: any) {
      setMsg(e.message || 'Falha ao iniciar');
    }
  };

  return (
    <div style={{ padding: '12px', backgroundColor: 'var(--bg-primary)', border: '1px solid var(--border-color)', borderRadius: 'var(--radius-md)' }}>
      <div style={{ display: 'flex', justifyContent: 'space-between', alignItems: 'center', flexWrap: 'wrap', gap: '10px' }}>
        <div style={{ flex: '1 1 300px' }}>
          <div style={{ fontSize: '13px', fontWeight: 600, color: 'var(--text-main)' }}>🧠 Backup do RAG e do Sistema</div>
          <div style={{ fontSize: '11px', color: 'var(--text-muted)', marginTop: '2px' }}>
            Sobe sozinho a cada atualização: o treino do RAG (manuais, OCR) assim que o treino da madrugada termina, e o sistema
            (código + chave de criptografia) a cada publicação. Ficam as 3 últimas cópias do RAG e as 10 últimas do sistema.
          </div>
          {st && <><Linha titulo="RAG" item={st.rag} /><Linha titulo="Sistema" item={st.sistema} /></>}
          {msg && <div style={{ fontSize: '12px', color: 'var(--text-muted)', marginTop: '6px' }}>{msg}</div>}
        </div>
        <button
          type="button"
          onClick={rodar}
          disabled={!!st?.em_andamento || conectado === false}
          className="btn-secondary"
          style={{ display: 'inline-flex', alignItems: 'center', gap: '6px', fontSize: '12px', padding: '8px 14px', whiteSpace: 'nowrap' }}
        >
          <RefreshCw size={14} className={st?.em_andamento ? 'animate-spin' : ''} /> {st?.em_andamento ? 'Enviando...' : 'Rodar Backup Agora'}
        </button>
      </div>
    </div>
  );
};
