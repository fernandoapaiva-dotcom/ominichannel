const { app, BrowserWindow, Tray, Menu, ipcMain, shell, Notification } = require('electron');
const path = require('path');

let mainWindow = null;
let tray = null;
let isQuitting = false;

// Guarantee single instance
const gotTheLock = app.requestSingleInstanceLock();
if (!gotTheLock) {
  app.quit();
} else {
  app.on('second-instance', () => {
    if (mainWindow) {
      if (mainWindow.isMinimized()) mainWindow.restore();
      mainWindow.show();
      mainWindow.focus();
    }
  });
}

function createWindow() {
  mainWindow = new BrowserWindow({
    width: 1280,
    height: 820,
    minWidth: 900,
    minHeight: 600,
    title: 'OminiChannel - WhatsApp & Atendimento',
    icon: path.join(__dirname, 'assets', 'icon.png'),
    autoHideMenuBar: true,
    backgroundColor: '#0f172a',
    webPreferences: {
      preload: path.join(__dirname, 'preload.js'),
      nodeIntegration: false,
      contextIsolation: true,
      spellcheck: true
    }
  });

  mainWindow.loadURL('https://ominichannel.duckdns.org');

  // When clicking 'X', minimize to tray instead of quitting
  mainWindow.on('close', (event) => {
    if (!isQuitting) {
      event.preventDefault();
      mainWindow.hide();
    }
  });

  // Handle external links (open in default OS browser)
  mainWindow.webContents.setWindowOpenHandler(({ url }) => {
    if (!url.includes('ominichannel.duckdns.org') && !url.startsWith('file://')) {
      shell.openExternal(url);
      return { action: 'deny' };
    }
    return { action: 'allow' };
  });

  // Stop flashing taskbar when user focuses window
  mainWindow.on('focus', () => {
    mainWindow.flashFrame(false);
  });
}

function createTray() {
  const iconPath = path.join(__dirname, 'assets', 'tray-icon.png');
  tray = new Tray(iconPath);
  tray.setToolTip('OminiChannel - WhatsApp');

  const updateTrayMenu = () => {
    const isAutoStart = app.getLoginItemSettings().openAtLogin;

    const contextMenu = Menu.buildFromTemplate([
      {
        label: '🟢 Abrir OminiChannel',
        click: () => {
          if (mainWindow) {
            mainWindow.show();
            mainWindow.focus();
          }
        }
      },
      {
        label: '🔄 Recarregar (F5)',
        click: () => {
          if (mainWindow) mainWindow.reload();
        }
      },
      { type: 'separator' },
      {
        label: '🚀 Iniciar com o Windows',
        type: 'checkbox',
        checked: isAutoStart,
        click: (menuItem) => {
          app.setLoginItemSettings({
            openAtLogin: menuItem.checked,
            path: process.execPath
          });
          updateTrayMenu();
        }
      },
      { type: 'separator' },
      {
        label: '🚪 Sair do OminiChannel',
        click: () => {
          isQuitting = true;
          app.quit();
        }
      }
    ]);

    tray.setContextMenu(contextMenu);
  };

  updateTrayMenu();

  // Single click or double click on tray icon restores window
  tray.on('click', () => {
    if (mainWindow) {
      if (mainWindow.isVisible() && !mainWindow.isMinimized()) {
        mainWindow.hide();
      } else {
        mainWindow.show();
        mainWindow.focus();
      }
    }
  });

  tray.on('double-click', () => {
    if (mainWindow) {
      mainWindow.show();
      mainWindow.focus();
    }
  });
}

// IPC Handlers
ipcMain.on('flash-frame', () => {
  if (mainWindow && !mainWindow.isFocused()) {
    mainWindow.flashFrame(true);
  }
});

ipcMain.on('update-badge', (event, count) => {
  if (app.isPackaged) {
    if (count > 0) {
      app.setBadgeCount(count);
    } else {
      app.setBadgeCount(0);
    }
  }
});

ipcMain.on('desktop-notification', (event, { title, body }) => {
  if (Notification.isSupported()) {
    const notif = new Notification({
      title: title || 'OminiChannel',
      body: body || 'Nova mensagem recebida',
      icon: path.join(__dirname, 'assets', 'icon.png')
    });
    notif.on('click', () => {
      if (mainWindow) {
        if (mainWindow.isMinimized()) mainWindow.restore();
        mainWindow.show();
        mainWindow.focus();
      }
    });
    notif.show();
  }
});

app.whenReady().then(() => {
  createWindow();
  createTray();

  app.on('activate', () => {
    if (BrowserWindow.getAllWindows().length === 0) createWindow();
  });
});

app.on('window-all-closed', () => {
  // Keep app active in background tray
  if (process.platform !== 'darwin' && isQuitting) {
    app.quit();
  }
});

app.on('before-quit', () => {
  isQuitting = true;
});
