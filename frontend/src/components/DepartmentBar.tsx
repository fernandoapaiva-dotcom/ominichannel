import React from 'react';
import {
  LayoutGrid, ShoppingBag, Key, Wrench, CreditCard,
  MessageSquare, Building, Headphones, Truck, HelpCircle, Layers
} from 'lucide-react';
import { WhatsAppNumber, Conversation } from '../types';

interface DepartmentBarProps {
  whatsappNumbers: WhatsAppNumber[];
  selectedDepartmentId: number | 'all';
  onSelectDepartment: (id: number | 'all') => void;
  conversations: Conversation[];
}

export const DepartmentBar: React.FC<DepartmentBarProps> = ({
  whatsappNumbers,
  selectedDepartmentId,
  onSelectDepartment,
  conversations
}) => {

  // Helper to pick context icon based on department name
  const getDepartmentIcon = (name: string) => {
    const lower = name.toLowerCase();
    if (lower.includes('todos') || lower.includes('geral')) return <LayoutGrid size={22} />;
    if (lower.includes('venda') || lower.includes('e-commerce') || lower.includes('comercial')) return <ShoppingBag size={22} />;
    if (lower.includes('loca') || lower.includes('alug')) return <Key size={22} />;
    if (lower.includes('assist') || lower.includes('téc') || lower.includes('tec')) return <Wrench size={22} />;
    if (lower.includes('finan') || lower.includes('cobr')) return <CreditCard size={22} />;
    if (lower.includes('supor') || lower.includes('ajuda')) return <HelpCircle size={22} />;
    if (lower.includes('entrega') || lower.includes('logís')) return <Truck size={22} />;
    if (lower.includes('atend')) return <Headphones size={22} />;
    return <Building size={22} />;
  };

  // Helper to compute unread messages count per department
  const getUnreadCount = (numberId: number | 'all') => {
    return conversations.filter(c => {
      if (numberId !== 'all' && c.whatsapp_number_id !== numberId) return false;
      const lastMsg = c.messages[c.messages.length - 1];
      return lastMsg && lastMsg.remetente.toLowerCase() === 'cliente';
    }).length;
  };

  const totalUnread = getUnreadCount('all');

  return (
    <div style={{
      width: '100%',
      backgroundColor: 'var(--bg-primary)',
      borderBottom: '1px solid var(--border-color)',
      padding: '10px 16px',
      display: 'flex',
      alignItems: 'center',
      gap: '12px',
      overflowX: 'auto',
      scrollbarWidth: 'thin'
    }}>
      <div style={{ fontSize: '11px', fontWeight: '700', color: 'var(--text-muted)', textTransform: 'uppercase', letterSpacing: '0.5px', marginRight: '4px', whiteSpace: 'nowrap' }}>
        Departamentos:
      </div>

      {/* Module Card for "Todos Dptos" */}
      <button
        onClick={() => onSelectDepartment('all')}
        style={{
          width: '78px',
          height: '72px',
          borderRadius: '12px',
          border: selectedDepartmentId === 'all'
            ? '2px solid var(--accent-primary)'
            : '1px solid rgba(255, 255, 255, 0.08)',
          backgroundColor: selectedDepartmentId === 'all'
            ? 'rgba(0, 230, 153, 0.16)'
            : 'rgba(255, 255, 255, 0.03)',
          color: selectedDepartmentId === 'all' ? 'var(--accent-primary)' : '#94a3b8',
          display: 'flex',
          flexDirection: 'column',
          alignItems: 'center',
          justifyContent: 'center',
          gap: '6px',
          cursor: 'pointer',
          position: 'relative',
          transition: 'all 0.2s cubic-bezier(0.4, 0, 0.2, 1)',
          boxShadow: selectedDepartmentId === 'all'
            ? '0 4px 14px rgba(0, 230, 153, 0.25)'
            : 'none',
          flexShrink: 0
        }}
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
            e.currentTarget.style.transform = 'translateY(0)';
            e.currentTarget.style.borderColor = 'rgba(255, 255, 255, 0.08)';
            e.currentTarget.style.backgroundColor = 'rgba(255, 255, 255, 0.03)';
            e.currentTarget.style.color = '#94a3b8';
          }
        }}
      >
        {totalUnread > 0 && (
          <span style={{
            position: 'absolute',
            top: '4px',
            right: '4px',
            backgroundColor: '#ef4444',
            color: '#fff',
            fontSize: '10px',
            fontWeight: 'bold',
            borderRadius: '10px',
            padding: '1px 5px',
            lineHeight: '1.2'
          }}>
            {totalUnread}
          </span>
        )}
        <div style={{ transition: 'transform 0.2s' }}>
          <LayoutGrid size={22} />
        </div>
        <span style={{ fontSize: '11px', fontWeight: '600', textAlign: 'center', lineHeight: '1.1', maxWidth: '70px', overflow: 'hidden', textOverflow: 'ellipsis', whiteSpace: 'nowrap' }}>
          Todos
        </span>
      </button>

      {/* Module Cards for each Department */}
      {whatsappNumbers.map(wn => {
        const isSelected = selectedDepartmentId === wn.id;
        const deptUnread = getUnreadCount(wn.id);
        const icon = getDepartmentIcon(wn.nome_departamento);

        return (
          <button
            key={wn.id}
            onClick={() => onSelectDepartment(wn.id)}
            style={{
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
              boxShadow: isSelected
                ? '0 4px 14px rgba(0, 230, 153, 0.25)'
                : 'none',
              flexShrink: 0
            }}
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
                e.currentTarget.style.transform = 'translateY(0)';
                e.currentTarget.style.borderColor = 'rgba(255, 255, 255, 0.08)';
                e.currentTarget.style.backgroundColor = 'rgba(255, 255, 255, 0.03)';
                e.currentTarget.style.color = '#94a3b8';
              }
            }}
          >
            {deptUnread > 0 && (
              <span style={{
                position: 'absolute',
                top: '4px',
                right: '4px',
                backgroundColor: '#ef4444',
                color: '#fff',
                fontSize: '10px',
                fontWeight: 'bold',
                borderRadius: '10px',
                padding: '1px 5px',
                lineHeight: '1.2'
              }}>
                {deptUnread}
              </span>
            )}
            <div style={{ transition: 'transform 0.2s' }}>
              {icon}
            </div>
            <span style={{ fontSize: '11px', fontWeight: '600', textAlign: 'center', lineHeight: '1.1', maxWidth: '70px', overflow: 'hidden', textOverflow: 'ellipsis', whiteSpace: 'nowrap' }}>
              {wn.nome_departamento}
            </span>
          </button>
        );
      })}
    </div>
  );
};
