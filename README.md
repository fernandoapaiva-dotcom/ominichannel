# 🚀 OminiChannel - Plataforma Omnichannel Inteligente com IA Concierge (Gemini RAG), Agenda Interativa & WhatsApp Integration

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
**OminiChannel** é uma plataforma corporativa multi-tenant de atendimento omnichannel que combina o poder de Modelos de Linguagem de Grande Porte (**LLMs via Google Gemini RAG**) com atendimento humano distribuído, agenda corporativa de tarefas e integração nativa com o **WhatsApp** (via Evolution API v2 e Meta Cloud API).

A plataforma automatiza a triagem, qualificação, resposta de dúvidas técnicas, cotações e o **gerenciamento de tarefas externas e chamados técnicos** com disparo de lembretes e botões interativos no WhatsApp do colaborador. Quando a solicitação exige intervenção humana, o sistema realiza a **distribuição inteligente por menor carga de trabalho (*least-busy operator*)** e notifica o atendente em tempo real via **WebSockets** com um **Resumo Estruturado da IA**.

---

### ✨ Principais Funcionalidades

1. **🤖 IA Concierge com RAG (Google Gemini):**
   - Respostas inteligentes e contextualizadas baseadas em arquivos da empresa (`.pdf`, `.txt`, `.docx`).
   - Suporte aos modelos de alta performance da família Gemini (`gemini-2.5-flash`, `gemini-3.1-flash-lite`).
   - Síntese de memórias estruturadas e histórico contínuo da conversa.

2. **📅 Agenda Interativa & Gestão de Chamados com Ciclo WhatsApp:**
   - **Agendamento Completo:** Criação e edição de tarefas com seleção de tipo (Visitas Técnicas, Entregas de Gás, Manutenções, Vendas, Atendimentos), prioridades, horários e cliente vinculado (com nome e telefone).
   - **Seleção Dinâmica de Departamento de Saída:** Roteamento do disparo para a instância correspondente (Locação, Técnica, Vendas, etc.).
   - **Sequência Interativa de Tarefas no WhatsApp do Funcionário:**
     - **1️⃣ Notificação de Agendamento:** O colaborador recebe o aviso da atividade com botões interativos (`Sim, confirmo a atividade` / `Não, quero recusar`).
     - **2️⃣ Aceite & Detalhes da Atividade:** Ao aceitar, o evento na agenda muda em tempo real para 🟡 **Em Andamento** e a IA entrega os dados completos da tarefa com o botão `Sim, atividade concluída`.
     - **3️⃣ Recusa com Registro:** Ao recusar, o evento no calendário muda para 🔴 **Cancelado** e fica sinalizado para remanejamento.
     - **4️⃣ Conclusão Automática:** Ao finalizar, o evento é marcado como 🟢 **Concluído** no calendário e o colaborador recebe a mensagem de encerramento.

3. **🛡️ Watchdog de Auto-Cura do WhatsApp (*Auto-Heal 30s Loop*):**
   - Monitoramento contínuo em segundo plano do estado das instâncias do WhatsApp.
   - Reconexão automática em caso de desconexão e restauração proativa de sockets em repouso.

4. **🔎 Resolvedor Canônico de JID (8 vs 9 Dígitos no Brasil):**
   - Resolução inteligente de números brasileiros (DDD 61 e similares), detectando automaticamente se o número está registrado com 8 ou 9 dígitos no WhatsApp para garantir 100% de entrega (`DELIVERY_ACK`).

5. **🔄 Transição Fluida IA ↔ Humano (Anti-Vácuo & Reengajamento):**
   - Transição automática para atendente humano quando solicitado pelo cliente ou por decisão da IA.
   - **Distribuição Inteligente (*Least-Busy Operator*):** Atribuição automática ao atendente com menor carga de atendimentos ativos.
   - **Banner de Resumo da IA:** Visualização instantânea no topo do chat com o resumo gerado pela IA.
   - **Lógica Anti-Vácuo:** Reativação automática da IA caso o atendente fique inativo por mais de 3 minutos.

6. **💬 WhatsApp Multicanais (Evolution API v2 & Meta Cloud API):**
   - Conexão via **QR Code** ou **Código de Pareamento**.
   - Suporte nativo a **linhas fixas de 12 dígitos**.
   - Envio e recebimento de textos, imagens, áudios, vídeos, documentos e botões rápidos.

7. **🏢 Multi-Tenant & Controle de Acesso (RBAC):**
   - Isolamento total por empresa (*Tenant*).
   - Níveis de permissão (`Admin` e `Atendente`).

8. **⚡ WebSockets & Push em Tempo Real:**
   - Atualização instantânea da agenda, conversas e notificações no navegador.

---

### 🛠️ Stack Tecnológica & Arquitetura

#### **Backend (Python / FastAPI)**
- **Linguagem:** Python 3.11+
- **Framework Web:** FastAPI (ASGI assíncrono de alta performance)
- **Banco de Dados & ORM:** SQLAlchemy 2.0 (AsyncIO) + SQLite / PostgreSQL
- **Engine de IA & RAG:** Google GenAI SDK (`google-genai`), LangChain, FAISS / ChromaDB, PyPDF2
- **Push Realtime:** WebSockets nativos (`ws_manager`)
- **Cliente HTTP Async:** `httpx`

#### **Frontend (React / TypeScript / Vite)**
- **Linguagem:** TypeScript
- **Framework UI:** React 18+ (Vite SPA)
- **Estilização:** CSS3 Moderno (Custom Properties, Flexbox/Grid, Dark Mode)
- **Componentes:** Modal de Calendário Avançado, Seletor de Departamentos e Atendentes
- **Ícones:** `lucide-react`
- **Conectividade:** Cliente `fetch` customizado com reconexão automática via WebSockets

#### **Infraestrutura & Integrações**
- **WhatsApp Engine:** Evolution API v2 (Node.js / Baileys) + Redis + PostgreSQL
- **Containerização:** Docker & Docker Compose
- **Meta Cloud API:** Suporte para API Oficial do WhatsApp Business

---

## 🇺🇸 English

### 📋 About the Project
**OminiChannel** is an enterprise multi-tenant customer service and task orchestration platform combining Large Language Models (**LLMs via Google Gemini RAG**) with distributed human agent routing, interactive corporate calendar management, and direct **WhatsApp** integration (via Evolution API v2 & Meta Cloud API).

---

### ✨ Key Features

1. **🤖 AI Concierge with RAG (Google Gemini):**
   - Document-grounded contextual replies (`.pdf`, `.txt`, `.docx`) using Gemini models.
   - Structured memory synthesis and conversation history tracking.

2. **📅 Interactive Calendar & 4-Step WhatsApp Task Lifecycle:**
   - **Comprehensive Task Scheduler:** Event creation with categories (Technical Visits, Gas Deliveries, Maintenance, Sales), priorities, schedules, and customer linking (name & phone).
   - **Departmental WhatsApp Instance Routing:** Dynamically dispatches reminders from designated departmental numbers (Rental, Tech, Sales, etc.).
   - **Sequential WhatsApp Employee Flow:**
     - **1️⃣ Assignment Notification:** Dispatches assignment prompt with interactive 1-tap buttons (`Sim, confirmo a atividade` / `Não, quero recusar`).
     - **2️⃣ Confirmation & Full Task Delivery:** Upon acceptance, the calendar updates to 🟡 **In Progress** in real time, and the AI delivers full task details plus a `Sim, atividade concluída` button.
     - **3️⃣ Refusal Handling:** If declined, the task is marked as 🔴 **Cancelled** for immediate reassignment.
     - **4️⃣ Task Conclusion:** Clicking completion updates the calendar to 🟢 **Completed** in real time.

3. **🛡️ WhatsApp Auto-Heal Watchdog (30s Background Loop):**
   - Active monitoring of WhatsApp instance connection states with automatic reconnection.

4. **🔎 Canonical JID Resolver (8 vs 9 Digits in Brazil):**
   - Real-time normalization of Brazilian phone numbers to ensure zero packet drop (`DELIVERY_ACK`).

5. **🔄 AI ↔ Human Intelligent Handoff (Least-Busy Operator Routing & Anti-Vacuum):**
   - Automated routing to the least-busy active human operator.
   - AI Executive Summary Card displayed above human chat.
   - Anti-vacuum fallback to AI on agent inactivity.

---

## 🚀 Quick Start / Como Executar

### 1. Requisitos / Prerequisites
- **Python 3.11+**
- **Node.js 18+** & `npm`
- **Docker Desktop**

### 2. Backend Setup
```bash
cd backend
python -m venv venv

# Windows:
venv\Scripts\activate
# Linux / macOS:
source venv/bin/activate

pip install -r requirements.txt
python -m uvicorn app.main:app --host 0.0.0.0 --port 8000
```

### 3. Frontend Setup
```bash
cd frontend
npm install
npm run dev
```

### 4. Evolution API (Docker Engine)
```bash
cd backend
docker-compose up -d
```

---

## 📄 Licença / License
Este projeto é distribuído sob a licença **MIT**. Veja o arquivo `LICENSE` para mais detalhes.
