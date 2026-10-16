// Tipos e chamadas da API do módulo Compras & Balcão (backend/app/api/v1/compras.py)

export type Empresa = 'servweld' | 'centrooeste';

export const NOME_LOJA: Record<Empresa, string> = {
  servweld: 'Servweld (Lucro Presumido)',
  centrooeste: 'Centro Oeste (Simples Nacional)',
};

export interface OpcaoMargem {
  rotulo: string;
  margem_pct: number;
  preco: number;
  abaixo_da_minima?: boolean;
}

export interface Concorrente {
  loja: string;
  preco: number;
  url: string;
  observacao?: string;
}

export interface ItemNota {
  id?: number;          // id do item já salvo na entrada
  item_id?: number;
  numero_item: number;
  codigo_fornecedor: string;
  ean?: string;
  descricao_fornecedor: string;
  ncm?: string;
  cest?: string;
  cfop?: string;
  unidade: string;
  quantidade: number;
  valor_unitario: number;
  valor_total: number;
  unidade_tributavel?: string;
  quantidade_tributavel?: number;
  cst_icms?: string;
  csosn?: string;
  v_icms?: number;
  v_icms_st?: number;
  v_ipi?: number;
  v_pis?: number;
  v_cofins?: number;
  // vínculo Softsystem
  softsystem_status?: 'vinculado' | 'novo' | 'indefinido';
  vinculo_metodo?: string | null;
  softsystem_prod_codigo?: string | null;
  softsystem_descricao?: string | null;
  softsystem_grupo?: string | null;
  softsystem_subgrupo?: string | null;
  softsystem_unidade?: string;
  softsystem_estoque?: number;
  softsystem_preco_venda?: number;
  softsystem_custo_medio?: number;
  softsystem_ncm?: string;
  alerta_ncm_diferente?: boolean;
  produto_modelo_codigo?: string | null;
  produto_modelo_descricao?: string | null;
  fator_conversao?: number;
  fator_conversao_sugerido?: number;
  // cálculo
  tem_st?: boolean;
  frete_rateado?: number;
  credito_icms?: number;
  credito_icms_cte?: number;
  custo_bruto_total?: number;
  custo_liquido_total?: number;
  custo_unitario_real?: number;
  impostos_saida?: Record<string, number>;
  impostos_saida_pct?: number;
  margem_lucro_pct?: number;
  preco_venda_sugerido?: number;
  preco_venda_final?: number;
  margem_real_pct?: number | null;
  markup_multiplicador?: number | null;
  variacao_custo_pct?: number | null;
  opcoes_margem?: OpcaoMargem[];
  composicao_preco?: Record<string, number> | null;
  alertas?: string[];
  preco_mercado_min?: number | null;
  preco_mercado_med?: number | null;
  preco_mercado_max?: number | null;
  preco_mercado_resumo?: string;
  concorrentes?: Concorrente[];
  // contagem
  qtd_esperada?: number;
  qtd_contada?: number | null;
  contado_por?: string | null;
  divergencia?: number;
  recontagens?: number;
}

export interface Nota {
  chave_acesso: string;
  numero_nf: string;
  serie: string;
  data_emissao: string;
  empresa_destino: Empresa;
  fornecedor: { cnpj: string; razao_social: string; nome_fantasia?: string; uf?: string; crt?: string };
  fornecedor_softsystem?: { codigo: string; razao_social: string } | null;
  destinatario: { cnpj: string; razao_social: string };
  transportadora: { cnpj: string; razao_social: string; modalidade_frete?: string };
  totais: Record<string, number>;
  duplicatas: { numero: string; vencimento: string; valor: number }[];
  itens: ItemNota[];
}

export interface Cte {
  carregado: boolean;
  chave_acesso: string;
  numero_cte?: string;
  transportadora?: { cnpj: string; razao_social: string };
  valor_frete_total?: number;
  icms?: { v_icms: number };
  frete_da_loja?: boolean;
  chaves_nfe?: string[];
  mensagem?: string;
}

export interface Parcela {
  numero: string;
  vencimento: string;
  valor: number;
  origem?: string;
}

export interface DespesaExtra {
  id: string;
  descricao: string;
  valor: number;
}

export interface Calculo {
  itens: ItemNota[];
  resumo: Record<string, number>;
  parametros: Record<string, any>;
}

export interface ResultadoBusca {
  status: 'ok' | 'ja_importada' | 'precisa_ciencia' | 'aguardando_xml' | 'nao_encontrado';
  proxima_tentativa_s?: number;
  mensagem?: string;
  origem?: string;
  empresa?: Empresa;
  nota?: Nota;
  cte?: Cte | null;
  calculo?: Calculo;
  parcelas?: Parcela[];
  avisos?: string[];
  entrada_id?: number;
  resumo?: { emitente_nome: string; emitente_cnpj: string; valor_total: number; data_emissao: string };
  chave?: string;
}

export interface EntradaResumo {
  id: number;
  empresa: Empresa;
  chave_acesso: string;
  numero_nf: string;
  fornecedor_nome: string;
  valor_total_nota: number;
  status: string;
  criado_em: string;
  criado_por: string;
  conferente?: string;
  data_emissao?: string;
  cte_numero?: string;
  valor_frete_cte?: number;
}

export interface Entrada extends EntradaResumo {
  itens: ItemNota[];
  eventos: { quando: string; usuario: string; acao: string; detalhe: string }[];
  parcelas: Parcela[];
  parcelas_cte: Parcela[];
  despesas_extras: DespesaExtra[];
  tipo_rateio_frete: string;
  divergencia_aprovada_por?: string;
  divergencia_justificativa?: string;
  fechada_por?: string;
  fechada_em?: string;
  softsystem_codcompra?: number | null;
  softsystem_modo?: 'desligado' | 'teste' | 'producao';
  eh_sem_cobranca?: boolean;
  natureza_operacao?: string;
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
  ncm: string;
  cod_clfiscal: string;
  custo_medio: number;
  similaridade?: number;
  palavras_em_comum?: string[];
}

export const STATUS_ENTRADA: Record<string, { rotulo: string; cor: string }> = {
  aguardando_contagem: { rotulo: 'Aguardando contagem', cor: '#f59e0b' },
  contagem_divergente: { rotulo: 'Contagem divergente', cor: '#ef4444' },
  contada: { rotulo: 'Contada - precificar', cor: '#3b82f6' },
  fechada: { rotulo: 'Fechada - aguardando Softsystem', cor: '#22c55e' },
  enviada_softsystem: { rotulo: 'Lançada no Softsystem', cor: '#16a34a' },
  cancelada: { rotulo: 'Cancelada', cor: '#6b7280' },
};

function headers(json = true): Record<string, string> {
  const h: Record<string, string> = { Authorization: `Bearer ${localStorage.getItem('token')}` };
  if (json) h['Content-Type'] = 'application/json';
  return h;
}

export async function api<T = any>(path: string, options: { method?: string; body?: any; form?: FormData; base?: string } = {}): Promise<T> {
  const method = options.method || (options.body || options.form ? 'POST' : 'GET');
  const fazer = () => fetch(`${options.base ?? '/api/v1/compras'}${path}`, {
    method,
    headers: headers(!options.form),
    body: options.form ? options.form : options.body !== undefined ? JSON.stringify(options.body) : undefined,
  });
  let res = await fazer();
  // consulta (GET) que pegou a conexão caindo: tenta de novo sozinha - envio (POST/PUT) não, pra
  // nunca gravar a mesma coisa duas vezes
  for (let tentativa = 0; method === 'GET' && [502, 503, 504].includes(res.status) && tentativa < 2; tentativa++) {
    await new Promise((r) => setTimeout(r, 1500 * (tentativa + 1)));
    res = await fazer();
  }
  let json: any = null;
  try {
    json = await res.json();
  } catch {
    /* resposta sem corpo */
  }
  if (!res.ok) {
    let msg = '';
    if (json) {
      if (typeof json.detail === 'string') msg = json.detail;
      else if (Array.isArray(json.detail)) msg = json.detail.map((d: any) => d.msg || JSON.stringify(d)).join('; ');
      else if (typeof json.message === 'string') msg = json.message;
      else if (typeof json.erro === 'string') msg = json.erro;
      else msg = JSON.stringify(json);
    }
    if (!msg) {
      // 502/503/504 sem corpo nosso = a conexão com o servidor caiu no caminho (túnel/internet)
      if ([502, 503, 504].includes(res.status)) {
        msg = 'A conexão com o servidor caiu por um instante (internet/túnel). Nada foi perdido do que já estava salvo - tente de novo em alguns segundos.';
      } else {
        msg = `Erro ${res.status}`;
      }
    }
    throw new Error(msg);
  }
  return json as T;
}

export const brl = (v?: number | null) =>
  v === undefined || v === null || Number.isNaN(v) ? '—' : v.toLocaleString('pt-BR', { style: 'currency', currency: 'BRL' });

export const pct = (v?: number | null, casas = 1) =>
  v === undefined || v === null || Number.isNaN(v) ? '—' : `${v.toLocaleString('pt-BR', { minimumFractionDigits: casas, maximumFractionDigits: casas })}%`;

export const dataBR = (iso?: string | null) => {
  if (!iso) return '—';
  const d = iso.length <= 10 ? new Date(`${iso}T12:00:00`) : new Date(iso);
  return Number.isNaN(d.getTime()) ? iso : d.toLocaleDateString('pt-BR');
};

export const formatarChave = (chave: string) => chave.replace(/\D/g, '').slice(0, 44).replace(/(\d{4})(?=\d)/g, '$1 ');

// Catálogo do site (fotos, textos web, vídeos, PDFs) - /api/v1/catalogo
export const catalogoApi = <T = any>(path: string, options: { method?: string; body?: any; form?: FormData } = {}) =>
  api<T>(path, { ...options, base: '/api/v1/catalogo' });

export interface PedidoCompraItem {
  id: number;
  pedido_id: number;
  referencia: string;
  descricao: string;
  quantidade: number;
  unidade: string;
  preco_estimado?: number | null;
  softsystem_codproduto?: number | null;
  balcao_espera_id?: number | null;
  observacao?: string | null;
  criado_em?: string;
}

export interface PedidoCompraResumo {
  id: number;
  empresa: Empresa;
  fabricante_nome: string;
  fornecedor_cnpj?: string | null;
  fornecedor_email?: string | null;
  fornecedor_whatsapp?: string | null;
  contato_nome?: string | null;
  status: 'aberto' | 'fechado' | 'cancelado';
  observacao?: string | null;
  criado_em: string;
  criado_por: string;
  fechado_em?: string | null;
  fechado_por?: string | null;
  total_itens: number;
  total_pecas: number;
}

export interface PedidoCompraDetalhe extends PedidoCompraResumo {
  itens: PedidoCompraItem[];
}

