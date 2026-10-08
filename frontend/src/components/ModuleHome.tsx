import React from 'react';
import { MessageSquare, Wrench, DollarSign, ShoppingCart, Truck, Settings } from 'lucide-react';
import { User } from '../types';

export type DashboardTab = 'chats' | 'groups' | 'contacts' | 'segmentation' | 'admin' | 'tecnicos' | 'home';

interface ModuleDef {
  id: DashboardTab;
  label: string;
  description: string;
  icon: React.ReactNode;
  comingSoon?: boolean;
  adminOnly?: boolean;
}

const MODULES: ModuleDef[] = [
  {
    id: 'chats',
    label: 'WhatsApp',
    description: 'Conversas, grupos, contatos e segmentação de clientes',
    icon: <MessageSquare size={28} />,
  },
  {
    id: 'tecnicos',
    label: 'Assistência Técnica',
    description: 'Quadro de O.S., técnicos, relatórios e peças',
    icon: <Wrench size={28} />,
  },
  {
    id: 'admin',
    label: 'Configurações',
    description: 'Números de WhatsApp, usuários, automações e integrações',
    icon: <Settings size={28} />,
    adminOnly: true,
  },
  {
    id: 'home', // placeholder id — módulo ainda não existe, card fica desabilitado
    label: 'Financeiro',
    description: 'Cobrança, contas a pagar/receber e boletos',
    icon: <DollarSign size={28} />,
    comingSoon: true,
  },
  {
    id: 'home',
    label: 'Compras',
    description: 'Pedidos a fornecedores e controle de estoque',
    icon: <ShoppingCart size={28} />,
    comingSoon: true,
  },
  {
    id: 'home',
    label: 'Locação',
    description: 'Contratos e controle de equipamentos locados',
    icon: <Truck size={28} />,
    comingSoon: true,
  },
];

interface ModuleHomeProps {
  user: User;
  onSelectModule: (tab: DashboardTab) => void;
}

export const ModuleHome: React.FC<ModuleHomeProps> = ({ user, onSelectModule }) => {
  return (
    <div
      style={{
        flex: 1,
        width: '100%',
        height: '100%',
        overflowY: 'auto',
        background: 'var(--bg-primary)',
        display: 'flex',
        flexDirection: 'column',
        alignItems: 'center',
        padding: '48px 24px',
        boxSizing: 'border-box',
      }}
    >
      <div style={{ width: '100%', maxWidth: '920px' }}>
        <div style={{ marginBottom: '36px' }}>
          <h1
            style={{
              fontFamily: 'var(--font-heading)',
              fontSize: '26px',
              fontWeight: 700,
              color: 'var(--text-main)',
              margin: 0,
            }}
          >
            Olá, {user.nome?.split(' ')[0] || 'tudo bem'} 👋
          </h1>
          <p style={{ color: 'var(--text-muted)', fontSize: '14px', marginTop: '6px' }}>
            Escolha um módulo pra começar
          </p>
        </div>

        <div
          style={{
            display: 'grid',
            gridTemplateColumns: 'repeat(auto-fill, minmax(230px, 1fr))',
            gap: '16px',
          }}
        >
          {MODULES.filter((mod) => !mod.adminOnly || user.role === 'admin').map((mod, idx) => (
            <button
              key={`${mod.label}-${idx}`}
              onClick={() => !mod.comingSoon && onSelectModule(mod.id)}
              disabled={mod.comingSoon}
              style={{
                textAlign: 'left',
                background: 'var(--bg-card, var(--bg-secondary))',
                border: '1px solid var(--border-color)',
                borderRadius: 'var(--radius-lg)',
                padding: '22px',
                cursor: mod.comingSoon ? 'default' : 'pointer',
                opacity: mod.comingSoon ? 0.5 : 1,
                display: 'flex',
                flexDirection: 'column',
                gap: '14px',
                transition: 'var(--transition-fast)',
                fontFamily: 'inherit',
              }}
              onMouseEnter={(e) => {
                if (mod.comingSoon) return;
                e.currentTarget.style.borderColor = 'var(--border-active)';
                e.currentTarget.style.transform = 'translateY(-2px)';
              }}
              onMouseLeave={(e) => {
                e.currentTarget.style.borderColor = 'var(--border-color)';
                e.currentTarget.style.transform = 'translateY(0)';
              }}
            >
              <div
                style={{
                  width: '48px',
                  height: '48px',
                  borderRadius: 'var(--radius-md)',
                  background: mod.comingSoon ? 'rgba(255,255,255,0.06)' : 'var(--accent-gradient)',
                  color: mod.comingSoon ? 'var(--text-muted)' : '#051a12',
                  display: 'flex',
                  alignItems: 'center',
                  justifyContent: 'center',
                }}
              >
                {mod.icon}
              </div>
              <div>
                <div
                  style={{
                    fontWeight: 600,
                    fontSize: '16px',
                    color: 'var(--text-main)',
                    display: 'flex',
                    alignItems: 'center',
                    gap: '8px',
                  }}
                >
                  {mod.label}
                  {mod.comingSoon && (
                    <span
                      style={{
                        fontSize: '10px',
                        fontWeight: 700,
                        letterSpacing: '0.03em',
                        textTransform: 'uppercase',
                        color: 'var(--text-muted)',
                        background: 'rgba(255,255,255,0.06)',
                        padding: '2px 8px',
                        borderRadius: 'var(--radius-full)',
                      }}
                    >
                      Em breve
                    </span>
                  )}
                </div>
                <div style={{ fontSize: '13px', color: 'var(--text-muted)', marginTop: '4px', lineHeight: 1.4 }}>
                  {mod.description}
                </div>
              </div>
            </button>
          ))}
        </div>
      </div>
    </div>
  );
};
