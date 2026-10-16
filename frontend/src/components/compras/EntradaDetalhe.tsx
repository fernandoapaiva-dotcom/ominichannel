import React, { useEffect, useState } from 'react';
import { ArrowLeft, ClipboardCheck, DollarSign, History, XCircle, Send, CheckCircle2, MapPin, Globe, FolderOpen } from 'lucide-react';
import { api, brl, dataBR, Entrada, NOME_LOJA, STATUS_ENTRADA } from './comprasApi';
import { Aviso, Botao, Chip, card, td, th } from './ui';
import { ContagemCega } from './ContagemCega';
import { Precificacao } from './Precificacao';
import { EstoqueLocalizacao } from './EstoqueLocalizacao';
import { FotosSiteEntrada } from './FotosSiteEntrada';

interface Props {
  entradaId: number;
  isAdmin: boolean;
  onVoltar: () => void;
}

type Aba = 'contagem' | 'preco' | 'estoque' | 'site' | 'historico';

const ROTULO_ACAO: Record<string, string> = {
  importada: 'Nota importada', contagem_iniciada: 'Contagem iniciada', contagem: 'Item contado', recontagem: 'Item recontado',
  contagem_ok: 'Contagem conferida', contagem_divergente: 'Divergência na contagem', divergencia_aprovada: 'Divergência aprovada',
  precificacao: 'Preços atualizados', fechada: 'Entrada fechada', cancelada: 'Entrada cancelada',
  lancada_softsystem: 'Lançada no Softsystem', lancamento_teste: 'Lançamento de TESTE (cópia)',
  lancamento_recusado: 'Lançamento recusado', lancamento_falhou: 'Erro no lançamento',
  localizacao: 'Localização gravada', auditoria_estoque: 'Estoque conferido (pós-lançamento)',
  auditoria_estoque_pendente: 'Estoque contado - aguardando administrador',
  cadastro_confirmado: 'Cadastro de produto novo confirmado', auditoria_item: 'Estoque contado por loja',
  arquivada_pasta: 'Via salva na pasta de notas', arquivo_falhou: 'Falha ao salvar na pasta de notas',
};

export const EntradaDetalhe: React.FC<Props> = ({ entradaId, isAdmin, onVoltar }) => {
  const [entrada, setEntrada] = useState<Entrada | null>(null);
  const [aba, setAba] = useState<Aba>('contagem');
  const [erro, setErro] = useState<string | null>(null);
  const [versao, setVersao] = useState(0);

  const carregar = async (escolherAba = false) => {
    try {
      const r = await api<{ entrada: Entrada }>(`/entradas/${entradaId}`);
      setEntrada(r.entrada);
      setVersao((v) => v + 1);
      if (escolherAba) {
        const ev = r.entrada.eventos || [];
        const lancadaJa = r.entrada.status === 'enviada_softsystem' || ev.some((e) => e.acao === 'lancamento_teste');
        // depois de lançar, o fluxo segue sozinho: 3. estoque/localização -> 4. fotos e site
        setAba(['aguardando_contagem', 'contagem_divergente'].includes(r.entrada.status) ? 'contagem'
          : lancadaJa ? (ev.some((e) => ['localizacao', 'auditoria_estoque', 'auditoria_estoque_pendente'].includes(e.acao)) ? 'site' : 'estoque')
          : 'preco');
      }
    } catch (e: any) {
      setErro(e.message);
    }
  };

  useEffect(() => {
    carregar(true);
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [entradaId]);

  // Lança (ou tenta de novo) no Softsystem - normalmente já acontece sozinho ao fechar
  const [lancando, setLancando] = useState(false);
  const [msgLanc, setMsgLanc] = useState<{ tipo: 'ok' | 'erro'; texto: string } | null>(null);
  const lancar = async () => {
    if (!entrada) return;
    const teste = entrada.softsystem_modo === 'teste';
    if (!confirm(teste
      ? 'Lançar na CÓPIA DE TESTE do Softsystem? (o Softsystem de verdade não é alterado)'
      : 'Lançar esta entrada no Softsystem? Grava a compra, as contas a pagar, soma o estoque pela quantidade contada e atualiza custos e preços.')) return;
    setLancando(true);
    setMsgLanc(null);
    try {
      const r = await api<any>(`/entradas/${entrada.id}/lancar-softsystem`, { method: 'POST' });
      setMsgLanc({ tipo: 'ok', texto: r.mensagem });
      carregar(true);
    } catch (e: any) {
      setMsgLanc({ tipo: 'erro', texto: e.message });
      carregar();
    } finally {
      setLancando(false);
    }
  };

  const [arquivando, setArquivando] = useState(false);
  const arquivar = async () => {
    if (!entrada) return;
    setArquivando(true);
    try {
      await api(`/entradas/${entrada.id}/arquivar-pasta`, { method: 'POST' });
    } catch (e: any) {
      alert(e.message);
    } finally {
      setArquivando(false);
      carregar();
    }
  };

  const cancelar = async () => {
    if (!confirm('Cancelar esta entrada? Ela some do fluxo (fica no histórico).')) return;
    try {
      await api(`/entradas/${entradaId}/cancelar`, { method: 'POST' });
      onVoltar();
    } catch (e: any) {
      setErro(e.message);
    }
  };

  if (erro) return <Aviso tipo="erro">{erro}</Aviso>;
  if (!entrada) return <div style={{ ...card, color: 'var(--text-muted)' }}>Carregando entrada...</div>;

  const st = STATUS_ENTRADA[entrada.status] || { rotulo: entrada.status, cor: '#6b7280' };
  const emContagem = ['aguardando_contagem', 'contagem_divergente'].includes(entrada.status);
  const ocultas = (entrada as any).quantidades_ocultas;
  // etapa 3 só depois de lançada (no modo teste, depois do lançamento na cópia)
  const lancada = entrada.status === 'enviada_softsystem'
    || (entrada.status === 'fechada' && entrada.softsystem_modo === 'teste' && (entrada.eventos || []).some((ev) => ev.acao === 'lancamento_teste'));
  const divergentes = entrada.itens.filter((i) => i.qtd_contada !== null && i.qtd_contada !== undefined && Math.abs(i.divergencia || 0) > 0.001);

  const abas: { id: Aba; rotulo: string; icone: React.ReactNode; desabilitada?: boolean }[] = [
    { id: 'contagem', rotulo: '1. Contagem física', icone: <ClipboardCheck size={14} /> },
    { id: 'preco', rotulo: '2. Preço e vencimentos', icone: <DollarSign size={14} />, desabilitada: ocultas },
    { id: 'estoque', rotulo: '3. Estoque e localização', icone: <MapPin size={14} />, desabilitada: !lancada },
    { id: 'site', rotulo: '4. Fotos e site', icone: <Globe size={14} />, desabilitada: !lancada },
    { id: 'historico', rotulo: 'Auditoria', icone: <History size={14} /> },
  ];

  return (
    <div style={{ display: 'flex', flexDirection: 'column', gap: '14px' }}>
      <div style={{ ...card, display: 'flex', justifyContent: 'space-between', gap: '12px', flexWrap: 'wrap', alignItems: 'center' }}>
        <div style={{ display: 'flex', gap: '12px', alignItems: 'center' }}>
          <Botao variante="fantasma" icone={<ArrowLeft size={16} />} onClick={onVoltar} />
          <div>
            <div style={{ fontSize: '11px', color: 'var(--text-muted)', textTransform: 'uppercase', fontWeight: 700 }}>
              Entrada #{entrada.id} · NF-e {entrada.numero_nf} · {NOME_LOJA[entrada.empresa]}
            </div>
            <div style={{ fontSize: '17px', fontWeight: 700, color: 'var(--text-main)' }}>{entrada.fornecedor_nome}</div>
            <div style={{ fontSize: '12px', color: 'var(--text-muted)' }}>
              Emitida {dataBR(entrada.data_emissao)} · importada por {entrada.criado_por} em {dataBR(entrada.criado_em)}
              {entrada.cte_numero && ` · CT-e ${entrada.cte_numero} (${brl(entrada.valor_frete_cte)})`}
            </div>
          </div>
        </div>
        <div style={{ display: 'flex', gap: '10px', alignItems: 'center' }}>
          {!ocultas && <strong style={{ color: 'var(--text-main)' }}>{brl(entrada.valor_total_nota)}</strong>}
          <Chip cor={st.cor}>{st.rotulo}</Chip>
          {isAdmin && !['enviada_softsystem', 'cancelada'].includes(entrada.status) && (
            <Botao variante="perigo" icone={<XCircle size={13} />} onClick={cancelar} style={{ padding: '5px 10px' }}>Cancelar</Botao>
          )}
        </div>
      </div>

      {entrada.status === 'enviada_softsystem' && (
        <Aviso tipo="ok">
          <span style={{ display: 'inline-flex', alignItems: 'center', gap: '6px', fontWeight: 700 }}>
            <CheckCircle2 size={15} /> Lançada no Softsystem{entrada.softsystem_codcompra ? ` - compra ${entrada.softsystem_codcompra}` : ''}.
          </span>{' '}
          Compra, contas a pagar, estoque (quantidade contada), custos e preços de venda já estão lá.{' '}
          <div style={{ display: 'flex', gap: '8px', flexWrap: 'wrap', marginTop: '8px' }}>
            <Botao variante={aba === 'estoque' ? 'primario' : 'secundario'} icone={<MapPin size={14} />} onClick={() => setAba('estoque')}>
              3. Conferir estoque e localização
            </Botao>
            <Botao variante={aba === 'site' ? 'primario' : 'secundario'} icone={<Globe size={14} />} onClick={() => setAba('site')}>
              4. Fotos e site (e-commerce)
            </Botao>
          </div>
          {(() => {
            const arq = [...(entrada.eventos || [])].reverse().find((ev) => ['arquivada_pasta', 'arquivo_falhou'].includes(ev.acao));
            return (
              <div style={{ marginTop: '6px', fontSize: '12.5px', display: 'flex', gap: '8px', alignItems: 'center', flexWrap: 'wrap' }}>
                <FolderOpen size={14} />
                <span style={{ color: arq?.acao === 'arquivo_falhou' ? '#f87171' : undefined }}>
                  {arq ? arq.detalhe : 'Via (XML + DANFE) ainda não salva na pasta de notas.'}
                </span>
                <Botao variante="fantasma" onClick={arquivar} disabled={arquivando} style={{ padding: '3px 8px' }}>
                  {arquivando ? 'Salvando...' : arq?.acao === 'arquivada_pasta' ? 'Salvar de novo' : 'Salvar na pasta'}
                </Botao>
              </div>
            );
          })()}
        </Aviso>
      )}
      {entrada.status === 'fechada' && (() => {
        const ultimo = [...(entrada.eventos || [])].reverse().find((ev) => ev.acao.startsWith('lancamento_'));
        const modo = entrada.softsystem_modo || 'desligado';
        return (
          <Aviso tipo={ultimo && ultimo.acao !== 'lancamento_teste' ? 'alerta' : 'ok'}>
            <div style={{ marginBottom: '6px' }}>
              Entrada fechada por {entrada.fechada_por} em {dataBR(entrada.fechada_em)}.{' '}
              {modo === 'desligado' && 'O lançamento automático no Softsystem ainda não foi liberado neste servidor.'}
              {modo === 'teste' && <strong>Modo TESTE: o lançamento vai para a cópia do Softsystem, não para o de verdade.</strong>}
              {modo === 'producao' && 'Ainda não lançada no Softsystem.'}
            </div>
            {ultimo && (
              <div style={{ fontSize: '12.5px', marginBottom: '8px' }}>
                <strong>Última tentativa ({dataBR(ultimo.quando)}):</strong> {ultimo.detalhe}
              </div>
            )}
            {msgLanc && <div style={{ fontSize: '12.5px', marginBottom: '8px', color: msgLanc.tipo === 'erro' ? '#f87171' : '#22c55e', fontWeight: 700 }}>{msgLanc.texto}</div>}
            {modo !== 'desligado' && (
              <Botao icone={<Send size={14} />} onClick={lancar} disabled={lancando}>
                {lancando ? 'Lançando no Softsystem...' : modo === 'teste' ? 'Lançar na cópia de teste' : 'Lançar no Softsystem'}
              </Botao>
            )}
          </Aviso>
        );
      })()}

      <div style={{ display: 'flex', gap: '6px', borderBottom: '1px solid var(--border-color)' }}>
        {abas.map((a) => (
          <button key={a.id} disabled={a.desabilitada} onClick={() => setAba(a.id)}
            title={a.desabilitada ? (['estoque', 'site'].includes(a.id) ? 'Liberado depois do lançamento no Softsystem' : 'Liberado depois da contagem física') : ''}
            style={{
              display: 'flex', gap: '6px', alignItems: 'center', padding: '8px 14px', fontSize: '13px', fontWeight: 600,
              background: 'transparent', border: 'none', cursor: a.desabilitada ? 'not-allowed' : 'pointer', opacity: a.desabilitada ? 0.4 : 1,
              color: aba === a.id ? 'var(--accent-primary)' : 'var(--text-muted)',
              borderBottom: aba === a.id ? '2px solid var(--accent-primary)' : '2px solid transparent',
            }}>
            {a.icone}{a.rotulo}
          </button>
        ))}
      </div>

      {aba === 'contagem' && (
        emContagem ? (
          <ContagemCega entradaId={entrada.id} isAdmin={isAdmin} empresa={entrada.empresa} onMudouStatus={() => carregar(true)} />
        ) : (
          <div style={{ ...card, padding: 0, overflowX: 'auto' }}>
            <div style={{ padding: '12px 16px', fontSize: '13px', color: 'var(--text-main)' }}>
              Contagem concluída{entrada.divergencia_aprovada_por
                ? <> com divergência aprovada por <strong>{entrada.divergencia_aprovada_por}</strong>: “{entrada.divergencia_justificativa}”</>
                : ' — bateu com a nota.'}
            </div>
            <table style={{ width: '100%', borderCollapse: 'collapse' }}>
              <thead><tr><th style={th}>Item</th><th style={th}>Nota</th><th style={th}>Contado</th><th style={th}>Diferença</th><th style={th}>Conferente</th></tr></thead>
              <tbody>
                {entrada.itens.map((i) => (
                  <tr key={i.id} style={{ background: divergentes.includes(i) ? 'rgba(239,68,68,0.08)' : undefined }}>
                    <td style={td}>{i.softsystem_descricao || i.descricao_fornecedor}</td>
                    <td style={td}>{i.qtd_esperada}</td>
                    <td style={td}>{i.qtd_contada ?? '—'}</td>
                    <td style={{ ...td, color: (i.divergencia || 0) < 0 ? '#f87171' : (i.divergencia || 0) > 0 ? '#f59e0b' : 'var(--text-muted)' }}>
                      {i.divergencia ? (i.divergencia > 0 ? `+${i.divergencia}` : i.divergencia) : '0'}
                    </td>
                    <td style={td}>{i.contado_por || '—'}{i.recontagens ? ` (${i.recontagens}x recontado)` : ''}</td>
                  </tr>
                ))}
              </tbody>
            </table>
          </div>
        )
      )}

      {aba === 'preco' && !ocultas && <Precificacao key={versao} entrada={entrada} onAtualizada={() => carregar()} />}

      {aba === 'estoque' && lancada && <EstoqueLocalizacao entradaId={entrada.id} onSalvo={() => carregar()} onProximo={() => setAba('site')} />}

      {aba === 'site' && lancada && <FotosSiteEntrada entrada={entrada} />}

      {aba === 'historico' && (
        <div style={{ ...card, display: 'flex', flexDirection: 'column', gap: '10px' }}>
          {entrada.eventos.map((ev, i) => (
            <div key={i} style={{ display: 'flex', gap: '12px', fontSize: '13px' }}>
              <div style={{ minWidth: '130px', color: 'var(--text-muted)', fontSize: '12px' }}>
                {new Date(ev.quando + 'Z').toLocaleString('pt-BR')}
              </div>
              <div>
                <strong style={{ color: 'var(--text-main)' }}>{ROTULO_ACAO[ev.acao] || ev.acao}</strong>
                <span style={{ color: 'var(--text-muted)' }}> · {ev.usuario}</span>
                {ev.detalhe && <div style={{ color: 'var(--text-muted)', whiteSpace: 'pre-wrap' }}>{ev.detalhe}</div>}
              </div>
            </div>
          ))}
        </div>
      )}
    </div>
  );
};
