/**
 * Utility to format raw message content, types, and file paths into clean, human-readable previews with icons.
 * Handles WhatsApp audio (.ogg, .mp3, ptt), images, videos, documents, locations, contacts, stickers, calls, etc.
 */

export function formatMessageContent(conteudo?: string | null, tipo?: string | null): string {
  if (!conteudo || !conteudo.trim()) {
    if (tipo) {
      const t = tipo.toLowerCase();
      if (t === 'audio' || t === 'voice' || t === 'ptt') return '🎵 Áudio';
      if (t === 'imagem' || t === 'image' || t === 'foto') return '📷 Foto';
      if (t === 'video') return '🎥 Vídeo';
      if (t === 'documento' || t === 'document' || t === 'arquivo' || t === 'file') return '📄 Documento';
      if (t === 'sticker' || t === 'figurinha') return '🎭 Figurinha';
      if (t === 'localizacao' || t === 'location') return '📍 Localização';
      if (t === 'contato' || t === 'contact') return '👤 Contato';
    }
    return 'Conversa iniciada';
  }

  const c = String(conteudo).trim();
  const t = String(tipo || '').toLowerCase();

  // 1. WhatsApp Calls & System Events
  if (c.startsWith('[CHAMADA_VIDEO_ATENDIDA]') || c.includes('Ligação de vídeo atendida')) {
    return '📹 Ligação de vídeo atendida';
  }
  if (c.startsWith('[CHAMADA_VOZ_ATENDIDA]') || c.includes('Ligação de voz atendida')) {
    return '📞 Ligação de voz atendida';
  }
  if (c.startsWith('[CHAMADA_VIDEO_PERDIDA]') || c.includes('Ligação de vídeo perdida') || (c.includes('CHAMADA') && c.includes('VÍDEO'))) {
    return '📹 Ligação de vídeo perdida';
  }
  if (c.startsWith('[CHAMADA_VOZ_PERDIDA]') || c.includes('Ligação de voz perdida') || c.includes('O CLIENTE ESTÁ LIGANDO') || (c.includes('CHAMADA') && c.includes('VOZ'))) {
    return '📞 Ligação de voz perdida';
  }
  if (c.startsWith('[CHAMADA_VIDEO]') || c.includes('Ligação de vídeo')) {
    return '📹 Ligação de vídeo';
  }
  if (c.startsWith('[CHAMADA_VOZ]') || c.includes('Ligação de voz')) {
    return '📞 Ligação de voz';
  }

  // 2. Contacts
  if (c.startsWith('[CONTATO]|') || c.includes('BEGIN:VCARD') || t === 'contact' || t === 'contato') {
    const parts = c.split('|');
    if (parts.length > 1 && parts[1].trim()) {
      return '👤 Contato: ' + parts[1].trim();
    }
    return '👤 Contato';
  }
  if (c.startsWith('[CONTATOS_MULTIPLOS]|')) {
    return '👥 Contatos';
  }

  // 3. Locations
  if (t === 'localizacao' || t === 'location' || c.startsWith('📍') || c.includes('LOCALIZAÇÃO') || c.includes('maps.google.com') || c.includes('google.com/maps')) {
    return '📍 Localização';
  }

  // 4. Pix & Payments
  if (c.includes('[PIX_COBRANCA]') || c.includes('[QRCODE_PIX]')) {
    return '⚡ Chave Pix';
  }
  if (c.includes('Comprovante') && (c.includes('PIX') || c.includes('Pix'))) {
    return '💸 Comprovante Pix';
  }

  // 5. Stickers
  if (t === 'sticker' || t === 'figurinha') {
    return '🎭 Figurinha';
  }

  // 6. Media / Uploads / URLs / Extensions
  let cleanUrl = c;
  let caption = '';
  if (c.includes('|')) {
    const pipeParts = c.split('|');
    cleanUrl = pipeParts[0].trim();
    caption = pipeParts.slice(1).join('|').trim();
  }

  const lowerUrl = cleanUrl.toLowerCase();

  // Audio / Voice notes (.ogg, .mp3, .m4a, .opus, .wav, .aac)
  if (
    t === 'audio' ||
    t === 'voice' ||
    t === 'ptt' ||
    lowerUrl.endsWith('.ogg') ||
    lowerUrl.endsWith('.mp3') ||
    lowerUrl.endsWith('.wav') ||
    lowerUrl.endsWith('.m4a') ||
    lowerUrl.endsWith('.opus') ||
    lowerUrl.endsWith('.aac')
  ) {
    return caption ? ('🎵 Áudio: ' + caption) : '🎵 Áudio';
  }

  // Images / Photos (.jpg, .png, .jpeg, .webp, .gif)
  if (
    t === 'imagem' ||
    t === 'image' ||
    t === 'foto' ||
    lowerUrl.endsWith('.png') ||
    lowerUrl.endsWith('.jpg') ||
    lowerUrl.endsWith('.jpeg') ||
    lowerUrl.endsWith('.webp') ||
    lowerUrl.endsWith('.gif') ||
    lowerUrl.endsWith('.bmp')
  ) {
    if (caption) {
      if (caption.toLowerCase().includes('comprovante') || caption.toLowerCase().includes('pix')) {
        return '💸 Comprovante Pix: ' + caption;
      }
      return '📷 Foto: ' + caption;
    }
    return '📷 Foto';
  }

  // Videos (.mp4, .mov, .avi, .mkv, .3gp)
  if (
    t === 'video' ||
    lowerUrl.endsWith('.mp4') ||
    lowerUrl.endsWith('.mov') ||
    lowerUrl.endsWith('.avi') ||
    lowerUrl.endsWith('.mkv') ||
    lowerUrl.endsWith('.3gp')
  ) {
    return caption ? ('🎥 Vídeo: ' + caption) : '🎥 Vídeo';
  }

  // Documents / Files (.pdf, .docx, .xlsx, etc.)
  if (
    t === 'documento' ||
    t === 'document' ||
    t === 'arquivo' ||
    t === 'file' ||
    lowerUrl.endsWith('.pdf') ||
    lowerUrl.endsWith('.docx') ||
    lowerUrl.endsWith('.doc') ||
    lowerUrl.endsWith('.xlsx') ||
    lowerUrl.endsWith('.xls') ||
    lowerUrl.endsWith('.csv') ||
    lowerUrl.endsWith('.txt') ||
    lowerUrl.endsWith('.zip') ||
    lowerUrl.endsWith('.rar')
  ) {
    if (caption) {
      return '📄 ' + caption;
    }
    if (lowerUrl.endsWith('.pdf')) return '📄 Documento PDF';
    if (lowerUrl.endsWith('.xlsx') || lowerUrl.endsWith('.xls')) return '📊 Planilha Excel';
    if (lowerUrl.endsWith('.docx') || lowerUrl.endsWith('.doc')) return '📄 Documento Word';
    return '📄 Documento';
  }

  // Generic /uploads/ fallback
  if (c.startsWith('/uploads/') || lowerUrl.startsWith('http')) {
    if (caption) return '📎 ' + caption;
    const fileName = cleanUrl.split('/').pop();
    if (fileName && fileName.length < 35 && !fileName.includes('?') && fileName.includes('.')) {
      return '📎 ' + fileName;
    }
    return '📎 Arquivo Anexo';
  }

  return c;
}

export function formatMessagePreview(msg: any | undefined): string {
  if (!msg) return 'Conversa iniciada';
  return formatMessageContent(msg.conteudo, msg.tipo);
}
