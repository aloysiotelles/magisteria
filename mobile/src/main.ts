import './styles.css';
import { API_BASE_URL } from './config';
import { api } from './api';
import { readSession } from './auth-store';
import { initializeNative, openExternal, saveAndShareFile, shareText } from './native';
import { ApiError, type AskEvent, type AskSource, type MobileUser } from './types';

function element<T extends HTMLElement>(selector: string): T {
  const found = document.querySelector<T>(selector);
  if (!found) throw new Error(`Elemento obrigatório ausente: ${selector}`);
  return found;
}

const views = {
  splash: element<HTMLElement>('#splash-view'),
  auth: element<HTMLElement>('#auth-view'),
  main: element<HTMLElement>('#main-view'),
};
const authForm = element<HTMLFormElement>('#auth-form');
const questionForm = element<HTMLFormElement>('#question-form');
const profileDialog = element<HTMLDialogElement>('#profile-dialog');
const offlineBanner = element<HTMLElement>('#offline-banner');
const serverBanner = element<HTMLElement>('#server-banner');
const toast = element<HTMLElement>('#toast');
let registerMode = false;
let currentQuestion = '';
let currentAnswer = '';
let connected = true;
let busy = false;
let toastTimer = 0;

function showView(name: keyof typeof views): void {
  for (const [key, view] of Object.entries(views)) view.hidden = key !== name;
}

function showToast(message: string): void {
  window.clearTimeout(toastTimer);
  toast.textContent = message;
  toast.hidden = false;
  toastTimer = window.setTimeout(() => { toast.hidden = true; }, 3500);
}

function friendlyError(error: unknown): string {
  if (error instanceof ApiError) return error.message;
  if (error instanceof DOMException && error.name === 'TimeoutError') return 'O servidor demorou demais para responder.';
  if (error instanceof Error) return error.message;
  return 'Ocorreu uma falha inesperada.';
}

function setServerUnavailable(value: boolean): void {
  serverBanner.hidden = !value;
}

function updateUser(user: MobileUser): void {
  const firstName = user.full_name.trim().split(/\s+/)[0] || 'bem-vindo';
  element('#welcome-title').textContent = `Olá, ${firstName}`;
  const plan = user.subscription.is_full_access ? 'Acesso completo' : 'Plano gratuito';
  element('#profile-summary').textContent = `${user.full_name} · ${user.email} · ${plan}`;
  element('#admin-upload').hidden = user.role !== 'admin';
}

async function restoreSession(): Promise<void> {
  if (!(await readSession())) {
    showView('auth');
    return;
  }
  try {
    const response = await api.request<{ user: MobileUser }>('/api/v1/mobile/me');
    updateUser(response.user);
    showView('main');
  } catch (error) {
    setServerUnavailable(!(error instanceof ApiError && error.status === 401));
    showView('auth');
  }
}

function setAuthMode(nextRegisterMode: boolean): void {
  registerMode = nextRegisterMode;
  element('#name-field').hidden = !registerMode;
  element('#auth-title').textContent = registerMode ? 'Criar conta' : 'Entrar';
  element<HTMLButtonElement>('#auth-submit').textContent = registerMode ? 'Criar e entrar' : 'Entrar';
  element<HTMLButtonElement>('#auth-toggle').textContent = registerMode ? 'Já tenho uma conta' : 'Criar uma conta';
  element<HTMLInputElement>('#password').autocomplete = registerMode ? 'new-password' : 'current-password';
  element('#auth-error').hidden = true;
}

authForm.addEventListener('submit', async (event) => {
  event.preventDefault();
  if (busy || !connected) return;
  const email = element<HTMLInputElement>('#email').value.trim();
  const password = element<HTMLInputElement>('#password').value;
  const fullName = element<HTMLInputElement>('#full-name').value.trim();
  const errorBox = element('#auth-error');
  const button = element<HTMLButtonElement>('#auth-submit');
  busy = true;
  button.disabled = true;
  errorBox.hidden = true;
  try {
    const user = registerMode
      ? await api.register(fullName, email, password)
      : await api.login(email, password);
    updateUser(user);
    authForm.reset();
    setServerUnavailable(false);
    showView('main');
  } catch (error) {
    errorBox.textContent = friendlyError(error);
    errorBox.hidden = false;
    setServerUnavailable(!(error instanceof ApiError));
  } finally {
    busy = false;
    button.disabled = false;
  }
});

element('#auth-toggle').addEventListener('click', () => setAuthMode(!registerMode));

function renderSources(sources: AskSource[]): void {
  const list = element<HTMLUListElement>('#source-list');
  list.replaceChildren();
  for (const source of sources) {
    const item = document.createElement('li');
    item.textContent = [source.documento || source.source || 'Documento', source.local].filter(Boolean).join(' — ');
    list.append(item);
  }
  element('#source-section').hidden = sources.length === 0;
}

function handleAskEvent(event: AskEvent): void {
  if (event.tipo === 'fontes') renderSources(event.fontes || []);
  if (event.tipo === 'texto') {
    currentAnswer = event.texto;
    element('#answer-text').textContent = currentAnswer;
  }
  if (event.tipo === 'erro') throw new Error(event.mensagem);
}

questionForm.addEventListener('submit', async (event) => {
  event.preventDefault();
  if (busy || !connected) return;
  currentQuestion = element<HTMLTextAreaElement>('#question').value.trim();
  if (!currentQuestion) return;
  busy = true;
  currentAnswer = '';
  const button = element<HTMLButtonElement>('#ask-button');
  button.disabled = true;
  element('#answer-card').hidden = true;
  element('#answer-loading').hidden = false;
  setServerUnavailable(false);
  try {
    await api.askStream(currentQuestion, handleAskEvent);
    if (!currentAnswer) throw new Error('O servidor encerrou a resposta antes de enviar o texto.');
    element('#answer-title').textContent = currentQuestion;
    element('#answer-card').hidden = false;
    element('#answer-card').scrollIntoView({ behavior: 'smooth', block: 'start' });
  } catch (error) {
    showToast(friendlyError(error));
    setServerUnavailable(!(error instanceof ApiError));
  } finally {
    element('#answer-loading').hidden = true;
    button.disabled = false;
    busy = false;
  }
});

element('#share-answer').addEventListener('click', async () => {
  if (currentAnswer) await shareText(currentQuestion || 'MAGISTERIA', currentAnswer);
});

async function createDocument(kind: 'script' | 'slides'): Promise<void> {
  if (busy || !currentAnswer) return;
  busy = true;
  const path = kind === 'script' ? '/criar-roteiro' : '/criar-slides';
  const filename = kind === 'script' ? 'magisteria-roteiro.docx' : 'magisteria-slides.pptx';
  try {
    showToast('Preparando o arquivo…');
    const blob = await api.download(path, { titulo: currentQuestion, resposta: currentAnswer, idioma: 'pt-BR' });
    await saveAndShareFile(blob, filename);
  } catch (error) {
    showToast(friendlyError(error));
  } finally {
    busy = false;
  }
}

element('#create-script').addEventListener('click', () => void createDocument('script'));
element('#create-slides').addEventListener('click', () => void createDocument('slides'));
element('#profile-button').addEventListener('click', () => profileDialog.showModal());
element('#close-profile').addEventListener('click', () => profileDialog.close());

for (const button of document.querySelectorAll<HTMLButtonElement>('[data-external]')) {
  button.addEventListener('click', async () => {
    const path = button.dataset.external;
    if (path) await openExternal(`${API_BASE_URL}${path}`);
  });
}

element('#logout-button').addEventListener('click', async () => {
  await api.logout();
  profileDialog.close();
  setAuthMode(false);
  showView('auth');
});

element('#delete-account').addEventListener('click', async () => {
  if (busy) return;
  const password = element<HTMLInputElement>('#delete-password').value;
  const confirmation = element<HTMLInputElement>('#delete-confirmation').value;
  busy = true;
  try {
    await api.request('/api/v1/mobile/account', {
      method: 'DELETE',
      headers: { 'Content-Type': 'application/json' },
      body: JSON.stringify({ password, confirmation }),
    });
    await api.logout();
    profileDialog.close();
    showView('auth');
    showToast('Sua conta foi excluída.');
  } catch (error) {
    showToast(friendlyError(error));
  } finally {
    busy = false;
  }
});

element('#upload-document').addEventListener('click', async () => {
  const input = element<HTMLInputElement>('#document-file');
  const file = input.files?.[0];
  if (!file || busy) return;
  const allowed = ['pdf', 'docx', 'txt', 'md', 'markdown'];
  const extension = file.name.split('.').pop()?.toLowerCase() || '';
  if (!allowed.includes(extension)) {
    showToast('Tipo de arquivo não permitido.');
    return;
  }
  const progress = element<HTMLProgressElement>('#upload-progress');
  busy = true;
  progress.value = 0;
  progress.hidden = false;
  try {
    await api.uploadDocument(file, (percent) => { progress.value = percent; });
    input.value = '';
    showToast('Documento enviado. Reindexe a base pelo painel administrativo.');
  } catch (error) {
    showToast(friendlyError(error));
  } finally {
    busy = false;
    window.setTimeout(() => { progress.hidden = true; }, 1200);
  }
});

element('#retry-button').addEventListener('click', () => void restoreSession());

async function boot(): Promise<void> {
  try {
    await initializeNative((isConnected) => {
      const wasOffline = !connected;
      connected = isConnected;
      offlineBanner.hidden = connected;
      element<HTMLButtonElement>('#ask-button').disabled = !connected || busy;
      if (connected && wasOffline) void restoreSession();
    });
  } catch (error) {
    console.warn('Recursos nativos indisponíveis no navegador de desenvolvimento.', error);
  }
  await restoreSession();
}

void boot();
