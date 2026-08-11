import React, { useState, useEffect } from 'react';
import { StyleSheet, Text, View, TextInput, TouchableOpacity, FlatList, SafeAreaView, StatusBar, ActivityIndicator } from 'react-native';

export default function App() {
  const [token, setToken] = useState<string | null>(null);
  const [username, setUsername] = useState('');
  const [password, setPassword] = useState('');
  const [loading, setLoading] = useState(false);
  const [conversations, setConversations] = useState<any[]>([]);

  const handleLogin = async () => {
    if (!username || !password) return;
    setLoading(true);
    try {
      const formData = new URLSearchParams();
      formData.append('username', username);
      formData.append('password', password);

      const res = await fetch('http://10.0.2.2:8000/api/v1/auth/login', {
        method: 'POST',
        headers: { 'Content-Type': 'application/x-www-form-urlencoded' },
        body: formData.toString()
      });

      if (!res.ok) {
        alert('Credenciais inválidas');
        return;
      }
      const data = await res.json();
      setToken(data.access_token);
      loadConversations(data.access_token);
    } catch (err) {
      alert('Erro de conexão com o servidor backend');
    } finally {
      setLoading(false);
    }
  };

  const loadConversations = async (jwtToken: string) => {
    try {
      const res = await fetch('http://10.0.2.2:8000/api/v1/conversations/', {
        headers: { Authorization: `Bearer ${jwtToken}` }
      });
      const data = await res.json();
      setConversations(data);
    } catch (err) {
      console.error(err);
    }
  };

  if (!token) {
    return (
      <SafeAreaView style={styles.container}>
        <StatusBar barStyle="light-content" />
        <View style={styles.loginCard}>
          <Text style={styles.title}>OminiChannel Mobile</Text>
          <Text style={styles.subtitle}>Atendimento WhatsApp para Android</Text>

          <TextInput
            style={styles.input}
            placeholder="Login"
            placeholderTextColor="#8a99ad"
            value={username}
            onChangeText={setUsername}
            autoCapitalize="none"
          />

          <TextInput
            style={styles.input}
            placeholder="Senha"
            placeholderTextColor="#8a99ad"
            secureTextEntry
            value={password}
            onChangeText={setPassword}
          />

          <TouchableOpacity style={styles.button} onPress={handleLogin} disabled={loading}>
            {loading ? <ActivityIndicator color="#051a12" /> : <Text style={styles.buttonText}>ENTRAR</Text>}
          </TouchableOpacity>
        </View>
      </SafeAreaView>
    );
  }

  return (
    <SafeAreaView style={styles.container}>
      <StatusBar barStyle="light-content" />
      <View style={styles.header}>
        <Text style={styles.headerTitle}>Minhas Conversas</Text>
        <TouchableOpacity onPress={() => setToken(null)}>
          <Text style={{ color: '#ef4444', fontWeight: 'bold' }}>Sair</Text>
        </TouchableOpacity>
      </View>

      <FlatList
        data={conversations}
        keyExtractor={(item) => item.id.toString()}
        renderItem={({ item }) => (
          <View style={styles.chatItem}>
            <View style={{ flexDirection: 'row', justifyContent: 'space-between' }}>
              <Text style={styles.chatTitle}>{item.contact?.nome || item.contact?.telefone}</Text>
              <Text style={styles.chatStatus}>{item.status}</Text>
            </View>
            <Text style={styles.chatDept}>{item.whatsapp_number?.nome_departamento}</Text>
          </View>
        )}
      />
    </SafeAreaView>
  );
}

const styles = StyleSheet.create({
  container: {
    flex: 1,
    backgroundColor: '#0b0f19',
  },
  loginCard: {
    flex: 1,
    justifyContent: 'center',
    padding: 24,
  },
  title: {
    fontSize: 24,
    fontWeight: 'bold',
    color: '#00e699',
    textAlign: 'center',
    marginBottom: 6,
  },
  subtitle: {
    fontSize: 14,
    color: '#8a99ad',
    textAlign: 'center',
    marginBottom: 32,
  },
  input: {
    backgroundColor: '#131b2e',
    borderWidth: 1,
    borderColor: 'rgba(255, 255, 255, 0.1)',
    borderRadius: 10,
    padding: 14,
    color: '#f0f4f8',
    marginBottom: 16,
    fontSize: 16,
  },
  button: {
    backgroundColor: '#00e699',
    padding: 16,
    borderRadius: 10,
    alignItems: 'center',
    marginTop: 8,
  },
  buttonText: {
    color: '#051a12',
    fontWeight: 'bold',
    fontSize: 16,
  },
  header: {
    padding: 20,
    borderBottomWidth: 1,
    borderBottomColor: 'rgba(255, 255, 255, 0.1)',
    flexDirection: 'row',
    justifyContent: 'space-between',
    alignItems: 'center',
  },
  headerTitle: {
    fontSize: 20,
    fontWeight: 'bold',
    color: '#f0f4f8',
  },
  chatItem: {
    padding: 16,
    borderBottomWidth: 1,
    borderBottomColor: 'rgba(255, 255, 255, 0.05)',
  },
  chatTitle: {
    fontSize: 16,
    fontWeight: '600',
    color: '#f0f4f8',
  },
  chatStatus: {
    fontSize: 12,
    color: '#00e699',
    fontWeight: 'bold',
  },
  chatDept: {
    fontSize: 12,
    color: '#8a99ad',
    marginTop: 4,
  },
});
