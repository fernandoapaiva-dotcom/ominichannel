export type UserRole = 'admin' | 'atendente';
export type ConversationStatus = 'com_ia' | 'com_humano' | 'encerrada' | 'expirada_por_inatividade';
export type MessageSender = 'cliente' | 'ia' | 'atendente' | 'sistema';
export type MessageType = 'texto' | 'audio' | 'imagem' | 'video' | 'arquivo';

export interface WhatsAppNumber {
  id: number;
  tenant_id: number;
  provider_type?: 'evolution' | 'meta';
  numero: string;
  nome_departamento: string;
  instancia_evolution_api?: string;
  meta_phone_number_id?: string;
  meta_waba_id?: string;
  meta_access_token_masked?: string;
  status: boolean;
}

export interface User {
  id: number;
  tenant_id: number;
  nome: string;
  login: string;
  foto_perfil_url?: string | null;
  role: UserRole;
  status: boolean;
  whatsapp_numbers: WhatsAppNumber[];
}

export interface Contact {
  id: number;
  tenant_id: number;
  telefone: string;
  nome?: string;
  foto_perfil_url?: string | null;
  dados_adicionais?: Record<string, any>;
}

export interface Message {
  id: number;
  conversation_id: number;
  remetente: MessageSender;
  conteudo: string;
  tipo: MessageType;
  status?: 'sending' | 'pending' | 'sent' | 'delivered' | 'read' | 'failed';
  whatsapp_msg_id?: string;
}

export interface Conversation {
  id: number;
  tenant_id: number;
  whatsapp_number_id: number;
  contact_id: number;
  protocol_number?: string;
  status: ConversationStatus;
  assigned_user_id?: number;
  assigned_user_name?: string;
  resumo_ia?: string;
  assunto_atual?: string;
  dados_adicionais?: Record<string, any>;
  criado_em: string;
  ultima_interacao_em: string;
  contact?: Contact;
  whatsapp_number?: WhatsAppNumber;
  messages: Message[];
}


export interface WhatsAppGroup {
  id: number;
  tenant_id: number;
  whatsapp_number_id: number;
  group_jid: string;
  nome: string;
  ia_ativa: boolean;
  criado_em?: string;
  departamento?: string;
  instancia?: string;
  numero?: string;
}

export interface AuthorizedTechnician {
  id: number;
  tenant_id: number;
  nome: string;
  telefone: string;
  cargo?: string | null;
  departamento?: string | null;
  especialidade?: string | null;
  ativo: boolean;
  criado_em: string;
}

export interface CalendarEvent {
  id: number;
  tenant_id: number;
  user_id: number;
  contact_id?: number | null;
  conversation_id?: number | null;
  message_id?: number | null;
  title: string;
  description?: string | null;
  event_type?: string;
  start_time: string;
  end_time?: string | null;
  all_day: boolean;
  color: string;
  priority: 'baixa' | 'media' | 'alta' | 'urgente';
  status: 'pendente' | 'em_progresso' | 'concluido' | 'cancelado';
  reminder_minutes?: number | null;
  employee_id?: number | null;
  employee_name?: string | null;
  employee_phone?: string | null;
  notify_whatsapp?: boolean;
  notified_creation?: boolean;
  notified_day_of?: boolean;
  notified_hours_before?: boolean;
  custom_reminder_hours?: number;
  confirmed_by_employee?: boolean;
  confirmed_at?: string | null;
  confirmation_token?: string | null;
  criado_em: string;
  atualizado_em: string;
  contact_name?: string | null;
  contact_phone?: string | null;
}


