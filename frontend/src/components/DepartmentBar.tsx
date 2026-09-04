import React from 'react';
import {
  LayoutGrid, ShoppingBag, Key, Wrench, CreditCard,
  Building, Headphones, Truck, HelpCircle, Calendar
} from 'lucide-react';
import { WhatsAppNumber, Conversation } from '../types';

interface DepartmentBarProps {
  whatsappNumbers: WhatsAppNumber[];
  selectedDepartmentId: number | 'all';
  onSelectDepartment: (id: number | 'all') => void;
  conversations: Conversation[];
  onOpenCalendar?: () => void;
  calendarSummary?: { today_pending: number; overdue: number; total_pending: number } | null;
  pendingBadgeCount?: number;
  groupPendingBadgeCount?: number;
}

export const DepartmentBar: React.FC<DepartmentBarProps> = ({
  whatsappNumbers,
  selectedDepartmentId,
  onSelectDepartment,
  conversations,
  onOpenCalendar,
  calendarSummary,
  pendingBadgeCount = 0,
  groupPendingBadgeCount = 0
}) => {

  const getDepartmentIcon = (name: string, size = 16) => {
    const lower = name.toLowerCase();
    if (lower.includes('todos') || lower.includes('geral')) return <LayoutGrid size={size} />;
    if (lower.includes('venda') || lower.includes('e-commerce') || lower.includes('comercial')) return <ShoppingBag size={size} />;
    if (lower.includes('loca') || lower.includes('alug')) return <Key size={size} />;
    if (lower.includes('assist') || lower.includes('téc') || lower.includes('tec')) return <Wrench size={size} />;
    if (lower.includes('finan') || lower.includes('cobr')) return <CreditCard size={size} />;
    if (lower.includes('supor') || lower.includes('ajuda')) return <HelpCircle size={size} />;
    if (lower.includes('entrega') || lower.includes('logís')) return <Truck size={size} />;
    if (lower.includes('atend')) return <Headphones size={size} />;
    return <Building size={size} />;
  };

  const getUnreadCount = (numberId: number | 'all') => {
    return conversations.filter(c => {
      if (numberId !== 'all' && String(c.whatsapp_number_id) !== String(numberId)) return false;
      const extra = c.dados_adicionais || {};
      if (extra.marked_as_read) return false;
      const msgs = c.messages || [];
      if (msgs.length === 0) return false;

      let lastAttendantIdx = -1;
      for (let i = 0; i < msgs.length; i++) {
        const r = String(msgs[i].remetente || '').toLowerCase();
        if (r === 'atendente' || r === 'sistema' || r === 'ia' || r === 'bot') {
          lastAttendantIdx = i;
        }
      }

      for (let i = lastAttendantIdx + 1; i < msgs.length; i++) {
        const r = String(msgs[i].remetente || '').toLowerCase();
        if (r === 'cliente' && msgs[i].status !== 'read') {
          return true;
        }
      }
      return false;
    }).length;
  };

  const calendarPending = calendarSummary?.today_pending ?? 0;

  const tabBtnStyle = (isSelected: boolean): React.CSSProperties => ({
    display: 'flex',
    flexDirection: 'row',
    alignItems: 'center',
    justifyContent: 'center',
    gap: '6px',
    height: '34px',
    padding: '0 14px',
    borderRadius: '17px',
    border: isSelected
      ? '1.5px solid var(--accent-primary)'
      : '1px solid rgba(255, 255, 255, 0.10)',
    backgroundColor: isSelected
      ? 'rgba(0, 230, 153, 0.15)'
      : 'rgba(255, 255, 255, 0.04)',
    color: isSelected ? 'var(--accent-primary)' : 'var(--text-muted)',
    fontSize: '12px',
    fontWeight: isSelected ? '700' : '500',
    cursor: 'pointer',
    whiteSpace: 'nowrap',
    flexShrink: 0,
    boxShadow: isSelected ? '0 2px 10px rgba(0, 230, 153, 0.2)' : 'none',
    transition: 'all 0.15s ease',
    position: 'relative',
  });

  const desktopCardStyle = (isSelected: boolean): React.CSSProperties => ({
    width: '78px',
    height: '72px',
    borderRadius: '12px',
    border: isSelected
      ? '2px solid var(--accent-primary)'
      : '1px solid rgba(255, 255, 255, 0.08)',
    backgroundColor: isSelected
      ? 'rgba(0, 230, 153, 0.16)'
      : 'rgba(255, 255, 255, 0.03)',
    color: isSelected ? 'var(--accent-primary)' : '#94a3b8',
    display: 'flex',
    flexDirection: 'column',
    alignItems: 'center',
    justifyContent: 'center',
    gap: '6px',
    cursor: 'pointer',
    position: 'relative',
    transition: 'all 0.2s cubic-bezier(0.4, 0, 0.2, 1)',
    boxShadow: isSelected ? '0 4px 14px rgba(0, 230, 153, 0.25)' : 'none',
    flexShrink: 0,
  });

  return (
    <div
      className="dept-bar-outer"
      style={{
        width: '100%',
        backgroundColor: 'var(--bg-primary)',
        borderBottom: '1px solid var(--border-color)',
        padding: '8px 16px',
        display: 'flex',
        alignItems: 'center',
        gap: '10px',
        overflowX: 'auto',
        scrollbarWidth: 'thin',
      }}
    >
      {/* Mobile-only app icon with red (chat) / yellow (group) alert badge */}
      <div
        className="mobile-only-app-badge"
        style={{
          position: 'relative',
          display: 'none',
          alignItems: 'center',
          justifyContent: 'center',
          flexShrink: 0,
          marginRight: '2px'
        }}
        title={pendingBadgeCount > 0 ? `${pendingBadgeCount} conversa(s) de chat pendente(s)` : groupPendingBadgeCount > 0 ? `${groupPendingBadgeCount} grupo(s) com novas mensagens` : 'OminiChannel'}
      >
        <img
          src="/favicon.svg"
          alt="OminiChannel"
          style={{ width: '28px', height: '28px', borderRadius: '8px' }}
        />
        {(pendingBadgeCount > 0 || groupPendingBadgeCount > 0) && (
          <span
            style={{
              position: 'absolute',
              top: '-3px',
              right: '-4px',
              width: '12px',
              height: '12px',
              borderRadius: '50%',
              backgroundColor: pendingBadgeCount > 0 ? '#ef4444' : '#f59e0b',
              border: '2px solid var(--bg-primary)',
              boxShadow: `0 0 6px ${pendingBadgeCount > 0 ? 'rgba(239, 68, 68, 0.8)' : 'rgba(245, 158, 11, 0.8)'}`
            }}
          />
        )}
      </div>

      {/* "Departamentos:" label — hidden on mobile via CSS */}
      <div
        className="dept-bar-label"
        style={{
          fontSize: '11px',
          fontWeight: '700',
          color: 'var(--text-muted)',
          textTransform: 'uppercase',
          letterSpacing: '0.5px',
          marginRight: '4px',
          whiteSpace: 'nowrap',
        }}
      >
        Departamentos:
      </div>

      {/* "Todos" button — pill on mobile, card on desktop */}
      <button
        className="dept-bar-btn"
        onClick={() => onSelectDepartment('all')}
        style={desktopCardStyle(selectedDepartmentId === 'all')}
        onMouseEnter={(e) => {
          if (selectedDepartmentId !== 'all') {
            e.currentTarget.style.transform = 'translateY(-3px)';
            e.currentTarget.style.borderColor = 'var(--accent-primary)';
            e.currentTarget.style.backgroundColor = 'rgba(0, 230, 153, 0.08)';
            e.currentTarget.style.color = '#fff';
          }
        }}
        onMouseLeave={(e) => {
          if (selectedDepartmentId !== 'all') {
            e.currentTarget.style.transform = '';
            e.currentTarget.style.borderColor = 'rgba(255, 255, 255, 0.08)';
            e.currentTarget.style.backgroundColor = 'rgba(255, 255, 255, 0.03)';
            e.currentTarget.style.color = '#94a3b8';
          }
        }}
      >
        <LayoutGrid size={18} />
        <span style={{ fontSize: '11px', fontWeight: '600', textAlign: 'center', lineHeight: '1.1', maxWidth: '70px', overflow: 'hidden', textOverflow: 'ellipsis', whiteSpace: 'nowrap' }}>
          Todos
        </span>
      </button>

      {/* Department cards */}
      {whatsappNumbers.map(wn => {
        const isSelected = selectedDepartmentId === wn.id;
        const unread = getUnreadCount(wn.id);
        const shortName = wn.nome_departamento.split(' ')[0]; // first word for mobile

        return (
          <button
            key={wn.id}
            className="dept-bar-btn"
            onClick={() => onSelectDepartment(wn.id)}
            style={desktopCardStyle(isSelected)}
            onMouseEnter={(e) => {
              if (!isSelected) {
                e.currentTarget.style.transform = 'translateY(-3px)';
                e.currentTarget.style.borderColor = 'var(--accent-primary)';
                e.currentTarget.style.backgroundColor = 'rgba(0, 230, 153, 0.08)';
                e.currentTarget.style.color = '#fff';
              }
            }}
            onMouseLeave={(e) => {
              if (!isSelected) {
                e.currentTarget.style.transform = '';
                e.currentTarget.style.borderColor = 'rgba(255, 255, 255, 0.08)';
                e.currentTarget.style.backgroundColor = 'rgba(255, 255, 255, 0.03)';
                e.currentTarget.style.color = '#94a3b8';
              }
            }}
          >
            {getDepartmentIcon(wn.nome_departamento, 18)}
            <span style={{ fontSize: '11px', fontWeight: '600', textAlign: 'center', lineHeight: '1.1', maxWidth: '70px', overflow: 'hidden', textOverflow: 'ellipsis', whiteSpace: 'nowrap' }}>
              {wn.nome_departamento}
            </span>
            {unread > 0 && (
              <span style={{
                position: 'absolute',
                top: '4px',
                right: '4px',
                backgroundColor: '#ef4444',
                color: '#fff',
                borderRadius: '10px',
                fontSize: '9px',
                fontWeight: '800',
                minWidth: '16px',
                height: '16px',
                display: 'flex',
                alignItems: 'center',
                justifyContent: 'center',
                padding: '0 3px',
              }}>
                {unread > 99 ? '99+' : unread}
              </span>
            )}
          </button>
        );
      })}

      {/* Spacer */}
      <div style={{ flex: 1 }} />

      {/* Calendar / Agenda button */}
      {onOpenCalendar && (
        <button
          className="calendar-btn-mobile"
          onClick={onOpenCalendar}
          title="Abrir Agenda & Tarefas"
          style={{
            height: '72px',
            padding: '0 16px',
            borderRadius: '12px',
            border: '1px solid rgba(16, 185, 129, 0.3)',
            backgroundColor: 'rgba(16, 185, 129, 0.08)',
            color: 'var(--accent-primary)',
            display: 'flex',
            alignItems: 'center',
            gap: '12px',
            cursor: 'pointer',
            position: 'relative',
            transition: 'all 0.2s cubic-bezier(0.4, 0, 0.2, 1)',
            boxShadow: '0 4px 14px rgba(0, 0, 0, 0.2)',
            flexShrink: 0,
          }}
          onMouseEnter={(e) => {
            e.currentTarget.style.transform = 'translateY(-2px)';
            e.currentTarget.style.borderColor = 'var(--accent-primary)';
            e.currentTarget.style.backgroundColor = 'rgba(16, 185, 129, 0.16)';
          }}
          onMouseLeave={(e) => {
            e.currentTarget.style.transform = '';
            e.currentTarget.style.borderColor = 'rgba(16, 185, 129, 0.3)';
            e.currentTarget.style.backgroundColor = 'rgba(16, 185, 129, 0.08)';
          }}
        >
          <div style={{
            width: '36px',
            height: '36px',
            borderRadius: '10px',
            backgroundColor: 'rgba(16, 185, 129, 0.2)',
            display: 'flex',
            alignItems: 'center',
            justifyContent: 'center',
            color: 'var(--accent-primary)',
            flexShrink: 0,
          }}>
            <Calendar size={20} />
          </div>

          {/* Text — hidden on mobile via CSS class */}
          <div className="calendar-btn-text" style={{ display: 'flex', flexDirection: 'column', alignItems: 'flex-start', textAlign: 'left' }}>
            <span style={{ fontSize: '13px', fontWeight: 'bold', color: '#fff' }}>
              Minha Agenda
            </span>
            <span style={{ fontSize: '11px', color: 'var(--text-muted)' }}>
              {calendarPending > 0 ? `${calendarPending} pendente(s) hoje` : 'Tarefas & Lembretes'}
            </span>
          </div>

          {calendarPending > 0 && (
            <span style={{
              backgroundColor: 'rgba(0, 230, 153, 0.2)',
              color: 'var(--accent-primary)',
              border: '1px solid rgba(0, 230, 153, 0.4)',
              fontSize: '11px',
              fontWeight: 'bold',
              borderRadius: '12px',
              padding: '2px 8px',
            }}>
              {calendarPending}
            </span>
          )}
        </button>
      )}
    </div>
  );
};
