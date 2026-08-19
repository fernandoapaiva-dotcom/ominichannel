# 🚀 OminiChannel - Plataforma Omnichannel Inteligente com IA Concierge (Gemini RAG) & WhatsApp Integration

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
**OminiChannel** é uma plataforma corporativa multi-tenant de atendimento omnichannel que combina o poder de Modelos de Linguagem de Grande Porte (**LLMs via Google Gemini RAG**) com atendimento humano distribuído e integração nativa com o **WhatsApp** (via Evolution API v2 e Meta Cloud API).

A plataforma automatiza a triagem, qualificação, resposta de dúvidas técnicas e cotações utilizando **Retrieval-Augmented Generation (RAG)** alimentado por documentos e bases de conhecimento. Quando a solicitação exige intervenção humana, o sistema realiza a **distribuição inteligente por menor carga de trabalho (*least-busy operator*)** e notifica o atendente em tempo real via **WebSockets** com um **Resumo Estruturado da IA**.

---

### ✨ Principais Funcionalidades

1. **🤖 IA Concierge com RAG (Google Gemini):**
   - Respostas inteligentes e contextualizadas baseadas em arquivos da empresa (`.pdf`, `.txt`, `.docx`).
   - Suporte aos modelos de alta performance da família Gemini (`gemini-2.5-flash`, `gemini-3.1-flash-lite`).
   - Síntese de memórias estruturadas e histórico contínuo da conversa.

2. **🔄 Transição Fluida IA ↔ Humano (Anti-Vácuo & Reengajamento):**
   - Transição automática para atendente humano quando solicitado pelo cliente ou por decisão da IA.
   - **Distribuição Inteligente (*Least-Busy Operator*):** O sistema calcula em tempo real o atendente com menos chamados ativos e atribui a conversa automaticamente a ele.
   - **Banner de Resumo da IA:** O atendente humano visualiza instantaneamente no topo do chat o resumo do atendimento realizado pela IA.
   - **Lógica Anti-Vácuo:** Reativação automática do atendimento da IA se o cliente enviar saudações ou se um atendente humano ficar inativo por mais de 3 minutos.

3. **💬 Integração WhatsApp Multicanais (Evolution API v2 & Meta Cloud API):**
   - Conexão simplificada via **QR Code** ou **Código de Pareamento de 8 dígitos**.
   - **Reset de Conexão com 1-Clique** no painel de administração.
   - Suporte nativo a **linhas fixas/empresariais de 12 dígitos** (sem corrupção indevida de DDD + 9).
   - Envio e recebimento de textos, imagens, áudios, vídeos, documentos e chamadas WebRTC.
   - Varredor em segundo plano (*background sweeper*) para mensagens de clientes não respondidas.

4. **🏢 Arquitetura Multi-Tenant & Controle de Acesso (RBAC):**
   - Isolamento completo de dados por empresa (*Tenant*).
   - Níveis de permissão (`Admin` e `Atendente`).
   - Gestão de departamentos e vínculo de permissões por número de WhatsApp.

5. **⚡ Comunicação em Tempo Real (WebSockets & Notificações Live):**
   - Transmissão instantânea de mensagens, alterações de status e alertas sonoros no navegador.

---

### 🛠️ Stack Tecnológica & Arquitetura

#### **Backend (Python / FastAPI)**
- **Linguagem:** Python 3.11+
- **Framework Web:** FastAPI (ASGI assíncrono de altíssima performance)
- **Banco de Dados & ORM:** SQLAlchemy 2.0 (AsyncIO) + SQLite / PostgreSQL
- **Engine de IA & RAG:** Google GenAI SDK (`google-genai`), LangChain, FAISS / ChromaDB, PyPDF2
- **Push Realtime:** WebSockets nativos (`ws_manager`)
- **Cliente HTTP Async:** `httpx`

#### **Frontend (React / TypeScript / Vite)**
- **Linguagem:** TypeScript
- **Framework UI:** React 18+ (Vite SPA)
- **Estilização:** CSS3 Moderno (Custom Properties, Flexbox/Grid, Dark Mode)
- **Ícones & Componentes:** `lucide-react`
- **Conectividade:** Cliente `fetch` customizado com reconexão automática via WebSockets

#### **Infraestrutura & Integrações**
- **WhatsApp Engine:** Evolution API v2 (Node.js / Baileys) + Redis + PostgreSQL
- **Containerização:** Docker & Docker Compose
- **Meta Cloud API:** Suporte para API Oficial do WhatsApp Business

---

## 🇺🇸 English

### 📋 About the Project
**OminiChannel** is an enterprise multi-tenant omnichannel customer service platform combining Large Language Models (**LLMs via Google Gemini RAG**) with distributed human agent routing and direct **WhatsApp** integration (via Evolution API v2 & Meta Cloud API).

The platform automates triage, lead qualification, technical answers, and price quotes using **Retrieval-Augmented Generation (RAG)** backed by custom knowledge bases. When a customer query requires human intervention, the system executes **smart least-busy operator routing** and notifies the assigned agent in real time via **WebSockets** alongside an **AI Executive Summary Card**.

---

### ✨ Key Features

1. **🤖 AI Concierge with RAG (Google Gemini):**
   - Context-aware responses trained on custom company documents (`.pdf`, `.txt`, `.docx`).
   - Supported models include high-performance Gemini models (`gemini-2.5-flash`, `gemini-3.1-flash-lite`).
   - Structured memory synthesis and ongoing conversation history tracking.

2. **🔄 Seamless AI ↔ Human Transition (Anti-Vacuum & Re-engagement):**
   - Automatic handoff to human agents upon customer request or AI decision.
   - **Smart Least-Busy Operator Routing:** Real-time workload calculation to auto-assign incoming chats to the agent with the fewest active conversations.
   - **AI Summary Banner:** Human agents instantly view a concise structured summary of the conversation upon handoff.
   - **Anti-Vacuum Protection:** Automatic re-engagement by the AI if customers send greetings or if human agents remain inactive for >3 minutes.

3. **💬 Multi-Channel WhatsApp Integration (Evolution API v2 & Meta Cloud API):**
   - Easy device connection via **QR Code** or **8-digit Pairing Code**.
   - **1-Click Session Reset** directly in the admin dashboard.
   - Native support for **12-digit landline WhatsApp numbers** without forced digit mutation.
   - Full support for text, media (images, audio, video, documents), and WebRTC Voice/Video calls.
   - Automated background sweeper for unreplied customer messages.

4. **🏢 Multi-Tenant Architecture & Role-Based Access (RBAC):**
   - Complete data isolation per enterprise tenant.
   - Access roles (`Admin` and `Agent/Atendente`).
   - Department management and per-number access control.

5. **⚡ Real-Time WebSockets & Live Alerts:**
   - Instant broadcast of new messages, status changes, and audible browser notifications.

---

### 🛠️ Tech Stack & Architecture

#### **Backend (Python / FastAPI)**
- **Language:** Python 3.11+
- **Web Framework:** FastAPI (High-performance async ASGI)
- **Database & ORM:** SQLAlchemy 2.0 (AsyncIO) + SQLite / PostgreSQL
- **AI & RAG Engine:** Google GenAI SDK (`google-genai`), LangChain, FAISS / ChromaDB, PyPDF2
- **Realtime Push:** Native WebSockets (`ws_manager`)
- **Async HTTP Client:** `httpx`

#### **Frontend (React / TypeScript / Vite)**
- **Language:** TypeScript
- **UI Framework:** React 18+ (Vite SPA)
- **Styling:** Modern CSS3 (Custom Variables, Flexbox/Grid, Dark Mode)
- **Icons & Components:** `lucide-react`
- **Realtime Connectivity:** Custom `fetch` client + dynamic WebSocket auto-reconnect

#### **Infrastructure & Third-Party APIs**
- **WhatsApp Engine:** Evolution API v2 (Node.js / Baileys) + Redis + PostgreSQL
- **Containerization:** Docker & Docker Compose
- **Meta Cloud API:** Official WhatsApp Business Cloud API support

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
