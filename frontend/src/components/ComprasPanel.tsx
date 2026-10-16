import React, { useState, useEffect, useRef } from 'react';
import {
  ShoppingCart, Search, Plus, Send, CheckCircle, ShieldCheck, X, ArrowLeft,
  Store, RefreshCw, Layers, Database, ClipboardList
} from 'lucide-react';
import { User } from '../types';
import { EntradaNotaFiscal } from './compras/EntradaNotaFiscal';
import { ParametrosCustoLoja } from './compras/ParametrosCustoLoja';
import { AcertoEstoque } from './compras/AcertoEstoque';
import { CatalogoSite } from './compras/CatalogoSite';
import { PedidosCompraPanel } from './compras/PedidosCompraPanel';


interface ComprasPanelProps {
  user: User;
  onBack: () => void;
}

export interface SoftsystemProduto {
  codigo: number;
  cod_original: string;
  cod_barras: string;
  descricao: string;
  unidade: string;
  grupo: string;
  subgrupo: string;
  estoque: number;
  preco_venda: number;
  preco_aquisicao: number;
  ncm?: string;
}

interface BalcaoDemanda {
  id: number;
  empresa: string;
  cliente_nome: string;
  cliente_telefone: string;
  cliente_documento?: string;
  produto_nome: string;
  produto_codigo?: string;
  produto_ean?: string;
  quantidade_desejada: number;
  atendente_nome: string;
  observacao?: string;
  status: 'aguardando' | 'notificado' | 'convertido' | 'cancelado';
  criado_em: string;
  notificado_em?: string;
  historico_auditoria?: string;
}

export const ComprasPanel: React.FC<ComprasPanelProps> = ({ user, onBack }) => {
  const [activeSubTab, setActiveSubTab] = useState<'nfe' | 'pedidos' | 'balcao' | 'estoque' | 'site' | 'custos'>('nfe');
  const [empresaAtiva, setEmpresaAtiva] = useState<'servweld' | 'centrooeste'>('servweld');

  
  // Balcão Estado
  const [demandas, setDemandas] = useState<BalcaoDemanda[]>([]);
  const [loadingDemandas, setLoadingDemandas] = useState(false);
  const [buscaBalcao, setBuscaBalcao] = useState('');
  const [filtroStatus, setFiltroStatus] = useState('todos');
  const [modalNovaDemanda, setModalNovaDemanda] = useState(false);
  const [modalAuditoria, setModalAuditoria] = useState<BalcaoDemanda | null>(null);

  // Form Nova Demanda Balcão
  const [novoClienteNome, setNovoClienteNome] = useState('');
  const [novoClienteTelefone, setNovoClienteTelefone] = useState('');
  const [novoProdutoNome, setNovoProdutoNome] = useState('');
  const [novoProdutoCodigo, setNovoProdutoCodigo] = useState('');
  const [novoQuantidade, setNovoQuantidade] = useState(1);
  const [novoObservacao, setNovoObservacao] = useState('');
  const [salvandoDemanda, setSalvandoDemanda] = useState(false);

  // Auto-busca Softsystem no Balcão
  const [buscandoSoftsystemBalcao, setBuscandoSoftsystemBalcao] = useState(false);
  const [softsystemResultadosBalcao, setSoftsystemResultadosBalcao] = useState<SoftsystemProduto[]>([]);
  const [softsystemProdutoSelecionado, setSoftsystemProdutoSelecionado] = useState<SoftsystemProduto | null>(null);
  const debounceTimerRef = useRef<any>(null);

  // Carrega as demandas do balcão ao iniciar
  useEffect(() => {
    carregarDemandas();
  }, []);

  const getAuthHeaders = () => {
    const token = localStorage.getItem('token');
    return {
      'Authorization': `Bearer ${token}`,
      'Content-Type': 'application/json'
    };
  };

  const carregarDemandas = async () => {
    try {
      setLoadingDemandas(true);
      const params = new URLSearchParams();
      if (buscaBalcao) params.set('busca', buscaBalcao);
      if (filtroStatus !== 'todos') params.set('status', filtroStatus);
      params.set('empresa', empresaAtiva);

      const res = await fetch(`/api/v1/compras/balcao-espera?${params.toString()}`, {
        headers: getAuthHeaders()
      });
      if (res.ok) {
        const json = await res.json();
        setDemandas(json.demandas || []);
      }
    } catch (err) {
      console.error('Erro ao carregar demandas do balcão:', err);
    } finally {
      setLoadingDemandas(false);
    }
  };

  // Busca Inteligente no Softsystem para o Balcão ("Avise-me quando Chegar")
  const handleBuscaSoftsystemBalcao = (termo: string) => {
    setNovoProdutoCodigo(termo);
    if (debounceTimerRef.current) clearTimeout(debounceTimerRef.current);

    if (!termo || termo.trim().length < 2) {
      setSoftsystemResultadosBalcao([]);
      return;
    }

    debounceTimerRef.current = setTimeout(async () => {
      try {
        setBuscandoSoftsystemBalcao(true);
        const res = await fetch(`/api/v1/compras/softsystem/buscar-produto?empresa=${empresaAtiva}&termo=${encodeURIComponent(termo.trim())}&limite=10`, {
          headers: getAuthHeaders()
        });
        if (res.ok) {
          const json = await res.json();
          setSoftsystemResultadosBalcao(json.produtos || []);

          // Se tiver match exato com número digitado
          if (json.produtos && json.produtos.length === 1 && termo.trim() === String(json.produtos[0].codigo)) {
            selecionarProdutoSoftsystemBalcao(json.produtos[0]);
          }
        }
      } catch (err) {
        console.error('Erro na busca Softsystem balcão:', err);
      } finally {
        setBuscandoSoftsystemBalcao(false);
      }
    }, 350);
  };

  const selecionarProdutoSoftsystemBalcao = (p: SoftsystemProduto) => {
    setSoftsystemProdutoSelecionado(p);
    setNovoProdutoNome(p.descricao);
    setNovoProdutoCodigo(String(p.codigo));
    setSoftsystemResultadosBalcao([]);
  };

  // Salvar Demanda do Balcão
  const handleSalvarDemanda = async (e: React.FormEvent) => {
    e.preventDefault();
    if (!novoClienteNome || !novoClienteTelefone || !novoProdutoNome) {
      alert('Preencha os campos obrigatórios (Cliente, Telefone e Produto).');
      return;
    }

    try {
      setSalvandoDemanda(true);
      const res = await fetch('/api/v1/compras/balcao-espera', {
        method: 'POST',
        headers: getAuthHeaders(),
        body: JSON.stringify({
          empresa: empresaAtiva,
          cliente_nome: novoClienteNome,
          cliente_telefone: novoClienteTelefone,
          produto_nome: novoProdutoNome,
          produto_codigo: novoProdutoCodigo || undefined,
          quantidade_desejada: novoQuantidade,
          observacao: novoObservacao || undefined,
        })
      });

      if (res.ok) {
        setModalNovaDemanda(false);
        setNovoClienteNome('');
        setNovoClienteTelefone('');
        setNovoProdutoNome('');
        setNovoProdutoCodigo('');
        setNovoQuantidade(1);
        setNovoObservacao('');
        setSoftsystemProdutoSelecionado(null);
        carregarDemandas();
      } else {
        alert('Erro ao registrar demanda.');
      }
    } catch (err) {
      console.error(err);
      alert('Erro de comunicação.');
    } finally {
      setSalvandoDemanda(false);
    }
  };

  // Disparar Notificação Manual de Demanda
  const handleNotificarManual = async (demandaId: number) => {
    if (!confirm('Deseja enviar a notificação de WhatsApp para este cliente agora?')) return;
    try {
      const res = await fetch(`/api/v1/compras/balcao-espera/${demandaId}/notificar`, {
        method: 'POST',
        headers: getAuthHeaders(),
      });
      const json = await res.json();
      if (json.success) {
        alert('Aviso enviado com sucesso via WhatsApp!');
        carregarDemandas();
      } else {
        alert(`Falha no envio: ${json.error || 'Verifique a Evolution API'}`);
      }
    } catch (err) {
      alert('Erro de envio.');
    }
  };

  // Alterar Status da Demanda
  const handleAlterarStatusDemanda = async (demandaId: number, novoStatus: string) => {
    try {
      const res = await fetch(`/api/v1/compras/balcao-espera/${demandaId}/status?status=${novoStatus}`, {
        method: 'PATCH',
        headers: getAuthHeaders(),
      });
      if (res.ok) {
        carregarDemandas();
      }
    } catch (err) {
      console.error(err);
    }
  };

  return (
    <div style={{ flex: 1, display: 'flex', flexDirection: 'column', height: '100%', background: 'var(--bg-primary)', overflow: 'hidden' }}>
      {/* Top Header */}
      <div style={{
        padding: '14px 20px',
        background: 'var(--bg-secondary)',
        borderBottom: '1px solid var(--border-color)',
        display: 'flex',
        alignItems: 'center',
        justifyContent: 'space-between',
        flexShrink: 0
      }}>
        <div style={{ display: 'flex', alignItems: 'center', gap: '14px' }}>
          <button
            onClick={onBack}
            style={{
              background: 'transparent',
              border: 'none',
              color: 'var(--text-muted)',
              cursor: 'pointer',
              display: 'flex',
              alignItems: 'center',
              padding: '6px',
              borderRadius: 'var(--radius-sm)'
            }}
            title="Voltar aos módulos"
          >
            <ArrowLeft size={18} />
          </button>
          <div>
            <div style={{ display: 'flex', alignItems: 'center', gap: '10px' }}>
              <h2 style={{ margin: 0, fontSize: '18px', fontWeight: 700, color: 'var(--text-main)' }}>
                Módulo de Compras & Balcão
              </h2>
              {/* Seletor de Loja */}
              <div style={{ display: 'flex', background: 'var(--bg-primary)', borderRadius: 'var(--radius-sm)', padding: '2px', border: '1px solid var(--border-color)' }}>
                <button
                  onClick={() => setEmpresaAtiva('servweld')}
                  style={{
                    padding: '4px 10px',
                    fontSize: '12px',
                    fontWeight: 600,
                    borderRadius: 'var(--radius-sm)',
                    border: 'none',
                    cursor: 'pointer',
                    background: empresaAtiva === 'servweld' ? 'var(--accent-primary)' : 'transparent',
                    color: empresaAtiva === 'servweld' ? '#051a12' : 'var(--text-muted)',
                  }}
                >
                  Servweld (Lucro Presumido)
                </button>
                <button
                  onClick={() => setEmpresaAtiva('centrooeste')}
                  style={{
                    padding: '4px 10px',
                    fontSize: '12px',
                    fontWeight: 600,
                    borderRadius: 'var(--radius-sm)',
                    border: 'none',
                    cursor: 'pointer',
                    background: empresaAtiva === 'centrooeste' ? 'var(--accent-primary)' : 'transparent',
                    color: empresaAtiva === 'centrooeste' ? '#051a12' : 'var(--text-muted)',
                  }}
                >
                  Centro Oeste (Simples Nacional)
                </button>
              </div>
            </div>
            <p style={{ margin: 0, fontSize: '12px', color: 'var(--text-muted)', marginTop: '2px' }}>
              Entrada de NF-e/CT-e por Chave de 44 dígitos, rateio de contas extras, integração Softsystem e balcão
            </p>
          </div>
        </div>

        {/* Sub-abas de navegação interna */}
        <div style={{ display: 'flex', gap: '8px' }}>
          <button
            onClick={() => setActiveSubTab('nfe')}
            style={{
              display: 'flex',
              alignItems: 'center',
              gap: '6px',
              padding: '8px 14px',
              fontSize: '13px',
              fontWeight: 600,
              borderRadius: 'var(--radius-sm)',
              border: 'none',
              cursor: 'pointer',
              background: activeSubTab === 'nfe' ? 'var(--bg-primary)' : 'transparent',
              color: activeSubTab === 'nfe' ? 'var(--accent-primary)' : 'var(--text-muted)',
              borderBottom: activeSubTab === 'nfe' ? '2px solid var(--accent-primary)' : 'none'
            }}
          >
            <ShoppingCart size={15} />
            Entrada de NF-e & Precificação
          </button>
          <button
            onClick={() => setActiveSubTab('pedidos')}
            style={{
              display: 'flex',
              alignItems: 'center',
              gap: '6px',
              padding: '8px 14px',
              fontSize: '13px',
              fontWeight: 600,
              borderRadius: 'var(--radius-sm)',
              border: 'none',
              cursor: 'pointer',
              background: activeSubTab === 'pedidos' ? 'var(--bg-primary)' : 'transparent',
              color: activeSubTab === 'pedidos' ? 'var(--accent-primary)' : 'var(--text-muted)',
              borderBottom: activeSubTab === 'pedidos' ? '2px solid var(--accent-primary)' : 'none'
            }}
          >
            <ClipboardList size={15} />
            Pedidos por Fabricante
          </button>
          <button
            onClick={() => {
              setActiveSubTab('balcao');
              carregarDemandas();
            }}

            style={{
              display: 'flex',
              alignItems: 'center',
              gap: '6px',
              padding: '8px 14px',
              fontSize: '13px',
              fontWeight: 600,
              borderRadius: 'var(--radius-sm)',
              border: 'none',
              cursor: 'pointer',
              background: activeSubTab === 'balcao' ? 'var(--bg-primary)' : 'transparent',
              color: activeSubTab === 'balcao' ? 'var(--accent-primary)' : 'var(--text-muted)',
              borderBottom: activeSubTab === 'balcao' ? '2px solid var(--accent-primary)' : 'none'
            }}
          >
            <Store size={15} />
            Fila do Balcão ("Avise-me quando Chegar")
            {demandas.filter(d => d.status === 'aguardando').length > 0 && (
              <span style={{
                background: 'var(--accent-primary)',
                color: '#051a12',
                fontSize: '10px',
                padding: '1px 6px',
                borderRadius: '10px',
                fontWeight: 700
              }}>
                {demandas.filter(d => d.status === 'aguardando').length}
              </span>
            )}
          </button>
          <button
            onClick={() => setActiveSubTab('estoque')}
            style={{
              display: 'flex',
              alignItems: 'center',
              gap: '6px',
              padding: '8px 14px',
              fontSize: '13px',
              fontWeight: 600,
              borderRadius: 'var(--radius-sm)',
              border: 'none',
              cursor: 'pointer',
              background: activeSubTab === 'estoque' ? 'var(--bg-primary)' : 'transparent',
              color: activeSubTab === 'estoque' ? 'var(--accent-primary)' : 'var(--text-muted)',
              borderBottom: activeSubTab === 'estoque' ? '2px solid var(--accent-primary)' : 'none'
            }}
          >
            <ClipboardList size={15} />
            Acerto de Estoque
          </button>
          <button
            onClick={() => setActiveSubTab('custos')}
            style={{
              display: 'flex',
              alignItems: 'center',
              gap: '6px',
              padding: '8px 14px',
              fontSize: '13px',
              fontWeight: 600,
              borderRadius: 'var(--radius-sm)',
              border: 'none',
              cursor: 'pointer',
              background: activeSubTab === 'custos' ? 'var(--bg-primary)' : 'transparent',
              color: activeSubTab === 'custos' ? 'var(--accent-primary)' : 'var(--text-muted)',
              borderBottom: activeSubTab === 'custos' ? '2px solid var(--accent-primary)' : 'none'
            }}
          >
            <Layers size={15} />
            Parâmetros de Custo
          </button>
          <button
            onClick={() => setActiveSubTab('site')}
            style={{
              display: 'flex',
              alignItems: 'center',
              gap: '6px',
              padding: '8px 14px',
              fontSize: '13px',
              fontWeight: 600,
              borderRadius: 'var(--radius-sm)',
              border: 'none',
              cursor: 'pointer',
              background: activeSubTab === 'site' ? 'var(--bg-primary)' : 'transparent',
              color: activeSubTab === 'site' ? 'var(--accent-primary)' : 'var(--text-muted)',
              borderBottom: activeSubTab === 'site' ? '2px solid var(--accent-primary)' : 'none'
            }}
          >
            <Store size={15} />
            Catálogo do Site
          </button>
        </div>
      </div>

      {/* Conteúdo Principal */}
      <div style={{ flex: 1, overflowY: 'auto', padding: '20px' }}>

        {/* ============================================================== */}
        {/* ABA 1: ENTRADA DE NF-E (chave -> conferência -> contagem cega -> preço) */}
        {/* ============================================================== */}
        {activeSubTab === 'nfe' && (
          <EntradaNotaFiscal empresa={empresaAtiva} isAdmin={user.role === 'admin'} />
        )}

        {/* ============================================================== */}
        {/* ABA: PEDIDOS DE COMPRA POR FABRICANTE (TELECONTROL / BALCÃO)   */}
        {/* ============================================================== */}
        {activeSubTab === 'pedidos' && (
          <PedidosCompraPanel empresa={empresaAtiva} usuarioNome={user.name || user.email} />
        )}

        {/* ============================================================== */}
        {/* ABA 2: BALCÃO - FILA "AVISE-ME QUANDO CHEGAR"                   */}
        {/* ============================================================== */}

        {activeSubTab === 'balcao' && (
          <div style={{ display: 'flex', flexDirection: 'column', gap: '16px' }}>
            {/* Barra de Ações do Balcão */}
            <div style={{ display: 'flex', justifyContent: 'space-between', alignItems: 'center', gap: '10px', flexWrap: 'wrap' }}>
              <div style={{ display: 'flex', gap: '10px', flex: 1, maxWidth: '500px' }}>
                <div style={{ position: 'relative', flex: 1 }}>
                  <Search size={15} style={{ position: 'absolute', left: '10px', top: '10px', color: 'var(--text-muted)' }} />
                  <input
                    type="text"
                    placeholder="Buscar cliente, telefone ou produto..."
                    value={buscaBalcao}
                    onChange={(e) => setBuscaBalcao(e.target.value)}
                    onKeyDown={(e) => e.key === 'Enter' && carregarDemandas()}
                    style={{
                      width: '100%',
                      padding: '8px 10px 8px 32px',
                      background: 'var(--bg-secondary)',
                      border: '1px solid var(--border-color)',
                      borderRadius: 'var(--radius-sm)',
                      color: 'var(--text-main)',
                      fontSize: '13px'
                    }}
                  />
                </div>
                <select
                  value={filtroStatus}
                  onChange={(e) => {
                    setFiltroStatus(e.target.value);
                    carregarDemandas();
                  }}
                  style={{
                    padding: '8px 12px',
                    background: 'var(--bg-secondary)',
                    border: '1px solid var(--border-color)',
                    borderRadius: 'var(--radius-sm)',
                    color: 'var(--text-main)',
                    fontSize: '13px'
                  }}
                >
                  <option value="todos">Todos os status</option>
                  <option value="aguardando">Aguardando Chegada</option>
                  <option value="notificado">Notificados (WhatsApp)</option>
                  <option value="convertido">Convertidos em Venda</option>
                  <option value="cancelado">Cancelados</option>
                </select>
              </div>

              <button
                onClick={() => {
                  setModalNovaDemanda(true);
                  setSoftsystemProdutoSelecionado(null);
                  setSoftsystemResultadosBalcao([]);
                }}
                style={{
                  padding: '9px 16px',
                  background: 'var(--accent-primary)',
                  color: '#051a12',
                  border: 'none',
                  borderRadius: 'var(--radius-sm)',
                  fontSize: '13px',
                  fontWeight: 600,
                  cursor: 'pointer',
                  display: 'flex',
                  alignItems: 'center',
                  gap: '6px'
                }}
              >
                <Plus size={16} />
                Registrar Falta no Balcão
              </button>
            </div>

            {/* Tabela de Demandas */}
            <div style={{
              background: 'var(--bg-secondary)',
              border: '1px solid var(--border-color)',
              borderRadius: 'var(--radius-md)',
              overflow: 'hidden'
            }}>
              <table style={{ width: '100%', borderCollapse: 'collapse', textAlign: 'left', fontSize: '13px' }}>
                <thead>
                  <tr style={{ background: 'rgba(255,255,255,0.02)', color: 'var(--text-muted)', borderBottom: '1px solid var(--border-color)' }}>
                    <th style={{ padding: '12px 16px' }}>Data / Loja</th>
                    <th style={{ padding: '12px 16px' }}>Cliente / WhatsApp</th>
                    <th style={{ padding: '12px 16px' }}>Produto Desejado</th>
                    <th style={{ padding: '12px 16px' }}>Qtd</th>
                    <th style={{ padding: '12px 16px' }}>Atendente</th>
                    <th style={{ padding: '12px 16px' }}>Status</th>
                    <th style={{ padding: '12px 16px', textAlign: 'right' }}>Ações / Auditoria</th>
                  </tr>
                </thead>
                <tbody>
                  {demandas.length === 0 ? (
                    <tr>
                      <td colSpan={7} style={{ padding: '30px', textAlign: 'center', color: 'var(--text-muted)' }}>
                        {loadingDemandas ? 'Carregando lista de espera...' : 'Nenhuma demanda de balcão registrada.'}
                      </td>
                    </tr>
                  ) : (
                    demandas.map((d) => (
                      <tr key={d.id} style={{ borderBottom: '1px solid var(--border-color)' }}>
                        <td style={{ padding: '12px 16px' }}>
                          <div style={{ color: 'var(--text-main)', fontSize: '12px' }}>
                            {new Date(d.criado_em).toLocaleDateString('pt-BR')}
                          </div>
                          <div style={{ fontSize: '11px', color: 'var(--text-muted)' }}>
                            {d.empresa === 'servweld' ? 'Servweld' : 'Centro Oeste'}
                          </div>
                        </td>
                        <td style={{ padding: '12px 16px' }}>
                          <div style={{ fontWeight: 600, color: 'var(--text-main)' }}>
                            {d.cliente_nome}
                          </div>
                          <div style={{ fontSize: '12px', color: '#38bdf8', marginTop: '2px' }}>
                            📱 {d.cliente_telefone}
                          </div>
                        </td>
                        <td style={{ padding: '12px 16px' }}>
                          <div style={{ fontWeight: 600, color: 'var(--text-main)' }}>
                            {d.produto_nome}
                          </div>
                          {d.produto_codigo && (
                            <div style={{ fontSize: '11px', color: 'var(--text-muted)', display: 'flex', alignItems: 'center', gap: '4px', marginTop: '2px' }}>
                              <Database size={11} /> Cód. Softsystem: #{d.produto_codigo}
                            </div>
                          )}
                        </td>
                        <td style={{ padding: '12px 16px', color: 'var(--text-main)' }}>
                          {d.quantidade_desejada} UN
                        </td>
                        <td style={{ padding: '12px 16px', color: 'var(--text-muted)' }}>
                          {d.atendente_nome}
                        </td>
                        <td style={{ padding: '12px 16px' }}>
                          <span style={{
                            padding: '3px 8px',
                            borderRadius: '12px',
                            fontSize: '11px',
                            fontWeight: 600,
                            background: d.status === 'aguardando' ? 'rgba(245, 158, 11, 0.15)' :
                              d.status === 'notificado' ? 'rgba(56, 189, 248, 0.15)' :
                              d.status === 'convertido' ? 'rgba(34, 197, 94, 0.15)' : 'rgba(239, 68, 68, 0.15)',
                            color: d.status === 'aguardando' ? '#f59e0b' :
                              d.status === 'notificado' ? '#38bdf8' :
                              d.status === 'convertido' ? '#4ade80' : '#f87171',
                          }}>
                            {d.status === 'aguardando' ? 'Aguardando Chegada' :
                             d.status === 'notificado' ? 'Notificado WhatsApp' :
                             d.status === 'convertido' ? 'Venda Concluída' : 'Cancelado'}
                          </span>
                        </td>
                        <td style={{ padding: '12px 16px', textAlign: 'right' }}>
                          <div style={{ display: 'flex', gap: '6px', justifyContent: 'flex-end' }}>
                            {d.status === 'aguardando' && (
                              <button
                                onClick={() => handleNotificarManual(d.id)}
                                title="Enviar WhatsApp manualmente agora"
                                style={{
                                  padding: '5px 10px',
                                  background: 'rgba(56, 189, 248, 0.15)',
                                  border: '1px solid rgba(56, 189, 248, 0.3)',
                                  color: '#38bdf8',
                                  borderRadius: '4px',
                                  cursor: 'pointer',
                                  fontSize: '11px',
                                  display: 'flex',
                                  alignItems: 'center',
                                  gap: '4px'
                                }}
                              >
                                <Send size={12} />
                                Notificar
                              </button>
                            )}
                            <button
                              onClick={() => setModalAuditoria(d)}
                              title="Ver histórico de auditoria"
                              style={{
                                padding: '5px 8px',
                                background: 'transparent',
                                border: '1px solid var(--border-color)',
                                color: 'var(--text-muted)',
                                borderRadius: '4px',
                                cursor: 'pointer'
                              }}
                            >
                              <ShieldCheck size={14} />
                            </button>
                          </div>
                        </td>
                      </tr>
                    ))
                  )}
                </tbody>
              </table>
            </div>
          </div>
        )}

        {/* ============================================================== */}
        {/* ABA 3: PARÂMETROS DE CUSTO, IMPOSTOS E CUSTOS FIXOS DA LOJA     */}
        {/* ============================================================== */}
        {activeSubTab === 'site' && <CatalogoSite empresa={empresaAtiva} />}

        {activeSubTab === 'estoque' && (
          <AcertoEstoque empresa={empresaAtiva} isAdmin={user.role === 'admin'} />
        )}

        {activeSubTab === 'custos' && (
          <ParametrosCustoLoja empresa={empresaAtiva} isAdmin={user.role === 'admin'} />
        )}
      </div>

      {/* ============================================================== */}
      {/* MODAL: REGISTRAR FALTA NO BALCÃO COM AUTO-BUSCA SOFTSYSTEM      */}
      {/* ============================================================== */}
      {modalNovaDemanda && (
        <div style={{
          position: 'fixed',
          top: 0, left: 0, right: 0, bottom: 0,
          background: 'rgba(0,0,0,0.7)',
          display: 'flex',
          alignItems: 'center',
          justifyContent: 'center',
          zIndex: 10000,
          padding: '20px'
        }}>
          <div style={{
            background: 'var(--bg-secondary)',
            border: '1px solid var(--border-color)',
            borderRadius: 'var(--radius-lg)',
            width: '100%',
            maxWidth: '520px',
            padding: '24px',
            boxShadow: '0 10px 25px rgba(0,0,0,0.5)',
            display: 'flex',
            flexDirection: 'column',
            gap: '16px'
          }}>
            <div style={{ display: 'flex', justifyContent: 'space-between', alignItems: 'center' }}>
              <div>
                <h3 style={{ margin: 0, fontSize: '17px', color: 'var(--text-main)', fontWeight: 700 }}>
                  Registrar Espera no Balcão
                </h3>
                <span style={{ fontSize: '12px', color: 'var(--text-muted)' }}>
                  Loja: <strong>{empresaAtiva === 'servweld' ? 'Servweld' : 'Centro Oeste'}</strong>
                </span>
              </div>
              <button onClick={() => setModalNovaDemanda(false)} style={{ background: 'transparent', border: 'none', color: 'var(--text-muted)', cursor: 'pointer' }}>
                <X size={18} />
              </button>
            </div>

            <form onSubmit={handleSalvarDemanda} style={{ display: 'flex', flexDirection: 'column', gap: '12px', fontSize: '13px' }}>
              {/* CÓDIGO SOFTSYSTEM OU CÓDIGO ORIGINAL - COM AUTOCOMPLETAR */}
              <div style={{ position: 'relative' }}>
                <label style={{ color: 'var(--text-main)', display: 'flex', justifyContent: 'space-between', fontWeight: 600, marginBottom: '4px' }}>
                  <span>Cód. Softsystem ou Cód. Original / Descrição:</span>
                  {buscandoSoftsystemBalcao && <span style={{ color: 'var(--accent-primary)', fontSize: '11px' }}>Consultando Softsystem...</span>}
                </label>
                <div style={{ position: 'relative' }}>
                  <input
                    type="text"
                    placeholder="Digite o código (ex: 3298) ou código original..."
                    value={novoProdutoCodigo}
                    onChange={(e) => handleBuscaSoftsystemBalcao(e.target.value)}
                    style={{
                      width: '100%',
                      padding: '8px 10px',
                      background: 'var(--bg-primary)',
                      border: '1px solid var(--border-color)',
                      borderRadius: '4px',
                      color: 'var(--text-main)',
                      fontWeight: 600
                    }}
                  />
                  {buscandoSoftsystemBalcao && (
                    <RefreshCw size={14} className="animate-spin" style={{ position: 'absolute', right: '10px', top: '10px', color: 'var(--accent-primary)' }} />
                  )}
                </div>

                {/* Dropdown de Resultados da Busca Softsystem */}
                {softsystemResultadosBalcao.length > 0 && (
                  <div style={{
                    position: 'absolute',
                    top: '100%',
                    left: 0,
                    right: 0,
                    background: '#1e293b',
                    border: '1px solid var(--border-color)',
                    borderRadius: '4px',
                    boxShadow: '0 8px 16px rgba(0,0,0,0.5)',
                    zIndex: 20,
                    maxHeight: '180px',
                    overflowY: 'auto'
                  }}>
                    {softsystemResultadosBalcao.map((p) => (
                      <div
                        key={p.codigo}
                        onClick={() => selecionarProdutoSoftsystemBalcao(p)}
                        style={{
                          padding: '8px 12px',
                          borderBottom: '1px solid rgba(255,255,255,0.06)',
                          cursor: 'pointer',
                          display: 'flex',
                          justifyContent: 'space-between',
                          alignItems: 'center'
                        }}
                        onMouseEnter={(e) => e.currentTarget.style.background = 'rgba(255,255,255,0.05)'}
                        onMouseLeave={(e) => e.currentTarget.style.background = 'transparent'}
                      >
                        <div>
                          <div style={{ fontWeight: 600, color: '#f8fafc', fontSize: '12px' }}>
                            #{p.codigo} · {p.descricao}
                          </div>
                          <div style={{ fontSize: '11px', color: '#94a3b8' }}>
                            Original: {p.cod_original || '-'} · Grupo: {p.grupo}
                          </div>
                        </div>
                        <div style={{ textAlign: 'right' }}>
                          <div style={{ fontSize: '12px', color: 'var(--accent-primary)', fontWeight: 700 }}>
                            R$ {p.preco_venda.toFixed(2)}
                          </div>
                          <div style={{ fontSize: '11px', color: p.estoque > 0 ? '#4ade80' : '#f87171' }}>
                            Estoque: {p.estoque} {p.unidade}
                          </div>
                        </div>
                      </div>
                    ))}
                  </div>
                )}
              </div>

              {/* CARD DE PRODUTO IDENTIFICADO NO SOFTSYSTEM */}
              {softsystemProdutoSelecionado && (
                <div style={{
                  padding: '10px 12px',
                  background: 'rgba(34, 197, 94, 0.1)',
                  border: '1px solid rgba(34, 197, 94, 0.3)',
                  borderRadius: '6px',
                  fontSize: '12px'
                }}>
                  <div style={{ display: 'flex', justifyContent: 'space-between', alignItems: 'center' }}>
                    <div style={{ fontWeight: 700, color: '#4ade80', display: 'flex', alignItems: 'center', gap: '6px' }}>
                      <CheckCircle size={14} /> Produto Encontrado no Softsystem
                    </div>
                    <span style={{ fontSize: '11px', color: '#94a3b8' }}>Cód: #{softsystemProdutoSelecionado.codigo}</span>
                  </div>
                  <div style={{ marginTop: '4px', color: 'var(--text-main)', fontWeight: 600 }}>
                    {softsystemProdutoSelecionado.descricao}
                  </div>
                  <div style={{ marginTop: '4px', display: 'flex', gap: '14px', color: 'var(--text-muted)' }}>
                    <span>Estoque: <strong style={{ color: softsystemProdutoSelecionado.estoque > 0 ? '#4ade80' : '#f87171' }}>{softsystemProdutoSelecionado.estoque} {softsystemProdutoSelecionado.unidade}</strong></span>
                    <span>Preço Balcão: <strong style={{ color: 'var(--accent-primary)' }}>R$ {softsystemProdutoSelecionado.preco_venda.toFixed(2)}</strong></span>
                  </div>
                </div>
              )}

              {/* Nome do Produto */}
              <div>
                <label style={{ color: 'var(--text-muted)', display: 'block', marginBottom: '4px' }}>Descrição do Produto *</label>
                <input
                  type="text"
                  required
                  placeholder="Ex: CIRCUITO A DE CONTROLE DO PAINEL JOY 223 DV"
                  value={novoProdutoNome}
                  onChange={(e) => setNovoProdutoNome(e.target.value)}
                  style={{ width: '100%', padding: '8px', background: 'var(--bg-primary)', border: '1px solid var(--border-color)', borderRadius: '4px', color: 'var(--text-main)' }}
                />
              </div>

              {/* Dados do Cliente */}
              <div>
                <label style={{ color: 'var(--text-muted)', display: 'block', marginBottom: '4px' }}>Nome do Cliente *</label>
                <input
                  type="text"
                  required
                  placeholder="Ex: João da Silva / Metalúrgica Alfa"
                  value={novoClienteNome}
                  onChange={(e) => setNovoClienteNome(e.target.value)}
                  style={{ width: '100%', padding: '8px', background: 'var(--bg-primary)', border: '1px solid var(--border-color)', borderRadius: '4px', color: 'var(--text-main)' }}
                />
              </div>

              <div style={{ display: 'flex', gap: '10px' }}>
                <div style={{ flex: 1 }}>
                  <label style={{ color: 'var(--text-muted)', display: 'block', marginBottom: '4px' }}>WhatsApp com DDD (para aviso automático) *</label>
                  <input
                    type="text"
                    required
                    placeholder="Ex: 61999998888"
                    value={novoClienteTelefone}
                    onChange={(e) => setNovoClienteTelefone(e.target.value)}
                    style={{ width: '100%', padding: '8px', background: 'var(--bg-primary)', border: '1px solid var(--border-color)', borderRadius: '4px', color: 'var(--text-main)' }}
                  />
                </div>
                <div style={{ width: '90px' }}>
                  <label style={{ color: 'var(--text-muted)', display: 'block', marginBottom: '4px' }}>Quantidade</label>
                  <input
                    type="number"
                    min="1"
                    value={novoQuantidade}
                    onChange={(e) => setNovoQuantidade(parseFloat(e.target.value) || 1)}
                    style={{ width: '100%', padding: '8px', background: 'var(--bg-primary)', border: '1px solid var(--border-color)', borderRadius: '4px', color: 'var(--text-main)' }}
                  />
                </div>
              </div>

              <div>
                <label style={{ color: 'var(--text-muted)', display: 'block', marginBottom: '4px' }}>Observação do Atendimento</label>
                <input
                  type="text"
                  placeholder="Ex: Cliente aguardando para retirar no balcão"
                  value={novoObservacao}
                  onChange={(e) => setNovoObservacao(e.target.value)}
                  style={{ width: '100%', padding: '8px', background: 'var(--bg-primary)', border: '1px solid var(--border-color)', borderRadius: '4px', color: 'var(--text-main)' }}
                />
              </div>

              <div style={{ display: 'flex', justifyContent: 'flex-end', gap: '8px', marginTop: '10px' }}>
                <button
                  type="button"
                  onClick={() => setModalNovaDemanda(false)}
                  style={{ padding: '8px 14px', background: 'transparent', border: '1px solid var(--border-color)', color: 'var(--text-muted)', borderRadius: '4px', cursor: 'pointer' }}
                >
                  Cancelar
                </button>
                <button
                  type="submit"
                  disabled={salvandoDemanda}
                  style={{ padding: '8px 18px', background: 'var(--accent-primary)', color: '#051a12', border: 'none', borderRadius: '4px', fontWeight: 600, cursor: 'pointer' }}
                >
                  {salvandoDemanda ? 'Salvando...' : 'Registrar'}
                </button>
              </div>
            </form>
          </div>
        </div>
      )}

      {/* ============================================================== */}
      {/* MODAL: AUDITORIA DA DEMANDA                                    */}
      {/* ============================================================== */}
      {modalAuditoria && (
        <div style={{
          position: 'fixed',
          top: 0, left: 0, right: 0, bottom: 0,
          background: 'rgba(0,0,0,0.7)',
          display: 'flex',
          alignItems: 'center',
          justifyContent: 'center',
          zIndex: 10000,
          padding: '20px'
        }}>
          <div style={{
            background: 'var(--bg-secondary)',
            border: '1px solid var(--border-color)',
            borderRadius: 'var(--radius-lg)',
            width: '100%',
            maxWidth: '560px',
            padding: '24px',
            display: 'flex',
            flexDirection: 'column',
            gap: '16px'
          }}>
            <div style={{ display: 'flex', justifyContent: 'space-between', alignItems: 'center' }}>
              <div style={{ display: 'flex', alignItems: 'center', gap: '8px' }}>
                <ShieldCheck size={20} color="var(--accent-primary)" />
                <h3 style={{ margin: 0, fontSize: '16px', color: 'var(--text-main)', fontWeight: 700 }}>
                  Auditoria da Demanda #{modalAuditoria.id}
                </h3>
              </div>
              <button onClick={() => setModalAuditoria(null)} style={{ background: 'transparent', border: 'none', color: 'var(--text-muted)', cursor: 'pointer' }}>
                <X size={18} />
              </button>
            </div>

            <div style={{ fontSize: '13px', color: 'var(--text-muted)' }}>
              Cliente: <strong style={{ color: 'var(--text-main)' }}>{modalAuditoria.cliente_nome}</strong> · Telefone: <strong style={{ color: '#38bdf8' }}>{modalAuditoria.cliente_telefone}</strong>
            </div>

            <div style={{
              background: 'var(--bg-primary)',
              border: '1px solid var(--border-color)',
              borderRadius: 'var(--radius-sm)',
              padding: '14px',
              fontFamily: 'monospace',
              fontSize: '12px',
              color: 'var(--text-main)',
              maxHeight: '260px',
              overflowY: 'auto',
              whiteSpace: 'pre-wrap',
              lineHeight: 1.6
            }}>
              {modalAuditoria.historico_auditoria || 'Nenhum log gravado ainda.'}
            </div>

            <div style={{ display: 'flex', justifyContent: 'flex-end' }}>
              <button
                onClick={() => setModalAuditoria(null)}
                style={{ padding: '8px 16px', background: 'var(--bg-secondary)', border: '1px solid var(--border-color)', color: 'var(--text-main)', borderRadius: '4px', cursor: 'pointer' }}
              >
                Fechar
              </button>
            </div>
          </div>
        </div>
      )}

    </div>
  );
};

