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
const languageSelect = document.querySelector("#language-select");
const i18n = window.MagisterIAI18n;
const t = (key, values = {}) => i18n.t(key, values);
let conversationHistory = [];
let currentPresentation = null;
let isSearching = false;
let statusTimer = null;
let lastStatusError = "";

function formatDate(value) {
  if (!value) return t("common.neverUpdated");
  const locale = { "pt-BR": "pt-BR", en: "en", es: "es" }[i18n.language];
  return new Intl.DateTimeFormat(locale, { dateStyle: "short", timeStyle: "short" }).format(new Date(value));
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
  if (!detail) return t("error.unexpected");
  if (typeof detail === "string") {
    if (detail === "Field required") return t("error.required");
    return i18n.language === "pt-BR" ? detail : t("error.unexpected");
  }
  if (Array.isArray(detail)) {
    if (detail.some(item => item?.msg === "Field required")) {
      return t("error.required");
    }
    return detail.map(item => item?.msg || item?.message || JSON.stringify(item)).join(" ");
  }
  const message = detail.msg || detail.message || JSON.stringify(detail);
  return message === "Field required" ? t("error.required") : message;
}

async function request(url, options = {}) {
  const { timeout = 20000, ...fetchOptions } = options;
  const controller = new AbortController();
  const timer = setTimeout(() => controller.abort(), timeout);
  try {
    const response = await fetch(url, {
      credentials: "same-origin",
      ...fetchOptions,
      headers: { "Accept-Language": i18n.language, ...(fetchOptions.headers || {}) },
      signal: controller.signal,
    });
    const data = await response.json().catch(() => ({}));
    if (!response.ok) throw new Error(readableErrorMessage(data.detail));
    return data;
  } catch (error) {
    if (error?.name === "AbortError") {
      throw new Error(t("error.timeout"));
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
        ? t("status.calculating")
        : indexing.segundos_restantes <= 1
          ? t("status.lessSecond")
          : t("status.seconds", { seconds: indexing.segundos_restantes });
      statusElement.querySelector("span:last-child").textContent = t("status.updating");
    } else {
      progressBar.classList.remove("indeterminate");
      progressPanel.classList.add("hidden");
      statusElement.querySelector("span:last-child").textContent =
        t("status.summary", { documents: status.documentos, chunks: status.trechos, date: formatDate(status.ultima_atualizacao) });
      if (indexing.erro && indexing.erro !== lastStatusError) {
        lastStatusError = indexing.erro;
        showMessage(t("status.updateError", { error: indexing.erro }));
      }
    }
    scheduleStatusRefresh(indexing.ativa ? 800 : 20000);
  } catch {
    statusElement.querySelector("span:last-child").textContent = t("status.unavailable");
    scheduleStatusRefresh(10000);
  }
}

function scheduleStatusRefresh(delay) {
  if (statusTimer) clearTimeout(statusTimer);
  statusTimer = setTimeout(refreshStatus, delay);
}

function renderSources(sources) {
  if (!sources.length) {
    sourcesElement.innerHTML = `<p class="empty-sources">${t("result.emptySources")}</p>`;
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
    category.textContent = source.categoria || t("common.document");
    const location = document.createElement("div");
    location.className = "source-location";
    location.textContent = source.local;
    item.append(category, name, location);
    return item;
  }));
}

function reviewLabel(status) {
  return t("result.reviewed");
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
  databaseSummary.textContent = t("database.loading");
  databaseModal.showModal();
  try {
    const data = await request("/documentos");
    databaseSummary.textContent = data.documentos.length
      ? t("database.available", { count: data.documentos.length })
      : t("database.empty");
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
    subscriptionSummary.textContent = t("subscription.loading");
    paymentStatus.textContent = "";
    subscriptionModal.showModal();
    try {
      const data = await request("/assinatura");
      subscriptionSummary.textContent = data.usuario.plano === "completo"
        ? t("subscription.accessFull")
        : t("subscription.accessFree");
      const monthlyPrice = data.pagamento.valor_base || String(data.pagamento.valor || "").replace(/ por mês$/i, "");
      paymentPrice.textContent = monthlyPrice ? t("subscription.price", { value: monthlyPrice }) : "";
      paymentCheckoutButton.disabled = data.usuario.plano === "completo" || !data.pagamento.disponivel;
      if (!data.pagamento.disponivel) {
        paymentStatus.textContent = t("subscription.unavailable");
      } else if (data.pagamento.status === "pending") {
        paymentStatus.textContent = t("subscription.pending");
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
      paymentStatus.textContent = t("subscription.invalidDocument");
      paymentDocument.focus();
      return;
    }
    paymentCheckoutButton.disabled = true;
    paymentStatus.textContent = t("subscription.preparing");
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
    aprovado: t("payment.approved"),
    approved: t("payment.approved"),
    pendente: t("payment.pending"),
    pending: t("payment.pending"),
    falha: t("payment.failure"),
    failure: t("payment.failure"),
    rejected: t("payment.rejected"),
  };
  paymentStatus.textContent = paymentReturnMessages[paymentReturn] || t("payment.received");
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
    changePasswordStatus.textContent = t("password.mismatch");
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
  statsSummary.textContent = t("admin.statsLoading");
  renderTable(statsTable, [], []);
  const data = await request("/admin/estatisticas");
  statsSummary.textContent = t("admin.usersCount", { count: data.usuarios.length });
  renderTable(statsTable, [t("table.name"), t("table.email"), t("table.account"), t("table.subscription"), t("table.origin"), t("table.accesses"), t("table.lastAccess"), t("table.queries"), t("table.scripts"), t("table.slides"), t("table.actions")], data.usuarios.map(user => {
    const actions = document.createElement("div");
    actions.className = "row-actions";
    if (user.can_revoke_coupon) {
      const revoke = document.createElement("button");
      revoke.type = "button";
      revoke.textContent = t("admin.revokeCoupon");
      revoke.addEventListener("click", async () => {
        if (!window.confirm(t("admin.revokeConfirm", { name: user.full_name }))) return;
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
  return { dia: t("admin.oneDay"), semana: t("admin.oneWeek"), mes: t("admin.oneMonth") }[value] || value;
}

async function refreshAdminCoupons() {
  couponsSummary.textContent = t("admin.couponsLoading");
  renderTable(couponsTable, [], []);
  const data = await request("/admin/cupons");
  const activeCount = data.cupons.filter(coupon => coupon.status === "ativo").length;
  couponsSummary.textContent = t("admin.couponsCount", { total: data.cupons.length, active: activeCount });
  renderTable(couponsTable, [t("table.coupon"), t("table.term"), t("table.created"), t("table.validUntil"), t("table.status"), t("table.uses"), t("table.activeAccesses")], data.cupons.map(coupon => [
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
    couponsSummary.textContent = t("admin.creatingCoupon");
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
  adminDocumentsSummary.textContent = t("admin.documentsLoading");
  renderTable(adminDocumentsTable, [], []);
  const data = await request("/admin/base-documental");
  adminDocumentsSummary.textContent = t("admin.documentsCount", { count: data.documentos.length });
  renderTable(adminDocumentsTable, [t("table.document"), t("table.type"), t("table.included"), t("table.status"), t("table.actions")], data.documentos.map(documento => {
    const actions = document.createElement("div");
    const action = document.createElement("button");
    action.type = "button";
    action.textContent = documento.is_active ? t("admin.deactivate") : t("admin.activate");
    action.addEventListener("click", async () => {
      const endpoint = documento.is_active ? "/admin/base-documental/desativar" : "/admin/base-documental/ativar";
      await request(endpoint, { method: "POST", headers: { "Content-Type": "application/json" }, body: JSON.stringify({ source: documento.source }) });
      await refreshAdminDocuments();
      await refreshStatus();
    });
    const reindex = document.createElement("button");
    reindex.type = "button";
    reindex.textContent = t("admin.reindexAction");
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
  ragDiagnosticsSummary.textContent = t("admin.ragLoading");
  renderTable(ragDiagnosticsTable, [], []);
  const data = await request("/admin/rag/diagnosticos?limit=100");
  ragDiagnosticsSummary.textContent = t("admin.ragCount", { count: data.consultas.length });
  renderTable(
    ragDiagnosticsTable,
    [t("table.date"), t("table.query"), t("table.type"), t("table.time"), t("table.candidates"), t("table.chunks"), t("table.bestScore"), t("table.status"), t("table.documents"), t("table.validator"), t("table.action")],
    data.consultas.map(item => {
      const repeat = document.createElement("button");
      repeat.type = "button";
      repeat.textContent = t("admin.repeatSearch");
      repeat.addEventListener("click", async () => {
        repeat.disabled = true;
        ragDiagnosticsSummary.textContent = t("admin.repeating", { query: item.query_text });
        try {
          const result = await request("/admin/rag/repetir", {
            method: "POST",
            headers: { "Content-Type": "application/json" },
            body: JSON.stringify({ pergunta: item.query_text }),
          });
          const counts = result.diagnostico?.candidate_counts || {};
          ragDiagnosticsSummary.textContent = t("admin.searchDone", { time: result.tempo_ms, sources: result.fontes.length, strategies: JSON.stringify(counts) });
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
    adminDocumentsSummary.textContent = t("admin.reindexing");
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
    adminDocumentsSummary.textContent = t("admin.uploading");
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
        adminDocumentsSummary.textContent = i18n.language === "pt-BR" && data.detail ? data.detail : t("admin.uploadError");
        return;
      }
      offset += chunk.size;
      adminDocumentsSummary.textContent = t("admin.uploadingProgress", { progress: Math.round((offset / file.size) * 100) });
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
      couponStatus.textContent = i18n.language === "pt-BR" ? data.mensagem : t("subscription.couponApplied");
      subscriptionSummary.textContent = t("subscription.couponApplied");
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
        ? t("subscription.freeEnabled")
        : t("subscription.freeReviewed");
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
      body: JSON.stringify({ ...currentPresentation, idioma: i18n.language }),
    });
    if (!response.ok) {
      const data = await response.json().catch(() => ({}));
      throw new Error(i18n.language === "pt-BR" && data.detail ? data.detail : t("presentation.error"));
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
    presentationStatus.textContent = t("presentation.ready");
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
  "/criar-roteiro", createScriptButton, t("presentation.scriptProgress"), "roteiro-magisteria.docx"
));
createSlidesButton.addEventListener("click", () => createPresentation(
  "/criar-slides", createSlidesButton, t("presentation.slidesProgress"), "slides-magisteria.pptx"
));

form.addEventListener("submit", async event => {
  event.preventDefault();
  clearMessage();
  const pergunta = questionField.value.trim();
  if (!pergunta.length) return showMessage(t("error.emptyQuestion"));

  searchButton.disabled = true;
  questionField.disabled = true;
  if (languageSelect) languageSelect.disabled = true;
  isSearching = true;
  searchButton.classList.add("loading");
  followupPanel.classList.add("hidden");
  try {
    const response = await fetch("/perguntar-stream", {
      method: "POST",
      headers: { "Content-Type": "application/json" },
      body: JSON.stringify({ pergunta, historico: conversationHistory, idioma: i18n.language }),
    });
    if (!response.ok) {
      const data = await response.json().catch(() => ({}));
      if (response.status === 404) {
        throw new Error(t("error.oldServer"));
      }
      throw new Error(i18n.language === "pt-BR" && data.detail ? data.detail : t("error.search"));
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
          if (abntReferences) answerElement.textContent += `\n\n${t("result.references")}\n${abntReferences}`;
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
      questionField.placeholder = t("search.followupPlaceholder");
      searchButton.innerHTML = `<span class="button-icon">⌕</span> <span>${t("search.continue")}</span>`;
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
    if (languageSelect) languageSelect.disabled = false;
    searchButton.classList.remove("loading");
    if (conversationHistory.length && form.parentElement === followupSlot) {
      followupPanel.classList.remove("hidden");
    }
  }
});

if (languageSelect) {
  languageSelect.addEventListener("change", () => i18n.setLanguage(languageSelect.value));
}

window.addEventListener("magisteria:languagechange", () => {
  if (conversationHistory.length) {
    questionField.placeholder = t("search.followupPlaceholder");
    searchButton.innerHTML = `<span class="button-icon">⌕</span> <span>${t("search.continue")}</span>`;
  }
  refreshStatus();
  if (databaseModal?.open) {
    databaseModal.close();
    databaseButton.click();
  }
  if (subscriptionModal?.open) {
    subscriptionModal.close();
    subscriptionButton.click();
  }
  if (statsModal?.open) refreshAdminStatistics().catch(error => { statsSummary.textContent = error.message; });
  if (couponsModal?.open) refreshAdminCoupons().catch(error => { couponsSummary.textContent = error.message; });
  if (adminDocumentsModal?.open) refreshAdminDocuments().catch(error => { adminDocumentsSummary.textContent = error.message; });
  if (ragDiagnosticsModal?.open) loadRagDiagnostics().catch(error => { ragDiagnosticsSummary.textContent = error.message; });
});

refreshStatus();
