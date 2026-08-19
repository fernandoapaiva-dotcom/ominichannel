import React, { useState } from 'react';
import { X, MapPin, Navigation, Send, Search, Loader2 } from 'lucide-react';
import { apiFetch } from '../services/api';

interface LocationPickerModalProps {
  isOpen: boolean;
  onClose: () => void;
  conversationId: number | null;
  onLocationSent?: () => void;
}

export const LocationPickerModal: React.FC<LocationPickerModalProps> = ({
  isOpen,
  onClose,
  conversationId,
  onLocationSent
}) => {
  const [loading, setLoading] = useState(false);
  const [search, setSearch] = useState('');

  const places = [
    {
      id: 'servweld_main',
      name: 'Servsolda Comercial / Servweld',
      address: 'SOF Sul Quadra 05 Conjunto A Lote 05 Loja 02 - Guará, Brasília - DF, 71215-226',
      lat: -15.820418,
      lng: -47.956467,
      badge: 'Principal (Localização Oficial)'
    },
    {
      id: 'servweld_tech',
      name: 'Servweld Assistência Técnica e Locação',
      address: 'SOF Sul Quadra 05 Lote 05 Loja 02 - Guará, Brasília - DF, 71215-226',
      lat: -15.820418,
      lng: -47.956467,
      badge: 'Galpão Técnico'
    },
    {
      id: 'dom_bosco',
      name: 'Oficina Dom Bosco',
      address: 'SOF Q 5, Guará, 71215-220, DF, BR',
      lat: -15.821000,
      lng: -47.957000,
      badge: 'Ponto Próximo'
    },
    {
      id: 'decathlon',
      name: 'Decathlon Brasília EPIA Sul',
      address: 'SGV Lt 7/8 - Guará, Brasília - DF',
      lat: -15.818500,
      lng: -47.954000,
      badge: 'Ponto Próximo'
    },
    {
      id: 'casapark',
      name: 'Casa Park Shopping',
      address: 'SGCV Lote 22 - Guará, Brasília - DF',
      lat: -15.823000,
      lng: -47.953000,
      badge: 'Ponto Próximo'
    }
  ];

  const [selectedPlace, setSelectedPlace] = useState(places[0]);

  const filteredPlaces = places.filter(p => {
    if (!search.trim()) return true;
    const q = search.toLowerCase();
    return p.name.toLowerCase().includes(q) || p.address.toLowerCase().includes(q);
  });

  if (!isOpen) return null;

  const handleSendLocation = async (place: typeof places[0]) => {
    if (!conversationId) return;

    try {
      setLoading(true);
      await apiFetch(`/conversations/${conversationId}/send-location`, {
        method: 'POST',
        body: JSON.stringify({
          name: place.name,
          address: place.address,
          latitude: place.lat,
          longitude: place.lng
        })
      });
      if (onLocationSent) onLocationSent();
      onClose();
    } catch (err: any) {
      alert(err.message || 'Erro ao enviar localização.');
    } finally {
      setLoading(false);
    }
  };

  const mapBbox = `${selectedPlace.lng - 0.004},${selectedPlace.lat - 0.0025},${selectedPlace.lng + 0.004},${selectedPlace.lat + 0.0025}`;
  const mapIframeUrl = `https://www.openstreetmap.org/export/embed.html?bbox=${mapBbox}&layer=mapnik`;

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
        {/* Header Estilo WhatsApp */}
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
              backgroundColor: 'rgba(0, 230, 153, 0.15)',
              color: 'var(--accent-primary)',
              display: 'flex',
              alignItems: 'center',
              justifyContent: 'center'
            }}>
              <MapPin size={20} />
            </div>
            <div>
              <h3 style={{ margin: 0, fontSize: '16px', fontWeight: '700', color: '#fff' }}>Enviar localização</h3>
              <span style={{ fontSize: '11px', color: 'var(--text-muted)' }}>Card de mapa nativo interativo do WhatsApp</span>
            </div>
          </div>
          <button onClick={onClose} style={{ background: 'none', border: 'none', color: 'var(--text-muted)', cursor: 'pointer' }}>
            <X size={20} />
          </button>
        </div>

        {/* Mapa Preview Real OpenStreetMap */}
        <div style={{
          height: '180px',
          backgroundColor: '#0f172a',
          position: 'relative',
          overflow: 'hidden',
          borderBottom: '1px solid var(--border-color)'
        }}>
          <iframe
            title="Mapa Servweld"
            src={mapIframeUrl}
            style={{
              width: '100%',
              height: '100%',
              border: 0,
              filter: 'brightness(0.9) contrast(1.1)',
              pointerEvents: 'none'
            }}
          />

          {/* Red Pin Overlay */}
          <div style={{
            position: 'absolute',
            top: '50%',
            left: '50%',
            transform: 'translate(-50%, -100%)',
            display: 'flex',
            flexDirection: 'column',
            alignItems: 'center',
            gap: '4px',
            pointerEvents: 'none',
            zIndex: 10
          }}>
            <div style={{
              backgroundColor: '#ef4444',
              color: '#fff',
              padding: '8px',
              borderRadius: '50%',
              boxShadow: '0 0 24px rgba(239, 68, 68, 0.9)',
              border: '2px solid #fff'
            }}>
              <MapPin size={22} />
            </div>
            <span style={{
              fontSize: '11px',
              fontWeight: '700',
              backgroundColor: '#0f172a',
              padding: '4px 10px',
              borderRadius: '6px',
              border: '1px solid #3b82f6',
              color: '#fff',
              boxShadow: '0 4px 14px rgba(0,0,0,0.7)',
              whiteSpace: 'nowrap'
            }}>
              📍 {selectedPlace.name}
            </span>
          </div>

          <div style={{
            position: 'absolute',
            bottom: '8px',
            right: '8px',
            fontSize: '10px',
            fontWeight: '600',
            color: '#fff',
            backgroundColor: 'rgba(15, 23, 42, 0.85)',
            padding: '3px 8px',
            borderRadius: '4px',
            border: '1px solid rgba(255,255,255,0.1)',
            zIndex: 10
          }}>
            GPS: ({selectedPlace.lat.toFixed(6)}, {selectedPlace.lng.toFixed(6)})
          </div>
        </div>

        {/* Action Button: Localização Atual da Loja */}
        <div
          onClick={() => {
            setSelectedPlace(places[0]);
            handleSendLocation(places[0]);
          }}
          style={{
            padding: '14px 20px',
            backgroundColor: 'rgba(0, 230, 153, 0.08)',
            borderBottom: '1px solid var(--border-color)',
            display: 'flex',
            alignItems: 'center',
            gap: '14px',
            cursor: 'pointer',
            transition: 'background-color 0.2s'
          }}
          className="hover:bg-emerald-950/20"
        >
          <div style={{
            width: '40px',
            height: '40px',
            borderRadius: '50%',
            backgroundColor: 'var(--accent-primary)',
            color: '#000',
            display: 'flex',
            alignItems: 'center',
            justifyContent: 'center',
            flexShrink: 0
          }}>
            <Navigation size={20} />
          </div>
          <div style={{ flex: 1 }}>
            <div style={{ fontSize: '14px', fontWeight: '700', color: 'var(--accent-primary)' }}>
              Localização atual da loja
            </div>
            <div style={{ fontSize: '12px', color: 'var(--text-muted)' }}>
              Precisão GPS de 10 metros • SOF Sul Quadra 5
            </div>
          </div>
          <button
            className="btn-primary"
            disabled={loading}
            style={{ padding: '6px 12px', fontSize: '12px', whiteSpace: 'nowrap' }}
          >
            {loading ? <Loader2 size={14} className="animate-spin" /> : <Send size={14} />}
            {loading ? 'Enviando...' : 'Enviar Agora'}
          </button>
        </div>

        {/* Search Bar */}
        <div style={{ padding: '12px 20px', borderBottom: '1px solid var(--border-color)' }}>
          <div style={{ position: 'relative' }}>
            <Search size={16} style={{ position: 'absolute', left: '12px', top: '10px', color: 'var(--text-muted)' }} />
            <input
              type="text"
              placeholder="Buscar estabelecimentos próximos..."
              value={search}
              onChange={(e) => setSearch(e.target.value)}
              style={{
                width: '100%',
                padding: '8px 12px 8px 36px',
                backgroundColor: 'var(--bg-secondary)',
                border: '1px solid var(--border-color)',
                borderRadius: 'var(--radius-md)',
                color: 'var(--text-main)',
                fontSize: '13px'
              }}
            />
          </div>
        </div>

        {/* Locais Próximos List */}
        <div style={{ padding: '12px 20px', maxHeight: '200px', overflowY: 'auto', display: 'flex', flexDirection: 'column', gap: '8px' }}>
          <div style={{ fontSize: '11px', fontWeight: '700', color: 'var(--text-muted)', textTransform: 'uppercase', marginBottom: '4px' }}>
            Locais Próximos ({filteredPlaces.length})
          </div>

          {filteredPlaces.map(place => {
            const isSelected = selectedPlace.id === place.id;
            return (
              <div
                key={place.id}
                onClick={() => setSelectedPlace(place)}
                style={{
                  padding: '10px 12px',
                  backgroundColor: isSelected ? '#1e293b' : 'transparent',
                  border: isSelected ? '1px solid var(--accent-primary)' : '1px solid transparent',
                  borderRadius: 'var(--radius-md)',
                  display: 'flex',
                  alignItems: 'center',
                  justifyContent: 'space-between',
                  cursor: 'pointer',
                  gap: '12px'
                }}
              >
                <div style={{ display: 'flex', alignItems: 'center', gap: '10px', flex: 1, overflow: 'hidden' }}>
                  <div style={{
                    width: '32px',
                    height: '32px',
                    borderRadius: '50%',
                    backgroundColor: 'rgba(255, 255, 255, 0.05)',
                    color: isSelected ? 'var(--accent-primary)' : 'var(--text-muted)',
                    display: 'flex',
                    alignItems: 'center',
                    justifyContent: 'center',
                    flexShrink: 0
                  }}>
                    <MapPin size={16} />
                  </div>
                  <div style={{ overflow: 'hidden' }}>
                    <div style={{ fontSize: '13px', fontWeight: '600', color: 'var(--text-main)', whiteSpace: 'nowrap', overflow: 'hidden', textOverflow: 'ellipsis' }}>
                      {place.name}
                    </div>
                    <div style={{ fontSize: '11px', color: 'var(--text-muted)', whiteSpace: 'nowrap', overflow: 'hidden', textOverflow: 'ellipsis' }}>
                      {place.address}
                    </div>
                  </div>
                </div>

                <button
                  type="button"
                  onClick={(e) => {
                    e.stopPropagation();
                    setSelectedPlace(place);
                    handleSendLocation(place);
                  }}
                  style={{
                    backgroundColor: 'transparent',
                    border: 'none',
                    color: 'var(--accent-primary)',
                    fontSize: '12px',
                    fontWeight: '600',
                    cursor: 'pointer',
                    display: 'flex',
                    alignItems: 'center',
                    gap: '4px',
                    whiteSpace: 'nowrap'
                  }}
                >
                  Enviar <Send size={12} />
                </button>
              </div>
            );
          })}
        </div>
      </div>
    </div>
  );
};
