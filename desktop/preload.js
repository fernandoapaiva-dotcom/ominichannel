const { contextBridge, ipcRenderer } = require('electron');

contextBridge.exposeInMainWorld('electronAPI', {
  isDesktop: true,
  updateBadge: (count) => ipcRenderer.send('update-badge', count),
  sendNotification: (title, body) => ipcRenderer.send('desktop-notification', { title, body }),
  flashFrame: () => ipcRenderer.send('flash-frame')
});
