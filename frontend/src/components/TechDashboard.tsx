import React, { useEffect, useState } from 'react';
import { BarChart3, Trophy, X } from 'lucide-react';
import { BoardData } from './TechBoard';
import { titleCase, colorForTechnician } from './TechBoard';

// Cor por estágio (ordem de BOARD_STAGES no backend) - espectro que acompanha o "clima" de cada
// etapa: cinza/azul no começo, verde quando aprova, vermelho quando não aprova, laranja/teal na
// reta final, cinza de novo quando não teve conserto.
const STAGE_COLORS: Record<string, string> = {
  entrada: '#64748b',
  avaliacao: '#818cf8',
  orcamento: '#fbbf24',
  aprovado: '#34d399',
  nao_aprovado: '#f87171',
  execucao: '#60a5fa',
  peca: '#fb923c',
  retirada: '#2dd4bf',
  sem_reparo: '#94a3b8',
  descarte: '#fb7185',
};

interface TechDashboardProps {
  board: BoardData;
  tvMode?: boolean;
  onClose?: () => void;
}

export const TechDashboard: React.FC<TechDashboardProps> = ({ board, tvMode, onClose }) => {
  // Dispara a animação de "encher" as barras só depois do primeiro render (senão a barra já
  // nasce no tamanho final e não dá pra perceber a animação de entrada).
  const [grown, setGrown] = useState(false);
  useEffect(() => {
    const t = requestAnimationFrame(() => setGrown(true));
    return () => cancelAnimationFrame(t);
  }, [board.generated_at]);

  const fs = (px: number) => tvMode ? `${Math.round(px * 1.15)}px` : `${px}px`;
  const maxStageCount = Math.max(1, ...board.stages.map(s => board.totals[s.key] || 0));
  const leaderboard = board.leaderboard || [];
  const maxFinalizadas = Math.max(1, ...leaderboard.map(l => l.finalizadas));
  const techByOpen = [...board.technicians].sort((a, b) => b.total_open - a.total_open);

  return (
    <div
      style={{
        flex: 1,
        minHeight: 0,
        overflowY: 'auto',
        display: 'flex',
        flexDirection: 'column',
        gap: tvMode ? '18px' : '16px',
        padding: tvMode ? '4px 2px 20px' : '4px 2px 16px',
      }}
    >
      {!tvMode && (
        <div style={{ display: 'flex', alignItems: 'center', gap: '10px' }}>
          <BarChart3 size={18} style={{ color: 'var(--accent-primary)' }} />
          <div style={{ fontSize: '16px', fontWeight: 800, color: 'var(--text-main)' }}>Painel do Fluxo</div>
          <div style={{ flex: 1 }} />
          {onClose && (
            <button
              onClick={onClose}
              style={{
                width: '30px', height: '30px', borderRadius: '8px', border: '1px solid var(--border-color)',
                background: 'transparent', color: 'var(--text-muted)', display: 'flex', alignItems: 'center',
                justifyContent: 'center', cursor: 'pointer',
              }}
            >
              <X size={16} />
            </button>
          )}
        </div>
      )}

      <div
        style={{
          display: 'grid',
          gridTemplateColumns: tvMode ? '1.1fr 1fr' : '1fr',
          gap: tvMode ? '20px' : '16px',
          alignItems: 'start',
        }}
      >
        {/* Distribuição por status */}
        <div
          style={{
            background: 'var(--bg-card, var(--bg-secondary))',
            border: '1px solid var(--border-color)',
            borderRadius: 'var(--radius-lg)',
            padding: tvMode ? '20px 22px' : '16px 18px',
          }}
        >
          <div style={{ fontSize: fs(13), fontWeight: 700, color: 'var(--text-muted)', textTransform: 'uppercase', letterSpacing: '0.04em', marginBottom: '14px' }}>
            O.S. por status ({board.total_open} em aberto)
          </div>
          <div style={{ display: 'flex', flexDirection: 'column', gap: tvMode ? '10px' : '8px' }}>
            {board.stages.map(stage => {
              const count = board.totals[stage.key] || 0;
              const pct = grown ? Math.round((count / maxStageCount) * 100) : 0;
              const color = STAGE_COLORS[stage.key] || 'var(--accent-primary)';
              return (
                <div key={stage.key} style={{ display: 'flex', alignItems: 'center', gap: '10px' }}>
                  <div style={{ width: tvMode ? '150px' : '120px', flexShrink: 0, fontSize: fs(12), color: 'var(--text-muted)', fontWeight: 600 }}>
                    {stage.label}
                  </div>
                  <div style={{ flex: 1, height: tvMode ? '16px' : '12px', borderRadius: '999px', background: 'rgba(255,255,255,0.06)', overflow: 'hidden' }}>
                    <div
                      style={{
                        height: '100%',
                        width: `${pct}%`,
                        background: color,
                        borderRadius: '999px',
                        transition: 'width 1s cubic-bezier(0.22, 1, 0.36, 1)',
                      }}
                    />
                  </div>
                  <div style={{ width: tvMode ? '34px' : '26px', textAlign: 'right', fontSize: fs(13), fontWeight: 800, color: 'var(--text-main)', fontVariantNumeric: 'tabular-nums' }}>
                    {count}
                  </div>
                </div>
              );
            })}
          </div>

          {/* Legenda de status x técnico */}
          <div style={{ fontSize: fs(13), fontWeight: 700, color: 'var(--text-muted)', textTransform: 'uppercase', letterSpacing: '0.04em', margin: '18px 0 12px' }}>
            Carga por técnico
          </div>
          <div style={{ display: 'flex', flexDirection: 'column', gap: tvMode ? '10px' : '8px' }}>
            {techByOpen.slice(0, tvMode ? 10 : 8).map(tech => (
              <div key={tech.name} style={{ display: 'flex', alignItems: 'center', gap: '10px' }}>
                <div style={{ width: tvMode ? '150px' : '120px', flexShrink: 0, fontSize: fs(12), color: colorForTechnician(tech.name), fontWeight: 700, whiteSpace: 'nowrap', overflow: 'hidden', textOverflow: 'ellipsis' }}>
                  {titleCase(tech.name)}
                </div>
                <div style={{ flex: 1, height: tvMode ? '16px' : '12px', borderRadius: '999px', background: 'rgba(255,255,255,0.06)', overflow: 'hidden', display: 'flex' }}>
                  {board.stages.map(stage => {
                    const count = tech.cells[stage.key]?.count || 0;
                    if (!count) return null;
                    const pct = grown ? (count / Math.max(1, tech.total_open)) * 100 : 0;
                    return (
                      <div
                        key={stage.key}
                        title={`${stage.label}: ${count}`}
                        style={{
                          height: '100%',
                          width: `${pct}%`,
                          background: STAGE_COLORS[stage.key] || 'var(--accent-primary)',
                          transition: 'width 1s cubic-bezier(0.22, 1, 0.36, 1)',
                        }}
                      />
                    );
                  })}
                </div>
                <div style={{ width: tvMode ? '34px' : '26px', textAlign: 'right', fontSize: fs(13), fontWeight: 800, color: 'var(--text-main)', fontVariantNumeric: 'tabular-nums' }}>
                  {tech.total_open}
                </div>
              </div>
            ))}
          </div>
        </div>

        {/* Ranking do mês */}
        <div
          style={{
            background: 'var(--bg-card, var(--bg-secondary))',
            border: '1px solid var(--border-color)',
            borderRadius: 'var(--radius-lg)',
            padding: tvMode ? '20px 22px' : '16px 18px',
          }}
        >
          <div style={{ fontSize: fs(13), fontWeight: 700, color: 'var(--text-muted)', textTransform: 'uppercase', letterSpacing: '0.04em', marginBottom: '14px', display: 'flex', alignItems: 'center', gap: '8px' }}>
            <Trophy size={14} style={{ color: '#fbbf24' }} />
            Destaque do mês · {board.leaderboard_month_label || ''}
          </div>

          {leaderboard.length === 0 ? (
            <div style={{ fontSize: fs(13), color: 'var(--text-dim, var(--text-muted))', padding: '20px 0', textAlign: 'center' }}>
              Nenhuma O.S. finalizada neste mês ainda.
            </div>
          ) : (
            <div style={{ display: 'flex', flexDirection: 'column', gap: tvMode ? '14px' : '10px' }}>
              {leaderboard.slice(0, tvMode ? 8 : 6).map((row, idx) => {
                const isLeader = idx === 0;
                const pct = grown ? Math.round((row.finalizadas / maxFinalizadas) * 100) : 0;
                const color = colorForTechnician(row.tecnico);
                return (
                  <div
                    key={row.tecnico}
                    className={isLeader ? 'leader-glow-card' : undefined}
                    style={{
                      display: 'flex',
                      alignItems: 'center',
                      gap: '12px',
                      padding: isLeader ? (tvMode ? '14px 16px' : '10px 12px') : '2px 0',
                      borderRadius: 'var(--radius-md)',
                      background: isLeader ? 'rgba(251, 191, 36, 0.08)' : 'transparent',
                      border: isLeader ? '1px solid rgba(251, 191, 36, 0.35)' : 'none',
                    }}
                  >
                    <div style={{ width: tvMode ? '28px' : '22px', textAlign: 'center', fontSize: fs(isLeader ? 20 : 14), fontWeight: 900, color: isLeader ? '#fbbf24' : 'var(--text-dim, var(--text-muted))', flexShrink: 0 }}>
                      {isLeader ? <span className="trophy-bounce">🏆</span> : `${idx + 1}º`}
                    </div>
                    <div style={{ flex: 1, minWidth: 0 }}>
                      <div style={{ display: 'flex', justifyContent: 'space-between', marginBottom: '4px' }}>
                        <span style={{ fontSize: fs(isLeader ? 15 : 13), fontWeight: isLeader ? 800 : 700, color: isLeader ? 'var(--text-main)' : color, whiteSpace: 'nowrap', overflow: 'hidden', textOverflow: 'ellipsis' }}>
                          {titleCase(row.tecnico)}
                        </span>
                        <span style={{ fontSize: fs(isLeader ? 15 : 13), fontWeight: 800, color: 'var(--text-main)', fontVariantNumeric: 'tabular-nums', flexShrink: 0, marginLeft: '8px' }}>
                          {row.finalizadas} O.S.
                        </span>
                      </div>
                      <div style={{ height: isLeader ? '10px' : '7px', borderRadius: '999px', background: 'rgba(255,255,255,0.06)', overflow: 'hidden' }}>
                        <div
                          style={{
                            height: '100%',
                            width: `${pct}%`,
                            background: isLeader ? 'linear-gradient(90deg, #fbbf24, #f59e0b)' : color,
                            borderRadius: '999px',
                            transition: `width 1.2s cubic-bezier(0.22, 1, 0.36, 1) ${idx * 0.08}s`,
                          }}
                        />
                      </div>
                    </div>
                  </div>
                );
              })}
            </div>
          )}
        </div>
      </div>
    </div>
  );
};
