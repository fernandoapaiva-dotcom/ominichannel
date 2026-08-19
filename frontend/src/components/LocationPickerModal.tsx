import React, { useState, useEffect } from 'react';
import { X, MapPin, Navigation, Send, Search, Loader2, Globe } from 'lucide-react';
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
  const [searchingGlobal, setSearchingGlobal] = useState(false);
  const [globalResults, setGlobalResults] = useState<any[]>([]);

  const defaultPlaces = [
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

  const [selectedPlace, setSelectedPlace] = useState(defaultPlaces[0]);

  // Worldwide Places Search Engine (OpenStreetMap Nominatim Global Geocoding)
  useEffect(() => {
    if (!search.trim() || search.trim().length < 2) {
      setGlobalResults([]);
      setSearchingGlobal(false);
      return;
    }

    const timer = setTimeout(async () => {
      try {
        setSearchingGlobal(true);
        const url = `https://nominatim.openstreetmap.org/search?q=${encodeURIComponent(search)}&format=json&addressdetails=1&limit=15`;
        const res = await fetch(url, {
          headers: { 'User-Agent': 'OminiChannel/1.0' }
        });
        const data = await res.json();
        const mapped = (data || []).map((item: any) => ({
          id: `osm_${item.place_id}`,
          name: item.display_name.split(',')[0] || item.display_name,
          address: item.display_name,
          lat: parseFloat(item.lat),
          lng: parseFloat(item.lon),
          badge: item.type ? item.type.toUpperCase() : 'LOCAL GLOBAL'
        }));
        setGlobalResults(mapped);

        // If results found, auto-select first search result for map preview
        if (mapped.length > 0) {
          setSelectedPlace(mapped[0]);
        }
      } catch (err) {
        console.error('Error searching global places:', err);
      } finally {
        setSearchingGlobal(false);
      }
    }, 450);

    return () => clearTimeout(timer);
  }, [search]);

  if (!isOpen) return null;

  const displayPlaces = search.trim().length >= 2 ? globalResults : defaultPlaces;

  const handleSendLocation = async (place: any) => {
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
        maxWidth: '500px',
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
              <Globe size={20} />
            </div>
            <div>
              <h3 style={{ margin: 0, fontSize: '16px', fontWeight: '700', color: '#fff' }}>Enviar localização</h3>
              <span style={{ fontSize: '11px', color: 'var(--text-muted)' }}>Busca Global de Lugares (Estilo WhatsApp Mundial)</span>
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
            title="Mapa Mundial OpenStreetMap"
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
              maxWidth: '300px',
              whiteSpace: 'nowrap',
              overflow: 'hidden',
              textOverflow: 'ellipsis'
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
            setSelectedPlace(defaultPlaces[0]);
            handleSendLocation(defaultPlaces[0]);
          }}
          style={{
            padding: '12px 20px',
            backgroundColor: 'rgba(0, 230, 153, 0.08)',
            borderBottom: '1px solid var(--border-color)',
            display: 'flex',
            alignItems: 'center',
            gap: '14px',
            cursor: 'pointer'
          }}
        >
          <div style={{
            width: '38px',
            height: '38px',
            borderRadius: '50%',
            backgroundColor: 'var(--accent-primary)',
            color: '#000',
            display: 'flex',
            alignItems: 'center',
            justifyContent: 'center',
            flexShrink: 0
          }}>
            <Navigation size={18} />
          </div>
          <div style={{ flex: 1 }}>
            <div style={{ fontSize: '13px', fontWeight: '700', color: 'var(--accent-primary)' }}>
              Localização atual da loja Servweld
            </div>
            <div style={{ fontSize: '11px', color: 'var(--text-muted)' }}>
              SOF Sul Quadra 5 • Guará, Brasília - DF
            </div>
          </div>
          <button
            className="btn-primary"
            disabled={loading}
            style={{ padding: '6px 12px', fontSize: '12px', whiteSpace: 'nowrap' }}
          >
            {loading ? <Loader2 size={14} className="animate-spin" /> : <Send size={14} />}
            {loading ? 'Enviando...' : 'Enviar'}
          </button>
        </div>

        {/* Search Bar Worldwide */}
        <div style={{ padding: '12px 20px', borderBottom: '1px solid var(--border-color)' }}>
          <div style={{ position: 'relative' }}>
            <Search size={16} style={{ position: 'absolute', left: '12px', top: '10px', color: 'var(--text-muted)' }} />
            <input
              type="text"
              placeholder="Digite ferramentaria, rua, bairro, loja ou cidade..."
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
            {searchingGlobal && (
              <Loader2 size={16} className="animate-spin" style={{ position: 'absolute', right: '12px', top: '10px', color: 'var(--accent-primary)' }} />
            )}
          </div>
        </div>

        {/* Locais List (Mundial / Global) */}
        <div style={{ padding: '12px 20px', maxHeight: '220px', overflowY: 'auto', display: 'flex', flexDirection: 'column', gap: '8px' }}>
          <div style={{ fontSize: '11px', fontWeight: '700', color: 'var(--text-muted)', textTransform: 'uppercase', marginBottom: '4px', display: 'flex', justifyContent: 'space-between' }}>
            <span>
              {search.trim().length >= 2 ? `Resultados Globais (${displayPlaces.length})` : `Locais Sugeridos (${displayPlaces.length})`}
            </span>
            {searchingGlobal && <span style={{ color: 'var(--accent-primary)' }}>Buscando no mundo...</span>}
          </div>

          {searchingGlobal && displayPlaces.length === 0 ? (
            <div style={{ padding: '20px', textAlign: 'center', color: 'var(--text-muted)', fontSize: '13px' }}>
              <Loader2 size={20} className="animate-spin" style={{ margin: '0 auto 8px', color: 'var(--accent-primary)' }} />
              Buscando estabelecimentos em todo o mundo...
            </div>
          ) : displayPlaces.length === 0 ? (
            <div style={{ padding: '20px', textAlign: 'center', color: 'var(--text-muted)', fontSize: '13px' }}>
              Nenhum local encontrado para "{search}". Tente buscar por outro termo, cidade ou endereço.
            </div>
          ) : (
            displayPlaces.map(place => {
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
            })
          )}
        </div>
      </div>
    </div>
  );
};
