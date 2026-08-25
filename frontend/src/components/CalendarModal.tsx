import React, { useState, useEffect, useMemo } from 'react';
import {
  X, Calendar as CalendarIcon, ChevronLeft, ChevronRight, Plus, Check, Clock,
  AlertCircle, AlertTriangle, User, Phone, MessageSquare, Trash2, Edit3,
  Search, Filter, CheckCircle2, Circle, MoreVertical, ExternalLink, Tag,
  Truck, Wrench, Users, Bell, CheckSquare, ShieldCheck
} from 'lucide-react';
import { apiFetch } from '../services/api';
import { CalendarEvent, User as UserType, AuthorizedTechnician } from '../types';

interface CalendarModalProps {
  isOpen: boolean;
  onClose: () => void;
  currentUser: UserType;
  initialEventData?: Partial<CalendarEvent> | null;
  onSelectConversation?: (conversationId: number) => void;
}

const GOOGLE_COLORS = [
  { name: 'Esmeralda', hex: '#10b981' },
  { name: 'Azul', hex: '#3b82f6' },
  { name: 'Roxo', hex: '#8b5cf6' },
  { name: 'Âmbar', hex: '#f59e0b' },
  { name: 'Vermelho', hex: '#ef4444' },
  { name: 'Rosa', hex: '#ec4899' },
  { name: 'Ciano', hex: '#06b6d4' },
  { name: 'Grafite', hex: '#6b7280' },
];

const MONTH_NAMES = [
  'Janeiro', 'Fevereiro', 'Março', 'Abril', 'Maio', 'Junho',
  'Julho', 'Agosto', 'Setembro', 'Outubro', 'Novembro', 'Dezembro'
];

const WEEKDAYS = ['Dom', 'Seg', 'Ter', 'Qua', 'Qui', 'Sex', 'Sáb'];

export const CalendarModal: React.FC<CalendarModalProps> = ({
  isOpen,
  onClose,
  currentUser,
  initialEventData,
  onSelectConversation
}) => {
  const [currentDate, setCurrentDate] = useState<Date>(new Date());
  const [viewMode, setViewMode] = useState<'month' | 'week' | 'day' | 'agenda'>('month');
  const [events, setEvents] = useState<CalendarEvent[]>([]);
  const [employees, setEmployees] = useState<AuthorizedTechnician[]>([]);
  const [loading, setLoading] = useState<boolean>(false);
  const [searchTerm, setSearchTerm] = useState<string>('');
  const [statusFilter, setStatusFilter] = useState<'all' | 'pendente' | 'concluido'>('all');
  const [priorityFilter, setPriorityFilter] = useState<'all' | 'baixa' | 'media' | 'alta' | 'urgente'>('all');

  // Form Modal State (New / Edit)
  const [isFormOpen, setIsFormOpen] = useState<boolean>(false);
  const [editingEvent, setEditingEvent] = useState<CalendarEvent | null>(null);
  const [formTitle, setFormTitle] = useState<string>('');
  const [formDescription, setFormDescription] = useState<string>('');
  const [formEventType, setFormEventType] = useState<string>('geral');
  const [formStartDate, setFormStartDate] = useState<string>('');
  const [formStartTime, setFormStartTime] = useState<string>('09:00');
  const [formEndDate, setFormEndDate] = useState<string>('');
  const [formEndTime, setFormEndTime] = useState<string>('10:00');
  const [formAllDay, setFormAllDay] = useState<boolean>(false);
  const [formColor, setFormColor] = useState<string>('#10b981');
  const [formPriority, setFormPriority] = useState<'baixa' | 'media' | 'alta' | 'urgente'>('media');
  const [formStatus, setFormStatus] = useState<'pendente' | 'em_progresso' | 'concluido' | 'cancelado'>('pendente');
  const [formReminder, setFormReminder] = useState<number | null>(30);
  const [formContactId, setFormContactId] = useState<number | null>(null);
  const [formConversationId, setFormConversationId] = useState<number | null>(null);
  const [formContactName, setFormContactName] = useState<string | null>(null);
  const [formContactPhone, setFormContactPhone] = useState<string | null>(null);
  
  // Store Employee & WhatsApp Reminders
  const [formEmployeeId, setFormEmployeeId] = useState<number | ''>('');
  const [formEmployeeName, setFormEmployeeName] = useState<string>('');
  const [formEmployeePhone, setFormEmployeePhone] = useState<string>('');
  const [formNotifyWhatsApp, setFormNotifyWhatsApp] = useState<boolean>(true);
  const [formCustomReminderHours, setFormCustomReminderHours] = useState<number>(2);
  const [formConfirmedByEmployee, setFormConfirmedByEmployee] = useState<boolean>(false);
  const [isSaving, setIsSaving] = useState<boolean>(false);

  // Load events and employees
  const fetchEvents = async () => {
    try {
      setLoading(true);
      const [eventsData, empData] = await Promise.all([
        apiFetch('/calendar/events'),
        apiFetch('/technicians/')
      ]);
      setEvents(eventsData || []);
      setEmployees(empData || []);
    } catch (err) {
      console.error('Error fetching calendar events or employees:', err);
    } finally {
      setLoading(false);
    }
  };

  useEffect(() => {
    if (isOpen) {
      fetchEvents();
    }
  }, [isOpen]);

  // Handle incoming initialEventData (e.g. from WhatsApp message context menu)
  useEffect(() => {
    if (initialEventData && isOpen) {
      openNewEventModal(initialEventData);
    }
  }, [initialEventData, isOpen]);

  const openNewEventModal = (prefill?: Partial<CalendarEvent>, selectedDay?: Date) => {
    setEditingEvent(null);
    const targetDate = selectedDay || new Date();
    const dateStr = targetDate.toISOString().split('T')[0];

    const now = new Date();
    const nextHour = new Date(now.getTime() + 60 * 60 * 1000);
    const startTimeStr = `${String(now.getHours()).padStart(2, '0')}:00`;
    const endTimeStr = `${String(nextHour.getHours()).padStart(2, '0')}:00`;

    setFormTitle(prefill?.title || '');
    setFormDescription(prefill?.description || '');
    setFormEventType(prefill?.event_type || 'geral');
    setFormStartDate(dateStr);
    setFormStartTime(prefill?.start_time ? prefill.start_time.split('T')[1]?.substring(0, 5) || startTimeStr : startTimeStr);
    setFormEndDate(dateStr);
    setFormEndTime(endTimeStr);
    setFormAllDay(prefill?.all_day || false);
    setFormColor(prefill?.color || '#10b981');
    setFormPriority(prefill?.priority || 'media');
    setFormStatus(prefill?.status || 'pendente');
    setFormReminder(prefill?.reminder_minutes ?? 30);
    setFormContactId(prefill?.contact_id || null);
    setFormConversationId(prefill?.conversation_id || null);
    setFormContactName(prefill?.contact_name || null);
    setFormContactPhone(prefill?.contact_phone || null);

    setFormEmployeeId(prefill?.employee_id || '');
    setFormEmployeeName(prefill?.employee_name || '');
    setFormEmployeePhone(prefill?.employee_phone || '');
    setFormNotifyWhatsApp(prefill?.notify_whatsapp ?? true);
    setFormCustomReminderHours(prefill?.custom_reminder_hours || 2);
    setFormConfirmedByEmployee(prefill?.confirmed_by_employee || false);

    setIsFormOpen(true);
  };

  const openEditEventModal = (event: CalendarEvent) => {
    setEditingEvent(event);
    const startDt = new Date(event.start_time);
    const endDt = event.end_time ? new Date(event.end_time) : startDt;

    setFormTitle(event.title);
    setFormDescription(event.description || '');
    setFormEventType(event.event_type || 'geral');
    setFormStartDate(startDt.toISOString().split('T')[0]);
    setFormStartTime(`${String(startDt.getHours()).padStart(2, '0')}:${String(startDt.getMinutes()).padStart(2, '0')}`);
    setFormEndDate(endDt.toISOString().split('T')[0]);
    setFormEndTime(`${String(endDt.getHours()).padStart(2, '0')}:${String(endDt.getMinutes()).padStart(2, '0')}`);
    setFormAllDay(event.all_day);
    setFormColor(event.color || '#10b981');
    setFormPriority(event.priority);
    setFormStatus(event.status);
    setFormReminder(event.reminder_minutes ?? null);
    setFormContactId(event.contact_id || null);
    setFormConversationId(event.conversation_id || null);
    setFormContactName(event.contact_name || null);
    setFormContactPhone(event.contact_phone || null);

    setFormEmployeeId(event.employee_id || '');
    setFormEmployeeName(event.employee_name || '');
    setFormEmployeePhone(event.employee_phone || '');
    setFormNotifyWhatsApp(event.notify_whatsapp ?? true);
    setFormCustomReminderHours(event.custom_reminder_hours || 2);
    setFormConfirmedByEmployee(event.confirmed_by_employee || false);

    setIsFormOpen(true);
  };

  const handleSaveEvent = async (e: React.FormEvent) => {
    e.preventDefault();
    if (!formTitle.trim()) return;

    try {
      setIsSaving(true);
      const startDateTimeStr = formAllDay
        ? `${formStartDate}T00:00:00`
        : `${formStartDate}T${formStartTime}:00`;
      const endDateTimeStr = formAllDay
        ? `${formEndDate || formStartDate}T23:59:59`
        : `${formEndDate || formStartDate}T${formEndTime}:00`;

      const payload = {
        title: formTitle.trim(),
        description: formDescription.trim() || null,
        event_type: formEventType,
        start_time: new Date(startDateTimeStr).toISOString(),
        end_time: new Date(endDateTimeStr).toISOString(),
        all_day: formAllDay,
        color: formColor,
        priority: formPriority,
        status: formStatus,
        reminder_minutes: formReminder,
        contact_id: formContactId,
        conversation_id: formConversationId,
        employee_id: formEmployeeId ? Number(formEmployeeId) : null,
        employee_name: formEmployeeName || null,
        employee_phone: formEmployeePhone || null,
        notify_whatsapp: formNotifyWhatsApp,
        custom_reminder_hours: formCustomReminderHours,
        confirmed_by_employee: formConfirmedByEmployee
      };

      if (editingEvent) {
        const updated = await apiFetch(`/calendar/events/${editingEvent.id}`, {
          method: 'PUT',
          body: JSON.stringify(payload)
        });
        setEvents(prev => prev.map(ev => ev.id === editingEvent.id ? updated : ev));
      } else {
        const created = await apiFetch('/calendar/events', {
          method: 'POST',
          body: JSON.stringify(payload)
        });
        setEvents(prev => [...prev, created]);
      }
      setIsFormOpen(false);
    } catch (err) {
      console.error('Error saving calendar event:', err);
      alert('Erro ao salvar evento. Verifique os dados e tente novamente.');
    } finally {
      setIsSaving(false);
    }
  };

  const handleToggleEmployeeConfirmation = async (event: CalendarEvent, e?: React.MouseEvent) => {
    if (e) e.stopPropagation();
    try {
      const updated = await apiFetch(`/calendar/events/${event.id}/confirm_employee`, { method: 'POST' });
      setEvents(prev => prev.map(ev => ev.id === event.id ? updated : ev));
    } catch (err) {
      console.error('Error toggling employee confirmation:', err);
    }
  };

  const handleDeleteEvent = async (eventId: number) => {
    if (!confirm('Deseja realmente excluir esta tarefa do seu calendário?')) return;
    try {
      await apiFetch(`/calendar/events/${eventId}`, { method: 'DELETE' });
      setEvents(prev => prev.filter(ev => ev.id !== eventId));
      if (editingEvent?.id === eventId) {
        setIsFormOpen(false);
      }
    } catch (err) {
      console.error('Error deleting event:', err);
    }
  };

  const handleToggleStatus = async (event: CalendarEvent, e?: React.MouseEvent) => {
    if (e) e.stopPropagation();
    try {
      const updated = await apiFetch(`/calendar/events/${event.id}/toggle`, { method: 'PATCH' });
      setEvents(prev => prev.map(ev => ev.id === event.id ? updated : ev));
    } catch (err) {
      console.error('Error toggling status:', err);
    }
  };

  // Date Navigation Helpers
  const handlePrev = () => {
    setCurrentDate(prev => {
      const d = new Date(prev);
      if (viewMode === 'month') d.setMonth(d.getMonth() - 1);
      else if (viewMode === 'week') d.setDate(d.getDate() - 7);
      else if (viewMode === 'day') d.setDate(d.getDate() - 1);
      return d;
    });
  };

  const handleNext = () => {
    setCurrentDate(prev => {
      const d = new Date(prev);
      if (viewMode === 'month') d.setMonth(d.getMonth() + 1);
      else if (viewMode === 'week') d.setDate(d.getDate() + 7);
      else if (viewMode === 'day') d.setDate(d.getDate() + 1);
      return d;
    });
  };

  const handleToday = () => {
    setCurrentDate(new Date());
  };

  // Filtered events
  const filteredEvents = useMemo(() => {
    return events.filter(ev => {
      if (statusFilter !== 'all') {
        if (statusFilter === 'concluido' && ev.status !== 'concluido') return false;
        if (statusFilter === 'pendente' && ev.status === 'concluido') return false;
      }
      if (priorityFilter !== 'all' && ev.priority !== priorityFilter) return false;
      if (searchTerm.trim()) {
        const q = searchTerm.toLowerCase();
        const matchesTitle = ev.title.toLowerCase().includes(q);
        const matchesDesc = ev.description?.toLowerCase().includes(q);
        const matchesContact = ev.contact_name?.toLowerCase().includes(q) || ev.contact_phone?.includes(q);
        if (!matchesTitle && !matchesDesc && !matchesContact) return false;
      }
      return true;
    });
  }, [events, statusFilter, priorityFilter, searchTerm]);

  // Month Matrix Calculation
  const monthDays = useMemo(() => {
    const year = currentDate.getFullYear();
    const month = currentDate.getMonth();

    const firstDayIndex = new Date(year, month, 1).getDay();
    const totalDaysInMonth = new Date(year, month + 1, 0).getDate();
    const prevMonthDays = new Date(year, month, 0).getDate();

    const days: { date: Date; isCurrentMonth: boolean; dateStr: string }[] = [];

    // Prev month padding
    for (let i = firstDayIndex - 1; i >= 0; i--) {
      const d = new Date(year, month - 1, prevMonthDays - i);
      days.push({ date: d, isCurrentMonth: false, dateStr: d.toISOString().split('T')[0] });
    }

    // Current month days
    for (let i = 1; i <= totalDaysInMonth; i++) {
      const d = new Date(year, month, i);
      days.push({ date: d, isCurrentMonth: true, dateStr: d.toISOString().split('T')[0] });
    }

    // Next month padding to fill 35 or 42 grid cells
    const remaining = (7 - (days.length % 7)) % 7;
    for (let i = 1; i <= remaining; i++) {
      const d = new Date(year, month + 1, i);
      days.push({ date: d, isCurrentMonth: false, dateStr: d.toISOString().split('T')[0] });
    }

    return days;
  }, [currentDate]);

  const HOURS_24 = useMemo(() => Array.from({ length: 24 }, (_, i) => i), []);

  const todayStr = useMemo(() => new Date().toISOString().split('T')[0], []);

  const weekDays = useMemo(() => {
    const startOfWeek = new Date(currentDate);
    const day = startOfWeek.getDay(); // 0 is Sunday
    startOfWeek.setDate(startOfWeek.getDate() - day);

    return Array.from({ length: 7 }, (_, i) => {
      const d = new Date(startOfWeek);
      d.setDate(d.getDate() + i);
      const dateStr = d.toISOString().split('T')[0];
      return {
        date: d,
        dateStr,
        dayName: WEEKDAYS[d.getDay()],
        dayNum: d.getDate(),
        isToday: dateStr === todayStr
      };
    });
  }, [currentDate, todayStr]);

  const handleDropOnDate = async (eventId: number, newDateStr: string, newHour?: number) => {
    const ev = events.find(e => e.id === eventId);
    if (!ev) return;

    try {
      const origStart = new Date(ev.start_time);
      const origEnd = ev.end_time ? new Date(ev.end_time) : origStart;
      const durationMs = Math.max(30 * 60 * 1000, origEnd.getTime() - origStart.getTime());

      let newStartDt: Date;
      if (newHour !== undefined) {
        newStartDt = new Date(`${newDateStr}T${String(newHour).padStart(2, '0')}:00:00`);
      } else {
        const timePart = ev.start_time.split('T')[1] || '09:00:00';
        newStartDt = new Date(`${newDateStr}T${timePart}`);
      }

      const newEndDt = new Date(newStartDt.getTime() + durationMs);

      const payload = {
        title: ev.title,
        description: ev.description,
        event_type: ev.event_type,
        start_time: newStartDt.toISOString(),
        end_time: newEndDt.toISOString(),
        all_day: ev.all_day,
        color: ev.color,
        priority: ev.priority,
        status: ev.status,
        reminder_minutes: ev.reminder_minutes,
        contact_id: ev.contact_id,
        conversation_id: ev.conversation_id,
        employee_id: ev.employee_id,
        employee_name: ev.employee_name,
        employee_phone: ev.employee_phone,
        notify_whatsapp: ev.notify_whatsapp,
        custom_reminder_hours: ev.custom_reminder_hours,
        confirmed_by_employee: ev.confirmed_by_employee
      };

      // Optimistic update
      const updatedOptimistic: CalendarEvent = {
        ...ev,
        start_time: newStartDt.toISOString(),
        end_time: newEndDt.toISOString()
      };
      setEvents(prev => prev.map(e => e.id === eventId ? updatedOptimistic : e));

      const updated = await apiFetch(`/calendar/events/${eventId}`, {
        method: 'PUT',
        body: JSON.stringify(payload)
      });
      setEvents(prev => prev.map(e => e.id === eventId ? updated : e));
    } catch (err) {
      console.error('Error rescheduling dragged event:', err);
    }
  };

  if (!isOpen) return null;

  return (
    <div style={{
      position: 'fixed',
      inset: 0,
      backgroundColor: 'rgba(0, 0, 0, 0.85)',
      backdropFilter: 'blur(6px)',
      zIndex: 999,
      display: 'flex',
      alignItems: 'center',
      justifyContent: 'center',
      padding: '16px'
    }}>
      <div style={{
        backgroundColor: 'var(--bg-secondary)',
        border: '1px solid var(--border-color)',
        borderRadius: '16px',
        width: '95vw',
        maxWidth: '1350px',
        height: '92vh',
        display: 'flex',
        flexDirection: 'column',
        boxShadow: '0 24px 60px rgba(0,0,0,0.8)',
        overflow: 'hidden'
      }}>
        {/* Top Header / Google Calendar Navigation */}
        <div style={{
          padding: '14px 24px',
          borderBottom: '1px solid var(--border-color)',
          display: 'flex',
          alignItems: 'center',
          justifyContent: 'space-between',
          flexWrap: 'wrap',
          gap: '16px',
          backgroundColor: 'var(--bg-primary)'
        }}>
          <div style={{ display: 'flex', alignItems: 'center', gap: '16px' }}>
            <div style={{
              display: 'flex',
              alignItems: 'center',
              gap: '10px',
              color: 'var(--accent-primary)',
              fontWeight: 'bold',
              fontSize: '18px'
            }}>
              <CalendarIcon size={24} />
              <span>Agenda de Tarefas</span>
            </div>

            <div style={{ display: 'flex', alignItems: 'center', gap: '6px' }}>
              <button
                type="button"
                onClick={handleToday}
                style={{
                  padding: '6px 14px',
                  borderRadius: '20px',
                  border: '1px solid var(--border-color)',
                  backgroundColor: 'var(--bg-secondary)',
                  color: 'var(--text-main)',
                  cursor: 'pointer',
                  fontSize: '13px',
                  fontWeight: '600'
                }}
              >
                Hoje
              </button>

              <button
                type="button"
                onClick={handlePrev}
                style={{
                  padding: '6px',
                  borderRadius: '50%',
                  border: '1px solid var(--border-color)',
                  backgroundColor: 'var(--bg-secondary)',
                  color: 'var(--text-main)',
                  cursor: 'pointer',
                  display: 'flex',
                  alignItems: 'center',
                  justifyContent: 'center'
                }}
              >
                <ChevronLeft size={18} />
              </button>

              <button
                type="button"
                onClick={handleNext}
                style={{
                  padding: '6px',
                  borderRadius: '50%',
                  border: '1px solid var(--border-color)',
                  backgroundColor: 'var(--bg-secondary)',
                  color: 'var(--text-main)',
                  cursor: 'pointer',
                  display: 'flex',
                  alignItems: 'center',
                  justifyContent: 'center'
                }}
              >
                <ChevronRight size={18} />
              </button>
            </div>

            <h2 style={{ fontSize: '19px', fontWeight: '700', color: '#fff', margin: 0, minWidth: '200px' }}>
              {MONTH_NAMES[currentDate.getMonth()]} de {currentDate.getFullYear()}
            </h2>
          </div>

          {/* Right Controls: Search, View Switchers, New Event Button & Close */}
          <div style={{ display: 'flex', alignItems: 'center', gap: '12px' }}>
            {/* Search Input */}
            <div style={{
              display: 'flex',
              alignItems: 'center',
              gap: '6px',
              backgroundColor: 'var(--bg-secondary)',
              border: '1px solid var(--border-color)',
              borderRadius: '20px',
              padding: '6px 12px',
              width: '200px'
            }}>
              <Search size={15} color="var(--text-muted)" />
              <input
                type="text"
                placeholder="Buscar tarefas..."
                value={searchTerm}
                onChange={e => setSearchTerm(e.target.value)}
                style={{
                  background: 'none',
                  border: 'none',
                  outline: 'none',
                  color: '#fff',
                  fontSize: '13px',
                  width: '100%'
                }}
              />
              {searchTerm && (
                <button
                  type="button"
                  onClick={() => setSearchTerm('')}
                  style={{ background: 'none', border: 'none', color: 'var(--text-muted)', cursor: 'pointer', padding: 0 }}
                >
                  <X size={14} />
                </button>
              )}
            </div>

            {/* View Mode Buttons */}
            <div style={{
              display: 'flex',
              backgroundColor: 'var(--bg-secondary)',
              borderRadius: '20px',
              border: '1px solid var(--border-color)',
              padding: '2px'
            }}>
              {(['month', 'week', 'day', 'agenda'] as const).map(mode => (
                <button
                  key={mode}
                  type="button"
                  onClick={() => setViewMode(mode)}
                  style={{
                    padding: '6px 14px',
                    borderRadius: '16px',
                    border: 'none',
                    backgroundColor: viewMode === mode ? 'var(--accent-primary)' : 'transparent',
                    color: viewMode === mode ? '#fff' : 'var(--text-muted)',
                    cursor: 'pointer',
                    fontSize: '12px',
                    fontWeight: viewMode === mode ? 'bold' : 'normal',
                    textTransform: 'capitalize',
                    transition: 'all 0.15s'
                  }}
                >
                  {mode === 'month' ? 'Mês' : mode === 'week' ? 'Semana' : mode === 'day' ? 'Dia' : 'Lista'}
                </button>
              ))}
            </div>

            {/* Status Filter */}
            <select
              value={statusFilter}
              onChange={e => setStatusFilter(e.target.value as any)}
              style={{
                backgroundColor: 'var(--bg-secondary)',
                border: '1px solid var(--border-color)',
                color: 'var(--text-main)',
                padding: '6px 10px',
                borderRadius: '8px',
                fontSize: '12px',
                outline: 'none',
                cursor: 'pointer'
              }}
            >
              <option value="all">Todas as Tarefas</option>
              <option value="pendente">⏳ Pendentes</option>
              <option value="concluido">✅ Concluídas</option>
            </select>

            {/* New Event Button */}
            <button
              type="button"
              onClick={() => openNewEventModal()}
              style={{
                display: 'flex',
                alignItems: 'center',
                gap: '6px',
                backgroundColor: 'var(--accent-primary)',
                color: '#fff',
                border: 'none',
                padding: '8px 16px',
                borderRadius: '20px',
                fontWeight: 'bold',
                fontSize: '13px',
                cursor: 'pointer',
                boxShadow: '0 4px 14px rgba(16, 185, 129, 0.35)',
                transition: 'transform 0.15s ease'
              }}
              onMouseEnter={e => (e.currentTarget.style.transform = 'scale(1.03)')}
              onMouseLeave={e => (e.currentTarget.style.transform = 'scale(1)')}
            >
              <Plus size={16} /> Novo Evento / Tarefa
            </button>

            {/* Close Modal Button */}
            <button
              type="button"
              onClick={onClose}
              style={{
                background: 'none',
                border: 'none',
                color: 'var(--text-muted)',
                cursor: 'pointer',
                padding: '6px',
                display: 'flex',
                alignItems: 'center',
                justifyContent: 'center'
              }}
              title="Fechar (Esc)"
            >
              <X size={24} />
            </button>
          </div>
        </div>

        {/* Calendar Body */}
        <div style={{ flex: 1, overflow: 'auto', display: 'flex', flexDirection: 'column' }}>
          {/* 1. MONTH VIEW */}
          {viewMode === 'month' && (
            <div style={{ display: 'flex', flexDirection: 'column', height: '100%', minHeight: '600px' }}>
              {/* Sticky Weekday Header */}
              <div style={{
                position: 'sticky',
                top: 0,
                zIndex: 10,
                display: 'grid',
                gridTemplateColumns: 'repeat(7, 1fr)',
                borderBottom: '1px solid var(--border-color)',
                backgroundColor: 'var(--bg-secondary)',
                backdropFilter: 'blur(10px)',
                boxShadow: '0 2px 8px rgba(0,0,0,0.3)'
              }}>
                {WEEKDAYS.map((day, idx) => (
                  <div
                    key={day}
                    style={{
                      padding: '12px 10px',
                      textAlign: 'center',
                      fontSize: '12px',
                      fontWeight: '700',
                      color: idx === 0 || idx === 6 ? 'var(--text-muted)' : 'var(--accent-primary)',
                      borderRight: idx < 6 ? '1px solid var(--border-color)' : 'none'
                    }}
                  >
                    {day.toUpperCase()}
                  </div>
                ))}
              </div>

              {/* Month Grid with Drag & Drop */}
              <div style={{
                display: 'grid',
                gridTemplateColumns: 'repeat(7, 1fr)',
                flex: 1,
                gridAutoRows: 'minmax(105px, 1fr)'
              }}>
                {monthDays.map((cell, idx) => {
                  const dayEvents = filteredEvents.filter(ev => {
                    const evDateStr = ev.start_time.split('T')[0];
                    return evDateStr === cell.dateStr;
                  });
                  const isToday = cell.dateStr === todayStr;

                  return (
                    <div
                      key={idx}
                      onClick={() => openNewEventModal(undefined, cell.date)}
                      onDragOver={(e) => {
                        e.preventDefault();
                        e.dataTransfer.dropEffect = 'move';
                        e.currentTarget.style.backgroundColor = 'rgba(16, 185, 129, 0.18)';
                      }}
                      onDragLeave={(e) => {
                        e.currentTarget.style.backgroundColor = isToday
                          ? 'rgba(16, 185, 129, 0.05)'
                          : cell.isCurrentMonth ? 'transparent' : 'rgba(0, 0, 0, 0.25)';
                      }}
                      onDrop={(e) => {
                        e.preventDefault();
                        e.currentTarget.style.backgroundColor = isToday
                          ? 'rgba(16, 185, 129, 0.05)'
                          : cell.isCurrentMonth ? 'transparent' : 'rgba(0, 0, 0, 0.25)';
                        const evId = Number(e.dataTransfer.getData('text/plain'));
                        if (evId) {
                          handleDropOnDate(evId, cell.dateStr);
                        }
                      }}
                      style={{
                        borderRight: (idx + 1) % 7 !== 0 ? '1px solid var(--border-color)' : 'none',
                        borderBottom: '1px solid var(--border-color)',
                        padding: '6px',
                        backgroundColor: isToday
                          ? 'rgba(16, 185, 129, 0.05)'
                          : cell.isCurrentMonth ? 'transparent' : 'rgba(0, 0, 0, 0.25)',
                        opacity: cell.isCurrentMonth ? 1 : 0.45,
                        display: 'flex',
                        flexDirection: 'column',
                        cursor: 'pointer',
                        transition: 'background 0.15s'
                      }}
                    >
                      {/* Day Number */}
                      <div style={{
                        display: 'flex',
                        justifyContent: 'space-between',
                        alignItems: 'center',
                        marginBottom: '4px'
                      }}>
                        <span style={{
                          fontSize: '13px',
                          fontWeight: isToday ? 'bold' : '500',
                          width: '24px',
                          height: '24px',
                          display: 'flex',
                          alignItems: 'center',
                          justifyContent: 'center',
                          borderRadius: '50%',
                          backgroundColor: isToday ? 'var(--accent-primary)' : 'transparent',
                          color: isToday ? '#fff' : 'var(--text-main)'
                        }}>
                          {cell.date.getDate()}
                        </span>

                        {dayEvents.length > 0 && (
                          <span style={{ fontSize: '11px', color: 'var(--text-muted)' }}>
                            {dayEvents.length} {dayEvents.length === 1 ? 'tarefa' : 'tarefas'}
                          </span>
                        )}
                      </div>

                      {/* Draggable Event Chips */}
                      <div style={{ display: 'flex', flexDirection: 'column', gap: '3px', overflowY: 'auto', flex: 1 }}>
                        {dayEvents.slice(0, 4).map(ev => {
                          const isDone = ev.status === 'concluido';
                          const timeStr = ev.all_day ? '' : ev.start_time.split('T')[1]?.substring(0, 5) || '';

                          return (
                            <div
                              key={ev.id}
                              draggable={true}
                              onDragStart={(e) => {
                                e.stopPropagation();
                                e.dataTransfer.setData('text/plain', String(ev.id));
                                e.dataTransfer.effectAllowed = 'move';
                              }}
                              onClick={e => {
                                e.stopPropagation();
                                openEditEventModal(ev);
                              }}
                              style={{
                                backgroundColor: isDone ? 'rgba(255, 255, 255, 0.05)' : (ev.color || '#10b981'),
                                color: isDone ? 'var(--text-muted)' : '#fff',
                                textDecoration: isDone ? 'line-through' : 'none',
                                borderRadius: '4px',
                                padding: '2px 6px',
                                fontSize: '11px',
                                fontWeight: '600',
                                display: 'flex',
                                alignItems: 'center',
                                gap: '4px',
                                cursor: 'grab',
                                opacity: isDone ? 0.65 : 0.95,
                                border: isDone ? '1px solid var(--border-color)' : 'none',
                                whiteSpace: 'nowrap',
                                overflow: 'hidden',
                                textOverflow: 'ellipsis',
                                transition: 'transform 0.1s ease'
                              }}
                              title={`${ev.title}${ev.contact_name ? ` (${ev.contact_name})` : ''} - Arraste para mover de dia`}
                            >
                              <button
                                type="button"
                                onClick={e => handleToggleStatus(ev, e)}
                                style={{
                                  background: 'none',
                                  border: 'none',
                                  padding: 0,
                                  color: 'inherit',
                                  cursor: 'pointer',
                                  display: 'flex',
                                  alignItems: 'center'
                                }}
                              >
                                {isDone ? <CheckCircle2 size={11} /> : <Circle size={11} />}
                              </button>
                              {timeStr && <span style={{ opacity: 0.85 }}>{timeStr}</span>}
                              <span style={{ overflow: 'hidden', textOverflow: 'ellipsis' }}>{ev.title}</span>
                            </div>
                          );
                        })}
                        {dayEvents.length > 4 && (
                          <div style={{ fontSize: '10px', color: 'var(--text-muted)', textAlign: 'center', fontWeight: 'bold' }}>
                            +{dayEvents.length - 4} mais
                          </div>
                        )}
                      </div>
                    </div>
                  );
                })}
              </div>
            </div>
          )}

          {/* 2. WEEK VIEW (24h Time Grid on Left + Sticky Weekdays Header + Drag & Drop) */}
          {viewMode === 'week' && (
            <div style={{ display: 'flex', flexDirection: 'column', height: '100%', minWidth: '850px' }}>
              {/* Sticky Top Header (Time label + 7 Days) */}
              <div style={{
                position: 'sticky',
                top: 0,
                zIndex: 20,
                display: 'grid',
                gridTemplateColumns: '70px repeat(7, 1fr)',
                borderBottom: '1px solid var(--border-color)',
                backgroundColor: 'var(--bg-secondary)',
                backdropFilter: 'blur(10px)',
                boxShadow: '0 2px 8px rgba(0,0,0,0.3)'
              }}>
                <div style={{
                  padding: '12px 8px',
                  textAlign: 'center',
                  fontSize: '11px',
                  fontWeight: '700',
                  color: 'var(--text-muted)',
                  borderRight: '1px solid var(--border-color)',
                  display: 'flex',
                  alignItems: 'center',
                  justifyContent: 'center',
                  gap: '4px'
                }}>
                  <Clock size={12} /> 24 HORAS
                </div>
                {weekDays.map((d, idx) => (
                  <div
                    key={d.dateStr}
                    style={{
                      padding: '10px',
                      textAlign: 'center',
                      borderRight: idx < 6 ? '1px solid var(--border-color)' : 'none',
                      backgroundColor: d.isToday ? 'rgba(16, 185, 129, 0.1)' : 'transparent'
                    }}
                  >
                    <div style={{ fontSize: '11px', fontWeight: '700', color: d.isToday ? 'var(--accent-primary)' : 'var(--text-muted)' }}>
                      {d.dayName.toUpperCase()}
                    </div>
                    <div style={{
                      fontSize: '16px',
                      fontWeight: '800',
                      color: d.isToday ? '#fff' : 'var(--text-main)',
                      width: '28px',
                      height: '28px',
                      borderRadius: '50%',
                      backgroundColor: d.isToday ? 'var(--accent-primary)' : 'transparent',
                      display: 'flex',
                      alignItems: 'center',
                      justifyContent: 'center',
                      margin: '2px auto 0'
                    }}>
                      {d.dayNum}
                    </div>
                  </div>
                ))}
              </div>

              {/* 24-Hour Time Rows */}
              <div style={{ flex: 1, display: 'flex', flexDirection: 'column' }}>
                {HOURS_24.map(hour => {
                  const hourLabel = `${String(hour).padStart(2, '0')}:00`;

                  return (
                    <div
                      key={hour}
                      style={{
                        display: 'grid',
                        gridTemplateColumns: '70px repeat(7, 1fr)',
                        minHeight: '64px',
                        borderBottom: '1px solid rgba(255,255,255,0.06)'
                      }}
                    >
                      {/* Left 24h Column */}
                      <div style={{
                        padding: '6px 8px',
                        fontSize: '11px',
                        fontWeight: '700',
                        color: 'var(--text-muted)',
                        borderRight: '1px solid var(--border-color)',
                        backgroundColor: 'rgba(0,0,0,0.15)',
                        display: 'flex',
                        alignItems: 'flex-start',
                        justifyContent: 'center'
                      }}>
                        {hourLabel}
                      </div>

                      {/* 7 Day Slots for this hour */}
                      {weekDays.map((d, dIdx) => {
                        const slotEvents = filteredEvents.filter(ev => {
                          if (ev.all_day) return false;
                          const evDate = ev.start_time.split('T')[0];
                          const evHour = new Date(ev.start_time).getHours();
                          return evDate === d.dateStr && evHour === hour;
                        });

                        return (
                          <div
                            key={d.dateStr}
                            onClick={() => {
                              const targetDate = new Date(`${d.dateStr}T${String(hour).padStart(2, '0')}:00:00`);
                              openNewEventModal(undefined, targetDate);
                            }}
                            onDragOver={(e) => {
                              e.preventDefault();
                              e.dataTransfer.dropEffect = 'move';
                              e.currentTarget.style.backgroundColor = 'rgba(16, 185, 129, 0.2)';
                            }}
                            onDragLeave={(e) => {
                              e.currentTarget.style.backgroundColor = d.isToday ? 'rgba(16, 185, 129, 0.03)' : 'transparent';
                            }}
                            onDrop={(e) => {
                              e.preventDefault();
                              e.currentTarget.style.backgroundColor = d.isToday ? 'rgba(16, 185, 129, 0.03)' : 'transparent';
                              const evId = Number(e.dataTransfer.getData('text/plain'));
                              if (evId) {
                                handleDropOnDate(evId, d.dateStr, hour);
                              }
                            }}
                            style={{
                              borderRight: dIdx < 6 ? '1px solid rgba(255,255,255,0.06)' : 'none',
                              backgroundColor: d.isToday ? 'rgba(16, 185, 129, 0.03)' : 'transparent',
                              padding: '3px',
                              display: 'flex',
                              flexDirection: 'column',
                              gap: '4px',
                              cursor: 'pointer',
                              transition: 'background 0.15s'
                            }}
                          >
                            {slotEvents.map(ev => {
                              const isDone = ev.status === 'concluido';
                              return (
                                <div
                                  key={ev.id}
                                  draggable={true}
                                  onDragStart={(e) => {
                                    e.stopPropagation();
                                    e.dataTransfer.setData('text/plain', String(ev.id));
                                    e.dataTransfer.effectAllowed = 'move';
                                  }}
                                  onClick={(e) => {
                                    e.stopPropagation();
                                    openEditEventModal(ev);
                                  }}
                                  style={{
                                    backgroundColor: isDone ? 'rgba(255, 255, 255, 0.08)' : (ev.color || '#10b981'),
                                    color: '#fff',
                                    borderRadius: '6px',
                                    padding: '4px 6px',
                                    fontSize: '11px',
                                    fontWeight: '600',
                                    cursor: 'grab',
                                    boxShadow: '0 2px 6px rgba(0,0,0,0.3)',
                                    display: 'flex',
                                    flexDirection: 'column',
                                    gap: '2px',
                                    opacity: isDone ? 0.65 : 1
                                  }}
                                  title={`${ev.title} - Arraste para mover horário`}
                                >
                                  <div style={{ display: 'flex', alignItems: 'center', justifyContent: 'space-between', gap: '4px' }}>
                                    <span style={{ fontWeight: 'bold', overflow: 'hidden', textOverflow: 'ellipsis', whiteSpace: 'nowrap' }}>
                                      {ev.title}
                                    </span>
                                    {ev.confirmed_by_employee && <CheckSquare size={12} color="#4ade80" />}
                                  </div>
                                  {ev.employee_name && (
                                    <span style={{ fontSize: '10px', opacity: 0.9 }}>
                                      👤 {ev.employee_name}
                                    </span>
                                  )}
                                </div>
                              );
                            })}
                          </div>
                        );
                      })}
                    </div>
                  );
                })}
              </div>
            </div>
          )}

          {/* 3. DAY VIEW (24h Time Grid on Left + Sticky Header + Drag & Drop) */}
          {viewMode === 'day' && (
            <div style={{ display: 'flex', flexDirection: 'column', height: '100%', maxWidth: '900px', margin: '0 auto', width: '100%' }}>
              {/* Sticky Top Header for Single Day */}
              <div style={{
                position: 'sticky',
                top: 0,
                zIndex: 20,
                padding: '14px 20px',
                borderBottom: '1px solid var(--border-color)',
                backgroundColor: 'var(--bg-secondary)',
                backdropFilter: 'blur(10px)',
                display: 'flex',
                alignItems: 'center',
                justifyContent: 'space-between',
                boxShadow: '0 2px 8px rgba(0,0,0,0.3)'
              }}>
                <div>
                  <h3 style={{ fontSize: '16px', color: '#fff', margin: 0 }}>
                    {currentDate.toLocaleDateString('pt-BR', { weekday: 'long', day: '2-digit', month: 'long', year: 'numeric' })}
                  </h3>
                  <span style={{ fontSize: '12px', color: 'var(--text-muted)' }}>
                    Clique no horário desejado ou arraste os compromissos para reposicionar
                  </span>
                </div>
                <button
                  type="button"
                  onClick={() => openNewEventModal(undefined, currentDate)}
                  className="btn-primary"
                  style={{ padding: '6px 14px', fontSize: '12px' }}
                >
                  <Plus size={14} /> Adicionar no Dia
                </button>
              </div>

              {/* 24-Hour Day Rows */}
              <div style={{ flex: 1, display: 'flex', flexDirection: 'column' }}>
                {HOURS_24.map(hour => {
                  const hourLabel = `${String(hour).padStart(2, '0')}:00`;
                  const curDateStr = currentDate.toISOString().split('T')[0];
                  const slotEvents = filteredEvents.filter(ev => {
                    if (ev.all_day) return false;
                    const evDate = ev.start_time.split('T')[0];
                    const evHour = new Date(ev.start_time).getHours();
                    return evDate === curDateStr && evHour === hour;
                  });

                  return (
                    <div
                      key={hour}
                      onClick={() => {
                        const targetDate = new Date(`${curDateStr}T${String(hour).padStart(2, '0')}:00:00`);
                        openNewEventModal(undefined, targetDate);
                      }}
                      onDragOver={(e) => {
                        e.preventDefault();
                        e.dataTransfer.dropEffect = 'move';
                        e.currentTarget.style.backgroundColor = 'rgba(16, 185, 129, 0.2)';
                      }}
                      onDragLeave={(e) => {
                        e.currentTarget.style.backgroundColor = 'transparent';
                      }}
                      onDrop={(e) => {
                        e.preventDefault();
                        e.currentTarget.style.backgroundColor = 'transparent';
                        const evId = Number(e.dataTransfer.getData('text/plain'));
                        if (evId) {
                          handleDropOnDate(evId, curDateStr, hour);
                        }
                      }}
                      style={{
                        display: 'grid',
                        gridTemplateColumns: '70px 1fr',
                        minHeight: '64px',
                        borderBottom: '1px solid rgba(255,255,255,0.06)',
                        cursor: 'pointer',
                        transition: 'background 0.15s'
                      }}
                    >
                      {/* 24h Left Label */}
                      <div style={{
                        padding: '8px',
                        fontSize: '12px',
                        fontWeight: '700',
                        color: 'var(--text-muted)',
                        borderRight: '1px solid var(--border-color)',
                        backgroundColor: 'rgba(0,0,0,0.15)',
                        display: 'flex',
                        alignItems: 'flex-start',
                        justifyContent: 'center'
                      }}>
                        {hourLabel}
                      </div>

                      {/* Main Hour Content Slot */}
                      <div style={{ padding: '6px 12px', display: 'flex', flexDirection: 'column', gap: '6px' }}>
                        {slotEvents.map(ev => {
                          const isDone = ev.status === 'concluido';
                          return (
                            <div
                              key={ev.id}
                              draggable={true}
                              onDragStart={(e) => {
                                e.stopPropagation();
                                e.dataTransfer.setData('text/plain', String(ev.id));
                                e.dataTransfer.effectAllowed = 'move';
                              }}
                              onClick={(e) => {
                                e.stopPropagation();
                                openEditEventModal(ev);
                              }}
                              style={{
                                backgroundColor: isDone ? 'rgba(255, 255, 255, 0.08)' : (ev.color || '#10b981'),
                                color: '#fff',
                                borderRadius: '8px',
                                padding: '8px 12px',
                                fontSize: '13px',
                                fontWeight: '600',
                                cursor: 'grab',
                                boxShadow: '0 2px 8px rgba(0,0,0,0.3)',
                                display: 'flex',
                                alignItems: 'center',
                                justifyContent: 'space-between',
                                opacity: isDone ? 0.65 : 1
                              }}
                              title={`${ev.title} - Arraste para mover horário`}
                            >
                              <div style={{ display: 'flex', alignItems: 'center', gap: '10px' }}>
                                <button
                                  type="button"
                                  onClick={e => handleToggleStatus(ev, e)}
                                  style={{ background: 'none', border: 'none', color: '#fff', cursor: 'pointer', padding: 0 }}
                                >
                                  {isDone ? <CheckCircle2 size={18} /> : <Circle size={18} />}
                                </button>
                                <div>
                                  <div style={{ textDecoration: isDone ? 'line-through' : 'none' }}>
                                    {ev.title}
                                  </div>
                                  <div style={{ fontSize: '11px', opacity: 0.9, marginTop: '2px' }}>
                                    🕒 {ev.start_time.split('T')[1]?.substring(0, 5)} {ev.employee_name ? `• 👤 ${ev.employee_name}` : ''} {ev.contact_name ? `• 🏢 ${ev.contact_name}` : ''}
                                  </div>
                                </div>
                              </div>

                              {ev.employee_name && (
                                <div style={{
                                  fontSize: '11px',
                                  padding: '2px 8px',
                                  borderRadius: '12px',
                                  backgroundColor: ev.confirmed_by_employee ? 'rgba(34, 197, 94, 0.3)' : 'rgba(234, 179, 8, 0.3)',
                                  color: ev.confirmed_by_employee ? '#4ade80' : '#fde047',
                                  fontWeight: 'bold',
                                  display: 'flex',
                                  alignItems: 'center',
                                  gap: '4px'
                                }}>
                                  <CheckSquare size={12} />
                                  {ev.confirmed_by_employee ? 'Visualizado' : 'Aguardando'}
                                </div>
                              )}
                            </div>
                          );
                        })}
                      </div>
                    </div>
                  );
                })}
              </div>
            </div>
          )}

          {/* 4. AGENDA / LIST VIEW */}
          {viewMode === 'agenda' && (
            <div style={{ padding: '24px', maxWidth: '900px', margin: '0 auto', width: '100%' }}>
              {filteredEvents.length === 0 ? (
                <div style={{
                  textAlign: 'center',
                  padding: '60px 20px',
                  color: 'var(--text-muted)'
                }}>
                  <CalendarIcon size={56} style={{ margin: '0 auto 16px', opacity: 0.3 }} />
                  <h3 style={{ fontSize: '18px', color: '#fff', marginBottom: '8px' }}>Nenhuma tarefa encontrada</h3>
                  <p style={{ fontSize: '13px' }}>Clique em "+ Novo Evento / Tarefa" ou agende direto de uma conversa do WhatsApp.</p>
                </div>
              ) : (
                <div style={{ display: 'flex', flexDirection: 'column', gap: '12px' }}>
                  {filteredEvents.map(ev => {
                    const isDone = ev.status === 'concluido';
                    const evDate = new Date(ev.start_time);
                    const formattedDate = evDate.toLocaleDateString('pt-BR', { weekday: 'short', day: '2-digit', month: 'short' });
                    const timeStr = ev.all_day ? 'Dia Inteiro' : ev.start_time.split('T')[1]?.substring(0, 5) || '';

                    return (
                      <div
                        key={ev.id}
                        onClick={() => openEditEventModal(ev)}
                        style={{
                          backgroundColor: 'var(--bg-primary)',
                          border: `1px solid ${isDone ? 'var(--border-color)' : 'rgba(255,255,255,0.08)'}`,
                          borderLeft: `5px solid ${ev.color || '#10b981'}`,
                          borderRadius: '12px',
                          padding: '14px 18px',
                          display: 'flex',
                          alignItems: 'center',
                          justifyContent: 'space-between',
                          gap: '16px',
                          cursor: 'pointer',
                          opacity: isDone ? 0.6 : 1,
                          transition: 'transform 0.15s, background 0.15s'
                        }}
                        onMouseEnter={e => (e.currentTarget.style.transform = 'translateX(4px)')}
                        onMouseLeave={e => (e.currentTarget.style.transform = 'translateX(0)')}
                      >
                        <div style={{ display: 'flex', alignItems: 'center', gap: '14px', flex: 1, minWidth: 0 }}>
                          <button
                            type="button"
                            onClick={e => handleToggleStatus(ev, e)}
                            style={{
                              background: 'none',
                              border: 'none',
                              color: isDone ? 'var(--accent-primary)' : 'var(--text-muted)',
                              cursor: 'pointer',
                              padding: '4px',
                              display: 'flex',
                              alignItems: 'center'
                            }}
                          >
                            {isDone ? <CheckCircle2 size={22} color="var(--accent-primary)" /> : <Circle size={22} />}
                          </button>

                          <div style={{ minWidth: 0, flex: 1 }}>
                            <div style={{ display: 'flex', alignItems: 'center', gap: '8px', flexWrap: 'wrap' }}>
                              <h4 style={{
                                fontSize: '15px',
                                fontWeight: '600',
                                color: '#fff',
                                textDecoration: isDone ? 'line-through' : 'none',
                                margin: 0
                              }}>
                                {ev.title}
                              </h4>

                              {/* Event Type Badge */}
                              {ev.event_type === 'entrega_gas' && (
                                <span style={{ fontSize: '10px', backgroundColor: 'rgba(59, 130, 246, 0.2)', color: '#60a5fa', padding: '2px 8px', borderRadius: '10px', fontWeight: 'bold', display: 'flex', alignItems: 'center', gap: '4px' }}>
                                  <Truck size={11} /> Entrega de Gás
                                </span>
                              )}
                              {ev.event_type === 'visita_tecnica' && (
                                <span style={{ fontSize: '10px', backgroundColor: 'rgba(16, 185, 129, 0.2)', color: '#10b981', padding: '2px 8px', borderRadius: '10px', fontWeight: 'bold', display: 'flex', alignItems: 'center', gap: '4px' }}>
                                  <Wrench size={11} /> Visita Técnica
                                </span>
                              )}
                              {ev.event_type === 'manutencao' && (
                                <span style={{ fontSize: '10px', backgroundColor: 'rgba(245, 158, 11, 0.2)', color: '#f59e0b', padding: '2px 8px', borderRadius: '10px', fontWeight: 'bold', display: 'flex', alignItems: 'center', gap: '4px' }}>
                                  ⚙️ Manutenção
                                </span>
                              )}

                              {/* Employee Badge & Confirmation Check */}
                              {ev.employee_name && (
                                <span style={{
                                  fontSize: '10px',
                                  backgroundColor: ev.confirmed_by_employee ? 'rgba(34, 197, 94, 0.2)' : 'rgba(234, 179, 8, 0.2)',
                                  color: ev.confirmed_by_employee ? '#4ade80' : '#fde047',
                                  border: `1px solid ${ev.confirmed_by_employee ? 'rgba(34, 197, 94, 0.4)' : 'rgba(234, 179, 8, 0.4)'}`,
                                  padding: '2px 8px',
                                  borderRadius: '10px',
                                  fontWeight: 'bold',
                                  display: 'flex',
                                  alignItems: 'center',
                                  gap: '4px'
                                }}>
                                  <Users size={11} /> {ev.employee_name}
                                  {ev.confirmed_by_employee ? ' (✓ Visualizou)' : ' (⏳ Pendente)'}
                                </span>
                              )}

                              {ev.priority === 'urgente' && (
                                <span style={{ fontSize: '10px', backgroundColor: 'rgba(239, 68, 68, 0.2)', color: '#ef4444', padding: '2px 8px', borderRadius: '10px', fontWeight: 'bold' }}>
                                  URGENTE
                                </span>
                              )}
                              {ev.priority === 'alta' && (
                                <span style={{ fontSize: '10px', backgroundColor: 'rgba(245, 158, 11, 0.2)', color: '#f59e0b', padding: '2px 8px', borderRadius: '10px', fontWeight: 'bold' }}>
                                  ALTA
                                </span>
                              )}
                            </div>

                            {ev.description && (
                              <p style={{ fontSize: '13px', color: 'var(--text-muted)', marginTop: '4px', whiteSpace: 'pre-wrap', maxHeight: '40px', overflow: 'hidden', textOverflow: 'ellipsis' }}>
                                {ev.description}
                              </p>
                            )}

                            <div style={{ display: 'flex', alignItems: 'center', gap: '12px', marginTop: '6px', fontSize: '12px', color: 'var(--text-muted)', flexWrap: 'wrap' }}>
                              <span style={{ display: 'flex', alignItems: 'center', gap: '4px' }}>
                                <Clock size={13} /> {formattedDate} • {timeStr}
                              </span>

                              {ev.contact_name && (
                                <span style={{ display: 'flex', alignItems: 'center', gap: '4px', color: 'var(--accent-primary)' }}>
                                  <User size={13} /> {ev.contact_name}
                                </span>
                              )}

                              {ev.employee_phone && ev.notify_whatsapp && (
                                <span style={{ display: 'flex', alignItems: 'center', gap: '4px', color: '#60a5fa', fontSize: '11px' }}>
                                  <Bell size={11} /> WhatsApp Ativo
                                </span>
                              )}
                            </div>
                          </div>
                        </div>

                        <div style={{ display: 'flex', alignItems: 'center', gap: '8px' }}>
                          {ev.employee_name && (
                            <button
                              type="button"
                              onClick={e => handleToggleEmployeeConfirmation(ev, e)}
                              style={{
                                display: 'flex',
                                alignItems: 'center',
                                gap: '4px',
                                padding: '6px 10px',
                                borderRadius: '8px',
                                border: `1px solid ${ev.confirmed_by_employee ? 'rgba(34, 197, 94, 0.4)' : 'rgba(234, 179, 8, 0.4)'}`,
                                backgroundColor: ev.confirmed_by_employee ? 'rgba(34, 197, 94, 0.15)' : 'rgba(234, 179, 8, 0.12)',
                                color: ev.confirmed_by_employee ? '#4ade80' : '#fde047',
                                fontSize: '11px',
                                fontWeight: 'bold',
                                cursor: 'pointer'
                              }}
                              title={ev.confirmed_by_employee ? "Clique para desmarcar visualização" : "Clique para marcar que o funcionário confirmou visualização"}
                            >
                              <CheckSquare size={13} /> {ev.confirmed_by_employee ? 'Visualizado' : 'Dar Check'}
                            </button>
                          )}
                          {ev.conversation_id && onSelectConversation && (
                            <button
                              type="button"
                              onClick={e => {
                                e.stopPropagation();
                                onSelectConversation(ev.conversation_id!);
                                onClose();
                              }}
                              style={{
                                display: 'flex',
                                alignItems: 'center',
                                gap: '4px',
                                padding: '6px 12px',
                                borderRadius: '8px',
                                border: '1px solid var(--border-color)',
                                backgroundColor: 'var(--bg-secondary)',
                                color: 'var(--accent-primary)',
                                fontSize: '12px',
                                fontWeight: 'bold',
                                cursor: 'pointer'
                              }}
                              title="Abrir conversa no WhatsApp"
                            >
                              <MessageSquare size={14} /> Abrir Chat
                            </button>
                          )}

                          <button
                            type="button"
                            onClick={e => {
                              e.stopPropagation();
                              handleDeleteEvent(ev.id);
                            }}
                            style={{
                              background: 'none',
                              border: 'none',
                              color: 'var(--text-muted)',
                              cursor: 'pointer',
                              padding: '6px',
                              borderRadius: '6px'
                            }}
                            title="Excluir"
                          >
                            <Trash2 size={16} />
                          </button>
                        </div>
                      </div>
                    );
                  })}
                </div>
              )}
            </div>
          )}
        </div>
      </div>

      {/* New / Edit Event Modal (Form) */}
      {isFormOpen && (
        <div style={{
          position: 'fixed',
          inset: 0,
          backgroundColor: 'rgba(0, 0, 0, 0.85)',
          backdropFilter: 'blur(8px)',
          zIndex: 1100,
          display: 'flex',
          alignItems: 'center',
          justifyContent: 'center',
          padding: '16px'
        }}>
          <div style={{
            backgroundColor: 'var(--bg-secondary)',
            border: '1px solid var(--border-color)',
            borderRadius: '16px',
            width: '100%',
            maxWidth: '560px',
            maxHeight: '90vh',
            display: 'flex',
            flexDirection: 'column',
            boxShadow: '0 24px 60px rgba(0,0,0,0.9)',
            overflow: 'hidden'
          }}>
            <div style={{
              padding: '16px 20px',
              borderBottom: '1px solid var(--border-color)',
              display: 'flex',
              justifyContent: 'space-between',
              alignItems: 'center',
              backgroundColor: 'var(--bg-primary)',
              flexShrink: 0
            }}>
              <h3 style={{ margin: 0, fontSize: '16px', fontWeight: 'bold', color: '#fff', display: 'flex', alignItems: 'center', gap: '8px' }}>
                <CalendarIcon size={18} color="var(--accent-primary)" />
                {editingEvent ? 'Editar Tarefa / Compromisso' : 'Nova Tarefa / Compromisso'}
              </h3>
              <button
                type="button"
                onClick={() => setIsFormOpen(false)}
                style={{ background: 'none', border: 'none', color: 'var(--text-muted)', cursor: 'pointer', padding: 0 }}
              >
                <X size={20} />
              </button>
            </div>

            <form onSubmit={handleSaveEvent} style={{ display: 'flex', flexDirection: 'column', flex: 1, minHeight: 0, overflow: 'hidden' }}>
              <div style={{
                padding: '20px',
                display: 'flex',
                flexDirection: 'column',
                gap: '16px',
                overflowY: 'auto',
                flex: 1
              }}>
              {/* Event Title */}
              <div>
                <label style={{ display: 'block', fontSize: '12px', fontWeight: 'bold', color: 'var(--text-muted)', marginBottom: '6px' }}>
                  TÍTULO DA TAREFA *
                </label>
                <input
                  type="text"
                  required
                  placeholder="Ex: Ligar para confirmar entrega, enviar orçamento..."
                  value={formTitle}
                  onChange={e => setFormTitle(e.target.value)}
                  style={{
                    width: '100%',
                    padding: '10px 14px',
                    borderRadius: '8px',
                    border: '1px solid var(--border-color)',
                    backgroundColor: 'var(--bg-primary)',
                    color: '#fff',
                    fontSize: '14px',
                    outline: 'none'
                  }}
                  autoFocus
                />
              </div>

              {/* Linked Customer (if any) */}
              {(formContactName || formContactPhone) && (
                <div style={{
                  padding: '10px 14px',
                  borderRadius: '8px',
                  backgroundColor: 'rgba(16, 185, 129, 0.08)',
                  border: '1px solid rgba(16, 185, 129, 0.25)',
                  display: 'flex',
                  alignItems: 'center',
                  gap: '10px',
                  fontSize: '13px',
                  color: 'var(--accent-primary)'
                }}>
                  <User size={16} />
                  <div>
                    <span style={{ fontWeight: 'bold' }}>Cliente Vinculado: </span>
                    {formContactName || 'Sem nome'} ({formContactPhone})
                  </div>
                </div>
              )}

              {/* Event Type & Employee Row */}
              <div style={{ display: 'grid', gridTemplateColumns: '1fr 1fr', gap: '12px' }}>
                <div>
                  <label style={{ display: 'block', fontSize: '12px', fontWeight: 'bold', color: 'var(--text-muted)', marginBottom: '6px' }}>
                    TIPO DE COMPROMISSO
                  </label>
                  <select
                    value={formEventType}
                    onChange={e => setFormEventType(e.target.value)}
                    style={{
                      width: '100%',
                      padding: '8px 12px',
                      borderRadius: '8px',
                      border: '1px solid var(--border-color)',
                      backgroundColor: 'var(--bg-primary)',
                      color: '#fff',
                      fontSize: '13px',
                      outline: 'none'
                    }}
                  >
                    <option value="visita_tecnica">🔧 Visita Técnica</option>
                    <option value="entrega_gas">🚚 Entrega de Gás / Mercadoria</option>
                    <option value="manutencao">⚙️ Manutenção de Equipamento</option>
                    <option value="reuniao">👥 Reunião / Alinhamento</option>
                    <option value="atendimento">💬 Atendimento ao Cliente</option>
                    <option value="geral">📅 Tarefa / Compromisso Geral</option>
                  </select>
                </div>

                <div>
                  <label style={{ display: 'block', fontSize: '12px', fontWeight: 'bold', color: 'var(--text-muted)', marginBottom: '6px' }}>
                    FUNCIONÁRIO RESPONSÁVEL
                  </label>
                  <select
                    value={formEmployeeId}
                    onChange={e => {
                      const empId = e.target.value ? Number(e.target.value) : '';
                      setFormEmployeeId(empId);
                      const emp = employees.find(x => x.id === empId);
                      if (emp) {
                        setFormEmployeeName(emp.nome);
                        setFormEmployeePhone(emp.telefone);
                      } else {
                        setFormEmployeeName('');
                        setFormEmployeePhone('');
                      }
                    }}
                    style={{
                      width: '100%',
                      padding: '8px 12px',
                      borderRadius: '8px',
                      border: '1px solid var(--border-color)',
                      backgroundColor: 'var(--bg-primary)',
                      color: '#fff',
                      fontSize: '13px',
                      outline: 'none'
                    }}
                  >
                    <option value="">-- Nenhum funcionário selecionado --</option>
                    {employees.filter(e => e.ativo).map(emp => (
                      <option key={emp.id} value={emp.id}>
                        {emp.nome} ({emp.cargo || 'Equipe'} - {emp.telefone})
                      </option>
                    ))}
                  </select>
                </div>
              </div>

              {/* Employee WhatsApp Reminder Options (When an employee is selected) */}
              {formEmployeePhone && (
                <div style={{
                  padding: '12px 14px',
                  borderRadius: '10px',
                  backgroundColor: 'rgba(0, 230, 153, 0.08)',
                  border: '1px solid rgba(0, 230, 153, 0.25)',
                  display: 'flex',
                  flexDirection: 'column',
                  gap: '8px'
                }}>
                  <div style={{ display: 'flex', alignItems: 'center', justifyContent: 'space-between', flexWrap: 'wrap', gap: '8px' }}>
                    <div style={{ display: 'flex', alignItems: 'center', gap: '8px' }}>
                      <input
                        type="checkbox"
                        id="notifyWhatsAppCheck"
                        checked={formNotifyWhatsApp}
                        onChange={e => setFormNotifyWhatsApp(e.target.checked)}
                        style={{ cursor: 'pointer' }}
                      />
                      <label htmlFor="notifyWhatsAppCheck" style={{ fontSize: '13px', color: '#fff', fontWeight: '600', cursor: 'pointer' }}>
                        📲 Lembretes Automáticos no WhatsApp do Funcionário
                      </label>
                    </div>

                    <div style={{ display: 'flex', alignItems: 'center', gap: '6px' }}>
                      <label style={{ fontSize: '11px', color: 'var(--text-muted)' }}>Lembrar:</label>
                      <select
                        value={formCustomReminderHours}
                        onChange={e => setFormCustomReminderHours(Number(e.target.value))}
                        disabled={!formNotifyWhatsApp}
                        style={{
                          padding: '4px 8px',
                          borderRadius: '6px',
                          border: '1px solid var(--border-color)',
                          backgroundColor: 'var(--bg-primary)',
                          color: '#fff',
                          fontSize: '12px',
                          outline: 'none'
                        }}
                      >
                        <option value={1}>1 hora antes</option>
                        <option value={2}>2 horas antes</option>
                        <option value={4}>4 horas antes</option>
                        <option value={12}>12 horas antes</option>
                      </select>
                    </div>
                  </div>

                  <div style={{ fontSize: '11px', color: '#a7f3d0', lineHeight: '1.4' }}>
                    A IA enviará mensagem detalhada no WhatsApp de <strong>{formEmployeeName}</strong> ({formEmployeePhone}) na criação, no dia do evento às 08h e {formCustomReminderHours}h antes, com link para ele confirmar visualização!
                  </div>

                  {editingEvent && (
                    <div style={{
                      marginTop: '4px',
                      paddingTop: '8px',
                      borderTop: '1px solid rgba(255,255,255,0.1)',
                      display: 'flex',
                      alignItems: 'center',
                      justifyContent: 'space-between'
                    }}>
                      <div style={{ fontSize: '12px', color: formConfirmedByEmployee ? '#22c55e' : '#f59e0b', fontWeight: 'bold', display: 'flex', alignItems: 'center', gap: '6px' }}>
                        {formConfirmedByEmployee ? <CheckSquare size={14} /> : <Clock size={14} />}
                        {formConfirmedByEmployee ? 'Visualização Confirmada pelo Funcionário' : 'Aguardando Visualização do Funcionário'}
                      </div>
                      <button
                        type="button"
                        onClick={() => setFormConfirmedByEmployee(!formConfirmedByEmployee)}
                        style={{
                          background: formConfirmedByEmployee ? 'rgba(34, 197, 94, 0.15)' : 'rgba(255, 255, 255, 0.08)',
                          border: '1px solid rgba(255,255,255,0.2)',
                          borderRadius: '6px',
                          padding: '3px 8px',
                          fontSize: '11px',
                          color: '#fff',
                          cursor: 'pointer'
                        }}
                      >
                        {formConfirmedByEmployee ? 'Desmarcar Check' : 'Marcar como Confirmado'}
                      </button>
                    </div>
                  )}
                </div>
              )}

              {/* Date & Time Row */}
              <div style={{ display: 'grid', gridTemplateColumns: '1fr 1fr', gap: '12px' }}>
                <div>
                  <label style={{ display: 'block', fontSize: '12px', fontWeight: 'bold', color: 'var(--text-muted)', marginBottom: '6px' }}>
                    DATA *
                  </label>
                  <input
                    type="date"
                    required
                    value={formStartDate}
                    onChange={e => {
                      setFormStartDate(e.target.value);
                      setFormEndDate(e.target.value);
                    }}
                    style={{
                      width: '100%',
                      padding: '8px 12px',
                      borderRadius: '8px',
                      border: '1px solid var(--border-color)',
                      backgroundColor: 'var(--bg-primary)',
                      color: '#fff',
                      fontSize: '13px',
                      outline: 'none'
                    }}
                  />
                </div>

                <div>
                  <label style={{ display: 'block', fontSize: '12px', fontWeight: 'bold', color: 'var(--text-muted)', marginBottom: '6px' }}>
                    HORÁRIO
                  </label>
                  <div style={{ display: 'flex', alignItems: 'center', gap: '8px' }}>
                    <input
                      type="time"
                      disabled={formAllDay}
                      value={formStartTime}
                      onChange={e => setFormStartTime(e.target.value)}
                      style={{
                        width: '100%',
                        padding: '8px 12px',
                        borderRadius: '8px',
                        border: '1px solid var(--border-color)',
                        backgroundColor: formAllDay ? 'rgba(0,0,0,0.3)' : 'var(--bg-primary)',
                        color: formAllDay ? 'var(--text-muted)' : '#fff',
                        fontSize: '13px',
                        outline: 'none'
                      }}
                    />
                  </div>
                </div>
              </div>

              {/* All Day Checkbox */}
              <div style={{ display: 'flex', alignItems: 'center', gap: '8px' }}>
                <input
                  type="checkbox"
                  id="allDayCheck"
                  checked={formAllDay}
                  onChange={e => setFormAllDay(e.target.checked)}
                  style={{ cursor: 'pointer' }}
                />
                <label htmlFor="allDayCheck" style={{ fontSize: '13px', color: 'var(--text-main)', cursor: 'pointer' }}>
                  Compromisso para o dia inteiro (sem hora específica)
                </label>
              </div>

              {/* Color Palette (Google Calendar Style) */}
              <div>
                <label style={{ display: 'block', fontSize: '12px', fontWeight: 'bold', color: 'var(--text-muted)', marginBottom: '8px' }}>
                  COR DO EVENTO (GOOGLE CALENDAR)
                </label>
                <div style={{ display: 'flex', alignItems: 'center', gap: '10px', flexWrap: 'wrap' }}>
                  {GOOGLE_COLORS.map(c => (
                    <button
                      key={c.hex}
                      type="button"
                      onClick={() => setFormColor(c.hex)}
                      title={c.name}
                      style={{
                        width: '28px',
                        height: '28px',
                        borderRadius: '50%',
                        backgroundColor: c.hex,
                        border: formColor === c.hex ? '3px solid #fff' : '2px solid transparent',
                        cursor: 'pointer',
                        display: 'flex',
                        alignItems: 'center',
                        justifyContent: 'center',
                        boxShadow: formColor === c.hex ? '0 0 10px rgba(255,255,255,0.4)' : 'none',
                        transition: 'transform 0.15s ease'
                      }}
                    >
                      {formColor === c.hex && <Check size={14} color="#fff" strokeWidth={3} />}
                    </button>
                  ))}
                </div>
              </div>

              {/* Priority & Status Row */}
              <div style={{ display: 'grid', gridTemplateColumns: '1fr 1fr', gap: '12px' }}>
                <div>
                  <label style={{ display: 'block', fontSize: '12px', fontWeight: 'bold', color: 'var(--text-muted)', marginBottom: '6px' }}>
                    PRIORIDADE
                  </label>
                  <select
                    value={formPriority}
                    onChange={e => setFormPriority(e.target.value as any)}
                    style={{
                      width: '100%',
                      padding: '8px 12px',
                      borderRadius: '8px',
                      border: '1px solid var(--border-color)',
                      backgroundColor: 'var(--bg-primary)',
                      color: '#fff',
                      fontSize: '13px',
                      outline: 'none'
                    }}
                  >
                    <option value="baixa">🟢 Baixa</option>
                    <option value="media">🟡 Média</option>
                    <option value="alta">🟠 Alta</option>
                    <option value="urgente">🔴 Urgente</option>
                  </select>
                </div>

                <div>
                  <label style={{ display: 'block', fontSize: '12px', fontWeight: 'bold', color: 'var(--text-muted)', marginBottom: '6px' }}>
                    STATUS
                  </label>
                  <select
                    value={formStatus}
                    onChange={e => setFormStatus(e.target.value as any)}
                    style={{
                      width: '100%',
                      padding: '8px 12px',
                      borderRadius: '8px',
                      border: '1px solid var(--border-color)',
                      backgroundColor: 'var(--bg-primary)',
                      color: '#fff',
                      fontSize: '13px',
                      outline: 'none'
                    }}
                  >
                    <option value="pendente">⏳ Pendente</option>
                    <option value="em_progresso">⚡ Em Andamento</option>
                    <option value="concluido">✅ Concluído</option>
                    <option value="cancelado">❌ Cancelado</option>
                  </select>
                </div>
              </div>

              {/* Description / Notes */}
              <div>
                <label style={{ display: 'block', fontSize: '12px', fontWeight: 'bold', color: 'var(--text-muted)', marginBottom: '6px' }}>
                  OBSERVAÇÕES / DETALHES DA MENSAGEM
                </label>
                <textarea
                  rows={3}
                  placeholder="Anotações, detalhes combinados com o cliente, protocolo..."
                  value={formDescription}
                  onChange={e => setFormDescription(e.target.value)}
                  style={{
                    width: '100%',
                    padding: '10px 12px',
                    borderRadius: '8px',
                    border: '1px solid var(--border-color)',
                    backgroundColor: 'var(--bg-primary)',
                    color: '#fff',
                    fontSize: '13px',
                    outline: 'none',
                    resize: 'vertical'
                  }}
                />
              </div>
            </div>

            {/* Sticky Action Buttons Footer */}
            <div style={{
              padding: '14px 20px',
              borderTop: '1px solid var(--border-color)',
              backgroundColor: 'var(--bg-primary)',
              display: 'flex',
              justifyContent: 'space-between',
              alignItems: 'center',
              flexShrink: 0
            }}>
              {editingEvent ? (
                <button
                  type="button"
                  onClick={() => handleDeleteEvent(editingEvent.id)}
                  style={{
                    backgroundColor: 'rgba(239, 68, 68, 0.15)',
                    color: '#ef4444',
                    border: '1px solid rgba(239, 68, 68, 0.3)',
                    padding: '8px 14px',
                    borderRadius: '8px',
                    fontSize: '13px',
                    fontWeight: 'bold',
                    cursor: 'pointer'
                  }}
                >
                  Excluir
                </button>
              ) : <div />}

              <div style={{ display: 'flex', gap: '10px' }}>
                <button
                  type="button"
                  onClick={() => setIsFormOpen(false)}
                  style={{
                    backgroundColor: 'transparent',
                    color: 'var(--text-muted)',
                    border: '1px solid var(--border-color)',
                    padding: '8px 16px',
                    borderRadius: '8px',
                    fontSize: '13px',
                    cursor: 'pointer'
                  }}
                >
                  Cancelar
                </button>

                <button
                  type="submit"
                  disabled={isSaving}
                  style={{
                    backgroundColor: 'var(--accent-primary)',
                    color: '#fff',
                    border: 'none',
                    padding: '10px 24px',
                    borderRadius: '8px',
                    fontSize: '13px',
                    fontWeight: 'bold',
                    cursor: isSaving ? 'not-allowed' : 'pointer',
                    boxShadow: '0 4px 14px rgba(16, 185, 129, 0.4)',
                    display: 'flex',
                    alignItems: 'center',
                    gap: '6px'
                  }}
                >
                  <Check size={16} />
                  {isSaving ? 'Salvando...' : editingEvent ? 'Salvar Alterações' : 'Salvar e Agendar Tarefa'}
                </button>
              </div>
            </div>
          </form>
        </div>
      </div>
      )}
    </div>
  );
};
