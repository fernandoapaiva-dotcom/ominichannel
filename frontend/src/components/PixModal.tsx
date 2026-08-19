import React, { useState, useEffect } from 'react';
import { X, QrCode, Copy, Check, Send, ShieldCheck, DollarSign, Loader2 } from 'lucide-react';
import { apiFetch } from '../services/api';

interface PixModalProps {
  isOpen: boolean;
  onClose: () => void;
  conversationId: number | null;
  onPixSent?: () => void;
}

// Official Central Bank of Brazil (BACEN) EMV Co BR Code Generator
function generateBacenPixPayload(key: string, merchantName: string, merchantCity: string, amount?: number): string {
  const cleanKey = key.replace(/\D/g, '').length > 0 && !key.includes('@') ? key.replace(/\D/g, '') : key;
  const field26 = `0014br.gov.bcb.pix01${cleanKey.length.toString().padStart(2, '0')}${cleanKey}`;
  
  // BACEN standard formatting (no accents, uppercase)
  const nameClean = merchantName.normalize('NFD').replace(/[\u0300-\u036f]/g, '').toUpperCase().slice(0, 25);
  const cityClean = merchantCity.normalize('NFD').replace(/[\u0300-\u036f]/g, '').toUpperCase().slice(0, 15);

  const amountStr = amount && amount > 0 ? amount.toFixed(2) : '';
  const field54 = amountStr ? `54${amountStr.length.toString().padStart(2, '0')}${amountStr}` : '';

  const payloadNoCrc = 
    '000201' +
    `26${field26.length.toString().padStart(2, '0')}${field26}` +
    '52040000' +
    '5303986' +
    field54 +
    '5802BR' +
    `59${nameClean.length.toString().padStart(2, '0')}${nameClean}` +
    `60${cityClean.length.toString().padStart(2, '0')}${cityClean}` +
    '62070503***' +
    '6304';

  // CRC16-CCITT (0xFFFF)
  let crc = 0xFFFF;
  for (let i = 0; i < payloadNoCrc.length; i++) {
    crc ^= payloadNoCrc.charCodeAt(i) << 8;
    for (let j = 0; j < 8; j++) {
      if ((crc & 0x8000) !== 0) {
        crc = ((crc << 1) ^ 0x1021) & 0xFFFF;
      } else {
        crc = (crc << 1) & 0xFFFF;
      }
    }
  }
  const crcHex = (crc & 0xFFFF).toString(16).toUpperCase().padStart(4, '0');
  return payloadNoCrc + crcHex;
}

export const PixModal: React.FC<PixModalProps> = ({
  isOpen,
  onClose,
  conversationId,
  onPixSent
}) => {
  const [copiedKey, setCopiedKey] = useState(false);
  const [copiedPayload, setCopiedPayload] = useState(false);
  const [pixKeys, setPixKeys] = useState<any[]>([]);
  const [selectedKeyId, setSelectedKeyId] = useState<number | null>(null);
  const [amountInput, setAmountInput] = useState<string>('');
  const [sending, setSending] = useState(false);

  const defaultKey = {
    id: 0,
    titulo: "Pix Principal Servweld - CNPJ",
    tipo_chave: "CNPJ",
    chave: "54804458000122",
    favorecido: "Servweld / Servsolda Equipamentos e Serviços Ltda",
    cidade: "BRASILIA"
  };

  useEffect(() => {
    if (isOpen) {
      apiFetch('/pix-keys/')
        .then(data => {
          const activeKeys = (data || []).filter((k: any) => k.ativo !== false);
          setPixKeys(activeKeys);
          if (activeKeys.length > 0) {
            setSelectedKeyId(activeKeys[0].id);
          }
        })
        .catch(err => console.error('Error fetching tenant pix keys:', err));
    }
  }, [isOpen]);

  if (!isOpen) return null;

  const currentKey = pixKeys.find(k => k.id === selectedKeyId) || {
    titulo: defaultKey.titulo,
    tipo_chave: defaultKey.tipo_chave,
    chave: defaultKey.chave,
    favorecido: defaultKey.favorecido,
    cidade: defaultKey.cidade
  };

  const rawKey = currentKey.chave;
  const fullName = currentKey.favorecido;
  const merchantName = fullName.slice(0, 20).toUpperCase();
  const city = currentKey.cidade || "BRASILIA";
  const numAmount = parseFloat(amountInput.replace(',', '.')) || 0;

  // Official BACEN EMV Co Pix Copia e Cola Payload with optional amount
  const bacenPixPayload = generateBacenPixPayload(rawKey, merchantName, city, numAmount > 0 ? numAmount : undefined);

  // Generate QR Code from the official BACEN EMV Co string
  const qrCodeUrl = `https://api.qrserver.com/v1/create-qr-code/?size=300x300&data=${encodeURIComponent(bacenPixPayload)}`;

  const handleCopyKey = () => {
    navigator.clipboard.writeText(rawKey);
    setCopiedKey(true);
    setTimeout(() => setCopiedKey(false), 3000);
  };

  const handleCopyPayload = () => {
    navigator.clipboard.writeText(bacenPixPayload);
    setCopiedPayload(true);
    setTimeout(() => setCopiedPayload(false), 3000);
  };

  const handleSendToChat = async () => {
    if (!conversationId) {
      alert('Selecione uma conversa ativa para enviar o Pix.');
      return;
    }

    try {
      setSending(true);
      await apiFetch(`/conversations/${conversationId}/send-pix`, {
        method: 'POST',
        body: JSON.stringify({
          title: currentKey.titulo,
          key_type: currentKey.tipo_chave,
          key: rawKey,
          favorecido: fullName,
          cidade: city,
          amount: numAmount > 0 ? numAmount : null
        })
      });

      if (onPixSent) onPixSent();
      onClose();
    } catch (err: any) {
      alert('Erro ao enviar imagem do Pix no WhatsApp: ' + err.message);
    } finally {
      setSending(false);
    }
  };

  return (
    <div style={{
      position: 'fixed',
      inset: 0,
      backgroundColor: 'rgba(0, 0, 0, 0.8)',
      backdropFilter: 'blur(6px)',
      display: 'flex',
      alignItems: 'center',
      justifyContent: 'center',
      zIndex: 2000,
      padding: '16px'
    }}>
      <div className="glass-panel animate-fade-in" style={{
        width: '100%',
        maxWidth: '480px',
        borderRadius: 'var(--radius-lg)',
        backgroundColor: '#0b0f19',
        border: '1px solid var(--border-color)',
        overflow: 'hidden',
        boxShadow: '0 24px 48px rgba(0,0,0,0.6)'
      }}>
        {/* Header Estilo Pix */}
        <div style={{
          padding: '16px 20px',
          backgroundColor: '#111827',
          borderBottom: '1px solid var(--border-color)',
          display: 'flex',
          justify: 'space-between',
          alignItems: 'center'
        }}>
          <div style={{ display: 'flex', alignItems: 'center', gap: '10px' }}>
            <div style={{
              width: '36px',
              height: '36px',
              borderRadius: '50%',
              backgroundColor: 'rgba(234, 179, 8, 0.15)',
              color: '#eab308',
              display: 'flex',
              alignItems: 'center',
              justifyContent: 'center'
            }}>
              <QrCode size={20} />
            </div>
            <div>
              <h3 style={{ margin: 0, fontSize: '16px', fontWeight: '700', color: '#fff' }}>Pagamento via Pix</h3>
              <span style={{ fontSize: '11px', color: 'var(--text-muted)' }}>Gerador de Cobrança com Valor e QR Code</span>
            </div>
          </div>
          <button onClick={onClose} style={{ background: 'none', border: 'none', color: 'var(--text-muted)', cursor: 'pointer' }}>
            <X size={20} />
          </button>
        </div>

        {/* 1. Selector Dropdown if tenant has Pix keys */}
        <div style={{ padding: '14px 20px', backgroundColor: '#111827', borderBottom: '1px solid var(--border-color)', display: 'flex', flexDirection: 'column', gap: '10px' }}>
          <div>
            <label style={{ fontSize: '11px', color: 'var(--text-muted)', marginBottom: '4px', display: 'block', fontWeight: '700', textTransform: 'uppercase' }}>
              1. Selecione qual Chave Pix enviar
            </label>
            <select
              value={selectedKeyId || pixKeys[0]?.id || 0}
              onChange={(e) => setSelectedKeyId(Number(e.target.value))}
              style={{
                width: '100%',
                padding: '8px 12px',
                backgroundColor: '#1e293b',
                border: '1px solid var(--accent-primary)',
                borderRadius: 'var(--radius-md)',
                color: '#fff',
                fontSize: '13px',
                fontWeight: '600'
              }}
            >
              {pixKeys.length > 0 ? (
                pixKeys.map(k => (
                  <option key={k.id} value={k.id}>
                    {k.titulo} ({k.tipo_chave}: {k.chave})
                  </option>
                ))
              ) : (
                <option value={0}>{defaultKey.titulo} ({defaultKey.tipo_chave}: {defaultKey.chave})</option>
              )}
            </select>
          </div>

          {/* 2. Amount Input (Estilo Máquina de Cartão) */}
          <div>
            <label style={{ fontSize: '11px', color: 'var(--text-muted)', marginBottom: '4px', display: 'block', fontWeight: '700', textTransform: 'uppercase' }}>
              2. Digite o Valor a Pagar R$ (Igual máquina de cartão)
            </label>
            <div style={{ position: 'relative' }}>
              <DollarSign size={16} style={{ position: 'absolute', left: '12px', top: '10px', color: 'var(--accent-primary)' }} />
              <input
                type="text"
                placeholder="Ex: 150.00 (Deixe em branco para valor livre)"
                value={amountInput}
                onChange={(e) => setAmountInput(e.target.value)}
                style={{
                  width: '100%',
                  padding: '8px 12px 8px 36px',
                  backgroundColor: '#1e293b',
                  border: '1px solid var(--border-color)',
                  borderRadius: 'var(--radius-md)',
                  color: '#fff',
                  fontSize: '14px',
                  fontWeight: '700'
                }}
              />
            </div>
            {numAmount > 0 && (
              <span style={{ fontSize: '11px', color: '#34d399', fontWeight: '600', marginTop: '4px', display: 'block' }}>
                ✓ QR Code pré-fixado no valor exato de: <strong>R$ {numAmount.toFixed(2).replace('.', ',')}</strong>
              </span>
            )}
          </div>
        </div>

        {/* Content */}
        <div style={{ padding: '16px 20px', display: 'flex', flexDirection: 'column', alignItems: 'center', gap: '14px', maxHeight: '420px', overflowY: 'auto' }}>
          {/* QR Code Container com Moldura */}
          <div style={{
            padding: '14px',
            backgroundColor: '#fff',
            borderRadius: 'var(--radius-md)',
            boxShadow: '0 8px 24px rgba(0,0,0,0.4)',
            display: 'flex',
            flexDirection: 'column',
            alignItems: 'center',
            gap: '6px'
          }}>
            <img
              src={qrCodeUrl}
              alt="QR Code Pix Oficial Banco Central"
              style={{ width: '180px', height: '180px', objectFit: 'contain' }}
            />
            <span style={{ fontSize: '11px', fontWeight: '700', color: '#0f172a' }}>
              ✓ Imagem do QR Code enviada direto no WhatsApp
            </span>
          </div>

          {/* Details Card */}
          <div style={{
            width: '100%',
            padding: '12px',
            backgroundColor: '#111827',
            border: '1px solid var(--border-color)',
            borderRadius: 'var(--radius-md)',
            display: 'flex',
            flexDirection: 'column',
            gap: '8px'
          }}>
            <div>
              <div style={{ fontSize: '11px', color: 'var(--text-muted)', textTransform: 'uppercase', fontWeight: '700' }}>
                Favorecido / Razão Social
              </div>
              <div style={{ fontSize: '13px', fontWeight: '600', color: '#fff', display: 'flex', alignItems: 'center', gap: '6px', marginTop: '2px' }}>
                <ShieldCheck size={16} color="#34d399" /> {fullName}
              </div>
            </div>

            {/* Chave Pix */}
            <div>
              <div style={{ fontSize: '11px', color: 'var(--text-muted)', textTransform: 'uppercase', fontWeight: '700' }}>
                Chave Pix ({currentKey.tipo_chave})
              </div>
              <div style={{
                display: 'flex',
                alignItems: 'center',
                justifyContent: 'space-between',
                padding: '8px 12px',
                backgroundColor: '#1e293b',
                borderRadius: 'var(--radius-md)',
                marginTop: '4px'
              }}>
                <span style={{ fontFamily: 'monospace', fontSize: '13px', fontWeight: '700', color: 'var(--accent-primary)' }}>
                  {rawKey}
                </span>
                <button
                  type="button"
                  onClick={handleCopyKey}
                  style={{
                    background: 'none',
                    border: 'none',
                    color: copiedKey ? '#34d399' : 'var(--text-muted)',
                    cursor: 'pointer',
                    display: 'flex',
                    alignItems: 'center',
                    gap: '4px',
                    fontSize: '12px',
                    fontWeight: '600'
                  }}
                >
                  {copiedKey ? <Check size={14} /> : <Copy size={14} />}
                  {copiedKey ? 'Copiado!' : 'Copiar'}
                </button>
              </div>
            </div>

            {/* Pix Copia e Cola String */}
            <div>
              <div style={{ fontSize: '11px', color: 'var(--text-muted)', textTransform: 'uppercase', fontWeight: '700' }}>
                Pix Copia e Cola
              </div>
              <div style={{
                display: 'flex',
                alignItems: 'center',
                justifyContent: 'space-between',
                padding: '8px 12px',
                backgroundColor: '#1e293b',
                borderRadius: 'var(--radius-md)',
                marginTop: '4px',
                gap: '8px'
              }}>
                <span style={{
                  fontFamily: 'monospace',
                  fontSize: '11px',
                  color: '#94a3b8',
                  maxWidth: '260px',
                  overflow: 'hidden',
                  textOverflow: 'ellipsis',
                  whiteSpace: 'nowrap'
                }}>
                  {bacenPixPayload}
                </span>
                <button
                  type="button"
                  onClick={handleCopyPayload}
                  style={{
                    background: 'none',
                    border: 'none',
                    color: copiedPayload ? '#34d399' : '#eab308',
                    cursor: 'pointer',
                    display: 'flex',
                    alignItems: 'center',
                    gap: '4px',
                    fontSize: '12px',
                    fontWeight: '700',
                    whiteSpace: 'nowrap'
                  }}
                >
                  {copiedPayload ? <Check size={14} /> : <Copy size={14} />}
                  {copiedPayload ? 'Copiado!' : 'Copiar Pix'}
                </button>
              </div>
            </div>
          </div>

          {/* Action Buttons */}
          <div style={{ width: '100%', display: 'flex', gap: '12px', marginTop: '4px' }}>
            <button
              type="button"
              onClick={handleCopyPayload}
              className="btn-secondary"
              style={{ flex: 1, padding: '10px' }}
            >
              <Copy size={16} /> {copiedPayload ? 'Pix Copiado!' : 'Copiar Pix'}
            </button>

            <button
              type="button"
              onClick={handleSendToChat}
              className="btn-primary"
              disabled={sending}
              style={{ flex: 1, padding: '10px' }}
            >
              {sending ? <Loader2 size={16} className="animate-spin" /> : <Send size={16} />}
              {sending ? 'Enviando...' : 'Enviar QR Code e Dados'}
            </button>
          </div>
        </div>
      </div>
    </div>
  );
};
