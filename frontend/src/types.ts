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
  status: ConversationStatus;
  assigned_user_id?: number;
  assigned_user_name?: string;
  resumo_ia?: string;
  assunto_atual?: string;
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
  especialidade?: string;
  ativo: boolean;
  criado_em: string;
}

