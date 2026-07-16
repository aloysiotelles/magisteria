const form = document.querySelector("#question-form");
const questionField = document.querySelector("#question");
const searchButton = document.querySelector("#search-button");
const statusElement = document.querySelector("#base-status");
const resultPanel = document.querySelector("#result-panel");
const answerStatusElement = document.querySelector("#answer-status");
const retrievalNoticeElement = document.querySelector("#retrieval-notice");
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
const changePasswordButton = document.querySelector("#change-password-button");
const aboutButton = document.querySelector("#about-button");
const disclaimerModal = document.querySelector("#disclaimer-modal");
const disclaimerOkButton = document.querySelector("#disclaimer-ok-button");
const subscriptionButton = document.querySelector("#subscription-button");
const databaseModal = document.querySelector("#database-modal");
const subscriptionModal = document.querySelector("#subscription-modal");
const changePasswordModal = document.querySelector("#change-password-modal");
const changePasswordForm = document.querySelector("#change-password-form");
const currentPassword = document.querySelector("#current-password");
const newPassword = document.querySelector("#new-password");
const confirmPassword = document.querySelector("#confirm-password");
const changePasswordSubmit = document.querySelector("#change-password-submit");
const changePasswordStatus = document.querySelector("#change-password-status");
const aboutModal = document.querySelector("#about-modal");
const subscriptionSummary = document.querySelector("#subscription-summary");
const paymentCheckoutButton = document.querySelector("#payment-checkout-button");
const paymentPrice = document.querySelector("#payment-price");
const paymentDocument = document.querySelector("#payment-document");
const paymentStatus = document.querySelector("#payment-status");
const couponForm = document.querySelector("#coupon-form");
const couponInput = document.querySelector("#coupon-input");
const couponSubmit = document.querySelector("#coupon-submit");
const couponStatus = document.querySelector("#coupon-status");
const toggleFreeAccessButton = document.querySelector("#toggle-free-access-button");
const databaseList = document.querySelector("#database-list");
const databaseSummary = document.querySelector("#database-summary");
const searchCard = document.querySelector("#search-card");
const followupPanel = document.querySelector("#followup-panel");
const followupSlot = document.querySelector("#followup-slot");
const presentationModule = document.querySelector("#presentation-module");
const createScriptButton = document.querySelector("#create-script-button");
const createSlidesButton = document.querySelector("#create-slides-button");
const presentationStatus = document.querySelector("#presentation-status");
const statsButton = document.querySelector("#stats-button");
const statsModal = document.querySelector("#stats-modal");
const statsSummary = document.querySelector("#stats-summary");
const statsTable = document.querySelector("#stats-table");
const couponsButton = document.querySelector("#coupons-button");
const couponsModal = document.querySelector("#coupons-modal");
const couponsSummary = document.querySelector("#coupons-summary");
const couponsTable = document.querySelector("#coupons-table");
const adminCouponForm = document.querySelector("#admin-coupon-form");
const adminCouponCode = document.querySelector("#admin-coupon-code");
const adminCouponValidity = document.querySelector("#admin-coupon-validity");
const adminCouponSubmit = document.querySelector("#admin-coupon-submit");
const adminDocumentsButton = document.querySelector("#admin-documents-button");
const adminDocumentsModal = document.querySelector("#admin-documents-modal");
const adminDocumentsSummary = document.querySelector("#admin-documents-summary");
const adminDocumentsTable = document.querySelector("#admin-documents-table");
const ragDiagnosticsButton = document.querySelector("#rag-diagnostics-button");
const ragDiagnosticsModal = document.querySelector("#rag-diagnostics-modal");
const ragDiagnosticsSummary = document.querySelector("#rag-diagnostics-summary");
const ragDiagnosticsTable = document.querySelector("#rag-diagnostics-table");
const documentUploadForm = document.querySelector("#document-upload-form");
const documentUpload = document.querySelector("#document-upload");
const reindexDocumentsButton = document.querySelector("#reindex-documents-button");
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

function readableErrorMessage(detail) {
  if (!detail) return "Ocorreu um erro inesperado.";
  if (typeof detail === "string") {
    return detail === "Field required" ? "Preencha todos os campos obrigatórios." : detail;
  }
  if (Array.isArray(detail)) {
    if (detail.some(item => item?.msg === "Field required")) {
      return "Preencha todos os campos obrigatórios.";
    }
    return detail.map(item => item?.msg || item?.message || JSON.stringify(item)).join(" ");
  }
  const message = detail.msg || detail.message || JSON.stringify(detail);
  return message === "Field required" ? "Preencha todos os campos obrigatórios." : message;
}

async function request(url, options = {}) {
  const { timeout = 20000, ...fetchOptions } = options;
  const controller = new AbortController();
  const timer = setTimeout(() => controller.abort(), timeout);
  try {
    const response = await fetch(url, {
      credentials: "same-origin",
      ...fetchOptions,
      signal: controller.signal,
    });
    const data = await response.json().catch(() => ({}));
    if (!response.ok) throw new Error(readableErrorMessage(data.detail));
    return data;
  } catch (error) {
    if (error?.name === "AbortError") {
      throw new Error("A solicitaÃ§Ã£o demorou mais do que o esperado. Tente novamente.");
    }
    throw error;
  } finally {
    clearTimeout(timer);
  }
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

function reviewLabel(status) {
  if (status === "approve") return "Resposta duplamente checada na base de dados";
  if (status === "rewrite") return "Resposta duplamente checada na base de dados";
  if (status === "block") return "Resposta duplamente checada na base de dados";
  return "Resposta duplamente checada na base de dados";
}

function reviewTone(status) {
  if (status === "approve") return "approved";
  if (status === "rewrite") return "warning";
  if (status === "block") return "blocked";
  return "neutral";
}

function renderReviewStatus(status, reason) {
  if (!answerStatusElement) return;
  if (!status) {
    answerStatusElement.className = "review-status hidden";
    answerStatusElement.textContent = "";
    return;
  }
  answerStatusElement.className = `review-status ${reviewTone(status)}`;
  answerStatusElement.textContent = reviewLabel(status);
  answerStatusElement.classList.remove("hidden");
}

function closeModal(modal) {
  if (modal.open) modal.close();
}

function renderTable(table, headers, rows) {
  table.replaceChildren();
  const thead = document.createElement("thead");
  const headRow = document.createElement("tr");
  headers.forEach(header => {
    const cell = document.createElement("th");
    cell.textContent = header;
    headRow.appendChild(cell);
  });
  thead.appendChild(headRow);
  const tbody = document.createElement("tbody");
  rows.forEach(row => {
    const tr = document.createElement("tr");
    row.forEach(value => {
      const cell = document.createElement("td");
      if (value instanceof Node) cell.appendChild(value);
      else cell.textContent = value ?? "";
      tr.appendChild(cell);
    });
    tbody.appendChild(tr);
  });
  table.append(thead, tbody);
}

function formatAdminDate(value) {
  return value ? formatDate(value) : "-";
}

document.querySelectorAll("[data-close-modal]").forEach(button => {
  button.addEventListener("click", () => closeModal(button.closest("dialog")));
});

document.querySelectorAll("dialog").forEach(modal => {
  modal.addEventListener("click", event => {
    if (event.target === modal && !modal.dataset.requiresConfirmation) closeModal(modal);
  });
});

if (disclaimerModal && disclaimerOkButton) {
  disclaimerModal.addEventListener("cancel", event => event.preventDefault());
  disclaimerOkButton.addEventListener("click", () => disclaimerModal.close());
  disclaimerModal.showModal();
}

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
if (subscriptionButton) {
  subscriptionButton.addEventListener("click", async () => {
    subscriptionSummary.textContent = "Consultando sua assinatura...";
    paymentStatus.textContent = "";
    subscriptionModal.showModal();
    try {
      const data = await request("/assinatura");
      subscriptionSummary.textContent = `${data.usuario.plano === "completo" ? "Seu acesso está completo." : "Seu acesso está na modalidade gratuita."} ${data.pagamento.confirmacao}`;
      paymentPrice.textContent = data.pagamento.valor ? `Valor: ${data.pagamento.valor}.` : "";
      paymentCheckoutButton.disabled = data.usuario.plano === "completo" || !data.pagamento.disponivel;
      if (!data.pagamento.disponivel) {
        paymentStatus.textContent = "O pagamento ainda está sendo configurado pelo administrador.";
      } else if (data.pagamento.status === "pending") {
        paymentStatus.textContent = "Há um pagamento iniciado aguardando confirmação.";
      }
    } catch (error) {
      subscriptionSummary.textContent = error.message;
    }
  });
}

if (paymentCheckoutButton) {
  paymentCheckoutButton.addEventListener("click", async () => {
    const documentDigits = paymentDocument.value.replace(/\D/g, "");
    if (![11, 14].includes(documentDigits.length)) {
      paymentStatus.textContent = "Informe um CPF ou CNPJ válido para continuar.";
      paymentDocument.focus();
      return;
    }
    paymentCheckoutButton.disabled = true;
    paymentStatus.textContent = "Preparando sua assinatura segura...";
    try {
      const data = await request("/assinatura/checkout", {
        method: "POST",
        headers: { "Content-Type": "application/json" },
        body: JSON.stringify({ cpf_cnpj: documentDigits }),
      });
      window.location.assign(data.checkout_url);
    } catch (error) {
      paymentStatus.textContent = error.message;
      paymentCheckoutButton.disabled = false;
    }
  });
}

const paymentReturn = new URLSearchParams(window.location.search).get("pagamento");
if (paymentReturn && subscriptionButton) {
  subscriptionButton.click();
  const paymentReturnMessages = {
    aprovado: "Pagamento aprovado. Seu acesso completo já está liberado.",
    approved: "Pagamento aprovado. Seu acesso completo já está liberado.",
    pendente: "Pagamento pendente. A liberação ocorrerá assim que o Asaas confirmar.",
    pending: "Pagamento pendente. A liberação ocorrerá assim que o Asaas confirmar.",
    falha: "O pagamento não foi concluído. Você pode tentar novamente.",
    failure: "O pagamento não foi concluído. Você pode tentar novamente.",
    rejected: "O pagamento foi recusado. Confira os dados ou escolha outro meio de pagamento.",
  };
  paymentStatus.textContent = paymentReturnMessages[paymentReturn] || "O retorno foi recebido e a assinatura está sendo conferida.";
  window.history.replaceState({}, "", window.location.pathname);
}

changePasswordButton.addEventListener("click", () => {
  changePasswordForm.reset();
  changePasswordStatus.textContent = "";
  changePasswordModal.showModal();
});

changePasswordForm.addEventListener("submit", async event => {
  event.preventDefault();
  changePasswordStatus.textContent = "";
  if (newPassword.value !== confirmPassword.value) {
    changePasswordStatus.textContent = "A confirmação da nova senha não confere.";
    return;
  }
  changePasswordSubmit.disabled = true;
  try {
    const data = await request("/alterar-senha", {
      method: "POST",
      headers: { "Content-Type": "application/json" },
      body: JSON.stringify({
        senha_atual: currentPassword.value,
        nova_senha: newPassword.value,
        confirmar_senha: confirmPassword.value,
      }),
    });
    changePasswordForm.reset();
    changePasswordModal.close();
    clearMessage();
  } catch (error) {
    changePasswordStatus.textContent = error.message;
  } finally {
    changePasswordSubmit.disabled = false;
  }
});

async function refreshAdminStatistics() {
  statsSummary.textContent = "Consultando usuários...";
  renderTable(statsTable, [], []);
  const data = await request("/admin/estatisticas");
  statsSummary.textContent = `${data.usuarios.length} usuário(s) cadastrado(s).`;
  renderTable(statsTable, ["Nome", "Email", "Conta", "Assinatura", "Origem", "Acessos", "Último acesso", "Consultas", "Roteiros", "Slides", "Ações"], data.usuarios.map(user => {
    const actions = document.createElement("div");
    actions.className = "row-actions";
    if (user.can_revoke_coupon) {
      const revoke = document.createElement("button");
      revoke.type = "button";
      revoke.textContent = "Revogar cupom";
      revoke.addEventListener("click", async () => {
        if (!window.confirm(`Revogar o acesso completo de ${user.full_name}?`)) return;
        revoke.disabled = true;
        try {
          await request("/admin/assinatura/revogar-cupom", {
            method: "POST",
            headers: { "Content-Type": "application/json" },
            body: JSON.stringify({ usuario_id: user.id }),
          });
          await refreshAdminStatistics();
        } catch (error) {
          statsSummary.textContent = error.message;
          revoke.disabled = false;
        }
      });
      actions.appendChild(revoke);
    }
    const origin = user.coupon_code
      ? `Cupom ${user.coupon_code}`
      : user.access_origin === "pagamento"
        ? "Pagamento"
        : user.role === "admin" ? "Admin" : "Cadastro";
    return [
      user.full_name,
      user.email,
      user.account_type,
      user.subscription_status,
      origin,
      user.total_access_count,
      formatAdminDate(user.last_access_at),
      user.daily_query_count,
      user.script_generation_count,
      user.presentation_generation_count,
      actions,
    ];
  }));
}

if (statsButton) {
  statsButton.addEventListener("click", async () => {
    statsModal.showModal();
    try {
      await refreshAdminStatistics();
    } catch (error) {
      statsSummary.textContent = error.message;
    }
  });
}

function couponValidityLabel(value) {
  return { dia: "Um dia", semana: "Uma semana", mes: "Um mês" }[value] || value;
}

async function refreshAdminCoupons() {
  couponsSummary.textContent = "Consultando cupons...";
  renderTable(couponsTable, [], []);
  const data = await request("/admin/cupons");
  const activeCount = data.cupons.filter(coupon => coupon.status === "ativo").length;
  couponsSummary.textContent = `${data.cupons.length} cupom(ns) criado(s), ${activeCount} ativo(s).`;
  renderTable(couponsTable, ["Cupom", "Prazo", "Criado em", "Válido até", "Status", "Usos", "Acessos ativos"], data.cupons.map(coupon => [
    coupon.code,
    couponValidityLabel(coupon.validity_period),
    formatAdminDate(coupon.created_at),
    formatAdminDate(coupon.valid_until),
    coupon.status,
    coupon.total_redemptions,
    coupon.active_redemptions,
  ]));
}

if (couponsButton) {
  couponsButton.addEventListener("click", async () => {
    couponsModal.showModal();
    try {
      await refreshAdminCoupons();
    } catch (error) {
      couponsSummary.textContent = error.message;
    }
  });
}

if (adminCouponForm) {
  adminCouponForm.addEventListener("submit", async event => {
    event.preventDefault();
    adminCouponSubmit.disabled = true;
    couponsSummary.textContent = "Criando cupom...";
    try {
      const data = await request("/admin/cupons", {
        method: "POST",
        headers: { "Content-Type": "application/json" },
        body: JSON.stringify({
          cupom: adminCouponCode.value.trim(),
          validade: adminCouponValidity.value,
        }),
      });
      adminCouponForm.reset();
      await refreshAdminCoupons();
      couponsSummary.textContent = data.mensagem;
    } catch (error) {
      couponsSummary.textContent = error.message;
    } finally {
      adminCouponSubmit.disabled = false;
    }
  });
}

async function refreshAdminDocuments() {
  adminDocumentsSummary.textContent = "Consultando documentos...";
  renderTable(adminDocumentsTable, [], []);
  const data = await request("/admin/base-documental");
  adminDocumentsSummary.textContent = `${data.documentos.length} documento(s) registrado(s).`;
  renderTable(adminDocumentsTable, ["Documento", "Tipo", "Inclusão", "Status", "Ações"], data.documentos.map(documento => {
    const actions = document.createElement("div");
    const action = document.createElement("button");
    action.type = "button";
    action.textContent = documento.is_active ? "Desativar" : "Ativar";
    action.addEventListener("click", async () => {
      const endpoint = documento.is_active ? "/admin/base-documental/desativar" : "/admin/base-documental/ativar";
      await request(endpoint, { method: "POST", headers: { "Content-Type": "application/json" }, body: JSON.stringify({ source: documento.source }) });
      await refreshAdminDocuments();
      await refreshStatus();
    });
    const reindex = document.createElement("button");
    reindex.type = "button";
    reindex.textContent = "Reindexar";
    reindex.addEventListener("click", async () => {
      await request("/admin/base-documental/reindexar", { method: "POST" });
      await refreshAdminDocuments();
      await refreshStatus();
    });
    actions.className = "row-actions";
    actions.append(action, reindex);
    return [documento.filename, documento.file_type.toUpperCase(), formatAdminDate(documento.uploaded_at), documento.is_active ? "ativo" : "inativo", actions];
  }));
}

if (adminDocumentsButton) {
  adminDocumentsButton.addEventListener("click", async () => {
    adminDocumentsModal.showModal();
    try {
      await refreshAdminDocuments();
    } catch (error) {
      adminDocumentsSummary.textContent = error.message;
    }
  });
}

async function loadRagDiagnostics() {
  ragDiagnosticsSummary.textContent = "Consultando execuções do RAG...";
  renderTable(ragDiagnosticsTable, [], []);
  const data = await request("/admin/rag/diagnosticos?limit=100");
  ragDiagnosticsSummary.textContent = `${data.consultas.length} consulta(s) recente(s). O modo detalhado depende de RAG_DEBUG.`;
  renderTable(
    ragDiagnosticsTable,
    ["Data", "Consulta", "Tipo", "Tempo", "Candidatos", "Chunks", "Melhor score", "Status", "Documentos", "Validador", "Ação"],
    data.consultas.map(item => {
      const repeat = document.createElement("button");
      repeat.type = "button";
      repeat.textContent = "Repetir busca";
      repeat.addEventListener("click", async () => {
        repeat.disabled = true;
        ragDiagnosticsSummary.textContent = `Repetindo "${item.query_text}" sem cobrar franquia...`;
        try {
          const result = await request("/admin/rag/repetir", {
            method: "POST",
            headers: { "Content-Type": "application/json" },
            body: JSON.stringify({ pergunta: item.query_text }),
          });
          const counts = result.diagnostico?.candidate_counts || {};
          ragDiagnosticsSummary.textContent = `Busca concluída em ${result.tempo_ms} ms: ${result.fontes.length} fonte(s). Estratégias: ${JSON.stringify(counts)}.`;
        } catch (error) {
          ragDiagnosticsSummary.textContent = error.message;
        } finally {
          repeat.disabled = false;
        }
      });
      return [
        formatAdminDate(item.created_at),
        item.query_text,
        item.query_type,
        `${item.duration_ms} ms`,
        item.candidate_count,
        item.final_count,
        item.best_score == null ? "-" : Number(item.best_score).toFixed(3),
        item.status,
        (item.documents || []).join("; "),
        item.validator?.decision || "-",
        repeat,
      ];
    }),
  );
}

if (ragDiagnosticsButton) {
  ragDiagnosticsButton.addEventListener("click", async () => {
    ragDiagnosticsModal.showModal();
    try {
      await loadRagDiagnostics();
    } catch (error) {
      ragDiagnosticsSummary.textContent = error.message;
    }
  });
}

if (reindexDocumentsButton) {
  reindexDocumentsButton.addEventListener("click", async () => {
    reindexDocumentsButton.disabled = true;
    adminDocumentsSummary.textContent = "Reindexando a base...";
    try {
      await request("/admin/base-documental/reindexar", { method: "POST" });
      await refreshAdminDocuments();
      await refreshStatus();
    } catch (error) {
      adminDocumentsSummary.textContent = error.message;
    } finally {
      reindexDocumentsButton.disabled = false;
    }
  });
}

if (documentUploadForm) {
  documentUploadForm.addEventListener("submit", async event => {
    event.preventDefault();
    const file = documentUpload.files[0];
    if (!file) return;
    const chunkSize = 1024 * 1024;
    let offset = 0;
    adminDocumentsSummary.textContent = "Enviando documento...";
    while (offset < file.size) {
      const chunk = file.slice(offset, offset + chunkSize);
      const complete = offset + chunk.size >= file.size;
      const response = await fetch("/admin/upload-chunk", {
        method: "POST",
        headers: { "x-filename": encodeURIComponent(file.name), "x-offset": String(offset), "x-complete": complete ? "1" : "0" },
        body: chunk,
      });
      if (!response.ok) {
        const data = await response.json().catch(() => ({}));
        adminDocumentsSummary.textContent = data.detail || "Não foi possível enviar o documento.";
        return;
      }
      offset += chunk.size;
      adminDocumentsSummary.textContent = `Enviando documento... ${Math.round((offset / file.size) * 100)}%`;
    }
    documentUploadForm.reset();
    await refreshAdminDocuments();
    await refreshStatus();
  });
}

if (couponForm) {
  couponForm.addEventListener("submit", async event => {
    event.preventDefault();
    couponStatus.textContent = "";
    couponSubmit.disabled = true;
    try {
      const data = await request("/assinatura/cupom", {
        method: "POST",
        headers: { "Content-Type": "application/json" },
        body: JSON.stringify({ cupom: couponInput.value.trim() }),
      });
      couponStatus.textContent = data.mensagem;
      subscriptionSummary.textContent = "Seu acesso agora é completo.";
    } catch (error) {
      couponStatus.textContent = error.message;
    } finally {
      couponSubmit.disabled = false;
    }
  });
}

if (toggleFreeAccessButton) {
  toggleFreeAccessButton.addEventListener("click", async () => {
    toggleFreeAccessButton.disabled = true;
    try {
      const data = await request("/admin/assinatura/controle-gratuito", {
        method: "POST",
        headers: { "Content-Type": "application/json" },
        body: JSON.stringify({ permitir: false }),
      });
      subscriptionSummary.textContent = data.permitir
        ? "A modalidade gratuita está liberada novamente."
        : "A modalidade gratuita foi revista pelo Admin e o acesso passou a ser completo.";
    } catch (error) {
      subscriptionSummary.textContent = error.message;
    } finally {
      toggleFreeAccessButton.disabled = false;
    }
  });
}

function archiveCurrentResult() {
  if (resultPanel.classList.contains("hidden") || !answerElement.textContent.trim()) return;
  const archived = resultPanel.cloneNode(true);
  archived.removeAttribute("id");
  archived.classList.add("archived-result");
  archived.querySelector(".followup-inline")?.remove();
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
  if (!pergunta.length) return showMessage("Digite uma pergunta ou um tema para pesquisar.");

  searchButton.disabled = true;
  questionField.disabled = true;
  isSearching = true;
  searchButton.classList.add("loading");
  followupPanel.classList.add("hidden");
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
    if (retrievalNoticeElement) {
      retrievalNoticeElement.textContent = "";
      retrievalNoticeElement.classList.add("hidden");
    }
    renderReviewStatus("");
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
          if (retrievalNoticeElement && item.mensagem_busca) {
            retrievalNoticeElement.textContent = item.mensagem_busca;
            retrievalNoticeElement.classList.remove("hidden");
          }
        }
        if (item.tipo === "texto") {
          answerElement.textContent += item.texto;
          answerForHistory += item.texto;
          renderReviewStatus(item.status_revisao, item.motivo_revisao);
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
    if (conversationHistory.length && form.parentElement === followupSlot) {
      followupPanel.classList.remove("hidden");
    }
  }
});

refreshStatus();
