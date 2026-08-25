import React, { useState, useEffect, useMemo, useRef } from 'react';
import {
  X, Calendar as CalendarIcon, ChevronLeft, ChevronRight, Plus, Check, Clock,
  AlertCircle, AlertTriangle, User, Phone, MessageSquare, Trash2, Edit3,
  Search, Filter, CheckCircle2, Circle, MoreVertical, ExternalLink, Tag,
  Truck, Wrench, Users, Bell, CheckSquare, ShieldCheck, Menu, CheckSquare2
} from 'lucide-react';
import { apiFetch } from '../services/api';
import { CalendarEvent, User as UserType, AuthorizedTechnician, WhatsAppNumber } from '../types';

interface CalendarModalProps {
  isOpen: boolean;
  onClose: () => void;
  currentUser: UserType;
  initialEventData?: Partial<CalendarEvent> | null;
  onSelectConversation?: (conversationId: number) => void;
}

const GOOGLE_COLORS = [
  { name: 'Laranja', hex: '#ea580c' },
  { name: 'Roxo', hex: '#9333ea' },
  { name: 'Azul', hex: '#0284c7' },
  { name: 'Grafite', hex: '#475569' },
  { name: 'Esmeralda', hex: '#10b981' },
  { name: 'Âmbar', hex: '#d97706' },
  { name: 'Vermelho', hex: '#dc2626' },
  { name: 'Rosa', hex: '#db2777' },
];

const GOOGLE_CALENDAR_PALETTE = [
  '#e11d48', '#f43f5e', '#fb7185', '#ea580c', '#f97316', '#f59e0b', '#eab308', '#facc15',
  '#a3e635', '#22c55e', '#10b981', '#14b8a6', '#06b6d4', '#3b82f6', '#6366f1', '#8b5cf6',
  '#a855f7', '#d946ef', '#ec4899', '#78350f', '#71717a', '#a1a1aa'
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
  const [viewMode, setViewMode] = useState<'month' | 'week' | 'day' | 'agenda'>('week');
  const [events, setEvents] = useState<CalendarEvent[]>([]);
  const [employees, setEmployees] = useState<AuthorizedTechnician[]>([]);
  const [loading, setLoading] = useState<boolean>(true);
  const [selectedEventType, setSelectedEventType] = useState<string>('all');
  const [searchQuery, setSearchQuery] = useState<string>('');

  // Right-Click Context Menu State
  const [contextMenu, setContextMenu] = useState<{
    isOpen: boolean;
    x: number;
    y: number;
    event: CalendarEvent | null;
  }>({
    isOpen: false,
    x: 0,
    y: 0,
    event: null
  });

  const handleOpenContextMenu = (e: React.MouseEvent, ev: CalendarEvent) => {
    e.preventDefault();
    e.stopPropagation();
    const menuWidth = 240;
    const menuHeight = 220;
    const x = Math.min(e.clientX, window.innerWidth - menuWidth - 10);
    const y = Math.min(e.clientY, window.innerHeight - menuHeight - 10);
    setContextMenu({
      isOpen: true,
      x: Math.max(10, x),
      y: Math.max(10, y),
      event: ev
    });
  };

  const handleChangeEventColor = async (ev: CalendarEvent, newColor: string) => {
    try {
      setEvents(prev => prev.map(e => e.id === ev.id ? { ...e, color: newColor } : e));
      setContextMenu({ isOpen: false, x: 0, y: 0, event: null });
      await apiFetch(`/calendar/events/${ev.id}`, {
        method: 'PUT',
        body: JSON.stringify({
          title: ev.title,
          description: ev.description,
          event_type: ev.event_type,
          start_time: ev.start_time,
          end_time: ev.end_time,
          all_day: ev.all_day,
          color: newColor,
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
        })
      });
    } catch (err) {
      console.error('Error updating event color:', err);
    }
  };

  const handleChangeEventStatus = async (ev: CalendarEvent, newStatus: 'pendente' | 'em_progresso' | 'concluido' | 'cancelado') => {
    try {
      setEvents(prev => prev.map(e => e.id === ev.id ? { ...e, status: newStatus } : e));
      setContextMenu({ isOpen: false, x: 0, y: 0, event: null });
      await apiFetch(`/calendar/events/${ev.id}`, {
        method: 'PUT',
        body: JSON.stringify({
          title: ev.title,
          description: ev.description,
          event_type: ev.event_type,
          start_time: ev.start_time,
          end_time: ev.end_time,
          all_day: ev.all_day,
          color: ev.color,
          priority: ev.priority,
          status: newStatus,
          reminder_minutes: ev.reminder_minutes,
          contact_id: ev.contact_id,
          conversation_id: ev.conversation_id,
          employee_id: ev.employee_id,
          employee_name: ev.employee_name,
          employee_phone: ev.employee_phone,
          notify_whatsapp: ev.notify_whatsapp,
          custom_reminder_hours: ev.custom_reminder_hours,
          confirmed_by_employee: ev.confirmed_by_employee
        })
      });
    } catch (err) {
      console.error('Error updating event status:', err);
    }
  };

  useEffect(() => {
    const handleCloseCtx = () => {
      if (contextMenu.isOpen) {
        setContextMenu({ isOpen: false, x: 0, y: 0, event: null });
      }
    };
    window.addEventListener('click', handleCloseCtx);
    return () => window.removeEventListener('click', handleCloseCtx);
  }, [contextMenu.isOpen]);

  const [showSidebar, setShowSidebar] = useState<boolean>(true);
  const [miniCalDate, setMiniCalDate] = useState<Date>(new Date());
  const [selectedAgendas, setSelectedAgendas] = useState<Record<string, boolean>>({
    entrega_gas: true,
    visita_tecnica: true,
    manutencao: true,
    reuniao: true,
    atendimento: true,
    geral: true
  });
  const timeGridRef = useRef<HTMLDivElement>(null);
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
  const [whatsappNumbers, setWhatsappNumbers] = useState<WhatsAppNumber[]>([]);
  const [formEmployeeId, setFormEmployeeId] = useState<number | ''>('');
  const [formEmployeeName, setFormEmployeeName] = useState<string>('');
  const [formEmployeePhone, setFormEmployeePhone] = useState<string>('');
  const [formNotifyWhatsApp, setFormNotifyWhatsApp] = useState<boolean>(true);
  const [formCustomReminderHours, setFormCustomReminderHours] = useState<number>(2);
  const [formConfirmedByEmployee, setFormConfirmedByEmployee] = useState<boolean>(false);
  const [formWhatsappNumberId, setFormWhatsappNumberId] = useState<number | ''>('');
  const [formWhatsappInstance, setFormWhatsappInstance] = useState<string>('');
  const [isSaving, setIsSaving] = useState<boolean>(false);

  // Load events, employees and whatsapp department numbers
  const fetchEvents = async () => {
    try {
      setLoading(true);
      const [eventsData, empData, wnData] = await Promise.all([
        apiFetch('/calendar/events'),
        apiFetch('/technicians/'),
        apiFetch('/whatsapp-numbers/')
      ]);
      setEvents(eventsData || []);
      setEmployees(empData || []);
      setWhatsappNumbers(wnData || []);
    } catch (err) {
      console.error('Error fetching calendar events, employees or whatsapp numbers:', err);
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

  const formatLocalDateStr = (d: Date): string => {
    const year = d.getFullYear();
    const month = String(d.getMonth() + 1).padStart(2, '0');
    const day = String(d.getDate()).padStart(2, '0');
    return `${year}-${month}-${day}`;
  };

  const formatLocalIsoStr = (d: Date): string => {
    const year = d.getFullYear();
    const month = String(d.getMonth() + 1).padStart(2, '0');
    const day = String(d.getDate()).padStart(2, '0');
    const hours = String(d.getHours()).padStart(2, '0');
    const mins = String(d.getMinutes()).padStart(2, '0');
    const secs = String(d.getSeconds()).padStart(2, '0');
    return `${year}-${month}-${day}T${hours}:${mins}:${secs}`;
  };

  const openNewEventModal = (prefill?: Partial<CalendarEvent>, selectedDay?: Date) => {
    setEditingEvent(null);
    const targetDate = selectedDay || new Date();
    const dateStr = formatLocalDateStr(targetDate);

    const now = new Date();
    const curHour = targetDate.getHours() || now.getHours();
    const curMin = targetDate.getMinutes() || 0;
    const startTimeStr = `${String(curHour).padStart(2, '0')}:${String(curMin).padStart(2, '0')}`;
    const nextHourNum = (curHour + 1) % 24;
    const endTimeStr = `${String(nextHourNum).padStart(2, '0')}:${String(curMin).padStart(2, '0')}`;

    setFormTitle(prefill?.title || '');
    setFormDescription(prefill?.description || '');
    setFormEventType(prefill?.event_type || 'geral');
    setFormStartDate(dateStr);
    setFormStartTime(prefill?.start_time ? `${String(new Date(prefill.start_time).getHours()).padStart(2, '0')}:${String(new Date(prefill.start_time).getMinutes()).padStart(2, '0')}` : startTimeStr);
    setFormEndDate(dateStr);
    setFormEndTime(endTimeStr);
    setFormAllDay(prefill?.all_day || false);
    setFormColor(prefill?.color || '#ea580c');
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
    setFormWhatsappNumberId(prefill?.whatsapp_number_id || '');
    setFormWhatsappInstance(prefill?.whatsapp_instance || '');

    setIsFormOpen(true);
  };

  const openEditEventModal = (event: CalendarEvent) => {
    setEditingEvent(event);
    const startDt = new Date(event.start_time);
    const endDt = event.end_time ? new Date(event.end_time) : startDt;

    setFormTitle(event.title);
    setFormDescription(event.description || '');
    setFormEventType(event.event_type || 'geral');
    setFormStartDate(formatLocalDateStr(startDt));
    setFormStartTime(`${String(startDt.getHours()).padStart(2, '0')}:${String(startDt.getMinutes()).padStart(2, '0')}`);
    setFormEndDate(formatLocalDateStr(endDt));
    setFormEndTime(`${String(endDt.getHours()).padStart(2, '0')}:${String(endDt.getMinutes()).padStart(2, '0')}`);
    setFormAllDay(event.all_day);
    setFormColor(event.color || '#ea580c');
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
    setFormWhatsappNumberId(event.whatsapp_number_id || '');
    setFormWhatsappInstance(event.whatsapp_instance || '');

    setIsFormOpen(true);
  };

  const handleSaveEvent = async (e: React.FormEvent) => {
    e.preventDefault();
    if (!formTitle.trim()) return;

    try {
      setIsSaving(true);
      const [sYear, sMonth, sDay] = formStartDate.split('-').map(Number);
      const [sHour, sMin] = formAllDay ? [0, 0] : formStartTime.split(':').map(Number);
      const startDtObj = new Date(sYear, sMonth - 1, sDay, sHour, sMin, 0);

      const [eYear, eMonth, eDay] = (formEndDate || formStartDate).split('-').map(Number);
      const [eHour, eMin] = formAllDay ? [23, 59] : formEndTime.split(':').map(Number);
      const endDtObj = new Date(eYear, eMonth - 1, eDay, eHour, eMin, 0);

      const payload = {
        title: formTitle.trim(),
        description: formDescription.trim() || null,
        event_type: formEventType,
        start_time: formatLocalIsoStr(startDtObj),
        end_time: formatLocalIsoStr(endDtObj),
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
        confirmed_by_employee: formConfirmedByEmployee,
        whatsapp_number_id: formWhatsappNumberId ? Number(formWhatsappNumberId) : null,
        whatsapp_instance: formWhatsappInstance || null
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
      if (editingEvent?.id === eventId) setIsFormOpen(false);
    } catch (err) {
      console.error('Error deleting calendar event:', err);
      alert('Erro ao excluir evento.');
    }
  };

  const handleToggleStatus = async (event: CalendarEvent, e?: React.MouseEvent) => {
    if (e) e.stopPropagation();
    try {
      const newStatus = event.status === 'concluido' ? 'pendente' : 'concluido';
      const updated = await apiFetch(`/calendar/events/${event.id}`, {
        method: 'PUT',
        body: JSON.stringify({ ...event, status: newStatus })
      });
      setEvents(prev => prev.map(ev => ev.id === event.id ? updated : ev));
    } catch (err) {
      console.error('Error updating status:', err);
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

  useEffect(() => {
    if (timeGridRef.current && (viewMode === 'week' || viewMode === 'day')) {
      const curHour = new Date().getHours();
      const targetScroll = Math.max(0, Math.min(18, curHour - 2)) * 60;
      timeGridRef.current.scrollTop = targetScroll;
    }
  }, [viewMode, isOpen]);

  // Filtered events
  const filteredEvents = useMemo(() => {
    return events.filter(ev => {
      const typeKey = ev.event_type || 'geral';
      if (selectedAgendas[typeKey] === false) return false;

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
  }, [events, selectedAgendas, statusFilter, priorityFilter, searchTerm]);

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
      days.push({ date: d, isCurrentMonth: false, dateStr: formatLocalDateStr(d) });
    }

    // Current month days
    for (let i = 1; i <= totalDaysInMonth; i++) {
      const d = new Date(year, month, i);
      days.push({ date: d, isCurrentMonth: true, dateStr: formatLocalDateStr(d) });
    }

    // Next month padding to fill 35 or 42 grid cells
    const remaining = (7 - (days.length % 7)) % 7;
    for (let i = 1; i <= remaining; i++) {
      const d = new Date(year, month + 1, i);
      days.push({ date: d, isCurrentMonth: false, dateStr: formatLocalDateStr(d) });
    }

    return days;
  }, [currentDate]);

  // Mini Calendar Matrix Calculation
  const miniMonthDays = useMemo(() => {
    const year = miniCalDate.getFullYear();
    const month = miniCalDate.getMonth();
    const firstDayIndex = new Date(year, month, 1).getDay();
    const totalDaysInMonth = new Date(year, month + 1, 0).getDate();
    const prevMonthDays = new Date(year, month, 0).getDate();

    const days: { date: Date; isCurrentMonth: boolean; dateStr: string }[] = [];
    for (let i = firstDayIndex - 1; i >= 0; i--) {
      const d = new Date(year, month - 1, prevMonthDays - i);
      days.push({ date: d, isCurrentMonth: false, dateStr: formatLocalDateStr(d) });
    }
    for (let i = 1; i <= totalDaysInMonth; i++) {
      const d = new Date(year, month, i);
      days.push({ date: d, isCurrentMonth: true, dateStr: formatLocalDateStr(d) });
    }
    const rem = (7 - (days.length % 7)) % 7;
    for (let i = 1; i <= rem; i++) {
      const d = new Date(year, month + 1, i);
      days.push({ date: d, isCurrentMonth: false, dateStr: formatLocalDateStr(d) });
    }
    return days;
  }, [miniCalDate]);

  const HOURS_24 = useMemo(() => Array.from({ length: 24 }, (_, i) => i), []);

  const todayStr = useMemo(() => formatLocalDateStr(new Date()), []);

  const weekDays = useMemo(() => {
    const startOfWeek = new Date(currentDate);
    const day = startOfWeek.getDay(); // 0 is Sunday
    startOfWeek.setDate(startOfWeek.getDate() - day);

    return Array.from({ length: 7 }, (_, i) => {
      const d = new Date(startOfWeek);
      d.setDate(d.getDate() + i);
      const dateStr = formatLocalDateStr(d);
      return {
        date: d,
        dateStr,
        dayName: WEEKDAYS[d.getDay()],
        dayNum: d.getDate(),
        isToday: dateStr === todayStr
      };
    });
  }, [currentDate, todayStr]);

  const handleDropOnDate = async (eventId: number, newDateStr: string, newHour?: number, newMinute?: number) => {
    const ev = events.find(e => e.id === eventId);
    if (!ev) return;

    try {
      const origStart = new Date(ev.start_time);
      const origEnd = ev.end_time ? new Date(ev.end_time) : origStart;
      const durationMs = Math.max(15 * 60 * 1000, origEnd.getTime() - origStart.getTime());

      const [year, month, day] = newDateStr.split('-').map(Number);
      const targetHour = newHour !== undefined ? newHour : origStart.getHours();
      const targetMinute = newMinute !== undefined ? newMinute : (newHour !== undefined ? 0 : origStart.getMinutes());

      const newStartDt = new Date(year, month - 1, day, targetHour, targetMinute, 0);
      const newEndDt = new Date(newStartDt.getTime() + durationMs);

      const payload = {
        title: ev.title,
        description: ev.description,
        event_type: ev.event_type,
        start_time: formatLocalIsoStr(newStartDt),
        end_time: formatLocalIsoStr(newEndDt),
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
        start_time: formatLocalIsoStr(newStartDt),
        end_time: formatLocalIsoStr(newEndDt)
      };
      setEvents(prev => prev.map(e => e.id === eventId ? updatedOptimistic : e));

      const updated = await apiFetch(`/calendar/events/${eventId}`, {
        method: 'PUT',
        body: JSON.stringify(payload)
      });
      if (updated && updated.id) {
        setEvents(prev => prev.map(e => e.id === eventId ? updated : e));
      }
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
          padding: '12px 20px',
          borderBottom: '1px solid var(--border-color)',
          display: 'flex',
          alignItems: 'center',
          justifyContent: 'space-between',
          flexWrap: 'wrap',
          gap: '12px',
          backgroundColor: '#181d2c'
        }}>
          <div style={{ display: 'flex', alignItems: 'center', gap: '14px' }}>
            <button
              type="button"
              onClick={() => setShowSidebar(prev => !prev)}
              style={{
                background: 'none',
                border: 'none',
                color: 'var(--text-muted)',
                cursor: 'pointer',
                padding: '6px',
                borderRadius: '50%',
                display: 'flex',
                alignItems: 'center',
                justifyContent: 'center'
              }}
              title="Menu lateral"
            >
              <Menu size={20} />
            </button>

            {/* Google-like Logo Badge */}
            <div style={{
              display: 'flex',
              alignItems: 'center',
              gap: '8px',
              color: '#fff',
              fontWeight: 'bold',
              fontSize: '18px'
            }}>
              <div style={{
                backgroundColor: '#1a73e8',
                color: '#fff',
                width: '28px',
                height: '28px',
                borderRadius: '6px',
                display: 'flex',
                alignItems: 'center',
                justifyContent: 'center',
                fontSize: '14px',
                fontWeight: '800'
              }}>
                {new Date().getDate()}
              </div>
              <span>Agenda</span>
            </div>

            {/* Navigation Controls */}
            <div style={{ display: 'flex', alignItems: 'center', gap: '6px', marginLeft: '12px' }}>
              <button
                type="button"
                onClick={handleToday}
                style={{
                  padding: '6px 16px',
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

            <h2 style={{ fontSize: '18px', fontWeight: '700', color: '#fff', margin: '0 0 0 10px' }}>
              {MONTH_NAMES[currentDate.getMonth()]} de {currentDate.getFullYear()}
            </h2>
          </div>

          {/* Right Controls: Search, View Mode, Status Filter, Close */}
          <div style={{ display: 'flex', alignItems: 'center', gap: '12px' }}>
            {/* Search Input */}
            <div style={{
              display: 'flex',
              alignItems: 'center',
              gap: '6px',
              backgroundColor: 'var(--bg-primary)',
              border: '1px solid var(--border-color)',
              borderRadius: '20px',
              padding: '6px 12px',
              width: '180px'
            }}>
              <Search size={14} color="var(--text-muted)" />
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
                  fontSize: '12px',
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

            {/* View Mode Switcher */}
            <div style={{
              display: 'flex',
              backgroundColor: 'var(--bg-primary)',
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
                    padding: '5px 12px',
                    borderRadius: '16px',
                    border: 'none',
                    backgroundColor: viewMode === mode ? '#1a73e8' : 'transparent',
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
                backgroundColor: 'var(--bg-primary)',
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

            {/* Close Button */}
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
              <X size={22} />
            </button>
          </div>
        </div>

        {/* Main Body (Split into Left Sidebar + Main Calendar View) */}
        <div style={{ flex: 1, display: 'flex', overflow: 'hidden', backgroundColor: '#0d1117' }}>
          {/* LEFT SIDEBAR (Google Calendar Style) */}
          {showSidebar && (
            <div style={{
              width: '235px',
              backgroundColor: '#131722',
              borderRight: '1px solid var(--border-color)',
              padding: '16px 14px',
              display: 'flex',
              flexDirection: 'column',
              gap: '20px',
              overflowY: 'auto',
              flexShrink: 0
            }}>
              {/* + Criar Button */}
              <button
                type="button"
                onClick={() => openNewEventModal()}
                style={{
                  display: 'flex',
                  alignItems: 'center',
                  gap: '10px',
                  backgroundColor: '#202637',
                  border: '1px solid var(--border-color)',
                  color: '#fff',
                  padding: '10px 18px',
                  borderRadius: '28px',
                  fontWeight: '700',
                  fontSize: '14px',
                  cursor: 'pointer',
                  boxShadow: '0 4px 12px rgba(0,0,0,0.4)',
                  transition: 'all 0.15s ease',
                  width: 'fit-content'
                }}
                onMouseEnter={e => (e.currentTarget.style.backgroundColor = '#2a324b')}
                onMouseLeave={e => (e.currentTarget.style.backgroundColor = '#202637')}
              >
                <div style={{
                  width: '24px',
                  height: '24px',
                  borderRadius: '50%',
                  backgroundColor: '#1a73e8',
                  display: 'flex',
                  alignItems: 'center',
                  justifyContent: 'center'
                }}>
                  <Plus size={16} color="#fff" />
                </div>
                <span>Criar</span>
              </button>

              {/* Mini Calendar */}
              <div style={{ display: 'flex', flexDirection: 'column', gap: '8px' }}>
                <div style={{ display: 'flex', justifyContent: 'space-between', alignItems: 'center', padding: '0 4px' }}>
                  <span style={{ fontSize: '13px', fontWeight: 'bold', color: '#fff' }}>
                    {MONTH_NAMES[miniCalDate.getMonth()]} de {miniCalDate.getFullYear()}
                  </span>
                  <div style={{ display: 'flex', gap: '2px' }}>
                    <button
                      type="button"
                      onClick={() => setMiniCalDate(prev => {
                        const d = new Date(prev);
                        d.setMonth(d.getMonth() - 1);
                        return d;
                      })}
                      style={{ background: 'none', border: 'none', color: 'var(--text-muted)', cursor: 'pointer', padding: '2px' }}
                    >
                      <ChevronLeft size={16} />
                    </button>
                    <button
                      type="button"
                      onClick={() => setMiniCalDate(prev => {
                        const d = new Date(prev);
                        d.setMonth(d.getMonth() + 1);
                        return d;
                      })}
                      style={{ background: 'none', border: 'none', color: 'var(--text-muted)', cursor: 'pointer', padding: '2px' }}
                    >
                      <ChevronRight size={16} />
                    </button>
                  </div>
                </div>

                {/* Mini Day Letters */}
                <div style={{ display: 'grid', gridTemplateColumns: 'repeat(7, 1fr)', textAlign: 'center', fontSize: '10px', color: 'var(--text-muted)', fontWeight: 'bold' }}>
                  {['D', 'S', 'T', 'Q', 'Q', 'S', 'S'].map((l, i) => (
                    <span key={i}>{l}</span>
                  ))}
                </div>

                {/* Mini Days Grid */}
                <div style={{ display: 'grid', gridTemplateColumns: 'repeat(7, 1fr)', gap: '2px', textAlign: 'center', fontSize: '11px' }}>
                  {miniMonthDays.map((c, i) => {
                    const isCurSelected = c.dateStr === formatLocalDateStr(currentDate);
                    const isTodayCell = c.dateStr === todayStr;

                    return (
                      <button
                        key={i}
                        type="button"
                        onClick={() => setCurrentDate(c.date)}
                        style={{
                          background: isCurSelected ? '#1a73e8' : 'none',
                          color: isCurSelected ? '#fff' : isTodayCell ? 'var(--accent-primary)' : c.isCurrentMonth ? 'var(--text-main)' : 'rgba(255,255,255,0.2)',
                          border: isTodayCell && !isCurSelected ? '1px solid var(--accent-primary)' : 'none',
                          borderRadius: '50%',
                          width: '24px',
                          height: '24px',
                          display: 'flex',
                          alignItems: 'center',
                          justifyContent: 'center',
                          margin: '0 auto',
                          cursor: 'pointer',
                          fontWeight: isCurSelected || isTodayCell ? 'bold' : 'normal'
                        }}
                      >
                        {c.date.getDate()}
                      </button>
                    );
                  })}
                </div>
              </div>

              {/* Minhas Agendas / Filtros de Tipos de Tarefas */}
              <div style={{ display: 'flex', flexDirection: 'column', gap: '10px', borderTop: '1px solid var(--border-color)', paddingTop: '14px' }}>
                <span style={{ fontSize: '12px', fontWeight: 'bold', color: 'var(--text-muted)', textTransform: 'uppercase', letterSpacing: '0.5px' }}>
                  Minhas Agendas
                </span>

                {[
                  { key: 'entrega_gas', label: '🚚 Entregas de Gás', color: '#0284c7' },
                  { key: 'visita_tecnica', label: '🔧 Visitas Técnicas', color: '#10b981' },
                  { key: 'manutencao', label: '⚙️ Manutenções', color: '#d97706' },
                  { key: 'reuniao', label: '👥 Reuniões', color: '#9333ea' },
                  { key: 'atendimento', label: '💬 Atendimentos', color: '#06b6d4' },
                  { key: 'geral', label: '📅 Tarefas Gerais', color: '#475569' },
                ].map(ag => (
                  <label
                    key={ag.key}
                    style={{
                      display: 'flex',
                      alignItems: 'center',
                      gap: '8px',
                      fontSize: '12px',
                      color: selectedAgendas[ag.key] ? '#fff' : 'var(--text-muted)',
                      cursor: 'pointer'
                    }}
                  >
                    <input
                      type="checkbox"
                      checked={selectedAgendas[ag.key] !== false}
                      onChange={e => setSelectedAgendas(prev => ({ ...prev, [ag.key]: e.target.checked }))}
                      style={{ accentColor: ag.color, cursor: 'pointer' }}
                    />
                    <span style={{
                      width: '8px',
                      height: '8px',
                      borderRadius: '50%',
                      backgroundColor: ag.color,
                      display: 'inline-block'
                    }} />
                    <span>{ag.label}</span>
                  </label>
                ))}
              </div>
            </div>
          )}

          {/* MAIN CALENDAR AREA */}
          <div style={{ flex: 1, display: 'flex', flexDirection: 'column', height: '100%', overflow: 'hidden' }}>
            {/* 1. WEEK VIEW (Google Calendar Style with Absolute Block Positioning) */}
            {viewMode === 'week' && (
              <div style={{ flex: 1, display: 'flex', flexDirection: 'column', height: '100%', overflow: 'hidden' }}>
                {/* Sticky Top Header (Time label + 7 Days) */}
                <div style={{
                  display: 'grid',
                  gridTemplateColumns: '65px repeat(7, 1fr)',
                  borderBottom: '1px solid var(--border-color)',
                  backgroundColor: '#181d2c',
                  zIndex: 20,
                  boxShadow: '0 2px 8px rgba(0,0,0,0.3)',
                  flexShrink: 0
                }}>
                  <div style={{
                    padding: '12px 6px',
                    textAlign: 'center',
                    fontSize: '10px',
                    fontWeight: 'bold',
                    color: 'var(--text-muted)',
                    borderRight: '1px solid var(--border-color)',
                    display: 'flex',
                    alignItems: 'center',
                    justifyContent: 'center'
                  }}>
                    GMT-03
                  </div>
                  {weekDays.map((d, idx) => (
                    <div
                      key={d.dateStr}
                      style={{
                        padding: '10px 4px',
                        textAlign: 'center',
                        borderRight: idx < 6 ? '1px solid var(--border-color)' : 'none',
                        backgroundColor: d.isToday ? 'rgba(26, 115, 232, 0.08)' : 'transparent'
                      }}
                    >
                      <div style={{ fontSize: '11px', fontWeight: 'bold', color: d.isToday ? '#60a5fa' : 'var(--text-muted)' }}>
                        {d.dayName.toUpperCase()}.
                      </div>
                      <div style={{
                        fontSize: '18px',
                        fontWeight: '800',
                        color: d.isToday ? '#fff' : 'var(--text-main)',
                        width: '32px',
                        height: '32px',
                        borderRadius: '50%',
                        backgroundColor: d.isToday ? '#1a73e8' : 'transparent',
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

                {/* Scrollable 24h Time Grid */}
                <div
                  ref={timeGridRef}
                  style={{
                    flex: 1,
                    overflowY: 'auto',
                    display: 'grid',
                    gridTemplateColumns: '65px repeat(7, 1fr)',
                    position: 'relative',
                    backgroundColor: '#0f131d'
                  }}
                >
                  {/* Left Column (24 Hours Labels) */}
                  <div style={{
                    height: '1440px',
                    position: 'relative',
                    borderRight: '1px solid var(--border-color)',
                    backgroundColor: 'rgba(0,0,0,0.2)'
                  }}>
                    {HOURS_24.map(h => (
                      <div
                        key={h}
                        style={{
                          position: 'absolute',
                          top: `${h * 60 - 8}px`,
                          right: '8px',
                          fontSize: '11px',
                          color: 'var(--text-muted)',
                          fontWeight: '600'
                        }}
                      >
                        {h === 0 ? '12 AM' : h < 12 ? `${h} AM` : h === 12 ? '12 PM' : `${h - 12} PM`}
                      </div>
                    ))}
                  </div>

                  {/* 7 Day Columns */}
                  {weekDays.map((d, dIdx) => {
                    const dayEvents = filteredEvents.filter(ev => {
                      if (ev.all_day) return false;
                      const evDt = new Date(ev.start_time);
                      const evDate = formatLocalDateStr(evDt);
                      return evDate === d.dateStr;
                    });

                    // Current Time Red Indicator Line
                    const now = new Date();
                    const isCurrentDay = d.dateStr === todayStr;
                    const nowMinutes = now.getHours() * 60 + now.getMinutes();
                    const redLineTopPx = (nowMinutes / 60) * 60;

                    return (
                      <div
                        key={d.dateStr}
                        onDragOver={(e) => {
                          e.preventDefault();
                          e.dataTransfer.dropEffect = 'move';
                        }}
                        onDrop={(e) => {
                          e.preventDefault();
                          const evId = Number(e.dataTransfer.getData('text/plain'));
                          if (!evId) return;
                          const rect = e.currentTarget.getBoundingClientRect();
                          const offsetY = Math.max(0, e.clientY - rect.top);
                          const totalMinutes = Math.min(23 * 60 + 45, Math.floor(offsetY / 15) * 15);
                          const newHour = Math.floor(totalMinutes / 60);
                          const newMinute = totalMinutes % 60;
                          handleDropOnDate(evId, d.dateStr, newHour, newMinute);
                        }}
                        style={{
                          position: 'relative',
                          height: '1440px',
                          borderRight: dIdx < 6 ? '1px solid rgba(255,255,255,0.06)' : 'none',
                          backgroundColor: d.isToday ? 'rgba(26, 115, 232, 0.02)' : 'transparent'
                        }}
                      >
                        {/* 24 Horizontal Grid Lines & Drop Slots */}
                        {HOURS_24.map(hour => (
                          <div
                            key={hour}
                            onDragOver={(e) => {
                              e.preventDefault();
                              e.dataTransfer.dropEffect = 'move';
                              e.currentTarget.style.background = 'linear-gradient(90deg, rgba(59, 130, 246, 0.4) 0%, rgba(37, 99, 235, 0.28) 100%)';
                              e.currentTarget.style.boxShadow = 'inset 0 0 16px rgba(59, 130, 246, 0.65), 0 0 12px rgba(59, 130, 246, 0.4)';
                              e.currentTarget.style.border = '1.5px dashed #60a5fa';
                              e.currentTarget.style.zIndex = '5';
                            }}
                            onDragLeave={(e) => {
                              e.currentTarget.style.background = 'transparent';
                              e.currentTarget.style.boxShadow = 'none';
                              e.currentTarget.style.border = 'none';
                              e.currentTarget.style.borderBottom = '1px solid rgba(255,255,255,0.06)';
                              e.currentTarget.style.zIndex = '1';
                            }}
                            onDrop={(e) => {
                              e.preventDefault();
                              e.currentTarget.style.background = 'transparent';
                              e.currentTarget.style.boxShadow = 'none';
                              e.currentTarget.style.border = 'none';
                              e.currentTarget.style.borderBottom = '1px solid rgba(255,255,255,0.06)';
                              e.currentTarget.style.zIndex = '1';
                              const evId = Number(e.dataTransfer.getData('text/plain'));
                              if (evId) {
                                const rect = e.currentTarget.getBoundingClientRect();
                                const offsetY = Math.max(0, Math.min(59, e.clientY - rect.top));
                                const minute = Math.min(45, Math.floor(offsetY / 15) * 15);
                                handleDropOnDate(evId, d.dateStr, hour, minute);
                              }
                            }}
                            onClick={() => {
                              const [y, m, dayNum] = d.dateStr.split('-').map(Number);
                              const targetDate = new Date(y, m - 1, dayNum, hour, 0, 0);
                              openNewEventModal(undefined, targetDate);
                            }}
                            style={{
                              position: 'absolute',
                              top: `${hour * 60}px`,
                              left: 0,
                              right: 0,
                              height: '60px',
                              borderBottom: '1px solid rgba(255,255,255,0.06)',
                              cursor: 'pointer',
                              transition: 'background 0.1s ease, box-shadow 0.1s ease'
                            }}
                          />
                        ))}

                        {/* Red Line Current Time Indicator */}
                        {isCurrentDay && (
                          <div
                            style={{
                              position: 'absolute',
                              top: `${redLineTopPx}px`,
                              left: 0,
                              right: 0,
                              height: '2px',
                              backgroundColor: '#ef4444',
                              zIndex: 15,
                              pointerEvents: 'none'
                            }}
                          >
                            <div style={{
                              position: 'absolute',
                              left: '-5px',
                              top: '-4px',
                              width: '10px',
                              height: '10px',
                              borderRadius: '50%',
                              backgroundColor: '#ef4444'
                            }} />
                          </div>
                        )}

                        {/* Absolute Positioned Event Blocks */}
                        {dayEvents.map(ev => {
                          const startDt = new Date(ev.start_time);
                          const endDt = ev.end_time ? new Date(ev.end_time) : new Date(startDt.getTime() + 60 * 60 * 1000);
                          const startMin = startDt.getHours() * 60 + startDt.getMinutes();
                          const endMin = endDt.getHours() * 60 + endDt.getMinutes();
                          const durationMin = Math.max(30, endMin - startMin);

                          const topPx = (startMin / 60) * 60;
                          const heightPx = Math.max(26, (durationMin / 60) * 60 - 3);

                          const startHourStr = `${String(startDt.getHours()).padStart(2, '0')}:${String(startDt.getMinutes()).padStart(2, '0')}`;
                          const endHourStr = `${String(endDt.getHours()).padStart(2, '0')}:${String(endDt.getMinutes()).padStart(2, '0')}`;
                          const timeRangeText = `${startHourStr} - ${endHourStr}`;

                          const isDone = ev.status === 'concluido';

                          return (
                            <div
                              key={ev.id}
                              draggable={true}
                              onDragStart={(e) => {
                                e.dataTransfer.setData('text/plain', String(ev.id));
                                e.dataTransfer.effectAllowed = 'move';
                              }}
                              onDragOver={(e) => {
                                e.preventDefault();
                                e.dataTransfer.dropEffect = 'move';
                              }}
                              onDrop={(e) => {
                                e.preventDefault();
                                const evId = Number(e.dataTransfer.getData('text/plain'));
                                if (!evId) return;
                                const rect = e.currentTarget.getBoundingClientRect();
                                const offsetY = Math.max(0, e.clientY - rect.top);
                                const totalMinutes = Math.min(23 * 60 + 45, Math.floor((startMin + offsetY) / 15) * 15);
                                const newHour = Math.floor(totalMinutes / 60);
                                const newMinute = totalMinutes % 60;
                                handleDropOnDate(evId, d.dateStr, newHour, newMinute);
                              }}
                              onClick={(e) => {
                                e.stopPropagation();
                                openEditEventModal(ev);
                              }}
                              onContextMenu={(e) => handleOpenContextMenu(e, ev)}
                              style={{
                                position: 'absolute',
                                top: `${topPx}px`,
                                height: `${heightPx}px`,
                                left: '3px',
                                right: '3px',
                                backgroundColor: isDone ? 'rgba(255, 255, 255, 0.1)' : (ev.color || '#ea580c'),
                                color: '#fff',
                                borderRadius: '6px',
                                padding: '3px 8px',
                                fontSize: '11px',
                                fontWeight: '700',
                                cursor: 'grab',
                                overflow: 'hidden',
                                textOverflow: 'ellipsis',
                                whiteSpace: 'nowrap',
                                boxShadow: '0 2px 6px rgba(0,0,0,0.4)',
                                zIndex: 10,
                                opacity: isDone ? 0.65 : 1,
                                display: 'flex',
                                flexDirection: 'column',
                                justifyContent: 'flex-start',
                                borderLeft: `3px solid rgba(255,255,255,0.4)`
                              }}
                              title={`${ev.title} (${timeRangeText}) - Arraste para reposicionar no horário desejado`}
                            >
                              <div style={{ overflow: 'hidden', textOverflow: 'ellipsis', whiteSpace: 'nowrap' }}>
                                {ev.title}
                              </div>
                              <div style={{ fontSize: '10px', opacity: 0.85, fontWeight: 'normal' }}>
                                {timeRangeText}
                              </div>
                            </div>
                          );
                        })}
                      </div>
                    );
                  })}
                </div>
              </div>
            )}

            {/* 2. DAY VIEW (Google Calendar Style Single Day) */}
            {viewMode === 'day' && (
              <div style={{ flex: 1, display: 'flex', flexDirection: 'column', height: '100%', overflow: 'hidden' }}>
                {/* Sticky Header */}
                <div style={{
                  display: 'grid',
                  gridTemplateColumns: '65px 1fr',
                  borderBottom: '1px solid var(--border-color)',
                  backgroundColor: '#181d2c',
                  zIndex: 20,
                  boxShadow: '0 2px 8px rgba(0,0,0,0.3)',
                  flexShrink: 0
                }}>
                  <div style={{
                    padding: '12px 6px',
                    textAlign: 'center',
                    fontSize: '10px',
                    fontWeight: 'bold',
                    color: 'var(--text-muted)',
                    borderRight: '1px solid var(--border-color)',
                    display: 'flex',
                    alignItems: 'center',
                    justifyContent: 'center'
                  }}>
                    GMT-03
                  </div>
                  <div style={{ padding: '10px 16px', display: 'flex', alignItems: 'center', gap: '12px' }}>
                    <div style={{
                      fontSize: '18px',
                      fontWeight: '800',
                      color: '#fff',
                      width: '32px',
                      height: '32px',
                      borderRadius: '50%',
                      backgroundColor: '#1a73e8',
                      display: 'flex',
                      alignItems: 'center',
                      justifyContent: 'center'
                    }}>
                      {currentDate.getDate()}
                    </div>
                    <div>
                      <div style={{ fontSize: '13px', fontWeight: 'bold', color: '#fff' }}>
                        {currentDate.toLocaleDateString('pt-BR', { weekday: 'long' }).toUpperCase()}
                      </div>
                      <div style={{ fontSize: '11px', color: 'var(--text-muted)' }}>
                        {currentDate.toLocaleDateString('pt-BR', { day: '2-digit', month: 'long', year: 'numeric' })}
                      </div>
                    </div>
                  </div>
                </div>

                {/* Scrollable Day Grid */}
                <div
                  ref={timeGridRef}
                  style={{
                    flex: 1,
                    overflowY: 'auto',
                    display: 'grid',
                    gridTemplateColumns: '65px 1fr',
                    position: 'relative',
                    backgroundColor: '#0f131d'
                  }}
                >
                  {/* Left Column (24 Hours Labels) */}
                  <div style={{
                    height: '1440px',
                    position: 'relative',
                    borderRight: '1px solid var(--border-color)',
                    backgroundColor: 'rgba(0,0,0,0.2)'
                  }}>
                    {HOURS_24.map(h => (
                      <div
                        key={h}
                        style={{
                          position: 'absolute',
                          top: `${h * 60 - 8}px`,
                          right: '8px',
                          fontSize: '11px',
                          color: 'var(--text-muted)',
                          fontWeight: '600'
                        }}
                      >
                        {h === 0 ? '12 AM' : h < 12 ? `${h} AM` : h === 12 ? '12 PM' : `${h - 12} PM`}
                      </div>
                    ))}
                  </div>

                  {/* Single Day Area */}
                  {(() => {
                    const curDateStr = formatLocalDateStr(currentDate);
                    const dayEvents = filteredEvents.filter(ev => {
                      if (ev.all_day) return false;
                      const evDt = new Date(ev.start_time);
                      const evDate = formatLocalDateStr(evDt);
                      return evDate === curDateStr;
                    });

                    const now = new Date();
                    const isCurrentDay = curDateStr === todayStr;
                    const nowMinutes = now.getHours() * 60 + now.getMinutes();
                    const redLineTopPx = (nowMinutes / 60) * 60;

                    return (
                      <div
                        onDragOver={(e) => {
                          e.preventDefault();
                          e.dataTransfer.dropEffect = 'move';
                        }}
                        onDrop={(e) => {
                          e.preventDefault();
                          const evId = Number(e.dataTransfer.getData('text/plain'));
                          if (!evId) return;
                          const rect = e.currentTarget.getBoundingClientRect();
                          const offsetY = Math.max(0, e.clientY - rect.top);
                          const totalMinutes = Math.min(23 * 60 + 45, Math.floor(offsetY / 15) * 15);
                          const newHour = Math.floor(totalMinutes / 60);
                          const newMinute = totalMinutes % 60;
                          handleDropOnDate(evId, curDateStr, newHour, newMinute);
                        }}
                        style={{ position: 'relative', height: '1440px' }}
                      >
                        {/* 24 Grid Lines & Slots */}
                        {HOURS_24.map(hour => (
                          <div
                            key={hour}
                            onDragOver={(e) => {
                              e.preventDefault();
                              e.dataTransfer.dropEffect = 'move';
                              e.currentTarget.style.background = 'linear-gradient(90deg, rgba(59, 130, 246, 0.4) 0%, rgba(37, 99, 235, 0.28) 100%)';
                              e.currentTarget.style.boxShadow = 'inset 0 0 16px rgba(59, 130, 246, 0.65), 0 0 12px rgba(59, 130, 246, 0.4)';
                              e.currentTarget.style.border = '1.5px dashed #60a5fa';
                              e.currentTarget.style.zIndex = '5';
                            }}
                            onDragLeave={(e) => {
                              e.currentTarget.style.background = 'transparent';
                              e.currentTarget.style.boxShadow = 'none';
                              e.currentTarget.style.border = 'none';
                              e.currentTarget.style.borderBottom = '1px solid rgba(255,255,255,0.06)';
                              e.currentTarget.style.zIndex = '1';
                            }}
                            onDrop={(e) => {
                              e.preventDefault();
                              e.currentTarget.style.background = 'transparent';
                              e.currentTarget.style.boxShadow = 'none';
                              e.currentTarget.style.border = 'none';
                              e.currentTarget.style.borderBottom = '1px solid rgba(255,255,255,0.06)';
                              e.currentTarget.style.zIndex = '1';
                              const evId = Number(e.dataTransfer.getData('text/plain'));
                              if (evId) {
                                const rect = e.currentTarget.getBoundingClientRect();
                                const offsetY = Math.max(0, Math.min(59, e.clientY - rect.top));
                                const minute = Math.min(45, Math.floor(offsetY / 15) * 15);
                                handleDropOnDate(evId, curDateStr, hour, minute);
                              }
                            }}
                            onClick={() => {
                              const [y, m, dayNum] = curDateStr.split('-').map(Number);
                              const targetDate = new Date(y, m - 1, dayNum, hour, 0, 0);
                              openNewEventModal(undefined, targetDate);
                            }}
                            style={{
                              position: 'absolute',
                              top: `${hour * 60}px`,
                              left: 0,
                              right: 0,
                              height: '60px',
                              borderBottom: '1px solid rgba(255,255,255,0.06)',
                              cursor: 'pointer',
                              transition: 'background 0.1s ease, box-shadow 0.1s ease'
                            }}
                          />
                        ))}

                        {/* Red Line Current Time Indicator */}
                        {isCurrentDay && (
                          <div
                            style={{
                              position: 'absolute',
                              top: `${redLineTopPx}px`,
                              left: 0,
                              right: 0,
                              height: '2px',
                              backgroundColor: '#ef4444',
                              zIndex: 15,
                              pointerEvents: 'none'
                            }}
                          >
                            <div style={{
                              position: 'absolute',
                              left: '-5px',
                              top: '-4px',
                              width: '10px',
                              height: '10px',
                              borderRadius: '50%',
                              backgroundColor: '#ef4444'
                            }} />
                          </div>
                        )}

                        {/* Absolute Event Blocks */}
                        {dayEvents.map(ev => {
                          const startDt = new Date(ev.start_time);
                          const endDt = ev.end_time ? new Date(ev.end_time) : new Date(startDt.getTime() + 60 * 60 * 1000);
                          const startMin = startDt.getHours() * 60 + startDt.getMinutes();
                          const endMin = endDt.getHours() * 60 + endDt.getMinutes();
                          const durationMin = Math.max(30, endMin - startMin);

                          const topPx = (startMin / 60) * 60;
                          const heightPx = Math.max(32, (durationMin / 60) * 60 - 3);

                          const startHourStr = `${String(startDt.getHours()).padStart(2, '0')}:${String(startDt.getMinutes()).padStart(2, '0')}`;
                          const endHourStr = `${String(endDt.getHours()).padStart(2, '0')}:${String(endDt.getMinutes()).padStart(2, '0')}`;
                          const timeRangeText = `${startHourStr} - ${endHourStr}`;

                          const isDone = ev.status === 'concluido';

                          return (
                            <div
                              key={ev.id}
                              draggable={true}
                              onDragStart={(e) => {
                                e.dataTransfer.setData('text/plain', String(ev.id));
                                e.dataTransfer.effectAllowed = 'move';
                              }}
                              onDragOver={(e) => {
                                e.preventDefault();
                                e.dataTransfer.dropEffect = 'move';
                              }}
                              onDrop={(e) => {
                                e.preventDefault();
                                const evId = Number(e.dataTransfer.getData('text/plain'));
                                if (!evId) return;
                                const rect = e.currentTarget.getBoundingClientRect();
                                const offsetY = Math.max(0, e.clientY - rect.top);
                                const totalMinutes = Math.min(23 * 60 + 45, Math.floor((startMin + offsetY) / 15) * 15);
                                const newHour = Math.floor(totalMinutes / 60);
                                const newMinute = totalMinutes % 60;
                                handleDropOnDate(evId, curDateStr, newHour, newMinute);
                              }}
                              onClick={(e) => {
                                e.stopPropagation();
                                openEditEventModal(ev);
                              }}
                              onContextMenu={(e) => handleOpenContextMenu(e, ev)}
                              style={{
                                position: 'absolute',
                                top: `${topPx}px`,
                                height: `${heightPx}px`,
                                left: '8px',
                                right: '8px',
                                backgroundColor: isDone ? 'rgba(255, 255, 255, 0.1)' : (ev.color || '#ea580c'),
                                color: '#fff',
                                borderRadius: '8px',
                                padding: '6px 12px',
                                fontSize: '13px',
                                fontWeight: '700',
                                cursor: 'grab',
                                overflow: 'hidden',
                                textOverflow: 'ellipsis',
                                whiteSpace: 'nowrap',
                                boxShadow: '0 2px 8px rgba(0,0,0,0.4)',
                                zIndex: 10,
                                opacity: isDone ? 0.65 : 1,
                                display: 'flex',
                                alignItems: 'center',
                                justifyContent: 'space-between',
                                borderLeft: `4px solid rgba(255,255,255,0.4)`
                              }}
                              title={`${ev.title} (${timeRangeText}) - Arraste para mover`}
                            >
                              <div style={{ display: 'flex', alignItems: 'center', gap: '8px', overflow: 'hidden' }}>
                                <div style={{ overflow: 'hidden', textOverflow: 'ellipsis', whiteSpace: 'nowrap' }}>
                                  {ev.title}
                                </div>
                                <span style={{ fontSize: '11px', opacity: 0.85, fontWeight: 'normal' }}>
                                  ({timeRangeText})
                                </span>
                              </div>
                              {ev.employee_name && (
                                <span style={{ fontSize: '11px', backgroundColor: 'rgba(0,0,0,0.2)', padding: '2px 8px', borderRadius: '10px' }}>
                                  👤 {ev.employee_name}
                                </span>
                              )}
                            </div>
                          );
                        })}
                      </div>
                    );
                  })()}
                </div>
              </div>
            )}

            {/* 3. MONTH VIEW */}
            {viewMode === 'month' && (
              <div style={{ flex: 1, display: 'flex', flexDirection: 'column', height: '100%', overflowY: 'auto' }}>
                {/* Sticky Weekday Header */}
                <div style={{
                  position: 'sticky',
                  top: 0,
                  zIndex: 20,
                  display: 'grid',
                  gridTemplateColumns: 'repeat(7, 1fr)',
                  borderBottom: '1px solid var(--border-color)',
                  backgroundColor: '#181d2c',
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
                      const evDt = new Date(ev.start_time);
                      const evDateStr = formatLocalDateStr(evDt);
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
                          e.currentTarget.style.background = 'linear-gradient(135deg, rgba(59, 130, 246, 0.38) 0%, rgba(37, 99, 235, 0.28) 100%)';
                          e.currentTarget.style.boxShadow = 'inset 0 0 18px rgba(59, 130, 246, 0.7), 0 0 14px rgba(59, 130, 246, 0.5)';
                          e.currentTarget.style.borderColor = '#60a5fa';
                        }}
                        onDragLeave={(e) => {
                          e.currentTarget.style.background = isToday
                            ? 'rgba(16, 185, 129, 0.05)'
                            : cell.isCurrentMonth ? 'transparent' : 'rgba(0, 0, 0, 0.25)';
                          e.currentTarget.style.boxShadow = 'none';
                          e.currentTarget.style.borderColor = 'var(--border-color)';
                        }}
                        onDrop={(e) => {
                          e.preventDefault();
                          e.currentTarget.style.background = isToday
                            ? 'rgba(16, 185, 129, 0.05)'
                            : cell.isCurrentMonth ? 'transparent' : 'rgba(0, 0, 0, 0.25)';
                          e.currentTarget.style.boxShadow = 'none';
                          e.currentTarget.style.borderColor = 'var(--border-color)';
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
                          transition: 'background 0.15s, box-shadow 0.15s, border-color 0.15s'
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
                            backgroundColor: isToday ? '#1a73e8' : 'transparent',
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
                            const evDt = new Date(ev.start_time);
                            const timeStr = ev.all_day ? '' : `${String(evDt.getHours()).padStart(2, '0')}:${String(evDt.getMinutes()).padStart(2, '0')}`;

                            return (
                              <div
                                key={ev.id}
                                draggable={true}
                                onDragStart={(e) => {
                                  e.dataTransfer.setData('text/plain', String(ev.id));
                                  e.dataTransfer.effectAllowed = 'move';
                                }}
                                onClick={e => {
                                  e.stopPropagation();
                                  openEditEventModal(ev);
                                }}
                                onContextMenu={(e) => handleOpenContextMenu(e, ev)}
                                style={{
                                  backgroundColor: isDone ? 'rgba(255, 255, 255, 0.05)' : (ev.color || '#ea580c'),
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

            {/* 4. AGENDA / LIST VIEW */}
            {viewMode === 'agenda' && (
              <div style={{ padding: '24px', maxWidth: '900px', margin: '0 auto', width: '100%', overflowY: 'auto' }}>
                {filteredEvents.length === 0 ? (
                  <div style={{
                    textAlign: 'center',
                    padding: '60px 20px',
                    color: 'var(--text-muted)'
                  }}>
                    <CalendarIcon size={56} style={{ margin: '0 auto 16px', opacity: 0.3 }} />
                    <h3 style={{ fontSize: '18px', color: '#fff', marginBottom: '8px' }}>Nenhuma tarefa encontrada</h3>
                    <p style={{ fontSize: '13px' }}>Clique em "+ Criar" para agendar uma nova tarefa.</p>
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
                          onContextMenu={(e) => handleOpenContextMenu(e, ev)}
                          style={{
                            backgroundColor: 'var(--bg-primary)',
                            border: `1px solid ${isDone ? 'var(--border-color)' : 'rgba(255,255,255,0.08)'}`,
                            borderLeft: `5px solid ${ev.color || '#ea580c'}`,
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
                              </div>

                              <div style={{ display: 'flex', alignItems: 'center', gap: '12px', marginTop: '6px', fontSize: '12px', color: 'var(--text-muted)', flexWrap: 'wrap' }}>
                                <span style={{ display: 'flex', alignItems: 'center', gap: '4px' }}>
                                  <Clock size={13} /> {formattedDate} • {timeStr}
                                </span>

                                {ev.contact_name && (
                                  <span style={{ display: 'flex', alignItems: 'center', gap: '4px', color: 'var(--accent-primary)' }}>
                                    <User size={13} /> {ev.contact_name}
                                  </span>
                                )}
                              </div>
                            </div>
                          </div>

                          <div style={{ display: 'flex', alignItems: 'center', gap: '8px' }}>
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

                  {/* Department / WhatsApp Instance Selector */}
                  <div style={{
                    display: 'flex',
                    flexDirection: 'column',
                    gap: '4px',
                    backgroundColor: 'rgba(0, 0, 0, 0.25)',
                    padding: '8px 10px',
                    borderRadius: '8px',
                    border: '1px solid rgba(0, 230, 153, 0.2)'
                  }}>
                    <label style={{ fontSize: '11px', color: '#a7f3d0', fontWeight: 'bold' }}>
                      🏢 ENVIAR PELO WHATSAPP DO DEPARTAMENTO:
                    </label>
                    <select
                      value={formWhatsappNumberId}
                      onChange={e => {
                        const val = e.target.value;
                        setFormWhatsappNumberId(val ? Number(val) : '');
                        if (val) {
                          const found = whatsappNumbers.find(w => w.id === Number(val));
                          setFormWhatsappInstance(found?.instancia_evolution_api || '');
                        } else {
                          setFormWhatsappInstance('');
                        }
                      }}
                      style={{
                        padding: '6px 10px',
                        borderRadius: '6px',
                        border: '1px solid var(--border-color)',
                        backgroundColor: 'var(--bg-primary)',
                        color: '#fff',
                        fontSize: '12px',
                        outline: 'none',
                        cursor: 'pointer'
                      }}
                    >
                      <option value="">🤖 Automático (Roteamento Inteligente / Padrão)</option>
                      {whatsappNumbers.filter(w => w.status).map(wn => (
                        <option key={wn.id} value={wn.id}>
                          {wn.nome_departamento} ({wn.numero || wn.instancia_evolution_api})
                        </option>
                      ))}
                    </select>
                  </div>

                  <div style={{ fontSize: '11px', color: '#a7f3d0', lineHeight: '1.4' }}>
                    A mensagem da atividade será enviada para o WhatsApp de <strong>{formEmployeeName}</strong> ({formEmployeePhone}) com os botões interativos de visualização e conclusão!
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

      {/* Floating Right-Click Context Menu (Google Calendar Style) */}
      {contextMenu.isOpen && contextMenu.event && (
        <div
          onClick={e => e.stopPropagation()}
          style={{
            position: 'fixed',
            left: `${contextMenu.x}px`,
            top: `${contextMenu.y}px`,
            backgroundColor: '#202124',
            border: '1px solid rgba(255, 255, 255, 0.12)',
            borderRadius: '8px',
            boxShadow: '0 8px 24px rgba(0,0,0,0.7)',
            padding: '8px',
            width: '230px',
            zIndex: 9999,
            display: 'flex',
            flexDirection: 'column',
            gap: '8px',
            animation: 'fadeIn 0.1s ease'
          }}
        >
          {/* Excluir Option */}
          <button
            type="button"
            onClick={() => {
              const evId = contextMenu.event!.id;
              setContextMenu({ isOpen: false, x: 0, y: 0, event: null });
              handleDeleteEvent(evId);
            }}
            style={{
              display: 'flex',
              alignItems: 'center',
              gap: '10px',
              width: '100%',
              padding: '8px 10px',
              backgroundColor: 'transparent',
              border: 'none',
              borderRadius: '6px',
              color: '#f87171',
              fontSize: '13px',
              fontWeight: '600',
              cursor: 'pointer',
              textAlign: 'left',
              transition: 'background 0.15s'
            }}
            onMouseEnter={e => e.currentTarget.style.backgroundColor = 'rgba(239, 68, 68, 0.15)'}
            onMouseLeave={e => e.currentTarget.style.backgroundColor = 'transparent'}
          >
            <Trash2 size={16} />
            <span>Excluir</span>
          </button>

          {/* Separator */}
          <div style={{ height: '1px', backgroundColor: 'rgba(255, 255, 255, 0.1)', margin: '2px 0' }} />

          {/* Status Section */}
          <div>
            <div style={{ display: 'flex', alignItems: 'center', gap: '6px', padding: '0 4px 6px', color: 'var(--text-muted)', fontSize: '11px', fontWeight: 'bold' }}>
              <CheckSquare size={13} />
              <span>Status do Compromisso</span>
            </div>

            <div style={{ display: 'flex', flexDirection: 'column', gap: '3px' }}>
              {[
                { id: 'pendente', label: 'Pendente', color: '#f59e0b', bg: 'rgba(245, 158, 11, 0.15)' },
                { id: 'em_progresso', label: 'Em Andamento', color: '#3b82f6', bg: 'rgba(59, 130, 246, 0.15)' },
                { id: 'concluido', label: 'Concluído', color: '#10b981', bg: 'rgba(16, 185, 129, 0.15)' },
                { id: 'cancelado', label: 'Cancelado', color: '#ef4444', bg: 'rgba(239, 68, 68, 0.15)' },
              ].map(st => {
                const isCurrent = contextMenu.event?.status === st.id;
                return (
                  <button
                    key={st.id}
                    type="button"
                    onClick={() => handleChangeEventStatus(contextMenu.event!, st.id as any)}
                    style={{
                      display: 'flex',
                      alignItems: 'center',
                      justifyContent: 'space-between',
                      width: '100%',
                      padding: '6px 8px',
                      backgroundColor: isCurrent ? st.bg : 'transparent',
                      border: isCurrent ? `1px solid ${st.color}40` : '1px solid transparent',
                      borderRadius: '6px',
                      color: isCurrent ? st.color : '#e2e8f0',
                      fontSize: '12px',
                      fontWeight: isCurrent ? 'bold' : '500',
                      cursor: 'pointer',
                      textAlign: 'left',
                      transition: 'background 0.1s'
                    }}
                    onMouseEnter={e => {
                      if (!isCurrent) e.currentTarget.style.backgroundColor = 'rgba(255, 255, 255, 0.06)';
                    }}
                    onMouseLeave={e => {
                      if (!isCurrent) e.currentTarget.style.backgroundColor = 'transparent';
                    }}
                  >
                    <div style={{ display: 'flex', alignItems: 'center', gap: '8px' }}>
                      <span style={{
                        width: '8px',
                        height: '8px',
                        borderRadius: '50%',
                        backgroundColor: st.color,
                        display: 'inline-block'
                      }} />
                      <span>{st.label}</span>
                    </div>
                    {isCurrent && <Check size={13} color={st.color} strokeWidth={2.5} />}
                  </button>
                );
              })}
            </div>
          </div>

          {/* Separator */}
          <div style={{ height: '1px', backgroundColor: 'rgba(255, 255, 255, 0.1)', margin: '2px 0' }} />

          {/* Colors Palette */}
          <div>
            <div style={{ display: 'flex', alignItems: 'center', gap: '6px', padding: '0 4px 6px', color: 'var(--text-muted)', fontSize: '11px', fontWeight: 'bold' }}>
              <Edit3 size={13} />
              <span>Cor do Compromisso</span>
            </div>
            
            <div style={{
              display: 'grid',
              gridTemplateColumns: 'repeat(8, 1fr)',
              gap: '6px',
              padding: '2px 4px'
            }}>
              {GOOGLE_CALENDAR_PALETTE.map(color => {
                const isSelected = contextMenu.event?.color === color;
                return (
                  <button
                    key={color}
                    type="button"
                    title={color}
                    onClick={() => handleChangeEventColor(contextMenu.event!, color)}
                    style={{
                      width: '20px',
                      height: '20px',
                      borderRadius: '50%',
                      backgroundColor: color,
                      border: isSelected ? '2px solid #fff' : 'none',
                      cursor: 'pointer',
                      display: 'flex',
                      alignItems: 'center',
                      justifyContent: 'center',
                      padding: 0,
                      transition: 'transform 0.1s ease',
                      boxShadow: isSelected ? '0 0 6px rgba(255,255,255,0.6)' : 'none'
                    }}
                    onMouseEnter={e => e.currentTarget.style.transform = 'scale(1.2)'}
                    onMouseLeave={e => e.currentTarget.style.transform = 'scale(1)'}
                  >
                    {isSelected && <Check size={11} color="#fff" strokeWidth={3} />}
                  </button>
                );
              })}
            </div>

            {/* Padrão Button */}
            <div style={{ marginTop: '8px', padding: '0 4px' }}>
              <button
                type="button"
                onClick={() => handleChangeEventColor(contextMenu.event!, '#ea580c')}
                style={{
                  width: '100%',
                  display: 'flex',
                  alignItems: 'center',
                  justifyContent: 'center',
                  gap: '6px',
                  padding: '6px',
                  backgroundColor: 'rgba(255, 255, 255, 0.06)',
                  border: '1px solid rgba(255, 255, 255, 0.15)',
                  borderRadius: '16px',
                  color: '#fff',
                  fontSize: '12px',
                  fontWeight: '600',
                  cursor: 'pointer',
                  transition: 'background 0.15s'
                }}
                onMouseEnter={e => e.currentTarget.style.backgroundColor = 'rgba(255, 255, 255, 0.12)'}
                onMouseLeave={e => e.currentTarget.style.backgroundColor = 'rgba(255, 255, 255, 0.06)'}
              >
                <Circle size={12} fill="#ea580c" color="#ea580c" />
                <span>Padrão</span>
              </button>
            </div>
          </div>
        </div>
      )}
    </div>
  );
};
