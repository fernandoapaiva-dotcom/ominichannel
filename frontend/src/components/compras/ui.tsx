import React from 'react';
import { AlertCircle, X } from 'lucide-react';

// Peças visuais do módulo de Compras - seguem as variáveis de tema do restante do sistema.

export const card: React.CSSProperties = {
  background: 'var(--bg-secondary)',
  border: '1px solid var(--border-color)',
  borderRadius: 'var(--radius-lg)',
  padding: '20px',
};

export const input: React.CSSProperties = {
  width: '100%',
  padding: '8px 10px',
  background: 'var(--bg-primary)',
  border: '1px solid var(--border-color)',
  borderRadius: 'var(--radius-sm)',
  color: 'var(--text-main)',
  fontSize: '13px',
  boxSizing: 'border-box',
};

export const th: React.CSSProperties = {
  textAlign: 'left',
  padding: '8px 10px',
  fontSize: '11px',
  textTransform: 'uppercase',
  color: 'var(--text-muted)',
  fontWeight: 700,
  borderBottom: '1px solid var(--border-color)',
  whiteSpace: 'nowrap',
};

export const td: React.CSSProperties = {
  padding: '10px',
  fontSize: '13px',
  color: 'var(--text-main)',
  borderBottom: '1px solid var(--border-color)',
  verticalAlign: 'top',
};

type Variante = 'primario' | 'secundario' | 'perigo' | 'fantasma';

export const Botao: React.FC<React.ButtonHTMLAttributes<HTMLButtonElement> & { variante?: Variante; icone?: React.ReactNode }> = ({
  variante = 'primario', icone, children, style, disabled, ...rest
}) => {
  const cores: Record<Variante, React.CSSProperties> = {
    primario: { background: 'var(--accent-primary)', color: '#051a12', border: 'none' },
    secundario: { background: 'var(--bg-primary)', color: 'var(--text-main)', border: '1px solid var(--border-color)' },
    perigo: { background: 'rgba(239,68,68,0.15)', color: '#f87171', border: '1px solid rgba(239,68,68,0.4)' },
    fantasma: { background: 'transparent', color: 'var(--text-muted)', border: 'none' },
  };
  return (
    <button
      {...rest}
      disabled={disabled}
      style={{
        display: 'inline-flex', alignItems: 'center', gap: '6px', justifyContent: 'center',
        padding: '8px 14px', fontSize: '13px', fontWeight: 600, borderRadius: 'var(--radius-sm)',
        cursor: disabled ? 'not-allowed' : 'pointer', opacity: disabled ? 0.55 : 1, whiteSpace: 'nowrap',
        ...cores[variante], ...style,
      }}
    >
      {icone}
      {children}
    </button>
  );
};

export const Chip: React.FC<{ cor: string; children: React.ReactNode; title?: string }> = ({ cor, children, title }) => (
  <span
    title={title}
    style={{
      display: 'inline-flex', alignItems: 'center', gap: '4px', padding: '2px 8px', borderRadius: '10px',
      fontSize: '11px', fontWeight: 700, color: cor, background: `${cor}22`, border: `1px solid ${cor}55`, whiteSpace: 'nowrap',
    }}
  >
    {children}
  </span>
);

export const Campo: React.FC<{ rotulo: string; dica?: string; children: React.ReactNode; style?: React.CSSProperties }> = ({ rotulo, dica, children, style }) => (
  <label style={{ display: 'flex', flexDirection: 'column', gap: '4px', fontSize: '12px', color: 'var(--text-muted)', ...style }}>
    <span style={{ fontWeight: 600 }}>{rotulo}</span>
    {children}
    {dica && <span style={{ fontSize: '11px', opacity: 0.8 }}>{dica}</span>}
  </label>
);

export const Aviso: React.FC<{ tipo?: 'alerta' | 'erro' | 'ok' | 'info'; children: React.ReactNode; onFechar?: () => void }> = ({ tipo = 'alerta', children, onFechar }) => {
  const cor = { alerta: '#f59e0b', erro: '#ef4444', ok: '#22c55e', info: '#3b82f6' }[tipo];
  return (
    <div style={{
      display: 'flex', gap: '8px', alignItems: 'flex-start', padding: '10px 12px', borderRadius: 'var(--radius-sm)',
      background: `${cor}18`, border: `1px solid ${cor}55`, color: 'var(--text-main)', fontSize: '13px',
    }}>
      <AlertCircle size={16} color={cor} style={{ flexShrink: 0, marginTop: '1px' }} />
      <div style={{ flex: 1 }}>{children}</div>
      {onFechar && (
        <button onClick={onFechar} style={{ background: 'transparent', border: 'none', color: 'var(--text-muted)', cursor: 'pointer' }}>
          <X size={14} />
        </button>
      )}
    </div>
  );
};

export const Modal: React.FC<{ titulo: string; onFechar: () => void; children: React.ReactNode; largura?: number }> = ({ titulo, onFechar, children, largura = 720 }) => (
  <div
    onClick={onFechar}
    style={{
      position: 'fixed', inset: 0, background: 'rgba(0,0,0,0.7)', display: 'flex', alignItems: 'center',
      justifyContent: 'center', zIndex: 10000, padding: '16px',
    }}
  >
    <div
      onClick={(e) => e.stopPropagation()}
      style={{ ...card, width: '100%', maxWidth: `${largura}px`, maxHeight: '90vh', overflowY: 'auto', boxShadow: '0 20px 40px rgba(0,0,0,0.5)' }}
    >
      <div style={{ display: 'flex', justifyContent: 'space-between', alignItems: 'center', marginBottom: '14px' }}>
        <h3 style={{ margin: 0, fontSize: '16px', color: 'var(--text-main)' }}>{titulo}</h3>
        <button onClick={onFechar} style={{ background: 'transparent', border: 'none', color: 'var(--text-muted)', cursor: 'pointer' }}>
          <X size={18} />
        </button>
      </div>
      {children}
    </div>
  </div>
);
