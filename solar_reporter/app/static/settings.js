// --- Niet-opgeslagen wijzigingen bijhouden ---
let isDirty = false;
function markSettingsDirty() {
  isDirty = true;
}
window.markSettingsDirty = markSettingsDirty;

// Vangt alle gewone formuliervelden (tekst, textarea, select, checkbox) af.
// Klik-only interacties (chips, tags, entity-picker, PDF-editor) roepen
// markSettingsDirty() zelf expliciet aan, want die vuren geen input/change.
document.body.addEventListener("input", markSettingsDirty);
document.body.addEventListener("change", markSettingsDirty);

document.querySelector(".back-link").addEventListener("click", (e) => {
  if (isDirty && !confirm("Je hebt niet-opgeslagen wijzigingen. Weet je zeker dat je wilt teruggaan zonder op te slaan?")) {
    e.preventDefault();
  }
});

window.addEventListener("beforeunload", (e) => {
  if (!isDirty) return;
  e.preventDefault();
  e.returnValue = "";
});

// --- Tabbladen ---
document.querySelectorAll(".tab-btn").forEach((btn) => {
  btn.addEventListener("click", () => {
    document.querySelectorAll(".tab-btn").forEach((b) => b.classList.remove("active"));
    document.querySelectorAll(".tab-panel").forEach((p) => p.classList.remove("active"));
    btn.classList.add("active");
    document.getElementById(`tab-${btn.dataset.tab}`).classList.add("active");
  });
});

// --- Ontvangers-chips (eenvoudige e-mail-lijst per rapport) ---
function setupChipInput(wrapId, inputId, initial) {
  const wrap = document.getElementById(wrapId);
  const input = document.getElementById(inputId);
  let emails = [...initial];

  function render() {
    wrap.querySelectorAll(".chip").forEach((c) => c.remove());
    emails.forEach((email, idx) => {
      const chip = document.createElement("span");
      chip.className = "chip";
      chip.textContent = email;
      const remove = document.createElement("button");
      remove.type = "button";
      remove.textContent = "×";
      remove.addEventListener("click", () => {
        emails.splice(idx, 1);
        render();
        markSettingsDirty();
      });
      chip.appendChild(remove);
      wrap.insertBefore(chip, input);
    });
  }

  input.addEventListener("keydown", (e) => {
    if (e.key === "Enter" || e.key === ",") {
      e.preventDefault();
      const value = input.value.trim().replace(/,$/, "");
      if (value && !emails.includes(value)) {
        emails.push(value);
        render();
        markSettingsDirty();
      }
      input.value = "";
    }
  });

  render();
  return { get: () => emails };
}

// --- Zoekbare entiteiten-dropdown (Entiteiten-tab) ---
function setupEntityPicker(inputId, listId, unit) {
  const input = document.getElementById(inputId);
  const list = document.getElementById(listId);
  let entities = [];
  let loaded = false;

  async function ensureLoaded() {
    if (loaded) return;
    loaded = true;
    try {
      const res = await fetch(`api/ha/entities?unit=${encodeURIComponent(unit)}`);
      entities = await res.json();
    } catch (err) {
      entities = [];
    }
  }

  function render() {
    const q = input.value.trim().toLowerCase();
    const matches = !q
      ? entities
      : entities.filter(
          (e) => e.entity_id.toLowerCase().includes(q) || e.friendly_name.toLowerCase().includes(q)
        );

    if (!matches.length) {
      list.innerHTML = '<div class="entity-picker-empty">Geen entiteiten met eenheid "' + unit + '" gevonden.</div>';
    } else {
      list.innerHTML = matches
        .slice(0, 50)
        .map(
          (e) =>
            `<div class="entity-picker-item" data-id="${e.entity_id}"><strong>${e.friendly_name}</strong><span>${e.entity_id}</span></div>`
        )
        .join("");
      list.querySelectorAll(".entity-picker-item").forEach((item) => {
        item.addEventListener("mousedown", (ev) => {
          ev.preventDefault();
          input.value = item.dataset.id;
          list.classList.add("hidden");
          markSettingsDirty();
        });
      });
    }
    list.classList.remove("hidden");
  }

  input.addEventListener("focus", async () => {
    await ensureLoaded();
    render();
  });
  input.addEventListener("input", async () => {
    await ensureLoaded();
    render();
  });
  input.addEventListener("blur", () => {
    setTimeout(() => list.classList.add("hidden"), 100);
  });
}

setupEntityPicker("entity_power", "entity_power_list", "W");
setupEntityPicker("entity_energy_today", "entity_energy_today_list", "kWh");

// --- Klikbare tags voor mail-onderwerp/tekst ---
const MAIL_TAGS = {
  daily: [
    { tag: "datum", label: "Datum" },
    { tag: "opbrengst_kwh", label: "Opbrengst (kWh)" },
    { tag: "besparing_euro", label: "Besparing (€)" },
  ],
  monthly: [
    { tag: "maand", label: "Maand" },
    { tag: "opbrengst_kwh", label: "Opbrengst (kWh)" },
    { tag: "besparing_euro", label: "Besparing (€)" },
  ],
};

function setupTagChips(fieldId, wrapId, tags) {
  const field = document.getElementById(fieldId);
  const wrap = document.getElementById(wrapId);
  wrap.innerHTML = "";
  tags.forEach((tagDef) => {
    const chip = document.createElement("button");
    chip.type = "button";
    chip.className = "pdf-tag-chip";
    chip.textContent = tagDef.label;
    chip.title = "{" + tagDef.tag + "}";
    chip.addEventListener("click", () => {
      const insertion = "{" + tagDef.tag + "}";
      const start = field.selectionStart ?? field.value.length;
      const end = field.selectionEnd ?? field.value.length;
      field.value = field.value.slice(0, start) + insertion + field.value.slice(end);
      const pos = start + insertion.length;
      field.focus();
      field.setSelectionRange(pos, pos);
      markSettingsDirty();
    });
    wrap.appendChild(chip);
  });
}

setupTagChips("daily_subject", "daily_subject_tags", MAIL_TAGS.daily);
setupTagChips("daily_body", "daily_body_tags", MAIL_TAGS.daily);
setupTagChips("monthly_subject", "monthly_subject_tags", MAIL_TAGS.monthly);
setupTagChips("monthly_body", "monthly_body_tags", MAIL_TAGS.monthly);

let dailyChips, monthlyChips;

async function loadSettings() {
  const res = await fetch("api/settings");
  const s = await res.json();

  document.getElementById("refresh_interval").value = s.refresh_interval_seconds;

  document.getElementById("entity_power").value = s.entities.power;
  document.getElementById("entity_energy_today").value = s.entities.energy_today;

  document.getElementById("mqtt_enabled").checked = s.mqtt.enabled;
  document.getElementById("mqtt_host").value = s.mqtt.host;
  document.getElementById("mqtt_port").value = s.mqtt.port;
  document.getElementById("mqtt_username").value = s.mqtt.username;
  document.getElementById("mqtt_password").value = s.mqtt.password;

  document.getElementById("smtp_host").value = s.email.smtp_host;
  document.getElementById("smtp_port").value = s.email.smtp_port;
  document.getElementById("smtp_encryption").value = s.email.encryption;
  document.getElementById("smtp_username").value = s.email.username;
  document.getElementById("smtp_password").value = s.email.password;
  document.getElementById("smtp_from").value = s.email.from_address;

  document.getElementById("daily_enabled").checked = s.reports.daily.enabled;
  document.getElementById("daily_time").value = s.reports.daily.send_time;
  dailyChips = setupChipInput("daily_recipients_wrap", "daily_recipients_input", s.reports.daily.recipients);

  document.getElementById("monthly_enabled").checked = s.reports.monthly.enabled;
  document.getElementById("monthly_day").value = s.reports.monthly.send_day;
  document.getElementById("monthly_time").value = s.reports.monthly.send_time;
  monthlyChips = setupChipInput("monthly_recipients_wrap", "monthly_recipients_input", s.reports.monthly.recipients);

  document.getElementById("daily_subject").value = s.branding.daily_subject;
  document.getElementById("daily_body").value = s.branding.daily_body;
  document.getElementById("monthly_subject").value = s.branding.monthly_subject;
  document.getElementById("monthly_body").value = s.branding.monthly_body;

  if (window.PdfEditor) {
    PdfEditor.init(s.branding.pdf_template);
  }
}

function collectSettings() {
  return {
    refresh_interval_seconds: parseInt(document.getElementById("refresh_interval").value, 10) || 10,
    entities: {
      power: document.getElementById("entity_power").value.trim(),
      energy_today: document.getElementById("entity_energy_today").value.trim(),
    },
    mqtt: {
      enabled: document.getElementById("mqtt_enabled").checked,
      host: document.getElementById("mqtt_host").value.trim(),
      port: parseInt(document.getElementById("mqtt_port").value, 10) || 1883,
      username: document.getElementById("mqtt_username").value,
      password: document.getElementById("mqtt_password").value,
    },
    email: {
      smtp_host: document.getElementById("smtp_host").value.trim(),
      smtp_port: parseInt(document.getElementById("smtp_port").value, 10) || 587,
      encryption: document.getElementById("smtp_encryption").value,
      username: document.getElementById("smtp_username").value,
      password: document.getElementById("smtp_password").value,
      from_address: document.getElementById("smtp_from").value.trim(),
    },
    reports: {
      daily: {
        enabled: document.getElementById("daily_enabled").checked,
        send_time: document.getElementById("daily_time").value || "22:00",
        recipients: dailyChips ? dailyChips.get() : [],
      },
      monthly: {
        enabled: document.getElementById("monthly_enabled").checked,
        send_day: parseInt(document.getElementById("monthly_day").value, 10) || 1,
        send_time: document.getElementById("monthly_time").value || "08:00",
        recipients: monthlyChips ? monthlyChips.get() : [],
      },
    },
    branding: {
      daily_subject: document.getElementById("daily_subject").value.trim(),
      daily_body: document.getElementById("daily_body").value,
      monthly_subject: document.getElementById("monthly_subject").value.trim(),
      monthly_body: document.getElementById("monthly_body").value,
      pdf_template: window.PdfEditor ? PdfEditor.getTemplates() : { daily: { elements: [] }, monthly: { elements: [] } },
    },
  };
}

document.getElementById("save-btn").addEventListener("click", async () => {
  const status = document.getElementById("save-status");
  status.textContent = "Opslaan...";
  try {
    const res = await fetch("api/settings", {
      method: "POST",
      headers: { "Content-Type": "application/json" },
      body: JSON.stringify(collectSettings()),
    });
    if (res.ok) {
      status.textContent = "Opgeslagen.";
      isDirty = false;
    } else {
      status.textContent = "Opslaan mislukt.";
    }
  } catch (err) {
    status.textContent = "Opslaan mislukt: " + err;
  }
  setTimeout(() => (status.textContent = ""), 4000);
});

async function testSend(kind, btnId, resultId) {
  const btn = document.getElementById(btnId);
  const resultEl = document.getElementById(resultId);
  btn.disabled = true;
  resultEl.classList.remove("hidden");
  resultEl.textContent = "Bezig met versturen...";
  try {
    const res = await fetch(`api/reports/test-send/${kind}`, { method: "POST" });
    const data = await res.json();
    resultEl.textContent = data.message;
  } catch (err) {
    resultEl.textContent = "Mislukt: " + err;
  } finally {
    btn.disabled = false;
  }
}

document.getElementById("test-daily-btn").addEventListener("click", () =>
  testSend("daily", "test-daily-btn", "test-daily-result")
);
document.getElementById("test-monthly-btn").addEventListener("click", () =>
  testSend("monthly", "test-monthly-btn", "test-monthly-result")
);

document.getElementById("edit-pdf-daily-btn").addEventListener("click", () => {
  if (window.PdfEditor) PdfEditor.openEditor("daily");
});
document.getElementById("edit-pdf-monthly-btn").addEventListener("click", () => {
  if (window.PdfEditor) PdfEditor.openEditor("monthly");
});

loadSettings();
