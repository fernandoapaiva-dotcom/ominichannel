import React, { useEffect, useState } from 'react';
import { ShieldCheck, Upload, AlertTriangle } from 'lucide-react';
import { api, dataBR, Empresa, NOME_LOJA } from './comprasApi';
import { Aviso, Botao, Campo, Chip, card, input } from './ui';

interface InfoCert {
  configurado: boolean;
  titular?: string;
  cnpj?: string;
  validade?: string;
  dias_restantes?: number;
  erro?: string;
}

interface Props {
  empresa: Empresa;
  isAdmin: boolean;
}

/**
 * Certificado A1 (.pfx) da loja - é com ele que o sistema busca a NF-e/CT-e na SEFAZ só com a
 * chave. O arquivo fica no servidor e a senha é guardada criptografada; ninguém consegue ver
 * a senha depois de enviada.
 */
export const CertificadoDigital: React.FC<Props> = ({ empresa, isAdmin }) => {
  const [info, setInfo] = useState<InfoCert | null>(null);
  const [arquivo, setArquivo] = useState<File | null>(null);
  const [senha, setSenha] = useState('');
  const [enviando, setEnviando] = useState(false);
  const [mensagem, setMensagem] = useState<{ tipo: 'ok' | 'erro'; texto: string } | null>(null);
  const [trocar, setTrocar] = useState(false);

  const carregar = async () => {
    try {
      const r = await api<{ certificados: Record<string, InfoCert> }>('/certificados');
      setInfo(r.certificados[empresa]);
    } catch (e: any) {
      setMensagem({ tipo: 'erro', texto: e.message });
    }
  };

  useEffect(() => {
    setTrocar(false);
    setMensagem(null);
    carregar();
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [empresa]);

  const enviar = async () => {
    if (!arquivo || !senha) return;
    setEnviando(true);
    setMensagem(null);
    try {
      const form = new FormData();
      form.append('empresa', empresa);
      form.append('senha', senha);
      form.append('arquivo', arquivo);
      const r = await api<{ certificado: InfoCert }>('/certificados', { form });
      setInfo(r.certificado);
      setArquivo(null);
      setSenha('');
      setTrocar(false);
      setMensagem({ tipo: 'ok', texto: 'Certificado conferido e salvo. Agora a nota é buscada na SEFAZ só com a chave.' });
    } catch (e: any) {
      setMensagem({ tipo: 'erro', texto: e.message });
    } finally {
      setEnviando(false);
    }
  };

  const vencendo = info?.configurado && (info.dias_restantes ?? 999) <= 30;

  return (
    <div style={{ ...card, display: 'flex', flexDirection: 'column', gap: '10px' }}>
      <div style={{ display: 'flex', justifyContent: 'space-between', alignItems: 'center', gap: '8px', flexWrap: 'wrap' }}>
        <strong style={{ color: 'var(--text-main)', display: 'flex', gap: '6px', alignItems: 'center' }}>
          <ShieldCheck size={16} /> Certificado digital A1 — {NOME_LOJA[empresa]}
        </strong>
        {info && (info.configurado
          ? <Chip cor={vencendo ? '#f59e0b' : '#22c55e'}>{vencendo ? `vence em ${info.dias_restantes} dias` : 'configurado'}</Chip>
          : <Chip cor="#ef4444">não configurado</Chip>)}
      </div>

      {info?.configurado && (
        <div style={{ fontSize: '13px', color: 'var(--text-muted)' }}>
          {info.titular} · CNPJ {info.cnpj} · válido até <strong style={{ color: 'var(--text-main)' }}>{dataBR(info.validade)}</strong>
        </div>
      )}
      {info?.erro && <Aviso tipo="erro">{info.erro}</Aviso>}
      {vencendo && (
        <div style={{ fontSize: '12px', color: '#f59e0b', display: 'flex', gap: '4px', alignItems: 'center' }}>
          <AlertTriangle size={12} /> Renove o certificado antes do vencimento, senão a busca pela chave para de funcionar.
        </div>
      )}
      {mensagem && <Aviso tipo={mensagem.tipo} onFechar={() => setMensagem(null)}>{mensagem.texto}</Aviso>}

      {!info?.configurado || trocar ? (
        isAdmin ? (
          <>
            <div style={{ fontSize: '12px', color: 'var(--text-muted)' }}>
              É com ele que o sistema busca a nota na SEFAZ só digitando a chave. Envie o arquivo <strong>.pfx</strong> da loja
              e a senha. O sistema confere se a senha abre o arquivo, se é o CNPJ desta loja e se está na validade.
              A senha fica guardada criptografada e não aparece mais em lugar nenhum.
            </div>
            <div style={{ display: 'flex', gap: '10px', alignItems: 'flex-end', flexWrap: 'wrap' }}>
              <Campo rotulo="Arquivo do certificado (.pfx)" style={{ flex: '1 1 260px' }}>
                <input type="file" accept=".pfx,.p12" style={input} onChange={(e) => setArquivo(e.target.files?.[0] || null)} />
              </Campo>
              <Campo rotulo="Senha do certificado" style={{ flex: '1 1 200px' }}>
                <input type="password" autoComplete="new-password" style={input} value={senha} onChange={(e) => setSenha(e.target.value)}
                  onKeyDown={(e) => e.key === 'Enter' && enviar()} />
              </Campo>
              <Botao icone={<Upload size={14} />} onClick={enviar} disabled={!arquivo || !senha || enviando}>
                {enviando ? 'Conferindo...' : 'Enviar certificado'}
              </Botao>
              {trocar && <Botao variante="fantasma" onClick={() => setTrocar(false)}>Cancelar</Botao>}
            </div>
          </>
        ) : (
          <div style={{ fontSize: '12px', color: 'var(--text-muted)' }}>Peça a um administrador para enviar o certificado desta loja.</div>
        )
      ) : (
        isAdmin && <div><Botao variante="secundario" onClick={() => setTrocar(true)}>Trocar certificado</Botao></div>
      )}
    </div>
  );
};
