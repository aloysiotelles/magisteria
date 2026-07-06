const form = document.querySelector("#question-form");
const questionField = document.querySelector("#question");
const searchButton = document.querySelector("#search-button");
const statusElement = document.querySelector("#base-status");
const resultPanel = document.querySelector("#result-panel");
const answerElement = document.querySelector("#answer");
const sourcesElement = document.querySelector("#sources");
const messagePanel = document.querySelector("#message-panel");
const progressPanel = document.querySelector("#index-progress");
const progressBar = document.querySelector("#progress-bar");
const progressTrack = document.querySelector(".progress-track");
const progressPercent = document.querySelector("#progress-percent");
const progressDetail = document.querySelector("#progress-detail");
const progressEta = document.querySelector("#progress-eta");
const databaseButton = document.querySelector("#database-button");
const aboutButton = document.querySelector("#about-button");
const databaseModal = document.querySelector("#database-modal");
const aboutModal = document.querySelector("#about-modal");
const databaseList = document.querySelector("#database-list");
const databaseSummary = document.querySelector("#database-summary");
const searchCard = document.querySelector("#search-card");
const followupPanel = document.querySelector("#followup-panel");
const followupSlot = document.querySelector("#followup-slot");
const presentationModule = document.querySelector("#presentation-module");
const createScriptButton = document.querySelector("#create-script-button");
const createSlidesButton = document.querySelector("#create-slides-button");
const presentationStatus = document.querySelector("#presentation-status");
let conversationHistory = [];
let currentPresentation = null;
let isSearching = false;
let statusTimer = null;
let lastStatusError = "";

function formatDate(value) {
  if (!value) return "nunca atualizada";
  return new Intl.DateTimeFormat("pt-BR", { dateStyle: "short", timeStyle: "short" }).format(new Date(value));
}

function showMessage(message) {
  messagePanel.removeAttribute("style");
  messagePanel.textContent = message;
  messagePanel.classList.remove("hidden");
}

function clearMessage() {
  messagePanel.classList.add("hidden");
  messagePanel.textContent = "";
}

async function request(url, options = {}) {
  const response = await fetch(url, options);
  const data = await response.json().catch(() => ({}));
  if (!response.ok) throw new Error(data.detail || "Ocorreu um erro inesperado.");
  return data;
}

async function refreshStatus() {
  try {
    const status = await request("/status");
    const indexing = status.indexacao;
    statusElement.classList.toggle("indexing", indexing.ativa);
    statusElement.classList.toggle("ready", !indexing.ativa && status.trechos > 0);
    searchButton.disabled = indexing.ativa || isSearching;
    questionField.disabled = indexing.ativa || isSearching;

    if (indexing.ativa) {
      const percentage = Math.max(0, Math.min(100, indexing.percentual));
      progressPanel.classList.remove("hidden");
      progressBar.classList.toggle("indeterminate", percentage === 0);
      progressBar.style.width = `${percentage}%`;
      progressTrack.setAttribute("aria-valuenow", percentage);
      progressPercent.textContent = `${percentage}%`;
      progressDetail.textContent = indexing.arquivo_atual;
      progressEta.textContent = indexing.segundos_restantes == null
        ? "Calculando tempo restante…"
        : indexing.segundos_restantes <= 1
          ? "Menos de um segundo restante"
          : `Aproximadamente ${indexing.segundos_restantes}s restantes`;
      statusElement.querySelector("span:last-child").textContent = "Atualizando a base…";
    } else {
      progressBar.classList.remove("indeterminate");
      progressPanel.classList.add("hidden");
      statusElement.querySelector("span:last-child").textContent =
        `${status.documentos} documento(s) · ${status.trechos} trecho(s) · ${formatDate(status.ultima_atualizacao)}`;
      if (indexing.erro && indexing.erro !== lastStatusError) {
        lastStatusError = indexing.erro;
        showMessage(`Não foi possível atualizar a base: ${indexing.erro}`);
      }
    }
    scheduleStatusRefresh(indexing.ativa ? 800 : 20000);
  } catch {
    statusElement.querySelector("span:last-child").textContent = "Status indisponível";
    scheduleStatusRefresh(10000);
  }
}

function scheduleStatusRefresh(delay) {
  if (statusTimer) clearTimeout(statusTimer);
  statusTimer = setTimeout(refreshStatus, delay);
}

function renderSources(sources) {
  if (!sources.length) {
    sourcesElement.innerHTML = '<p class="empty-sources">Nenhuma fonte foi utilizada, pois não houve evidência suficiente na base.</p>';
    return;
  }
  sourcesElement.replaceChildren(...sources.map(source => {
    const item = document.createElement("div");
    item.className = "source-item";
    const name = document.createElement("span");
    name.className = "source-name";
    name.textContent = source.arquivo;
    const category = document.createElement("div");
    category.className = "source-category";
    category.textContent = source.categoria || "Documento";
    const location = document.createElement("div");
    location.className = "source-location";
    location.textContent = source.local;
    item.append(category, name, location);
    return item;
  }));
}

function closeModal(modal) {
  if (modal.open) modal.close();
}

document.querySelectorAll("[data-close-modal]").forEach(button => {
  button.addEventListener("click", () => closeModal(button.closest("dialog")));
});

document.querySelectorAll("dialog").forEach(modal => {
  modal.addEventListener("click", event => {
    if (event.target === modal) closeModal(modal);
  });
});

databaseButton.addEventListener("click", async () => {
  databaseList.replaceChildren();
  databaseSummary.textContent = "Consultando documentos…";
  databaseModal.showModal();
  try {
    const data = await request("/documentos");
    databaseSummary.textContent = data.documentos.length
      ? `${data.documentos.length} documento(s) disponível(is) para pesquisa.`
      : "Nenhum documento está cadastrado na base.";
    databaseList.replaceChildren(...data.documentos.map(name => {
      const item = document.createElement("li");
      item.textContent = name;
      return item;
    }));
  } catch (error) {
    databaseSummary.textContent = error.message;
  }
});

aboutButton.addEventListener("click", () => aboutModal.showModal());

function archiveCurrentResult() {
  if (resultPanel.classList.contains("hidden") || !answerElement.textContent.trim()) return;
  const archived = resultPanel.cloneNode(true);
  archived.removeAttribute("id");
  archived.classList.add("archived-result");
  archived.querySelectorAll("[id]").forEach(element => element.removeAttribute("id"));
  resultPanel.parentNode.insertBefore(archived, resultPanel);
}

function filenameFromDisposition(response, fallback) {
  const value = response.headers.get("Content-Disposition") || "";
  const match = value.match(/filename="?([^";]+)"?/i);
  return match ? match[1] : fallback;
}

async function createPresentation(endpoint, button, progressMessage, fallbackName) {
  if (!currentPresentation) return;
  clearMessage();
  presentationStatus.textContent = progressMessage;
  createScriptButton.disabled = true;
  createSlidesButton.disabled = true;
  button.classList.add("loading");
  try {
    const response = await fetch(endpoint, {
      method: "POST",
      headers: { "Content-Type": "application/json" },
      body: JSON.stringify(currentPresentation),
    });
    if (!response.ok) {
      const data = await response.json().catch(() => ({}));
      throw new Error(data.detail || "Não foi possível gerar o arquivo.");
    }
    const blob = await response.blob();
    const url = URL.createObjectURL(blob);
    const link = document.createElement("a");
    link.href = url;
    link.download = filenameFromDisposition(response, fallbackName);
    document.body.appendChild(link);
    link.click();
    link.remove();
    URL.revokeObjectURL(url);
    presentationStatus.textContent = "Arquivo criado e enviado para a pasta de downloads.";
  } catch (error) {
    presentationStatus.textContent = "";
    showMessage(error.message);
  } finally {
    createScriptButton.disabled = false;
    createSlidesButton.disabled = false;
    button.classList.remove("loading");
  }
}

createScriptButton.addEventListener("click", () => createPresentation(
  "/criar-roteiro", createScriptButton, "Organizando os tópicos e preparando o documento…", "roteiro-magisteria.docx"
));
createSlidesButton.addEventListener("click", () => createPresentation(
  "/criar-slides", createSlidesButton, "Organizando os tópicos e criando as imagens em paralelo…", "slides-magisteria.pptx"
));

form.addEventListener("submit", async event => {
  event.preventDefault();
  clearMessage();
  const pergunta = questionField.value.trim();
  if (pergunta.length < 3) return showMessage("Digite uma pergunta com pelo menos 3 caracteres.");

  searchButton.disabled = true;
  questionField.disabled = true;
  isSearching = true;
  searchButton.classList.add("loading");
  try {
    const response = await fetch("/perguntar-stream", {
      method: "POST",
      headers: { "Content-Type": "application/json" },
      body: JSON.stringify({ pergunta, historico: conversationHistory }),
    });
    if (!response.ok) {
      const data = await response.json().catch(() => ({}));
      if (response.status === 404) {
        throw new Error("O servidor aberto é de uma versão anterior. Execute novamente o inicializador do MAGISTERIA.");
      }
      throw new Error(data.detail || "Não foi possível realizar a pesquisa.");
    }

    archiveCurrentResult();
    answerElement.textContent = "";
    presentationModule.classList.add("hidden");
    presentationStatus.textContent = "";
    currentPresentation = null;
    renderSources([]);
    resultPanel.classList.remove("hidden");
    resultPanel.scrollIntoView({ behavior: "smooth", block: "start" });

    const reader = response.body.getReader();
    const decoder = new TextDecoder();
    let buffer = "";
    let completed = false;
    let answerForHistory = "";
    let abntReferences = "";
    while (true) {
      const { value, done } = await reader.read();
      buffer += decoder.decode(value || new Uint8Array(), { stream: !done });
      const lines = buffer.split("\n");
      buffer = lines.pop() || "";
      for (const line of lines) {
        if (!line.trim()) continue;
        const item = JSON.parse(line);
        if (item.tipo === "fontes") {
          renderSources(item.fontes);
          abntReferences = item.referencias_abnt || "";
        }
        if (item.tipo === "texto") {
          answerElement.textContent += item.texto;
          answerForHistory += item.texto;
        }
        if (item.tipo === "fim") {
          completed = true;
          if (abntReferences) answerElement.textContent += `\n\nREFERÊNCIAS\n${abntReferences}`;
        }
        if (item.tipo === "erro") throw new Error(item.mensagem);
      }
      if (done) break;
    }
    if (completed && answerElement.textContent.trim()) {
      currentPresentation = { titulo: pergunta, resposta: answerForHistory.trim() };
      presentationModule.classList.remove("hidden");
      conversationHistory.push({ pergunta, resposta: answerForHistory.trim() });
      conversationHistory = conversationHistory.slice(-6);
      questionField.value = "";
      questionField.placeholder = "Faça uma nova pergunta ou peça para aprofundar a resposta…";
      searchButton.innerHTML = '<span class="button-icon">⌕</span> Continuar conversa';
      followupSlot.appendChild(form);
      followupPanel.classList.remove("hidden");
      searchCard.classList.add("hidden");
    }
  } catch (error) {
    showMessage(error.message);
  } finally {
    isSearching = false;
    searchButton.disabled = false;
    questionField.disabled = false;
    searchButton.classList.remove("loading");
  }
});

refreshStatus();
