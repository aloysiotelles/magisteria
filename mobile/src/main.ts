import './styles.css';
import { API_BASE_URL } from './config';
import { api, type MobileSubscriptionInfo } from './api';
import { readSession } from './auth-store';
import { initializeNative, openExternal, saveAndShareFile, shareText } from './native';
import {
  canUsePlayBilling,
  getPlayProduct,
  purchasePlaySubscription,
  restorePlayPurchases,
} from './play-billing';
import { ApiError, type AskEvent, type AskMetadata, type AskSource, type MobileUser, type SearchHistoryItem } from './types';

type AppLanguage = 'pt-BR' | 'en' | 'es';
type UnknownRecord = Record<string, unknown>;

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
const offlineBanner = element<HTMLElement>('#offline-banner');
const serverBanner = element<HTMLElement>('#server-banner');
const toast = element<HTMLElement>('#toast');
const languageSelect = element<HTMLSelectElement>('#language-select');
const profileSelect = element<HTMLSelectElement>('#profile-select');
let registerMode = false;
let currentQuestion = '';
let currentAnswer = '';
let currentLanguage: AppLanguage = savedLanguage();
let currentProfile = localStorage.getItem('magisteria-profile') || 'adulto_leigo';
let connected = true;
let busy = false;
let toastTimer = 0;
let currentUser: MobileUser | null = null;
let googleSyncPromise: Promise<void> | null = null;

function savedLanguage(): AppLanguage {
  const value = localStorage.getItem('magisteria-language');
  return value === 'en' || value === 'es' ? value : 'pt-BR';
}

function showView(name: keyof typeof views): void {
  for (const [key, view] of Object.entries(views)) view.hidden = key !== name;
}

function showToast(message: string, duration = 4200): void {
  window.clearTimeout(toastTimer);
  toast.textContent = message;
  toast.hidden = false;
  toastTimer = window.setTimeout(() => { toast.hidden = true; }, duration);
}

function friendlyError(error: unknown): string {
  if (error instanceof ApiError) return error.message;
  if (error instanceof DOMException && (error.name === 'TimeoutError' || error.name === 'AbortError')) {
    return 'O servidor demorou demais para responder. Tente novamente.';
  }
  if (error instanceof Error) return error.message;
  return 'Ocorreu uma falha inesperada.';
}

function setServerUnavailable(value: boolean): void {
  serverBanner.hidden = !value;
}

function openDialog(selector: string): HTMLDialogElement {
  const dialog = element<HTMLDialogElement>(selector);
  dialog.showModal();
  return dialog;
}

function updateUser(user: MobileUser): void {
  currentUser = user;
  element('#user-chip').textContent = user.full_name;
  const plan = user.subscription.is_full_access ? 'Acesso completo' : 'Plano gratuito';
  element('#profile-summary').textContent = `${user.full_name} · ${user.email} · ${plan}`;
  element('#admin-menu').hidden = user.role !== 'admin';
}

async function obfuscatedAccountId(user: MobileUser): Promise<string> {
  const bytes = new TextEncoder().encode(`magisteria-play-account:${user.id}`);
  const digest = new Uint8Array(await crypto.subtle.digest('SHA-256', bytes));
  return Array.from(digest, (byte) => byte.toString(16).padStart(2, '0')).join('');
}

async function synchronizeGooglePurchases(user: MobileUser, reportError = false): Promise<void> {
  if (!canUsePlayBilling() || googleSyncPromise) return googleSyncPromise ?? Promise.resolve();
  googleSyncPromise = (async () => {
    try {
      const info = await api.subscription();
      if (!info.google_play.available || !info.google_play.product_id) return;
      const owned = await restorePlayPurchases();
      const receipts = owned
        .filter((purchase) => (
          purchase.state === 'purchased'
          && purchase.products.includes(info.google_play.product_id)
        ))
        .map((purchase) => ({
          product_id: info.google_play.product_id,
          purchase_token: purchase.purchaseToken,
        }));
      const response = await api.syncGooglePurchases(receipts);
      if (currentUser?.id === user.id) updateUser(response.user);
    } catch (error) {
      if (reportError) showToast(friendlyError(error));
    }
  })().finally(() => { googleSyncPromise = null; });
  return googleSyncPromise;
}

async function restoreSession(): Promise<void> {
  if (!(await readSession())) {
    showView('auth');
    return;
  }
  try {
    const response = await api.request<{ user: MobileUser }>('/api/v1/mobile/me');
    updateUser(response.user);
    setServerUnavailable(false);
    showView('main');
    void synchronizeGooglePurchases(response.user);
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
    void synchronizeGooglePurchases(user);
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
    item.textContent = [source.marcador ? `[${source.marcador}]` : '', source.arquivo || source.documento || source.source || 'Documento', source.local].filter(Boolean).join(' — ');
    list.append(item);
  }
  element('#source-section').hidden = sources.length === 0;
}

function renderSuggestions(metadata: AskMetadata): void {
  const section = element<HTMLElement>('#suggestions-section');
  const list = element<HTMLElement>('#suggestions-list');
  const depth = element<HTMLElement>('#answer-depth');
  list.replaceChildren();
  depth.textContent = metadata.plan.depth === 'aprofundado'
    ? 'Resposta aprofundada'
    : metadata.plan.depth === 'resumido' ? 'Resposta resumida' : 'Resposta explicativa';
  depth.hidden = false;
  const options = metadata.suggestions.map((label) => ({ label, query: `Explique ${label}.` }));
  if (metadata.continuation_query) {
    options.unshift({ label: 'Continuar esta explicação', query: metadata.continuation_query });
  }
  for (const option of options.slice(0, 5)) {
    const button = document.createElement('button');
    button.type = 'button';
    button.className = 'suggestion-button';
    button.textContent = option.label;
    button.addEventListener('click', () => void runQuestion(option.query));
    list.append(button);
  }
  section.hidden = options.length === 0;
}

function handleAskEvent(event: AskEvent): void {
  if (event.tipo === 'fontes') renderSources(event.fontes || []);
  if (event.tipo === 'texto') {
    currentAnswer = event.texto;
    element('#answer-text').textContent = currentAnswer;
  }
  if (event.tipo === 'metadados') renderSuggestions(event);
  if (event.tipo === 'erro') throw new Error(event.mensagem);
}

async function runQuestion(question: string): Promise<void> {
  if (busy || !connected) return;
  currentQuestion = question.trim();
  if (!currentQuestion) return;
  element<HTMLTextAreaElement>('#question').value = currentQuestion;
  busy = true;
  currentAnswer = '';
  const button = element<HTMLButtonElement>('#ask-button');
  button.disabled = true;
  element('#result-panel').hidden = true;
  element('#suggestions-section').hidden = true;
  element('#answer-depth').hidden = true;
  element('#answer-loading').hidden = false;
  setServerUnavailable(false);
  try {
    await api.askStream(currentQuestion, currentLanguage, currentProfile, handleAskEvent);
    if (!currentAnswer) throw new Error('O servidor encerrou a resposta antes de enviar o texto.');
    element('#answer-title').textContent = currentQuestion;
    element('#result-panel').hidden = false;
    element('#result-panel').scrollIntoView({ behavior: 'smooth', block: 'start' });
  } catch (error) {
    showToast(friendlyError(error));
    setServerUnavailable(false);
  } finally {
    element('#answer-loading').hidden = true;
    button.disabled = false;
    busy = false;
  }
}

questionForm.addEventListener('submit', async (event) => {
  event.preventDefault();
  await runQuestion(element<HTMLTextAreaElement>('#question').value);
});

element('#share-answer').addEventListener('click', async () => {
  if (currentAnswer) await shareText(currentQuestion || 'MAGISTERIA', currentAnswer);
});

async function createDocument(kind: 'script' | 'slides'): Promise<void> {
  if (busy || !currentAnswer) return;
  busy = true;
  const path = kind === 'script' ? '/criar-roteiro' : '/criar-slides';
  const fallbackName = kind === 'script' ? 'magisteria-roteiro.docx' : 'magisteria-slides.pptx';
  const title = kind === 'script' ? 'Criando o roteiro…' : 'Criando os slides…';
  const progress = element('#document-progress');
  const progressTitle = element('#document-progress-title');
  const progressDetail = element('#document-progress-detail');
  const buttons = [element<HTMLButtonElement>('#create-script'), element<HTMLButtonElement>('#create-slides')];
  progressTitle.textContent = title;
  progressDetail.textContent = kind === 'slides'
    ? 'Gerando a estrutura e as imagens. Mantenha o aplicativo aberto; isso pode levar até dois minutos.'
    : 'Organizando o conteúdo. Mantenha o aplicativo aberto.';
  progress.hidden = false;
  buttons.forEach((button) => { button.disabled = true; });
  const reminder = window.setTimeout(() => {
    progressDetail.textContent = 'O servidor ainda está trabalhando. O arquivo será oferecido assim que ficar pronto.';
  }, 35_000);
  try {
    const file = await api.download(
      path,
      { titulo: currentQuestion, resposta: currentAnswer, idioma: currentLanguage },
      fallbackName,
    );
    progressTitle.textContent = 'Arquivo concluído';
    progressDetail.textContent = 'Escolha onde abrir, salvar ou compartilhar.';
    await saveAndShareFile(file.blob, file.filename);
    showToast('Arquivo gerado com sucesso.');
  } catch (error) {
    showToast(friendlyError(error), 6500);
  } finally {
    window.clearTimeout(reminder);
    progress.hidden = true;
    buttons.forEach((button) => { button.disabled = false; });
    busy = false;
  }
}

element('#create-script').addEventListener('click', () => void createDocument('script'));
element('#create-slides').addEventListener('click', () => void createDocument('slides'));

languageSelect.value = currentLanguage;
languageSelect.addEventListener('change', () => {
  currentLanguage = languageSelect.value as AppLanguage;
  localStorage.setItem('magisteria-language', currentLanguage);
  const label = languageSelect.selectedOptions[0]?.textContent || languageSelect.value;
  showToast(`As próximas respostas e apresentações serão geradas em ${label}.`);
});

profileSelect.value = currentProfile;
profileSelect.addEventListener('change', () => {
  currentProfile = profileSelect.value;
  localStorage.setItem('magisteria-profile', currentProfile);
  showToast('O nível de linguagem foi atualizado para as próximas respostas.');
});

element('#database-button').addEventListener('click', async () => {
  const summary = element('#database-summary');
  const list = element<HTMLUListElement>('#database-list');
  list.replaceChildren();
  summary.textContent = 'Consultando documentos…';
  openDialog('#database-dialog');
  try {
    const data = await api.request<{ documents: string[] }>('/api/v1/documents');
    summary.textContent = data.documents.length
      ? `${data.documents.length} documento(s) disponível(is) para pesquisa.`
      : 'Nenhum documento disponível no momento.';
    for (const name of data.documents) {
      const item = document.createElement('li');
      item.textContent = name;
      list.append(item);
    }
  } catch (error) {
    summary.textContent = friendlyError(error);
  }
});

let historySearchTimer = 0;

function historyDate(value: string): string {
  const date = new Date(value);
  return Number.isNaN(date.getTime())
    ? value
    : new Intl.DateTimeFormat(currentLanguage, { dateStyle: 'short', timeStyle: 'short' }).format(date);
}

function historyButton(text: string, className: string): HTMLButtonElement {
  const button = document.createElement('button');
  button.type = 'button';
  button.className = className;
  button.textContent = text;
  return button;
}

function renderHistory(items: SearchHistoryItem[]): void {
  const list = element<HTMLElement>('#history-list');
  list.replaceChildren();
  element('#history-status').textContent = items.length
    ? `${items.length} tema(s) no seu histórico privado.`
    : 'Nenhuma consulta encontrada.';
  for (const item of items) {
    const card = document.createElement('article');
    card.className = 'record-card';
    const title = document.createElement('strong');
    title.textContent = item.display_title;
    const detail = document.createElement('small');
    const repeated = item.repeated ? ` · consultado ${item.search_count} vezes` : '';
    detail.textContent = `${item.depth_level} · ${historyDate(item.last_searched_at)}${repeated}`;
    const actions = document.createElement('div');
    actions.className = 'history-actions';
    const reopen = historyButton('Refazer pesquisa', 'secondary-button');
    reopen.addEventListener('click', async () => {
      reopen.disabled = true;
      try {
        const saved = await api.historyQuery(item.id);
        element<HTMLDialogElement>('#history-dialog').close();
        await runQuestion(saved.query);
      } catch (error) {
        element('#history-status').textContent = friendlyError(error);
      } finally {
        reopen.disabled = false;
      }
    });
    const remove = historyButton('Excluir', 'danger-button');
    remove.addEventListener('click', async () => {
      remove.disabled = true;
      try {
        await api.deleteHistoryItem(item.id);
        await loadHistory();
      } catch (error) {
        element('#history-status').textContent = friendlyError(error);
      }
    });
    actions.append(reopen, remove);
    card.append(title, detail, actions);
    list.append(card);
  }
}

async function loadHistory(): Promise<void> {
  const status = element('#history-status');
  status.textContent = 'Consultando seu histórico…';
  try {
    const search = element<HTMLInputElement>('#history-search').value.trim();
    const sort = element<HTMLSelectElement>('#history-sort').value as 'date' | 'frequency';
    renderHistory(await api.searchHistory(search, sort));
  } catch (error) {
    status.textContent = friendlyError(error);
  }
}

element('#history-button').addEventListener('click', async () => {
  openDialog('#history-dialog');
  await loadHistory();
});

element<HTMLInputElement>('#history-search').addEventListener('input', () => {
  window.clearTimeout(historySearchTimer);
  historySearchTimer = window.setTimeout(() => void loadHistory(), 250);
});
element<HTMLSelectElement>('#history-sort').addEventListener('change', () => void loadHistory());
element('#clear-history').addEventListener('click', async () => {
  if (!window.confirm('Limpar todo o seu histórico de consultas?')) return;
  try {
    await api.clearHistory();
    await loadHistory();
    showToast('Histórico limpo.');
  } catch (error) {
    element('#history-status').textContent = friendlyError(error);
  }
});

async function loadSubscriptionDialog(): Promise<void> {
  const summary = element('#subscription-summary');
  const usage = element('#subscription-usage');
  const playButton = element<HTMLButtonElement>('#play-subscription-button');
  const restoreButton = element<HTMLButtonElement>('#restore-subscription-button');
  const manageButton = element<HTMLButtonElement>('#manage-subscription-button');
  const price = element('#play-subscription-price');
  const playStatus = element('#play-subscription-status');
  summary.textContent = 'Consultando sua assinatura…';
  usage.replaceChildren();
  playButton.disabled = true;
  restoreButton.hidden = true;
  manageButton.hidden = true;
  price.hidden = true;
  playStatus.textContent = 'Verificando a disponibilidade da assinatura…';
  element('#coupon-status').textContent = '';
  try {
    const [profile, store] = await Promise.all([
      api.request<{ user: MobileUser }>('/api/v1/mobile/me'),
      api.subscription(),
    ]);
    updateUser(profile.user);
    const subscription = profile.user.subscription;
    summary.textContent = subscription.is_full_access ? 'Seu acesso é completo.' : 'Você está usando o plano gratuito.';
    usage.textContent = subscription.is_full_access
      ? 'Consultas e materiais liberados conforme as regras do acesso completo.'
      : `Uso de hoje: ${subscription.daily_query_count}/3 consultas · ${subscription.script_generation_count}/1 roteiro · ${subscription.presentation_generation_count}/1 apresentação.`;
    element<HTMLFormElement>('#coupon-form').hidden = subscription.is_full_access;
    playButton.dataset.productId = store.google_play.product_id;
    if (store.entitlement.source === 'android') {
      manageButton.hidden = false;
      manageButton.dataset.productId = store.google_play.product_id;
    }
    if (subscription.is_full_access) {
      playStatus.textContent = store.entitlement.source === 'android'
        ? 'Assinatura Google Play confirmada.'
        : 'Sua conta já possui acesso completo.';
      return;
    }
    if (!canUsePlayBilling()) {
      playStatus.textContent = 'A assinatura Google Play está disponível no aplicativo Android. Você também pode usar um cupom abaixo.';
      return;
    }
    restoreButton.hidden = false;
    if (!store.google_play.available) {
      playStatus.textContent = 'A verificação segura da assinatura ainda não está disponível. Use um cupom ou tente novamente mais tarde.';
      return;
    }
    const product = await getPlayProduct(store.google_play.product_id);
    price.textContent = `${product.formattedPrice} por mês`;
    price.hidden = false;
    playButton.textContent = `Assinar por ${product.formattedPrice}`;
    playButton.disabled = false;
    playStatus.textContent = 'Compra segura processada pela Google Play. Cancele quando quiser nas assinaturas da loja.';
  } catch (error) {
    summary.textContent = friendlyError(error);
  }
}

element('#subscription-button').addEventListener('click', async () => {
  openDialog('#subscription-dialog');
  await loadSubscriptionDialog();
});

element('#play-subscription-button').addEventListener('click', async () => {
  const button = element<HTMLButtonElement>('#play-subscription-button');
  const status = element('#play-subscription-status');
  const productId = button.dataset.productId || '';
  if (!currentUser || !productId) return;
  button.disabled = true;
  status.textContent = 'Abrindo a compra segura do Google Play…';
  try {
    const purchase = await purchasePlaySubscription(productId, await obfuscatedAccountId(currentUser));
    if (purchase.state === 'pending') {
      status.textContent = 'Pagamento pendente. O acesso será liberado depois da confirmação do Google Play.';
      return;
    }
    if (purchase.state !== 'purchased') throw new Error('A compra ainda não foi concluída.');
    status.textContent = 'Validando a compra com o Google Play…';
    const response = await api.verifyGooglePurchase({
      product_id: productId,
      purchase_token: purchase.purchaseToken,
    });
    updateUser(response.user);
    showToast(response.message);
    await loadSubscriptionDialog();
  } catch (error) {
    status.textContent = friendlyError(error);
  } finally {
    if (!currentUser?.subscription.is_full_access) button.disabled = false;
  }
});

element('#restore-subscription-button').addEventListener('click', async () => {
  const button = element<HTMLButtonElement>('#restore-subscription-button');
  const status = element('#play-subscription-status');
  const productId = element<HTMLButtonElement>('#play-subscription-button').dataset.productId || '';
  button.disabled = true;
  status.textContent = 'Consultando suas compras no Google Play…';
  try {
    const owned = await restorePlayPurchases();
    const receipts = owned
      .filter((purchase) => purchase.state === 'purchased' && purchase.products.includes(productId))
      .map((purchase) => ({ product_id: productId, purchase_token: purchase.purchaseToken }));
    const response = await api.syncGooglePurchases(receipts);
    updateUser(response.user);
    showToast(receipts.length ? 'Compra restaurada com sucesso.' : 'Nenhuma assinatura ativa foi encontrada nesta conta do Google Play.');
    await loadSubscriptionDialog();
  } catch (error) {
    status.textContent = friendlyError(error);
  } finally {
    button.disabled = false;
  }
});

element('#manage-subscription-button').addEventListener('click', async () => {
  const productId = element<HTMLButtonElement>('#manage-subscription-button').dataset.productId || '';
  const store = await api.subscription() as MobileSubscriptionInfo;
  const url = `https://play.google.com/store/account/subscriptions?sku=${encodeURIComponent(productId)}&package=${encodeURIComponent(store.google_play.package_name)}`;
  await openExternal(url);
});

element<HTMLFormElement>('#coupon-form').addEventListener('submit', async (event) => {
  event.preventDefault();
  const input = element<HTMLInputElement>('#coupon-input');
  const submit = element<HTMLButtonElement>('#coupon-submit');
  const status = element('#coupon-status');
  const code = input.value.trim();
  if (!code) {
    status.textContent = 'Informe o código do cupom.';
    return;
  }
  submit.disabled = true;
  status.textContent = 'Validando cupom…';
  try {
    const data = await api.redeemCoupon(code);
    input.value = '';
    status.textContent = data.message;
    updateUser(data.user);
    showToast(data.message);
    await loadSubscriptionDialog();
  } catch (error) {
    status.textContent = friendlyError(error);
  } finally {
    submit.disabled = false;
  }
});

element('#change-password-button').addEventListener('click', () => {
  element<HTMLFormElement>('#change-password-form').reset();
  element('#change-password-status').textContent = '';
  openDialog('#password-dialog');
});

element<HTMLFormElement>('#change-password-form').addEventListener('submit', async (event) => {
  event.preventDefault();
  const current = element<HTMLInputElement>('#current-password').value;
  const next = element<HTMLInputElement>('#new-password').value;
  const confirmation = element<HTMLInputElement>('#confirm-password').value;
  const status = element('#change-password-status');
  const submit = element<HTMLButtonElement>('#change-password-submit');
  if (next !== confirmation) {
    status.textContent = 'A confirmação da nova senha não confere.';
    return;
  }
  submit.disabled = true;
  try {
    await api.request('/alterar-senha', {
      method: 'POST',
      headers: { 'Content-Type': 'application/json' },
      body: JSON.stringify({ senha_atual: current, nova_senha: next, confirmar_senha: confirmation }),
    });
    element<HTMLFormElement>('#change-password-form').reset();
    element<HTMLDialogElement>('#password-dialog').close();
    showToast('Senha alterada com sucesso. Entre novamente se sua sessão for encerrada.');
  } catch (error) {
    status.textContent = friendlyError(error);
  } finally {
    submit.disabled = false;
  }
});

element('#about-button').addEventListener('click', () => openDialog('#about-dialog'));
element('#account-button').addEventListener('click', () => openDialog('#account-dialog'));

for (const button of document.querySelectorAll<HTMLButtonElement>('[data-close-dialog]')) {
  button.addEventListener('click', () => button.closest('dialog')?.close());
}
for (const dialog of document.querySelectorAll<HTMLDialogElement>('dialog')) {
  dialog.addEventListener('click', (event) => {
    if (event.target === dialog) dialog.close();
  });
}
for (const button of document.querySelectorAll<HTMLButtonElement>('[data-external]')) {
  button.addEventListener('click', async () => {
    const path = button.dataset.external;
    if (path) await openExternal(`${API_BASE_URL}${path}`);
  });
}

element('#logout-button').addEventListener('click', async () => {
  await api.logout();
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
    element<HTMLDialogElement>('#account-dialog').close();
    showView('auth');
    showToast('Sua conta foi excluída.');
  } catch (error) {
    showToast(friendlyError(error));
  } finally {
    busy = false;
  }
});

function adminDialog(title: string, summary: string): void {
  element('#admin-dialog-title').textContent = title;
  element('#admin-dialog-summary').textContent = summary;
  element('#admin-data-list').replaceChildren();
  element('#admin-coupon-form').hidden = true;
  element('#admin-upload').hidden = true;
  openDialog('#admin-dialog');
}

function addRecord(title: string, detail: string, actions: HTMLButtonElement[] = []): void {
  const card = document.createElement('article');
  card.className = 'record-card';
  const heading = document.createElement('strong');
  heading.textContent = title;
  const body = document.createElement('small');
  body.textContent = detail;
  card.append(heading, body, ...actions);
  element('#admin-data-list').append(card);
}

function value(record: UnknownRecord, key: string, fallback = '—'): string {
  const item = record[key];
  return item === null || item === undefined || item === '' ? fallback : String(item);
}

element('#stats-button').addEventListener('click', async () => {
  adminDialog('Estatísticas', 'Consultando usuários…');
  try {
    const data = await api.request<{ usuarios: UnknownRecord[] }>('/admin/estatisticas');
    element('#admin-dialog-summary').textContent = `${data.usuarios.length} usuário(s) cadastrado(s).`;
    data.usuarios.forEach((user) => addRecord(
      value(user, 'full_name'),
      `${value(user, 'email')} · ${value(user, 'account_type')} · acessos: ${value(user, 'total_access_count', '0')} · consultas hoje: ${value(user, 'daily_query_count', '0')} · slides: ${value(user, 'presentation_generation_count', '0')}`,
    ));
  } catch (error) {
    element('#admin-dialog-summary').textContent = friendlyError(error);
  }
});

async function loadCoupons(): Promise<void> {
  element('#admin-data-list').replaceChildren();
  const data = await api.request<{ cupons: UnknownRecord[] }>('/admin/cupons');
  const active = data.cupons.filter((coupon) => value(coupon, 'status') === 'ativo').length;
  element('#admin-dialog-summary').textContent = `${data.cupons.length} cupom(ns), ${active} ativo(s).`;
  data.cupons.forEach((coupon) => addRecord(
    value(coupon, 'code'),
    `${value(coupon, 'validity_period')} · ${value(coupon, 'status')} · usos: ${value(coupon, 'total_redemptions', '0')} · acessos ativos: ${value(coupon, 'active_redemptions', '0')}`,
  ));
}

element('#coupons-button').addEventListener('click', async () => {
  adminDialog('Cupons promocionais', 'Consultando cupons…');
  element('#admin-coupon-form').hidden = false;
  try { await loadCoupons(); } catch (error) { element('#admin-dialog-summary').textContent = friendlyError(error); }
});

element<HTMLFormElement>('#admin-coupon-form').addEventListener('submit', async (event) => {
  event.preventDefault();
  try {
    await api.request('/admin/cupons', {
      method: 'POST',
      headers: { 'Content-Type': 'application/json' },
      body: JSON.stringify({
        cupom: element<HTMLInputElement>('#admin-coupon-code').value.trim(),
        validade: element<HTMLSelectElement>('#admin-coupon-validity').value,
      }),
    });
    element<HTMLFormElement>('#admin-coupon-form').reset();
    await loadCoupons();
  } catch (error) {
    element('#admin-dialog-summary').textContent = friendlyError(error);
  }
});

async function loadAdminDocuments(): Promise<void> {
  element('#admin-data-list').replaceChildren();
  const data = await api.request<{ documentos: UnknownRecord[] }>('/admin/base-documental');
  element('#admin-dialog-summary').textContent = `${data.documentos.length} documento(s) cadastrado(s).`;
  for (const document of data.documentos) {
    const active = Boolean(document.is_active);
    const action = documentElement('button', active ? 'Desativar' : 'Ativar');
    action.addEventListener('click', async () => {
      action.disabled = true;
      try {
        await api.request(active ? '/admin/base-documental/desativar' : '/admin/base-documental/ativar', {
          method: 'POST',
          headers: { 'Content-Type': 'application/json' },
          body: JSON.stringify({ source: document.source }),
        });
        await loadAdminDocuments();
      } catch (error) {
        element('#admin-dialog-summary').textContent = friendlyError(error);
      }
    });
    addRecord(value(document, 'filename'), `${value(document, 'file_type').toUpperCase()} · ${active ? 'ativo' : 'inativo'}`, [action]);
  }
}

function documentElement(tag: 'button', text: string): HTMLButtonElement {
  const button = document.createElement(tag);
  button.type = 'button';
  button.className = 'secondary-button';
  button.textContent = text;
  return button;
}

element('#admin-documents-button').addEventListener('click', async () => {
  adminDialog('Base documental', 'Consultando documentos…');
  element('#admin-upload').hidden = false;
  try { await loadAdminDocuments(); } catch (error) { element('#admin-dialog-summary').textContent = friendlyError(error); }
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
    await loadAdminDocuments();
    showToast('Documento enviado. Reindexe a base para incluí-lo nas pesquisas.');
  } catch (error) {
    showToast(friendlyError(error));
  } finally {
    busy = false;
    window.setTimeout(() => { progress.hidden = true; }, 1200);
  }
});

element('#reindex-documents').addEventListener('click', async () => {
  const button = element<HTMLButtonElement>('#reindex-documents');
  button.disabled = true;
  element('#admin-dialog-summary').textContent = 'Reindexando a base documental…';
  try {
    await api.request('/admin/base-documental/reindexar', { method: 'POST' });
    await loadAdminDocuments();
    showToast('Base documental reindexada.');
  } catch (error) {
    element('#admin-dialog-summary').textContent = friendlyError(error);
  } finally {
    button.disabled = false;
  }
});

element('#rag-button').addEventListener('click', async () => {
  adminDialog('Diagnóstico RAG', 'Consultando execuções recentes…');
  try {
    const data = await api.request<{ consultas: UnknownRecord[] }>('/admin/rag/diagnosticos?limit=100');
    element('#admin-dialog-summary').textContent = `${data.consultas.length} execução(ões) recente(s).`;
    data.consultas.forEach((item) => addRecord(
      value(item, 'query_text'),
      `${value(item, 'query_type')} · ${value(item, 'duration_ms', '0')} ms · candidatos: ${value(item, 'candidate_count', '0')} · selecionados: ${value(item, 'final_count', '0')} · status: ${value(item, 'status')}`,
    ));
  } catch (error) {
    element('#admin-dialog-summary').textContent = friendlyError(error);
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
