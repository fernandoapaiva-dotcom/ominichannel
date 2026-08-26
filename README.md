# 🚀 OminiChannel - Plataforma Omnichannel Inteligente com IA Concierge (Gemini RAG), Automações de OS, Agenda Interativa & WhatsApp

[![Python](https://img.shields.io/badge/Python-3.11+-blue.svg)](https://www.python.org/)
[![FastAPI](https://img.shields.io/badge/FastAPI-0.100+-green.svg)](https://fastapi.tiangolo.com/)
[![React](https://img.shields.io/badge/React-18+-61DAFB.svg)](https://react.dev/)
[![TypeScript](https://img.shields.io/badge/TypeScript-5.0+-3178C6.svg)](https://www.typescriptlang.org/)
[![Vite](https://img.shields.io/badge/Vite-5.0+-646CFF.svg)](https://vitejs.dev/)
[![Docker](https://img.shields.io/badge/Docker-Supported-2496ED.svg)](https://www.docker.com/)

---

## 🌐 Language / Idioma
- [Português (Brasil) 🇧🇷](#-português-brasil)
- [English 🇺🇸](#-english)

---

## 🇧🇷 Português (Brasil)

### 📋 Sobre o Projeto
**OminiChannel** é uma plataforma corporativa multi-tenant de atendimento omnichannel que combina o poder de Modelos de Linguagem de Grande Porte (**LLMs via Google Gemini RAG**), automações inteligentes de Ordens de Serviço (OS), agenda corporativa interativa com fluxo de aceite pelo WhatsApp, repositório multimídia em tempo real e integração nativa com o **WhatsApp** (via Evolution API v2 e Meta Cloud API).

A plataforma automatiza a triagem, qualificação, resposta de dúvidas técnicas, cálculo de taxas de diagnóstico, cotações, geração de Pix BACEN com QR Code e o **gerenciamento de chamados técnicos e tarefas de campo** com botões interativos no WhatsApp do colaborador. Quando a solicitação exige intervenção humana, o sistema realiza a **distribuição inteligente por menor carga de trabalho (*least-busy operator*)** e notifica o atendente em tempo real via **WebSockets** com um **Resumo Estruturado da IA**.

---

### ✨ Principais Funcionalidades

#### 1. ⚡ **Automações & Gatilhos Inteligentes (OS & Respostas Padrão com IA Copilot)**
* **🛠️ Handler de Ordem de Serviço (Posto Autorizado):**
  - Identificação e parsing automático de mensagens de abertura de OS (ex: `status: orcamento`, `status: garantia de loja`, `status: garantia de fabrica`).
  - Reconhece o tipo de equipamento (Inversor, MIG, TIG, Plasma, CNC, Compressor, etc.) e aplica a taxa de diagnóstico configurada.
  - Disparo de sequências encadeadas de mensagens com saudação dinâmica (*Bom dia / Boa tarde*), nome do cliente, taxas, prazos de validade (15 dias), garantias (90 dias) e condições de sucateamento/abandono.
  - Modos de disparo flexíveis: quando o atendente/sistema envia a mensagem, quando o cliente envia, ou ambos.
* **💰 Tabela Interativa de Preços de Diagnóstico Técnico:**
  - Cadastro, busca rápida, edição e exclusão de taxas por equipamento em tempo real.
* **🤖 Assistente Copilot de Criação com IA:**
  - Chat interativo com o Gemini dentro das configurações para criar e refinar regras conversando em linguagem natural, com botão de aplicação instantânea (`✨ Aplicar Gatilho no Sistema`).
* **⏳ Simulação de "Digitando..." no WhatsApp:**
  - Envio de presença nativa (`composing`) com tempo de espera configurável por slider antes de cada balão.
* **🧪 Simulador em Tempo Real:**
  - Testador integrado para colar mensagens de OS ou dúvidas e validar a sequência de respostas antes de colocar em produção.
* **🎛️ Controle de Condições de Ativação:**
  - Suporte aos modos `Qualquer uma das palavras (OU)` e `Todas obrigatórias (E)`.

---

#### 2. 🤖 **IA Concierge com RAG Multimodal & Memórias Contínuas (Google Gemini)**
* Respostas inteligentes e contextualizadas baseadas em arquivos corporativos (`.pdf`, `.docx`, `.txt`).
* Suporte aos modelos de alta performance da família Gemini (`gemini-2.5-flash`, `gemini-3.1-flash-lite`).
* **Base RAG por Setor e Geral:** segmentação de documentos para Atendimento Geral, Técnico, Financeiro e Locação.
* **Banner de Resumo da IA:** síntese contextual exibida no topo do chat para os atendentes humanos.
* **Escudo Anti-Loop & Anti-Echo:** silenciamento automático contra números internos da empresa e robôs de outras empresas.

---

#### 3. 🖼️ **Repositório Avançado de Mídias & Arquivos**
* **Busca Instantânea em Tempo Real:** pesquise por nome do arquivo, legenda, atendente/cliente ou data.
* **Miniaturas Reais de Fotos:** visualização em alta definição com zoom Lightbox ao clicar.
* **Preview e Player de Vídeo:** reprodução direta na galeria com indicador de play.
* **Capa da 1ª Página de PDFs:** visualizador automático da primeira página de documentos sem necessidade de download prévio.
* **Alternador Grade / Lista:** navegue em formato de Cards visuais ou Lista detalhada com metadados.
* **Citação & Resposta Visual a Mídias:** barra de resposta ("Respondendo a...") e balões de citação exibem miniaturas reais e legendas amigáveis em vez de links brutos.

---

#### 4. 📅 **Agenda Interativa & Gestão de Chamados com Ciclo WhatsApp**
* **Agendamento Completo:** criação e edição de tarefas com seleção de tipo (Visitas Técnicas, Entregas de Gás, Manutenções, Vendas, Atendimentos), prioridades, horários e cliente vinculado.
* **Sequência Interativa de Tarefas no WhatsApp do Funcionário:**
  - **1️⃣ Notificação de Agendamento:** O colaborador recebe o aviso da atividade com botões interativos (`Sim, confirmo a atividade` / `Não, quero recusar`).
  - **2️⃣ Aceite & Detalhes da Atividade:** Ao aceitar, o evento na agenda muda em tempo real para 🟡 **Em Andamento** e a IA entrega os dados completos da tarefa.
  - **3️⃣ Recusa com Registro:** Ao recusar, o evento no calendário muda para 🔴 **Cancelado** e fica sinalizado para remanejamento.
  - **4️⃣ Conclusão Automática:** Ao finalizar, o evento é marcado como 🟢 **Concluído** no calendário.

---

#### 5. 💳 **Gestão de Chaves Pix com Gerador BACEN & QR Code**
* Cadastro e controle de múltiplas chaves Pix (CNPJ, E-mail, Telefone, EVP).
* Geração instantânea de **Payload Copia-e-Cola Padrão Banco Central (BACEN)** com valor dinâmico e QR Code diretamente na conversa com o cliente.

---

#### 6. 💬 **Chat Omnichannel em Tempo Real & Performance 0ms**
* **Fixação Imediata (0ms):** mensagens enviadas pelo atendente aparecem instantaneamente na tela sem sumir durante ciclos de sincronização ou polling.
* **Rolagem Ultra-Suave:** scroll direto no container sem tremidas de tela ou saltos verticais.
* **Gravação de Áudio no Navegador:** gravação e envio direto de áudios em formato nativo do WhatsApp (`audio/ogg; codecs=opus`).
* **Grupos do WhatsApp:** suporte total a conversas em grupo com menções em massa (`@todos`).

---

#### 7. 🛡️ **Watchdog de Auto-Cura do WhatsApp & Resolvedor Canônico de JID**
* **Auto-Heal 30s Loop:** monitoramento contínuo em segundo plano do estado das instâncias, com reconexão automática proativa.
* **Resolvedor Canônico de JID (8 vs 9 Dígitos):** detecção inteligente de números brasileiros (DDD 61 e outros) para garantir 100% de entrega (`DELIVERY_ACK`).

---

#### 8. 🏢 **Multi-Tenant, Segurança Fernet & Auditoria**
* Isolamento total de dados por empresa (*Tenant*).
* **Criptografia Simétrica Fernet:** chaves de API sensíveis (Google Gemini, Evolution API, Google Drive) são criptografadas antes de serem salvas no banco.
* **Trilha de Auditoria:** registro de todas as alterações administrativas com usuário, data e detalhes.
* Níveis de permissão baseados em funções (`Admin` e `Atendente`).

---

### 🛠️ Stack Tecnológica & Arquitetura

#### **Backend (Python / FastAPI)**
* **Linguagem:** Python 3.11+
* **Framework Web:** FastAPI (ASGI assíncrono de alta performance)
* **Banco de Dados & ORM:** SQLAlchemy 2.0 (AsyncIO) + SQLite / PostgreSQL
* **Engine de IA & RAG:** Google GenAI SDK (`google-genai`), LangChain, FAISS / ChromaDB, PyPDF2
* **Motor de Automações:** `AutomationService` com regex normalizado, fuzzy matching e IA Copilot
* **Segurança:** Criptografia Fernet (`cryptography`) + JWT Tokens
* **Push Realtime:** WebSockets nativos (`ws_manager`)
* **Cliente HTTP Async:** `httpx`

#### **Frontend (React / TypeScript / Vite)**
* **Linguagem:** TypeScript
* **Framework UI:** React 18+ (Vite SPA)
* **Estilização:** CSS3 Moderno (Custom Properties, Flexbox/Grid, Dark Mode)
* **Componentes:** Modal de Calendário Avançado, Galeria Multimídia Interativa, Painel de Automações com Copilot IA
* **Ícones:** `lucide-react`
* **Conectividade:** Cliente `fetch` customizado com reconexão automática via WebSockets

#### **Infraestrutura & Integrações**
* **WhatsApp Engine:** Evolution API v2 (Node.js / Baileys) + Redis + PostgreSQL
* **Meta Cloud API:** Suporte para API Oficial do WhatsApp Business
* **Containerização:** Docker & Docker Compose

---

## 🇺🇸 English

### 📋 About the Project
**OminiChannel** is an enterprise multi-tenant customer service and task orchestration platform combining Large Language Models (**LLMs via Google Gemini RAG**), smart Service Order (OS) diagnostic automations, interactive corporate calendar workflows with WhatsApp confirmation buttons, a real-time media repository, and native **WhatsApp** integration (via Evolution API v2 & Meta Cloud API).

---

### ✨ Key Features

1. **⚡ Smart Automations & Service Order (OS) Handlers with AI Copilot:**
   - Automatic detection of Service Order messages and status (`Quote / Diagnostic`, `Store Warranty`, `Factory Warranty`).
   - Dynamic technical diagnostic fee calculation across 23+ equipment types (Inverter, MIG, TIG, Plasma, CNC, Compressors).
   - Sequential multi-bubble message dispatch with humanized WhatsApp typing simulation (`composing`).
   - Conversational AI Copilot to create and refine custom automation triggers in natural language.
   - Real-time simulator to test triggers before production.

2. **🤖 AI Concierge with Multimodal RAG (Google Gemini):**
   - Context-aware automated responses powered by company documents (`.pdf`, `.docx`, `.txt`).
   - Sector-specific and global RAG knowledge bases.
   - AI Summary Banner for human operators.

3. **🖼️ Advanced Media Repository & File Gallery:**
   - Real-time search by filename, caption, sender, and date.
   - Live PDF 1st-page cover renderer, video previews, and image lightbox.
   - Quoted replies with live media thumbnails.

4. **📅 Interactive Calendar & Service Call Workflow:**
   - Dispatches scheduled tasks to staff members with interactive WhatsApp buttons (`Accept` / `Decline` / `Complete`).
   - Live status synchronization (Scheduled ➡️ In Progress ➡️ Completed).

5. **💳 Dynamic BACEN Pix Key & QR Code Generator:**
   - Generates official Central Bank of Brazil (BACEN) Copy-Paste strings and QR Codes with custom amounts directly in chat.

6. **💬 Real-Time Chat & 0ms Optimistic Messaging:**
   - Instant 0ms optimistic message rendering with jitter-free smooth scrolling.
   - Browser audio recording in native WhatsApp voice note format (`audio/ogg; codecs=opus`).
   - Group chat support with mass mentions (`@everyone`).

7. **🛡️ WhatsApp Auto-Healing Watchdog & Canonical JID Resolver:**
   - 30-second continuous background health monitor with automatic reconnection.
   - 8 vs 9 digit canonical phone number normalization for Brazilian numbers.

8. **🏢 Multi-Tenant, Fernet Encryption & Security Audit:**
   - Multi-tenant data segregation.
   - Fernet symmetric encryption for sensitive API keys.
   - Full audit logging for administrative actions.

---

### 📄 Licença / License
Distribuído sob licença proprietária corporativa SERVWELD / SERVSOLDA. Todos os direitos reservados.
Distributed under proprietary enterprise license. All rights reserved.
