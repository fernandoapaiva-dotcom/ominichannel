import React, { useState, useEffect } from 'react';
import {
  FileText, Plus, Download, Send, CheckCircle, AlertTriangle, Search, Trash2,
  RefreshCw, Check, ArrowRight, X, Phone, Mail, ShoppingCart, Info, Sparkles
} from 'lucide-react';
import {
  api, Empresa, NOME_LOJA, dataBR, PedidoCompraResumo, PedidoCompraDetalhe,
  PedidoCompraItem, SoftsystemProduto
} from './comprasApi';
import { CadastroProdutoModal } from './CadastroProdutoModal';

interface PedidosCompraPanelProps {
  empresa: Empresa;
  usuarioNome: string;
}

interface SugestaoBalcao {
  demanda_id: number;
  cliente_nome: string;
  cliente_telefone: string;
  produto_nome: string;
  produto_codigo?: string;
  quantidade_desejada: number;
  observacao?: string;
  criado_em: string;
  motivo_sugestao: string;
}

export const PedidosCompraPanel: React.FC<PedidosCompraPanelProps> = ({ empresa, usuarioNome }) => {
  const [pedidos, setPedidos] = useState<PedidoCompraResumo[]>([]);
  const [loading, setLoading] = useState(false);
  const [pedidoSelecionado, setPedidoSelecionado] = useState<PedidoCompraDetalhe | null>(null);
  const [loadingDetalhe, setLoadingDetalhe] = useState(false);

  // Modal Novo Pedido
  const [modalNovo, setModalNovo] = useState(false);
  const [novoFabricante, setNovoFabricante] = useState('');
  const [novoContato, setNovoContato] = useState('');
  const [novoEmail, setNovoEmail] = useState('');
  const [novoWhatsapp, setNovoWhatsapp] = useState('');
  const [novoObs, setNovoObs] = useState('');
  const [erroNovo, setErroNovo] = useState<string | null>(null);

  // Adicionar Item
  const [buscaProduto, setBuscaProduto] = useState('');
  const [produtosSugestao, setProdutosSugestao] = useState<SoftsystemProduto[]>([]);
  const [loadingBusca, setLoadingBusca] = useState(false);
  const [itemRef, setItemRef] = useState('');
  const [itemDesc, setItemDesc] = useState('');
  const [itemQtd, setItemQtd] = useState(1);
  const [itemUn, setItemUn] = useState('UN');
  const [itemCodSoft, setItemCodSoft] = useState<number | null>(null);
  const [itemObs, setItemObs] = useState('');
  const [salvandoItem, setSalvandoItem] = useState(false);

  // Sugestões do Balcão
  const [sugestoesBalcao, setSugestoesBalcao] = useState<SugestaoBalcao[]>([]);
  const [loadingSugestoes, setLoadingSugestoes] = useState(false);

  // Modal Fechar Pedido
  const [modalFechar, setModalFechar] = useState(false);
  const [fecharEnvioWhats, setFecharEnvioWhats] = useState(true);
  const [fecharEnvioEmail, setFecharEnvioEmail] = useState(false);
  const [fechando, setFechando] = useState(false);

  // Modal Cadastrar Novo Produto Softsystem
  const [modalCadastroNovo, setModalCadastroNovo] = useState(false);

  useEffect(() => {
    carregarPedidos();
  }, [empresa]);

  useEffect(() => {
    if (pedidoSelecionado) {
      carregarSugestoesBalcao(pedidoSelecionado.id);
    }
  }, [pedidoSelecionado?.id]);

  const carregarPedidos = async () => {
    setLoading(true);
    try {
      const res = await api<{ success: boolean; pedidos: PedidoCompraResumo[] }>(`/pedidos?empresa=${empresa}`);
      setPedidos(res.pedidos || []);
      if (pedidoSelecionado) {
        const atual = res.pedidos.find(p => p.id === pedidoSelecionado.id);
        if (atual) carregarDetalhe(atual.id);
      }
    } catch (err: any) {
      console.error('Erro ao carregar pedidos:', err);
    } finally {
      setLoading(false);
    }
  };

  const carregarDetalhe = async (id: number) => {
    setLoadingDetalhe(true);
    try {
      const res = await api<{ success: boolean; pedido: PedidoCompraDetalhe }>(`/pedidos/${id}`);
      setPedidoSelecionado(res.pedido);
    } catch (err: any) {
      alert(`Erro ao abrir pedido: ${err.message}`);
    } finally {
      setLoadingDetalhe(false);
    }
  };

  const carregarSugestoesBalcao = async (pedidoId: number, termoExtra?: string) => {
    setLoadingSugestoes(true);
    try {
      const url = termoExtra
        ? `/pedidos/${pedidoId}/sugestoes-balcao?termo=${encodeURIComponent(termoExtra)}`
        : `/pedidos/${pedidoId}/sugestoes-balcao`;
      const res = await api<{ success: boolean; sugestoes: SugestaoBalcao[] }>(url);
      setSugestoesBalcao(res.sugestoes || []);
    } catch (err) {
      console.error('Erro ao buscar sugestões do balcão:', err);
    } finally {
      setLoadingSugestoes(false);
    }
  };

  const handleCriarPedido = async (e: React.FormEvent) => {
    e.preventDefault();
    if (!novoFabricante.trim()) return;
    setErroNovo(null);

    try {
      const res = await api<{ success: boolean; ja_existia: boolean; mensagem?: string; pedido: PedidoCompraDetalhe }>('/pedidos', {
        method: 'POST',
        body: {
          empresa,
          fabricante_nome: novoFabricante.trim(),
          contato_nome: novoContato.trim() || undefined,
          fornecedor_email: novoEmail.trim() || undefined,
          fornecedor_whatsapp: novoWhatsapp.trim() || undefined,
          observacao: novoObs.trim() || undefined,
        }
      });

      if (res.ja_existia) {
        alert(`⚠️ ${res.mensagem}`);
      }

      setModalNovo(false);
      setNovoFabricante('');
      setNovoContato('');
      setNovoEmail('');
      setNovoWhatsapp('');
      setNovoObs('');
      await carregarPedidos();
      if (res.pedido) carregarDetalhe(res.pedido.id);
    } catch (err: any) {
      setErroNovo(err.message || 'Erro ao criar pedido');
    }
  };

  const handleBuscarProdutoSoft = async (termo: string) => {
    setBuscaProduto(termo);
    if (termo.length < 2) {
      setProdutosSugestao([]);
      return;
    }
    setLoadingBusca(true);
    try {
      const res = await api<{ success: boolean; produtos: SoftsystemProduto[] }>(
        `/softsystem/produtos?empresa=${empresa}&termo=${encodeURIComponent(termo)}&limite=15`
      );
      setProdutosSugestao(res.produtos || []);
    } catch (err) {
      console.error('Erro na busca Softsystem:', err);
    } finally {
      setLoadingBusca(false);
    }
  };

  const selecionarProduto = (prod: SoftsystemProduto) => {
    setItemRef(prod.cod_original || prod.codigo.toString());
    setItemDesc(prod.descricao);
    setItemUn(prod.unidade || 'UN');
    setItemCodSoft(prod.codigo);
    setProdutosSugestao([]);
    setBuscaProduto('');
    if (pedidoSelecionado) {
      carregarSugestoesBalcao(pedidoSelecionado.id, prod.descricao);
    }
  };

  const handleAdicionarItem = async (e: React.FormEvent) => {
    e.preventDefault();
    if (!pedidoSelecionado || !itemRef.trim() || !itemDesc.trim()) return;

    setSalvandoItem(true);
    try {
      await api(`/pedidos/${pedidoSelecionado.id}/itens`, {
        method: 'POST',
        body: {
          referencia: itemRef.trim(),
          descricao: itemDesc.trim(),
          quantidade: itemQtd,
          unidade: itemUn,
          softsystem_codproduto: itemCodSoft,
          observacao: itemObs.trim() || undefined,
        }
      });

      setItemRef('');
      setItemDesc('');
      setItemQtd(1);
      setItemUn('UN');
      setItemCodSoft(null);
      setItemObs('');
      carregarDetalhe(pedidoSelecionado.id);
      carregarPedidos();
    } catch (err: any) {
      alert(`Erro ao adicionar item: ${err.message}`);
    } finally {
      setSalvandoItem(false);
    }
  };

  const handleAdicionarSugestaoBalcao = async (sug: SugestaoBalcao) => {
    if (!pedidoSelecionado) return;
    try {
      await api(`/pedidos/${pedidoSelecionado.id}/itens`, {
        method: 'POST',
        body: {
          referencia: sug.produto_codigo || sug.produto_nome.slice(0, 30),
          descricao: sug.produto_nome,
          quantidade: sug.quantidade_desejada || 1,
          unidade: 'UN',
          balcao_espera_id: sug.demanda_id,
          observacao: `Demanda cliente balcão: ${sug.cliente_nome}`,
        }
      });
      alert(`✅ Item adicionado ao pedido e integrado à demanda de ${sug.cliente_nome}!`);
      carregarDetalhe(pedidoSelecionado.id);
      carregarSugestoesBalcao(pedidoSelecionado.id);
      carregarPedidos();
    } catch (err: any) {
      alert(`Erro: ${err.message}`);
    }
  };

  const handleRemoverItem = async (itemId: number) => {
    if (!pedidoSelecionado || !confirm('Remover este item do pedido?')) return;
    try {
      await api(`/pedidos/${pedidoSelecionado.id}/itens/${itemId}`, { method: 'DELETE' });
      carregarDetalhe(pedidoSelecionado.id);
      carregarPedidos();
    } catch (err: any) {
      alert(`Erro ao remover: ${err.message}`);
    }
  };

  const handleBaixarCsvTelecontrol = async () => {
    if (!pedidoSelecionado) return;
    try {
      const res = await api<{ success: boolean; arquivos: { nome_arquivo: string; conteudo_csv: string; linhas_total: number }[] }>(
        `/pedidos/${pedidoSelecionado.id}/exportar-csv`
      );
      if (!res.arquivos || res.arquivos.length === 0) {
        alert('Nenhum item para exportar no CSV.');
        return;
      }
      res.arquivos.forEach((arq) => {
        const blob = new Blob([arq.conteudo_csv], { type: 'text/csv;charset=utf-8;' });
        const url = URL.createObjectURL(blob);
        const a = document.createElement('a');
        a.href = url;
        a.download = arq.nome_arquivo;
        document.body.appendChild(a);
        a.click();
        document.body.removeChild(a);
        URL.revokeObjectURL(url);
      });
    } catch (err: any) {
      alert(`Erro ao exportar CSV: ${err.message}`);
    }
  };

  const handleBaixarPdf = () => {
    if (!pedidoSelecionado) return;
    window.open(`/api/v1/compras/pedidos/${pedidoSelecionado.id}/exportar-pdf`, '_blank');
  };

  const handleFecharPedido = async () => {
    if (!pedidoSelecionado) return;
    setFechando(true);
    try {
      await api(`/pedidos/${pedidoSelecionado.id}/fechar?enviar_whatsapp=${fecharEnvioWhats}&enviar_email=${fecharEnvioEmail}`, {
        method: 'POST'
      });
      alert('✅ Pedido de Compra finalizado com sucesso!');
      setModalFechar(false);
      carregarDetalhe(pedidoSelecionado.id);
      carregarPedidos();
    } catch (err: any) {
      alert(`Erro ao fechar pedido: ${err.message}`);
    } finally {
      setFechando(false);
    }
  };

  return (
    <div className="flex flex-col h-full bg-slate-50">
      {/* Topo / Header */}
      <div className="bg-white border-b border-slate-200 px-6 py-4 flex items-center justify-between">
        <div>
          <h2 className="text-xl font-bold text-slate-800 flex items-center gap-2">
            <ShoppingCart className="w-6 h-6 text-indigo-600" />
            Pedidos de Compra por Fabricante ({NOME_LOJA[empresa]})
          </h2>
          <p className="text-sm text-slate-500">
            Lançamento contínuo durante o mês, exportação Telecontrol (CSV 500 linhas) ou PDF e integração com Balcão de Espera.
          </p>
        </div>
        <button
          onClick={() => setModalNovo(true)}
          className="flex items-center gap-2 px-4 py-2 bg-indigo-600 hover:bg-indigo-700 text-white rounded-lg font-medium shadow-sm transition"
        >
          <Plus className="w-5 h-5" />
          Novo Pedido de Fornecedor
        </button>
      </div>

      {/* Conteúdo Principal (Grade com Lista à esquerda e Detalhe à direita) */}
      <div className="flex-1 flex overflow-hidden">
        {/* Painel Esquerdo: Lista de Pedidos */}
        <div className="w-80 md:w-96 border-r border-slate-200 bg-white flex flex-col">
          <div className="p-3 border-b border-slate-100 flex items-center justify-between text-xs font-semibold text-slate-500 uppercase">
            <span>Pedidos ({pedidos.length})</span>
            <button onClick={carregarPedidos} className="hover:text-slate-800 p-1">
              <RefreshCw className={`w-3.5 h-3.5 ${loading ? 'animate-spin' : ''}`} />
            </button>
          </div>

          <div className="flex-1 overflow-y-auto divide-y divide-slate-100">
            {pedidos.length === 0 && !loading && (
              <div className="p-6 text-center text-slate-400 text-sm">
                Nenhum pedido de compra criado ainda nesta loja.
              </div>
            )}
            {pedidos.map((p) => {
              const selecionado = pedidoSelecionado?.id === p.id;
              return (
                <div
                  key={p.id}
                  onClick={() => carregarDetalhe(p.id)}
                  className={`p-4 cursor-pointer transition flex flex-col gap-1.5 ${
                    selecionado ? 'bg-indigo-50/80 border-l-4 border-indigo-600' : 'hover:bg-slate-50'
                  }`}
                >
                  <div className="flex items-center justify-between">
                    <span className="font-bold text-slate-800 text-sm">{p.fabricante_nome}</span>
                    <span
                      className={`px-2 py-0.5 rounded-full text-xs font-semibold ${
                        p.status === 'aberto'
                          ? 'bg-amber-100 text-amber-800'
                          : p.status === 'fechado'
                          ? 'bg-emerald-100 text-emerald-800'
                          : 'bg-slate-100 text-slate-600'
                      }`}
                    >
                      {p.status.toUpperCase()}
                    </span>
                  </div>

                  <div className="flex items-center justify-between text-xs text-slate-500">
                    <span>Pedido #{p.id.toString().padStart(5, '0')}</span>
                    <span>{dataBR(p.criado_em)}</span>
                  </div>

                  <div className="flex items-center justify-between text-xs text-slate-600 font-medium mt-1">
                    <span>{p.total_itens} item(ns)</span>
                    <span className="text-slate-800 font-semibold">{p.total_pecas} peça(s)</span>
                  </div>
                </div>
              );
            })}
          </div>
        </div>

        {/* Painel Direito: Detalhes do Pedido Selecionado */}
        <div className="flex-1 flex flex-col overflow-y-auto bg-slate-50">
          {pedidoSelecionado ? (
            <div className="p-6 max-w-5xl w-full mx-auto flex flex-col gap-6">
              {/* Card de Cabeçalho do Pedido */}
              <div className="bg-white rounded-xl shadow-sm border border-slate-200 p-5 flex flex-col gap-4">
                <div className="flex items-start justify-between">
                  <div>
                    <div className="flex items-center gap-3">
                      <h3 className="text-2xl font-bold text-slate-800">{pedidoSelecionado.fabricante_nome}</h3>
                      <span
                        className={`px-3 py-1 rounded-full text-xs font-bold ${
                          pedidoSelecionado.status === 'aberto'
                            ? 'bg-amber-100 text-amber-800'
                            : 'bg-emerald-100 text-emerald-800'
                        }`}
                      >
                        {pedidoSelecionado.status === 'aberto' ? 'EM LANÇAMENTO CONTÍNUO' : 'PEDIDO FECHADO'}
                      </span>
                    </div>
                    <p className="text-sm text-slate-500 mt-0.5">
                      Pedido #{pedidoSelecionado.id.toString().padStart(5, '0')} • Criado por {pedidoSelecionado.criado_por} em {dataBR(pedidoSelecionado.criado_em)}
                    </p>
                  </div>

                  {/* Ações de Exportação e Fechamento */}
                  <div className="flex items-center gap-2">
                    <button
                      onClick={handleBaixarCsvTelecontrol}
                      title="Exportar CSV (Telecontrol - máx 500 linhas)"
                      className="flex items-center gap-1.5 px-3 py-2 bg-slate-100 hover:bg-slate-200 text-slate-700 rounded-lg text-sm font-medium transition"
                    >
                      <Download className="w-4 h-4 text-emerald-600" />
                      CSV Telecontrol
                    </button>
                    <button
                      onClick={handleBaixarPdf}
                      title="Exportar PDF Timbrado da Loja"
                      className="flex items-center gap-1.5 px-3 py-2 bg-slate-100 hover:bg-slate-200 text-slate-700 rounded-lg text-sm font-medium transition"
                    >
                      <FileText className="w-4 h-4 text-rose-600" />
                      PDF Loja
                    </button>
                    {pedidoSelecionado.status === 'aberto' && (
                      <button
                        onClick={() => setModalFechar(true)}
                        className="flex items-center gap-1.5 px-4 py-2 bg-emerald-600 hover:bg-emerald-700 text-white rounded-lg text-sm font-semibold shadow-sm transition"
                      >
                        <CheckCircle className="w-4 h-4" />
                        Fechar e Enviar
                      </button>
                    )}
                  </div>
                </div>

                {/* Dados de Contato e Resumo */}
                <div className="grid grid-cols-2 md:grid-cols-4 gap-3 pt-3 border-t border-slate-100 text-xs text-slate-600">
                  <div>
                    <span className="font-semibold block text-slate-500">Contato:</span>
                    {pedidoSelecionado.contato_nome || '—'}
                  </div>
                  <div>
                    <span className="font-semibold block text-slate-500">WhatsApp Fornecedor:</span>
                    {pedidoSelecionado.fornecedor_whatsapp || '—'}
                  </div>
                  <div>
                    <span className="font-semibold block text-slate-500">E-mail:</span>
                    {pedidoSelecionado.fornecedor_email || '—'}
                  </div>
                  <div>
                    <span className="font-semibold block text-slate-500">Total de Peças:</span>
                    <span className="text-slate-900 font-bold text-sm">
                      {pedidoSelecionado.itens.reduce((acc, it) => acc + it.quantidade, 0)} peças ({pedidoSelecionado.itens.length} itens)
                    </span>
                  </div>
                </div>
              </div>

              {/* Banner de Sugestões da Fila do Balcão */}
              {sugestoesBalcao.length > 0 && pedidoSelecionado.status === 'aberto' && (
                <div className="bg-gradient-to-r from-amber-50 to-orange-50 border border-amber-200 rounded-xl p-4 flex flex-col gap-3 shadow-sm">
                  <div className="flex items-center justify-between">
                    <div className="flex items-center gap-2">
                      <Sparkles className="w-5 h-5 text-amber-600" />
                      <h4 className="font-bold text-amber-950 text-sm">
                        Oportunidade do Balcão: Clientes aguardando peças compatíveis ({sugestoesBalcao.length})
                      </h4>
                    </div>
                    <span className="text-xs text-amber-700 font-medium">Avisa-me quando chegar</span>
                  </div>

                  <div className="grid grid-cols-1 md:grid-cols-2 gap-2">
                    {sugestoesBalcao.map((sug) => (
                      <div
                        key={sug.demanda_id}
                        className="bg-white/90 border border-amber-200 rounded-lg p-3 flex items-center justify-between gap-3 text-xs"
                      >
                        <div>
                          <div className="font-bold text-slate-800">{sug.produto_nome}</div>
                          <div className="text-slate-500">
                            Cliente: <span className="font-medium text-slate-700">{sug.cliente_nome}</span> • Qtd: <span className="font-bold text-indigo-700">{sug.quantidade_desejada}</span>
                          </div>
                          <div className="text-amber-800 text-[11px] font-medium mt-0.5">{sug.motivo_sugestao}</div>
                        </div>
                        <button
                          onClick={() => handleAdicionarSugestaoBalcao(sug)}
                          className="px-3 py-1.5 bg-amber-600 hover:bg-amber-700 text-white rounded-md font-semibold text-xs transition shrink-0"
                        >
                          + Adicionar ao Pedido
                        </button>
                      </div>
                    ))}
                  </div>
                </div>
              )}

              {/* Formulário: Adicionar Item ao Pedido */}
              {pedidoSelecionado.status === 'aberto' && (
                <div className="bg-white rounded-xl shadow-sm border border-slate-200 p-5 flex flex-col gap-4">
                  <div className="flex items-center justify-between">
                    <h4 className="font-bold text-slate-800 text-sm flex items-center gap-2">
                      <Plus className="w-4 h-4 text-indigo-600" />
                      Adicionar Peça / Item ao Pedido
                    </h4>
                    <button
                      type="button"
                      onClick={() => setModalCadastroNovo(true)}
                      className="text-xs text-indigo-600 hover:text-indigo-800 font-semibold flex items-center gap-1"
                    >
                      <Sparkles className="w-3.5 h-3.5" />
                      Peça não existe no Softsystem? Cadastrar nova
                    </button>
                  </div>

                  {/* Busca no Softsystem */}
                  <div className="relative">
                    <label className="text-xs font-semibold text-slate-600 block mb-1">
                      Puxar do cadastro do Softsystem (código, referência ou descrição):
                    </label>
                    <div className="relative">
                      <Search className="w-4 h-4 text-slate-400 absolute left-3 top-3" />
                      <input
                        type="text"
                        value={buscaProduto}
                        onChange={(e) => handleBuscarProdutoSoft(e.target.value)}
                        placeholder="Digite para buscar e autocompletar os dados..."
                        className="w-full pl-9 pr-4 py-2 border border-slate-300 rounded-lg text-sm focus:ring-2 focus:ring-indigo-500 outline-none"
                      />
                      {loadingBusca && (
                        <RefreshCw className="w-4 h-4 text-slate-400 animate-spin absolute right-3 top-3" />
                      )}
                    </div>

                    {/* Dropdown de Resultados da busca Softsystem */}
                    {produtosSugestao.length > 0 && (
                      <div className="absolute z-10 w-full mt-1 bg-white border border-slate-200 rounded-lg shadow-lg max-h-60 overflow-y-auto divide-y divide-slate-100">
                        {produtosSugestao.map((prod) => (
                          <div
                            key={prod.codigo}
                            onClick={() => selecionarProduto(prod)}
                            className="p-3 hover:bg-indigo-50 cursor-pointer flex items-center justify-between text-xs transition"
                          >
                            <div>
                              <div className="font-bold text-slate-800">{prod.descricao}</div>
                              <div className="text-slate-500">
                                Cód: <span className="font-semibold text-slate-700">{prod.codigo}</span> • Ref: {prod.cod_original || '—'} • Un: {prod.unidade}
                              </div>
                            </div>
                            <div className="text-right">
                              <span className="text-xs font-semibold text-emerald-600">Estoque: {prod.estoque}</span>
                            </div>
                          </div>
                        ))}
                      </div>
                    )}
                  </div>

                  {/* Campos do Item */}
                  <form onSubmit={handleAdicionarItem} className="grid grid-cols-1 md:grid-cols-12 gap-3 items-end">
                    <div className="md:col-span-3">
                      <label className="text-xs font-semibold text-slate-600 block mb-1">
                        Referência da Peça *
                      </label>
                      <input
                        type="text"
                        required
                        value={itemRef}
                        onChange={(e) => setItemRef(e.target.value)}
                        placeholder="Ex: 0905441"
                        className="w-full px-3 py-2 border border-slate-300 rounded-lg text-sm font-semibold uppercase outline-none focus:ring-2 focus:ring-indigo-500"
                      />
                    </div>

                    <div className="md:col-span-5">
                      <label className="text-xs font-semibold text-slate-600 block mb-1">
                        Descrição do Material *
                      </label>
                      <input
                        type="text"
                        required
                        value={itemDesc}
                        onChange={(e) => setItemDesc(e.target.value)}
                        placeholder="Ex: TOCHA MIG 5M BARBOSA SOLDAS"
                        className="w-full px-3 py-2 border border-slate-300 rounded-lg text-sm uppercase outline-none focus:ring-2 focus:ring-indigo-500"
                      />
                    </div>

                    <div className="md:col-span-2">
                      <label className="text-xs font-semibold text-slate-600 block mb-1">
                        Quantidade *
                      </label>
                      <input
                        type="number"
                        min="0.01"
                        step="any"
                        required
                        value={itemQtd}
                        onChange={(e) => setItemQtd(parseFloat(e.target.value) || 1)}
                        className="w-full px-3 py-2 border border-slate-300 rounded-lg text-sm text-center font-bold outline-none focus:ring-2 focus:ring-indigo-500"
                      />
                    </div>

                    <div className="md:col-span-2">
                      <button
                        type="submit"
                        disabled={salvandoItem}
                        className="w-full py-2 bg-indigo-600 hover:bg-indigo-700 text-white rounded-lg text-sm font-semibold shadow-sm transition flex items-center justify-center gap-1.5"
                      >
                        {salvandoItem ? <RefreshCw className="w-4 h-4 animate-spin" /> : <Plus className="w-4 h-4" />}
                        Lançar
                      </button>
                    </div>
                  </form>
                </div>
              )}

              {/* Tabela de Itens Lançados */}
              <div className="bg-white rounded-xl shadow-sm border border-slate-200 overflow-hidden">
                <div className="p-4 border-b border-slate-200 flex items-center justify-between">
                  <h4 className="font-bold text-slate-800 text-sm">Itens do Pedido ({pedidoSelecionado.itens.length})</h4>
                  <span className="text-xs text-slate-500">Padrão Telecontrol: Referência ; Quantidade</span>
                </div>

                <div className="overflow-x-auto">
                  <table className="w-full text-left text-sm">
                    <thead className="bg-slate-50 text-slate-600 font-semibold text-xs border-b border-slate-200">
                      <tr>
                        <th className="py-2.5 px-4 w-12 text-center">#</th>
                        <th className="py-2.5 px-4 w-40">Referência</th>
                        <th className="py-2.5 px-4">Descrição</th>
                        <th className="py-2.5 px-4 w-24 text-center">Un</th>
                        <th className="py-2.5 px-4 w-28 text-right">Qtd</th>
                        {pedidoSelecionado.status === 'aberto' && (
                          <th className="py-2.5 px-4 w-16 text-center">Ações</th>
                        )}
                      </tr>
                    </thead>
                    <tbody className="divide-y divide-slate-100">
                      {pedidoSelecionado.itens.length === 0 ? (
                        <tr>
                          <td colSpan={6} className="py-8 text-center text-slate-400">
                            Nenhum item lançado neste pedido ainda. Adicione acima.
                          </td>
                        </tr>
                      ) : (
                        pedidoSelecionado.itens.map((it, idx) => (
                          <tr key={it.id} className="hover:bg-slate-50/70">
                            <td className="py-2.5 px-4 text-center text-xs text-slate-400">{idx + 1}</td>
                            <td className="py-2.5 px-4 font-bold text-slate-900">{it.referencia}</td>
                            <td className="py-2.5 px-4">
                              <div className="font-medium text-slate-800">{it.descricao}</div>
                              {it.observacao && (
                                <div className="text-xs text-amber-700 italic">{it.observacao}</div>
                              )}
                            </td>
                            <td className="py-2.5 px-4 text-center text-xs text-slate-500">{it.unidade}</td>
                            <td className="py-2.5 px-4 text-right font-bold text-slate-900">{it.quantidade}</td>
                            {pedidoSelecionado.status === 'aberto' && (
                              <td className="py-2.5 px-4 text-center">
                                <button
                                  onClick={() => handleRemoverItem(it.id)}
                                  className="text-slate-400 hover:text-rose-600 p-1 rounded transition"
                                  title="Remover item"
                                >
                                  <Trash2 className="w-4 h-4" />
                                </button>
                              </td>
                            )}
                          </tr>
                        ))
                      )}
                    </tbody>
                  </table>
                </div>
              </div>
            </div>
          ) : (
            <div className="flex-1 flex flex-col items-center justify-center text-slate-400 gap-3">
              <ShoppingCart className="w-12 h-12 text-slate-300 stroke-[1.5]" />
              <p>Selecione um pedido à esquerda ou crie um novo para o fabricante.</p>
            </div>
          )}
        </div>
      </div>

      {/* Modal: Novo Pedido de Compra */}
      {modalNovo && (
        <div className="fixed inset-0 bg-slate-900/60 backdrop-blur-sm z-50 flex items-center justify-center p-4">
          <div className="bg-white rounded-xl shadow-2xl max-w-md w-full overflow-hidden animate-in fade-in zoom-in-95 duration-150">
            <div className="px-6 py-4 bg-slate-900 text-white flex items-center justify-between">
              <h3 className="font-bold flex items-center gap-2">
                <ShoppingCart className="w-5 h-5 text-indigo-400" />
                Novo Pedido por Fabricante
              </h3>
              <button onClick={() => setModalNovo(false)} className="text-slate-400 hover:text-white">
                <X className="w-5 h-5" />
              </button>
            </div>

            <form onSubmit={handleCriarPedido} className="p-6 flex flex-col gap-4">
              <div className="p-3 bg-amber-50 border border-amber-200 rounded-lg text-xs text-amber-900 leading-relaxed">
                <strong>Regra da Casa:</strong> Apenas 1 pedido em aberto por fabricante. Se já houver um aberto, o sistema direcionará você para continuar lançando nele.
              </div>

              {erroNovo && (
                <div className="p-3 bg-rose-50 border border-rose-200 text-rose-700 text-xs rounded-lg">
                  {erroNovo}
                </div>
              )}

              <div>
                <label className="text-xs font-semibold text-slate-700 block mb-1">
                  Nome do Fabricante / Fornecedor *
                </label>
                <input
                  type="text"
                  required
                  value={novoFabricante}
                  onChange={(e) => setNovoFabricante(e.target.value)}
                  placeholder="Ex: ESAB, BALMER, BARBOSA SOLDAS..."
                  className="w-full px-3 py-2 border border-slate-300 rounded-lg text-sm uppercase outline-none focus:ring-2 focus:ring-indigo-500"
                />
              </div>

              <div className="grid grid-cols-2 gap-3">
                <div>
                  <label className="text-xs font-semibold text-slate-700 block mb-1">
                    Nome do Contato
                  </label>
                  <input
                    type="text"
                    value={novoContato}
                    onChange={(e) => setNovoContato(e.target.value)}
                    placeholder="Vendedor / Representante"
                    className="w-full px-3 py-2 border border-slate-300 rounded-lg text-sm outline-none focus:ring-2 focus:ring-indigo-500"
                  />
                </div>
                <div>
                  <label className="text-xs font-semibold text-slate-700 block mb-1">
                    WhatsApp para Envio
                  </label>
                  <input
                    type="text"
                    value={novoWhatsapp}
                    onChange={(e) => setNovoWhatsapp(e.target.value)}
                    placeholder="61999999999"
                    className="w-full px-3 py-2 border border-slate-300 rounded-lg text-sm outline-none focus:ring-2 focus:ring-indigo-500"
                  />
                </div>
              </div>

              <div>
                <label className="text-xs font-semibold text-slate-700 block mb-1">
                  E-mail do Fornecedor
                </label>
                <input
                  type="email"
                  value={novoEmail}
                  onChange={(e) => setNovoEmail(e.target.value)}
                  placeholder="pedidos@fabricante.com.br"
                  className="w-full px-3 py-2 border border-slate-300 rounded-lg text-sm outline-none focus:ring-2 focus:ring-indigo-500"
                />
              </div>

              <div>
                <label className="text-xs font-semibold text-slate-700 block mb-1">
                  Observações Gerais
                </label>
                <textarea
                  value={novoObs}
                  onChange={(e) => setNovoObs(e.target.value)}
                  rows={2}
                  placeholder="Condição de pagamento, transportadora de preferência, etc."
                  className="w-full px-3 py-2 border border-slate-300 rounded-lg text-sm outline-none focus:ring-2 focus:ring-indigo-500"
                />
              </div>

              <div className="flex items-center justify-end gap-2 pt-2 border-t border-slate-100">
                <button
                  type="button"
                  onClick={() => setModalNovo(false)}
                  className="px-4 py-2 border border-slate-300 text-slate-700 rounded-lg text-sm font-medium hover:bg-slate-50 transition"
                >
                  Cancelar
                </button>
                <button
                  type="submit"
                  className="px-5 py-2 bg-indigo-600 hover:bg-indigo-700 text-white rounded-lg text-sm font-semibold transition"
                >
                  Abrir Pedido
                </button>
              </div>
            </form>
          </div>
        </div>
      )}

      {/* Modal: Fechar Pedido e Enviar */}
      {modalFechar && pedidoSelecionado && (
        <div className="fixed inset-0 bg-slate-900/60 backdrop-blur-sm z-50 flex items-center justify-center p-4">
          <div className="bg-white rounded-xl shadow-2xl max-w-md w-full overflow-hidden animate-in fade-in zoom-in-95 duration-150">
            <div className="px-6 py-4 bg-emerald-700 text-white flex items-center justify-between">
              <h3 className="font-bold flex items-center gap-2">
                <CheckCircle className="w-5 h-5" />
                Fechar Pedido de Compra
              </h3>
              <button onClick={() => setModalFechar(false)} className="text-emerald-200 hover:text-white">
                <X className="w-5 h-5" />
              </button>
            </div>

            <div className="p-6 flex flex-col gap-4">
              <p className="text-sm text-slate-600">
                Você está finalizando o pedido de <strong>{pedidoSelecionado.fabricante_nome}</strong> com{' '}
                <strong>{pedidoSelecionado.itens.length} itens</strong> ({pedidoSelecionado.itens.reduce((acc, it) => acc + it.quantidade, 0)} peças).
              </p>

              <div className="flex flex-col gap-2 p-3 bg-slate-50 border border-slate-200 rounded-lg">
                <span className="text-xs font-bold text-slate-700 uppercase">Canais de Envio:</span>
                <label className="flex items-center gap-2 text-sm text-slate-700 cursor-pointer">
                  <input
                    type="checkbox"
                    checked={fecharEnvioWhats}
                    onChange={(e) => setFecharEnvioWhats(e.target.checked)}
                    className="rounded text-indigo-600 focus:ring-indigo-500"
                  />
                  <span>
                    Enviar aviso via WhatsApp para: <strong>{pedidoSelecionado.fornecedor_whatsapp || '(não informado)'}</strong>
                  </span>
                </label>
              </div>

              <div className="flex items-center justify-end gap-2 pt-2 border-t border-slate-100">
                <button
                  type="button"
                  onClick={() => setModalFechar(false)}
                  className="px-4 py-2 border border-slate-300 text-slate-700 rounded-lg text-sm font-medium hover:bg-slate-50 transition"
                >
                  Voltar
                </button>
                <button
                  onClick={handleFecharPedido}
                  disabled={fechando}
                  className="px-5 py-2 bg-emerald-600 hover:bg-emerald-700 text-white rounded-lg text-sm font-semibold transition flex items-center gap-2"
                >
                  {fechando ? <RefreshCw className="w-4 h-4 animate-spin" /> : <Check className="w-4 h-4" />}
                  Confirmar e Fechar Pedido
                </button>
              </div>
            </div>
          </div>
        </div>
      )}

      {/* Modal: Cadastro de Novo Produto no Softsystem */}
      {modalCadastroNovo && (
        <CadastroProdutoModal
          empresa={empresa}
          item={{
            numero_item: 1,
            codigo_fornecedor: itemRef || '',
            descricao_fornecedor: itemDesc || '',
            unidade: itemUn || 'UN',
            quantidade: 1,
            valor_unitario: 0,
            valor_total: 0,
          }}
          fornecedorNome={pedidoSelecionado?.fabricante_nome || ''}
          onFechar={() => setModalCadastroNovo(false)}
          onSalvar={(confirmado) => {
            // Cria no Softsystem diretamente
            api<{ success: boolean; codproduto: number }>('/cadastrar-produto-direto', {
              method: 'POST',
              body: {
                empresa,
                descricao: confirmado.descricao,
                modelo_codigo: confirmado.modelo_codigo,
                unidade: confirmado.unidade,
                ncm: confirmado.ncm,
                codgrupo: confirmado.codgrupo,
                codsubgrupo: confirmado.codsubgrupo,
                codsubgruponivel2: confirmado.codsubgruponivel2,
                codsubgruponivel3: confirmado.codsubgruponivel3,
                codmarca: confirmado.codmarca,
                marca_nova: confirmado.marca_nova,
                referencia: confirmado.referencia || itemRef,
                peso: confirmado.peso,
              }
            }).then((res) => {
              alert(`✅ Produto cadastrado com sucesso no Softsystem! Código: ${res.codproduto}`);
              setItemRef(confirmado.referencia || itemRef || res.codproduto.toString());
              setItemDesc(confirmado.descricao);
              setItemUn(confirmado.unidade);
              setItemCodSoft(res.codproduto);
              setModalCadastroNovo(false);
            }).catch((err: any) => {
              alert(`Erro ao cadastrar produto no Softsystem: ${err.message}`);
            });
          }}
        />
      )}
    </div>
  );
};

