const form = document.getElementById("tariff-form");
const idField = document.getElementById("tariff-id");
const dateField = document.getElementById("valid_from");
const priceField = document.getElementById("price");
const submitBtn = document.getElementById("submit-btn");
const cancelBtn = document.getElementById("cancel-btn");
const errorEl = document.getElementById("form-error");
const tableBody = document.getElementById("tariff-table-body");
const addTariffBtn = document.getElementById("add-tariff-btn");
const tariffModalOverlay = document.getElementById("tariff-modal-overlay");
const tariffModalTitle = document.getElementById("tariff-modal-title");
const tariffModalClose = document.getElementById("tariff-modal-close");

function showForm(title) {
  tariffModalTitle.textContent = title;
  tariffModalOverlay.classList.remove("hidden");
}

function hideForm() {
  tariffModalOverlay.classList.add("hidden");
}

function showError(messages) {
  errorEl.textContent = Array.isArray(messages) ? messages.join(" ") : messages;
  errorEl.classList.remove("hidden");
}

function clearError() {
  errorEl.classList.add("hidden");
  errorEl.textContent = "";
}

function formatPrice(value) {
  return "€ " + Number(value).toFixed(7);
}

function formatDate(iso) {
  const [y, m, d] = iso.split("-");
  return `${d}-${m}-${y}`;
}

function resetForm() {
  idField.value = "";
  form.reset();
  submitBtn.textContent = "Tarief toevoegen";
  clearError();
}

async function loadTariffs() {
  const res = await fetch("api/tariffs");
  const data = await res.json();
  renderTable(data.tariffs, data.active_id);
}

function statusFor(tariff, activeId, allSorted) {
  const today = new Date().toISOString().slice(0, 10);
  if (tariff.id === activeId) return { label: "Actief", cls: "active" };
  if (tariff.valid_from > today) return { label: "Toekomstig", cls: "upcoming" };
  return { label: "Verlopen", cls: "past" };
}

function renderTable(tariffs, activeId) {
  tableBody.innerHTML = "";

  if (!tariffs.length) {
    tableBody.innerHTML = '<tr><td colspan="4" class="empty">Nog geen tarieven ingevoerd.</td></tr>';
    return;
  }

  tariffs.forEach((tariff) => {
    const status = statusFor(tariff, activeId);
    const row = document.createElement("tr");
    if (tariff.id === activeId) row.classList.add("active-row");

    row.innerHTML = `
      <td>${formatDate(tariff.valid_from)}</td>
      <td>${formatPrice(tariff.price)}</td>
      <td><span class="badge ${status.cls}">${status.label}</span></td>
      <td>
        <button class="small edit-btn" data-id="${tariff.id}">Bewerken</button>
        <button class="small danger delete-btn" data-id="${tariff.id}">Verwijderen</button>
      </td>
    `;
    tableBody.appendChild(row);
  });

  tableBody.querySelectorAll(".edit-btn").forEach((btn) => {
    btn.addEventListener("click", () => startEdit(btn.dataset.id));
  });
  tableBody.querySelectorAll(".delete-btn").forEach((btn) => {
    btn.addEventListener("click", () => deleteTariff(btn.dataset.id));
  });

  window.__tariffsCache = tariffs;
}

function startEdit(id) {
  const tariff = (window.__tariffsCache || []).find((t) => t.id === id);
  if (!tariff) return;

  idField.value = tariff.id;
  dateField.value = tariff.valid_from;
  priceField.value = tariff.price;
  submitBtn.textContent = "Tarief bijwerken";
  clearError();
  showForm("Tarief bewerken");
}

async function deleteTariff(id) {
  if (!confirm("Weet je zeker dat je dit tarief wilt verwijderen?")) return;

  const res = await fetch(`api/tariffs/${id}`, { method: "DELETE" });
  if (res.ok) {
    if (idField.value === id) {
      resetForm();
      hideForm();
    }
    loadTariffs();
  } else {
    const data = await res.json().catch(() => ({}));
    showError(data.errors || ["Verwijderen is mislukt."]);
  }
}

form.addEventListener("submit", async (e) => {
  e.preventDefault();
  clearError();

  const payload = {
    valid_from: dateField.value,
    price: priceField.value,
  };

  const id = idField.value;
  const url = id ? `api/tariffs/${id}` : "api/tariffs";
  const method = id ? "PUT" : "POST";

  const res = await fetch(url, {
    method,
    headers: { "Content-Type": "application/json" },
    body: JSON.stringify(payload),
  });

  const data = await res.json().catch(() => ({}));

  if (!res.ok) {
    showError(data.errors || ["Opslaan is mislukt."]);
    return;
  }

  resetForm();
  hideForm();
  loadTariffs();
});

addTariffBtn.addEventListener("click", () => {
  resetForm();
  showForm("Nieuw tarief");
});

cancelBtn.addEventListener("click", () => {
  resetForm();
  hideForm();
});

tariffModalClose.addEventListener("click", () => {
  resetForm();
  hideForm();
});

tariffModalOverlay.addEventListener("pointerdown", (e) => {
  if (e.target === tariffModalOverlay) {
    resetForm();
    hideForm();
  }
});

async function loadSavings() {
  try {
    const res = await fetch("api/savings");
    const data = await res.json();
    const noteEl = document.getElementById("savings-note");

    if (!data.success) {
      document.getElementById("savings-today").textContent = "—";
      document.getElementById("savings-total").textContent = "—";
      noteEl.textContent = data.message || "Nog geen besparingsgegevens beschikbaar.";
      noteEl.classList.remove("hidden");
      return;
    }

    document.getElementById("savings-today").textContent =
      `€ ${data.today_euro.toFixed(2)} (${data.today_kwh.toFixed(2)} kWh)`;
    document.getElementById("savings-total").textContent =
      `€ ${data.total_euro.toFixed(2)} (${data.total_kwh.toFixed(2)} kWh)`;
    noteEl.textContent = `Berekend sinds ${formatDate(data.vanaf)} over ${data.dagen_meegeteld} dag(en) met data.`;
    noteEl.classList.remove("hidden");
  } catch (err) {
    // stille fout: besparingskaart is een extra, geen kernfunctie
  }
}

// --- Rapportages-overzicht (schema + aan/uit) ---
const dailyToggle = document.getElementById("report-daily-toggle");
const monthlyToggle = document.getElementById("report-monthly-toggle");
const dailyInfo = document.getElementById("report-daily-info");
const monthlyInfo = document.getElementById("report-monthly-info");

async function loadReportsOverview() {
  try {
    const res = await fetch("api/settings");
    const s = await res.json();

    dailyToggle.checked = s.reports.daily.enabled;
    dailyInfo.textContent = `Elke dag om ${s.reports.daily.send_time}`;

    monthlyToggle.checked = s.reports.monthly.enabled;
    monthlyInfo.textContent = `Op dag ${s.reports.monthly.send_day} van de maand om ${s.reports.monthly.send_time}`;
  } catch (err) {
    // stille fout: overzicht is een extra, geen kernfunctie
  }
}

async function toggleReport(kind, enabled) {
  await fetch("api/settings", {
    method: "POST",
    headers: { "Content-Type": "application/json" },
    body: JSON.stringify({ reports: { [kind]: { enabled } } }),
  });
}

dailyToggle.addEventListener("change", () => toggleReport("daily", dailyToggle.checked));
monthlyToggle.addEventListener("change", () => toggleReport("monthly", monthlyToggle.checked));

loadTariffs();
loadSavings();
loadReportsOverview();
setInterval(loadSavings, 5 * 60 * 1000);
