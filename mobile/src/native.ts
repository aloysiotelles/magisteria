import { App } from '@capacitor/app';
import { Browser } from '@capacitor/browser';
import { Directory, Filesystem } from '@capacitor/filesystem';
import { Network } from '@capacitor/network';
import { Share } from '@capacitor/share';
import { SplashScreen } from '@capacitor/splash-screen';
import { ALLOWED_EXTERNAL_HOSTS } from './config';

export async function initializeNative(onNetworkChange: (connected: boolean) => void): Promise<void> {
  const status = await Network.getStatus();
  onNetworkChange(status.connected);
  await Network.addListener('networkStatusChange', (next) => onNetworkChange(next.connected));
  await App.addListener('backButton', async ({ canGoBack }) => {
    const dialog = document.querySelector<HTMLDialogElement>('dialog[open]');
    if (dialog) {
      dialog.close();
    } else if (canGoBack) {
      history.back();
    } else {
      await App.minimizeApp();
    }
  });
  await SplashScreen.hide();
}

export async function openExternal(rawUrl: string): Promise<void> {
  const url = new URL(rawUrl);
  if (!ALLOWED_EXTERNAL_HOSTS.has(url.hostname) || url.protocol !== 'https:') {
    throw new Error('Este endereço externo não é permitido.');
  }
  await Browser.open({ url: url.toString(), presentationStyle: 'popover' });
}

export async function shareText(title: string, text: string): Promise<void> {
  await Share.share({ title, text, dialogTitle: 'Compartilhar com' });
}

function bytesToBase64(bytes: Uint8Array): string {
  let binary = '';
  const chunk = 0x8000;
  for (let index = 0; index < bytes.length; index += chunk) {
    binary += String.fromCharCode(...bytes.subarray(index, index + chunk));
  }
  return btoa(binary);
}

export async function saveAndShareFile(blob: Blob, filename: string): Promise<void> {
  const data = bytesToBase64(new Uint8Array(await blob.arrayBuffer()));
  const result = await Filesystem.writeFile({
    path: filename,
    data,
    directory: Directory.Cache,
    recursive: true,
  });
  await Share.share({ title: filename, url: result.uri, dialogTitle: 'Abrir ou compartilhar arquivo' });
}
