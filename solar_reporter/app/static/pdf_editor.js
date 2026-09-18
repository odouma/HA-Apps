// Drag-and-drop editor voor de PDF-rapportlayout (tabblad "PDF-opmaak").
// Beheert twee onafhankelijke sjablonen (dag- en maandrapport) en geeft
// die als geheel terug via PdfEditor.getTemplates() zodat settings.js dit
// kan opslaan onder branding.pdf_template.{daily,monthly}.
const PdfEditor = (() => {
  let templates = { daily: [], monthly: [] };
  let currentKind = "daily";
  let selectedId = null;
  let availableTags = [];
  let tagsLoaded = false;
  let availableImages = [];
  let imagesLoaded = false;
  let previewTimer = null;
  let initialized = false;

  const page = () => document.getElementById("pdf-page");
  const inspector = () => document.getElementById("pdf-inspector");
  const els = () => templates[currentKind];

  function genId() {
    return "el_" + Date.now().toString(36) + Math.random().toString(36).slice(2, 7);
  }

  function clamp(value, min, max) {
    return Math.max(min, Math.min(max, value));
  }

  function findEl(id) {
    return els().find((e) => e.id === id) || null;
  }

  // Standaardkleuren voor de snelkeuze-swatches naast elke kleurenkiezer.
  const PRESET_COLORS = [
    "#000000", "#555555", "#9e9e9e", "#ffffff",
    "#e53935", "#fb8c00", "#fdd835", "#43a047",
    "#03a9f4", "#3949ab", "#8e24aa", "#6d4c41",
  ];

  // Bouwt een kleurenkiezer (native <input type="color">, voor het volledige
  // kleurenspectrum) met daaronder een rij klikbare standaardkleuren, zodat
  // je niet altijd zelf RGB-waarden hoeft in te stellen voor een gangbare
  // kleur. Retourneert het te plaatsen element; `onChange` wordt aangeroepen
  // met de nieuwe hexwaarde, zowel vanuit de kiezer als vanuit een swatch.
  function buildColorControl(value, onChange) {
    const wrap = document.createElement("div");
    wrap.className = "pdf-color-control";

    const input = document.createElement("input");
    input.type = "color";
    input.value = value || "#000000";
    input.addEventListener("input", () => onChange(input.value));
    wrap.appendChild(input);

    const swatches = document.createElement("div");
    swatches.className = "pdf-color-swatches";
    PRESET_COLORS.forEach((hex) => {
      const sw = document.createElement("button");
      sw.type = "button";
      sw.className = "pdf-color-swatch";
      sw.style.background = hex;
      sw.title = hex;
      sw.addEventListener("click", () => {
        input.value = hex;
        onChange(hex);
      });
      swatches.appendChild(sw);
    });
    wrap.appendChild(swatches);

    return wrap;
  }

  // --- Renderen van de pagina ---

  function render() {
    const pageEl = page();
    pageEl.innerHTML = "";
    els().forEach((el) => {
      const div = document.createElement("div");
      div.className = "pdf-el" + (el.id === selectedId ? " selected" : "");
      div.dataset.id = el.id;
      div.dataset.type = el.type;
      div.style.left = el.x + "%";
      div.style.top = el.y + "%";
      div.style.width = el.width + "%";
      div.style.height = el.height + "%";

      const content = document.createElement("div");
      content.className = "pdf-el-content";
      if (el.type === "image") {
        if (el.image_id) {
          const img = document.createElement("img");
          img.className = "pdf-el-image-preview";
          img.src = `api/images/${el.image_id}/file`;
          content.appendChild(img);
        } else {
          content.textContent = "🖼️ Afbeelding";
        }
      } else if (el.type === "chart") {
        const chartLabels = { bar: "📊 Staafdiagram", line: "📈 Lijndiagram", area: "🏔️ Vlakdiagram" };
        content.textContent = chartLabels[el.chart_type || "bar"] || "📊 Grafiek";
      }
      div.appendChild(content);

      const delBtn = document.createElement("button");
      delBtn.type = "button";
      delBtn.className = "pdf-el-delete";
      delBtn.textContent = "×";
      delBtn.title = "Verwijderen";
      delBtn.addEventListener("pointerdown", (e) => e.stopPropagation());
      delBtn.addEventListener("click", (e) => {
        e.stopPropagation();
        removeElement(el.id);
      });
      div.appendChild(delBtn);

      const handle = document.createElement("div");
      handle.className = "pdf-el-handle";
      handle.addEventListener("pointerdown", (e) => startResize(e, el.id));
      div.appendChild(handle);

      div.addEventListener("pointerdown", (e) => startDrag(e, el.id));
      pageEl.appendChild(div);

      updateElementContent(el);
    });
    renderInspector();
    renderLayers();
  }

  // --- Lagenpaneel ---

  function layerLabel(el) {
    const typeNames = { text: "Tekst", image: "Afbeelding", chart: "Grafiek", line: "Lijn", rect: "Rechthoek" };
    const base = typeNames[el.type] || el.type;
    if (el.type === "text") {
      const preview = (el.text || "").replace(/\s+/g, " ").trim().slice(0, 18);
      return base + (preview ? ": " + preview : "");
    }
    return base;
  }

  function moveElement(id, direction) {
    const arr = els();
    const idx = arr.findIndex((e) => e.id === id);
    if (idx === -1) return;
    const targetIdx = idx + direction;
    if (targetIdx < 0 || targetIdx >= arr.length) return;
    const tmp = arr[idx];
    arr[idx] = arr[targetIdx];
    arr[targetIdx] = tmp;
    render();
    markDirty();
  }

  function renderLayers() {
    const container = document.getElementById("pdf-layers");
    if (!container) return;
    container.innerHTML = "";

    const heading = document.createElement("h4");
    heading.textContent = "Volgorde (boven = voorgrond)";
    container.appendChild(heading);

    const arr = els();
    if (!arr.length) {
      const empty = document.createElement("p");
      empty.className = "hint";
      empty.textContent = "Nog geen onderdelen.";
      container.appendChild(empty);
      return;
    }

    for (let i = arr.length - 1; i >= 0; i--) {
      const el = arr[i];
      const row = document.createElement("div");
      row.className = "pdf-layer-item" + (el.id === selectedId ? " selected" : "");
      row.addEventListener("click", (e) => {
        if (e.target.tagName === "BUTTON") return;
        selectElement(el.id);
      });

      const label = document.createElement("span");
      label.className = "pdf-layer-label";
      label.textContent = layerLabel(el);
      row.appendChild(label);

      const upBtn = document.createElement("button");
      upBtn.type = "button";
      upBtn.textContent = "▲";
      upBtn.title = "Naar voren";
      upBtn.disabled = i === arr.length - 1;
      upBtn.addEventListener("click", (e) => {
        e.stopPropagation();
        moveElement(el.id, 1);
      });
      row.appendChild(upBtn);

      const downBtn = document.createElement("button");
      downBtn.type = "button";
      downBtn.textContent = "▼";
      downBtn.title = "Naar achteren";
      downBtn.disabled = i === 0;
      downBtn.addEventListener("click", (e) => {
        e.stopPropagation();
        moveElement(el.id, -1);
      });
      row.appendChild(downBtn);

      container.appendChild(row);
    }
  }

  function selectElement(id) {
    selectedId = id;
    render();
  }

  // --- Slepen ---

  function startDrag(evt, id) {
    if (evt.target.classList.contains("pdf-el-handle")) return;
    evt.preventDefault();
    selectElement(id);
    const el = findEl(id);
    const pageRect = page().getBoundingClientRect();
    const startX = evt.clientX;
    const startY = evt.clientY;
    const origX = el.x;
    const origY = el.y;

    function onMove(e) {
      const dxPct = ((e.clientX - startX) / pageRect.width) * 100;
      const dyPct = ((e.clientY - startY) / pageRect.height) * 100;
      el.x = clamp(origX + dxPct, 0, 100 - el.width);
      el.y = clamp(origY + dyPct, 0, 100 - el.height);
      const div = page().querySelector(`.pdf-el[data-id="${id}"]`);
      if (div) {
        div.style.left = el.x + "%";
        div.style.top = el.y + "%";
      }
    }

    function onUp() {
      document.removeEventListener("pointermove", onMove);
      document.removeEventListener("pointerup", onUp);
      markDirty();
    }

    document.addEventListener("pointermove", onMove);
    document.addEventListener("pointerup", onUp);
  }

  function startResize(evt, id) {
    evt.preventDefault();
    evt.stopPropagation();
    selectElement(id);
    const el = findEl(id);
    const pageRect = page().getBoundingClientRect();
    const startX = evt.clientX;
    const startY = evt.clientY;
    const origW = el.width;
    const origH = el.height;

    function onMove(e) {
      const dwPct = ((e.clientX - startX) / pageRect.width) * 100;
      const dhPct = ((e.clientY - startY) / pageRect.height) * 100;
      el.width = clamp(origW + dwPct, 3, 100 - el.x);
      el.height = clamp(origH + dhPct, 3, 100 - el.y);
      const div = page().querySelector(`.pdf-el[data-id="${id}"]`);
      if (div) {
        div.style.width = el.width + "%";
        div.style.height = el.height + "%";
      }
    }

    function onUp() {
      document.removeEventListener("pointermove", onMove);
      document.removeEventListener("pointerup", onUp);
      markDirty();
    }

    document.addEventListener("pointermove", onMove);
    document.addEventListener("pointerup", onUp);
  }

  // --- Inspector (rechterpaneel) ---

  function renderInspector() {
    const panel = inspector();
    const el = selectedId ? findEl(selectedId) : null;
    if (!el) {
      panel.innerHTML = '<p class="hint">Selecteer een onderdeel om de opmaak aan te passen.</p>';
      return;
    }

    panel.innerHTML = "";

    const heading = document.createElement("h4");
    heading.textContent = {
      text: "Tekstblok",
      image: "Afbeelding",
      chart: "Grafiek",
      line: "Lijn",
      rect: "Rechthoek",
    }[el.type] || "Onderdeel";
    panel.appendChild(heading);

    panel.appendChild(buildPositionFields(el));

    if (el.type === "text") {
      panel.appendChild(buildTextFields(el));
    } else if (el.type === "chart") {
      panel.appendChild(buildChartFields(el));
    } else if (el.type === "line") {
      panel.appendChild(buildLineFields(el));
    } else if (el.type === "rect") {
      panel.appendChild(buildRectFields(el));
    } else if (el.type === "image") {
      panel.appendChild(buildImageFields(el));
    }
  }

  function buildPositionFields(el) {
    const wrap = document.createElement("div");
    wrap.className = "pdf-field-row";

    const specs = [
      ["x", "X (%)"],
      ["y", "Y (%)"],
      ["width", "Breedte (%)"],
      ["height", "Hoogte (%)"],
    ];
    specs.forEach(([key, label]) => {
      const lab = document.createElement("label");
      lab.textContent = label;
      const input = document.createElement("input");
      input.type = "number";
      input.min = key === "width" || key === "height" ? "3" : "0";
      input.max = "100";
      input.step = "1";
      input.value = Math.round(el[key]);
      input.addEventListener("change", () => {
        el[key] = clamp(parseFloat(input.value) || 0, key === "width" || key === "height" ? 3 : 0, 100);
        render();
        markDirty();
      });
      lab.appendChild(input);
      wrap.appendChild(lab);
    });
    return wrap;
  }

  function buildTextFields(el) {
    const frag = document.createDocumentFragment();

    const textLabel = document.createElement("label");
    textLabel.textContent = "Tekst";
    textLabel.style.fontSize = "0.75rem";
    frag.appendChild(textLabel);

    const textarea = document.createElement("textarea");
    textarea.value = el.text || "";
    textarea.addEventListener("input", () => {
      el.text = textarea.value;
      updateElementContent(el);
      markDirty();
    });
    frag.appendChild(textarea);

    const tagWrap = document.createElement("div");
    tagWrap.className = "pdf-tag-list";
    (availableTags.length ? availableTags : []).forEach((tagDef) => {
      const chip = document.createElement("button");
      chip.type = "button";
      chip.className = "pdf-tag-chip";
      chip.textContent = tagDef.label;
      chip.title = "{" + tagDef.tag + "}";
      chip.addEventListener("click", () => {
        const insertion = "{" + tagDef.tag + "}";
        const start = textarea.selectionStart ?? textarea.value.length;
        const end = textarea.selectionEnd ?? textarea.value.length;
        textarea.value = textarea.value.slice(0, start) + insertion + textarea.value.slice(end);
        el.text = textarea.value;
        const pos = start + insertion.length;
        textarea.focus();
        textarea.setSelectionRange(pos, pos);
        updateElementContent(el);
        markDirty();
      });
      tagWrap.appendChild(chip);
    });
    frag.appendChild(tagWrap);

    const row1 = document.createElement("div");
    row1.className = "pdf-field-row";

    const sizeLabel = document.createElement("label");
    sizeLabel.textContent = "Lettergrootte";
    const sizeInput = document.createElement("input");
    sizeInput.type = "number";
    sizeInput.min = "6";
    sizeInput.max = "72";
    sizeInput.value = el.font_size || 12;
    sizeInput.addEventListener("change", () => {
      el.font_size = clamp(parseInt(sizeInput.value, 10) || 12, 6, 72);
      updateElementContent(el);
      markDirty();
    });
    sizeLabel.appendChild(sizeInput);
    row1.appendChild(sizeLabel);

    const familyLabel = document.createElement("label");
    familyLabel.textContent = "Lettertype";
    const familySelect = document.createElement("select");
    [
      ["sans-serif", "Sans-serif"],
      ["serif", "Serif"],
      ["monospace", "Monospace"],
    ].forEach(([value, label]) => {
      const opt = document.createElement("option");
      opt.value = value;
      opt.textContent = label;
      familySelect.appendChild(opt);
    });
    familySelect.value = el.font_family || "sans-serif";
    familySelect.addEventListener("change", () => {
      el.font_family = familySelect.value;
      updateElementContent(el);
      markDirty();
    });
    familyLabel.appendChild(familySelect);
    row1.appendChild(familyLabel);

    const colorLabel = document.createElement("label");
    colorLabel.textContent = "Kleur";
    colorLabel.appendChild(buildColorControl(el.color || "#111111", (hex) => {
      el.color = hex;
      updateElementContent(el);
      markDirty();
    }));
    row1.appendChild(colorLabel);

    frag.appendChild(row1);

    const row2 = document.createElement("div");
    row2.className = "pdf-field-row";

    const styleLabel = document.createElement("label");
    styleLabel.textContent = "Stijl";
    const styleGroup = document.createElement("div");
    styleGroup.className = "pdf-style-group";

    const boldBtn = document.createElement("button");
    boldBtn.type = "button";
    boldBtn.className = "pdf-style-btn" + (el.font_weight === "bold" ? " active" : "");
    boldBtn.textContent = "B";
    boldBtn.title = "Vet";
    boldBtn.style.fontWeight = "bold";
    boldBtn.addEventListener("click", () => {
      el.font_weight = el.font_weight === "bold" ? "normal" : "bold";
      updateElementContent(el);
      renderInspector();
      markDirty();
    });
    styleGroup.appendChild(boldBtn);

    const italicBtn = document.createElement("button");
    italicBtn.type = "button";
    italicBtn.className = "pdf-style-btn" + (el.font_style === "italic" ? " active" : "");
    italicBtn.textContent = "I";
    italicBtn.title = "Cursief";
    italicBtn.style.fontStyle = "italic";
    italicBtn.addEventListener("click", () => {
      el.font_style = el.font_style === "italic" ? "normal" : "italic";
      updateElementContent(el);
      renderInspector();
      markDirty();
    });
    styleGroup.appendChild(italicBtn);

    const underlineBtn = document.createElement("button");
    underlineBtn.type = "button";
    underlineBtn.className = "pdf-style-btn" + (el.underline ? " active" : "");
    underlineBtn.textContent = "U";
    underlineBtn.title = "Onderstrepen";
    underlineBtn.style.textDecoration = "underline";
    underlineBtn.addEventListener("click", () => {
      el.underline = !el.underline;
      updateElementContent(el);
      renderInspector();
      markDirty();
    });
    styleGroup.appendChild(underlineBtn);

    styleLabel.appendChild(styleGroup);
    row2.appendChild(styleLabel);

    const alignLabel = document.createElement("label");
    alignLabel.textContent = "Uitlijning";
    const alignGroup = document.createElement("div");
    alignGroup.className = "pdf-style-group";
    [
      ["left", "⯇"],
      ["center", "≡"],
      ["right", "⯈"],
    ].forEach(([value, symbol]) => {
      const btn = document.createElement("button");
      btn.type = "button";
      btn.className = "pdf-style-btn" + ((el.align || "left") === value ? " active" : "");
      btn.textContent = symbol;
      btn.addEventListener("click", () => {
        el.align = value;
        updateElementContent(el);
        renderInspector();
        markDirty();
      });
      alignGroup.appendChild(btn);
    });
    alignLabel.appendChild(alignGroup);
    row2.appendChild(alignLabel);

    frag.appendChild(row2);
    return frag;
  }

  function buildChartFields(el) {
    const frag = document.createDocumentFragment();
    const chartType = el.chart_type || "bar";

    const row1 = document.createElement("div");
    row1.className = "pdf-field-row";

    const typeLabel = document.createElement("label");
    typeLabel.textContent = "Soort grafiek";
    const typeSelect = document.createElement("select");
    [
      ["bar", "Staafdiagram"],
      ["line", "Lijndiagram"],
      ["area", "Vlakdiagram"],
    ].forEach(([value, label]) => {
      const opt = document.createElement("option");
      opt.value = value;
      opt.textContent = label;
      typeSelect.appendChild(opt);
    });
    typeSelect.value = chartType;
    typeSelect.addEventListener("change", () => {
      el.chart_type = typeSelect.value;
      render();
      markDirty();
    });
    typeLabel.appendChild(typeSelect);
    row1.appendChild(typeLabel);

    const colorLabel = document.createElement("label");
    colorLabel.textContent = chartType === "bar" ? "Kleur van de staven" : "Kleur van de lijn";
    colorLabel.appendChild(buildColorControl(el.chart_color || "#03a9f4", (hex) => {
      el.chart_color = hex;
      markDirty();
    }));
    row1.appendChild(colorLabel);
    frag.appendChild(row1);

    const checkRow = document.createElement("div");
    checkRow.className = "field checkbox-field";

    function addToggle(labelText, key, defaultValue, refresh) {
      const wrap = document.createElement("label");
      const input = document.createElement("input");
      input.type = "checkbox";
      input.checked = el[key] !== undefined ? !!el[key] : defaultValue;
      input.addEventListener("change", () => {
        el[key] = input.checked;
        if (refresh) renderInspector();
        markDirty();
      });
      wrap.appendChild(input);
      wrap.appendChild(document.createTextNode(" " + labelText));
      checkRow.appendChild(wrap);
      return wrap;
    }

    addToggle("Rasterlijnen tonen", "show_grid", true, false);
    addToggle("Waarden boven de grafiek tonen", "show_values", false, true);
    if (chartType !== "bar") {
      addToggle("Punten tonen", "show_markers", true, false);
    }
    frag.appendChild(checkRow);

    if (el.show_values) {
      const row3 = document.createElement("div");
      row3.className = "pdf-field-row";
      const decLabel = document.createElement("label");
      decLabel.textContent = "Aantal decimalen";
      const decInput = document.createElement("input");
      decInput.type = "number";
      decInput.min = "0";
      decInput.max = "4";
      decInput.step = "1";
      decInput.value = el.value_decimals !== undefined ? el.value_decimals : 2;
      decInput.addEventListener("change", () => {
        el.value_decimals = clamp(parseInt(decInput.value, 10), 0, 4);
        if (Number.isNaN(el.value_decimals)) el.value_decimals = 2;
        markDirty();
      });
      decLabel.appendChild(decInput);
      row3.appendChild(decLabel);
      frag.appendChild(row3);
    }

    if (chartType !== "bar") {
      const row4 = document.createElement("div");
      row4.className = "pdf-field-row";
      const widthLabel = document.createElement("label");
      widthLabel.textContent = "Lijndikte";
      const widthInput = document.createElement("input");
      widthInput.type = "number";
      widthInput.min = "0.5";
      widthInput.max = "8";
      widthInput.step = "0.5";
      widthInput.value = el.line_width || 2.5;
      widthInput.addEventListener("change", () => {
        el.line_width = clamp(parseFloat(widthInput.value) || 2.5, 0.5, 8);
        markDirty();
      });
      widthLabel.appendChild(widthInput);
      row4.appendChild(widthLabel);
      frag.appendChild(row4);
    }

    return frag;
  }

  function buildLineFields(el) {
    const frag = document.createDocumentFragment();
    const row1 = document.createElement("div");
    row1.className = "pdf-field-row";

    const orientLabel = document.createElement("label");
    orientLabel.textContent = "Richting";
    const orientSelect = document.createElement("select");
    [["horizontal", "Horizontaal"], ["vertical", "Verticaal"]].forEach(([value, label]) => {
      const opt = document.createElement("option");
      opt.value = value;
      opt.textContent = label;
      orientSelect.appendChild(opt);
    });
    orientSelect.value = el.orientation || "horizontal";
    orientSelect.addEventListener("change", () => {
      el.orientation = orientSelect.value;
      updateElementContent(el);
      markDirty();
    });
    orientLabel.appendChild(orientSelect);
    row1.appendChild(orientLabel);

    const colorLabel = document.createElement("label");
    colorLabel.textContent = "Kleur";
    colorLabel.appendChild(buildColorControl(el.line_color || "#c7ccd1", (hex) => {
      el.line_color = hex;
      updateElementContent(el);
      markDirty();
    }));
    row1.appendChild(colorLabel);
    frag.appendChild(row1);

    const row2 = document.createElement("div");
    row2.className = "pdf-field-row";
    const thicknessLabel = document.createElement("label");
    thicknessLabel.textContent = "Lijndikte (pt)";
    const thicknessInput = document.createElement("input");
    thicknessInput.type = "number";
    thicknessInput.min = "0.5";
    thicknessInput.max = "20";
    thicknessInput.step = "0.5";
    thicknessInput.value = el.line_thickness || 1.5;
    thicknessInput.addEventListener("change", () => {
      el.line_thickness = clamp(parseFloat(thicknessInput.value) || 1.5, 0.5, 20);
      updateElementContent(el);
      markDirty();
    });
    thicknessLabel.appendChild(thicknessInput);
    row2.appendChild(thicknessLabel);
    frag.appendChild(row2);

    return frag;
  }

  function buildRectFields(el) {
    const frag = document.createDocumentFragment();

    const checkRow = document.createElement("div");
    checkRow.className = "field checkbox-field";

    const fillWrap = document.createElement("label");
    const fillCheck = document.createElement("input");
    fillCheck.type = "checkbox";
    fillCheck.checked = !!el.has_fill;
    fillCheck.addEventListener("change", () => {
      el.has_fill = fillCheck.checked;
      updateElementContent(el);
      renderInspector();
      markDirty();
    });
    fillWrap.appendChild(fillCheck);
    fillWrap.appendChild(document.createTextNode(" Vullen"));
    checkRow.appendChild(fillWrap);

    const borderWrap = document.createElement("label");
    const borderCheck = document.createElement("input");
    borderCheck.type = "checkbox";
    borderCheck.checked = el.has_border !== undefined ? el.has_border : true;
    borderCheck.addEventListener("change", () => {
      el.has_border = borderCheck.checked;
      updateElementContent(el);
      renderInspector();
      markDirty();
    });
    borderWrap.appendChild(borderCheck);
    borderWrap.appendChild(document.createTextNode(" Rand"));
    checkRow.appendChild(borderWrap);
    frag.appendChild(checkRow);

    if (el.has_fill) {
      const row1 = document.createElement("div");
      row1.className = "pdf-field-row";
      const fillColorLabel = document.createElement("label");
      fillColorLabel.textContent = "Vulkleur";
      fillColorLabel.appendChild(buildColorControl(el.fill_color || "#03a9f4", (hex) => {
        el.fill_color = hex;
        updateElementContent(el);
        markDirty();
      }));
      row1.appendChild(fillColorLabel);
      frag.appendChild(row1);
    }

    if (el.has_border !== false) {
      const row2 = document.createElement("div");
      row2.className = "pdf-field-row";

      const borderColorLabel = document.createElement("label");
      borderColorLabel.textContent = "Randkleur";
      borderColorLabel.appendChild(buildColorControl(el.border_color || "#111111", (hex) => {
        el.border_color = hex;
        updateElementContent(el);
        markDirty();
      }));
      row2.appendChild(borderColorLabel);

      const borderWidthLabel = document.createElement("label");
      borderWidthLabel.textContent = "Randdikte (pt)";
      const borderWidthInput = document.createElement("input");
      borderWidthInput.type = "number";
      borderWidthInput.min = "0.5";
      borderWidthInput.max = "10";
      borderWidthInput.step = "0.5";
      borderWidthInput.value = el.border_width || 1.5;
      borderWidthInput.addEventListener("change", () => {
        el.border_width = clamp(parseFloat(borderWidthInput.value) || 1.5, 0.5, 10);
        updateElementContent(el);
        markDirty();
      });
      borderWidthLabel.appendChild(borderWidthInput);
      row2.appendChild(borderWidthLabel);

      frag.appendChild(row2);
    }

    return frag;
  }

  function buildImageFields(el) {
    const frag = document.createDocumentFragment();

    if (el.image_id) {
      const preview = document.createElement("img");
      preview.className = "pdf-image-preview";
      preview.src = `api/images/${el.image_id}/file`;
      frag.appendChild(preview);
    } else {
      const note = document.createElement("p");
      note.className = "hint";
      note.textContent = "Nog geen afbeelding gekozen.";
      frag.appendChild(note);
    }

    const fileLabel = document.createElement("label");
    fileLabel.textContent = "Nieuwe afbeelding uploaden";
    const fileInput = document.createElement("input");
    fileInput.type = "file";
    fileInput.accept = "image/*";
    fileInput.addEventListener("change", async () => {
      const file = fileInput.files[0];
      if (!file) return;
      const formData = new FormData();
      formData.append("image", file);
      const res = await fetch("api/images", { method: "POST", body: formData });
      const data = await res.json();
      if (data.success) {
        el.image_id = data.id;
        await loadImages(true);
        render();
        markDirty();
      }
    });
    fileLabel.appendChild(fileInput);
    frag.appendChild(fileLabel);

    if (availableImages.length) {
      const galleryLabel = document.createElement("p");
      galleryLabel.className = "hint";
      galleryLabel.textContent = "Of kies een eerder geüploade afbeelding:";
      frag.appendChild(galleryLabel);

      const gallery = document.createElement("div");
      gallery.className = "pdf-image-gallery";
      availableImages.forEach((img) => {
        const thumbWrap = document.createElement("div");
        thumbWrap.className = "pdf-image-thumb-wrap";

        const thumb = document.createElement("img");
        thumb.src = `api/images/${img.id}/file`;
        thumb.title = img.filename;
        thumb.className = "pdf-image-thumb" + (el.image_id === img.id ? " selected" : "");
        thumb.addEventListener("click", () => {
          el.image_id = img.id;
          render();
          markDirty();
        });
        thumbWrap.appendChild(thumb);

        const delBtn = document.createElement("button");
        delBtn.type = "button";
        delBtn.className = "pdf-image-thumb-delete";
        delBtn.textContent = "×";
        delBtn.title = "Afbeelding verwijderen";
        delBtn.addEventListener("click", async (e) => {
          e.stopPropagation();
          if (!confirm(`Afbeelding "${img.filename}" definitief verwijderen? Dit kan niet ongedaan worden gemaakt.`)) {
            return;
          }
          await fetch(`api/images/${img.id}`, { method: "DELETE" });
          await loadImages(true);
          ["daily", "monthly"].forEach((kind) => {
            templates[kind].forEach((otherEl) => {
              if (otherEl.type === "image" && otherEl.image_id === img.id) {
                otherEl.image_id = null;
              }
            });
          });
          render();
          markDirty();
        });
        thumbWrap.appendChild(delBtn);

        gallery.appendChild(thumbWrap);
      });
      frag.appendChild(gallery);
    }

    if (el.image_id) {
      const clearBtn = document.createElement("button");
      clearBtn.type = "button";
      clearBtn.className = "secondary small";
      clearBtn.textContent = "Geen afbeelding gebruiken";
      clearBtn.addEventListener("click", () => {
        el.image_id = null;
        render();
        markDirty();
      });
      frag.appendChild(clearBtn);
    }

    return frag;
  }

  function updateElementContent(el) {
    const div = page().querySelector(`.pdf-el[data-id="${el.id}"] .pdf-el-content`);
    if (!div) return;
    if (el.type === "text") {
      div.textContent = el.text || "";
      div.style.fontSize = Math.max(6, (el.font_size || 12) * 0.85) + "px";
      div.style.fontFamily = el.font_family || "sans-serif";
      div.style.fontWeight = el.font_weight || "normal";
      div.style.fontStyle = el.font_style || "normal";
      div.style.textDecoration = el.underline ? "underline" : "none";
      div.style.color = el.color || "#111111";
      div.style.textAlign = el.align || "left";
    } else if (el.type === "line") {
      div.style.background = el.line_color || "#c7ccd1";
      const thickness = Math.max(1, el.line_thickness || 1.5);
      if ((el.orientation || "horizontal") === "vertical") {
        div.style.width = thickness + "px";
        div.style.height = "100%";
      } else {
        div.style.width = "100%";
        div.style.height = thickness + "px";
      }
    } else if (el.type === "rect") {
      div.style.width = "100%";
      div.style.height = "100%";
      div.style.boxSizing = "border-box";
      div.style.background = el.has_fill ? (el.fill_color || "#03a9f4") : "transparent";
      div.style.border = el.has_border !== false
        ? Math.max(1, el.border_width || 1.5) + "px solid " + (el.border_color || "#111111")
        : "none";
    }
  }

  // --- Elementen toevoegen/verwijderen ---

  function addElement(type) {
    let el;
    if (type === "text") {
      el = {
        id: genId(), type: "text", x: 10, y: 10, width: 60, height: 8,
        text: "Nieuwe tekst", font_size: 12, font_family: "sans-serif",
        font_weight: "normal", font_style: "normal", underline: false,
        align: "left", color: "#111111",
      };
    } else if (type === "image") {
      el = { id: genId(), type: "image", x: 10, y: 10, width: 25, height: 10, image_id: null };
    } else if (type === "chart") {
      el = {
        id: genId(), type: "chart", x: 10, y: 40, width: 80, height: 40,
        chart_type: "bar", chart_color: "#03a9f4",
        show_grid: true, show_values: false, value_decimals: 2,
        show_markers: true, line_width: 2.5,
      };
    } else if (type === "line") {
      el = {
        id: genId(), type: "line", x: 10, y: 30, width: 60, height: 4,
        orientation: "horizontal", line_color: "#c7ccd1", line_thickness: 1.5,
      };
    } else {
      el = {
        id: genId(), type: "rect", x: 10, y: 30, width: 40, height: 20,
        has_fill: false, fill_color: "#03a9f4",
        has_border: true, border_color: "#111111", border_width: 1.5,
      };
    }
    els().push(el);
    selectElement(el.id);
    markDirty();
  }

  function removeElement(id) {
    templates[currentKind] = els().filter((e) => e.id !== id);
    if (selectedId === id) selectedId = null;
    render();
    markDirty();
  }

  // --- Voorbeeldweergave ---

  function markDirty() {
    if (window.markSettingsDirty) window.markSettingsDirty();
    schedulePreview();
  }

  function schedulePreview() {
    if (previewTimer) clearTimeout(previewTimer);
    previewTimer = setTimeout(refreshPreview, 700);
  }

  async function refreshPreview() {
    const status = document.getElementById("pdf-preview-status");
    if (!status) return;
    status.textContent = "Voorbeeld bijwerken...";
    try {
      const res = await fetch(`api/reports/preview/${currentKind}`, {
        method: "POST",
        headers: { "Content-Type": "application/json" },
        body: JSON.stringify({ elements: els() }),
      });
      if (!res.ok) throw new Error("HTTP " + res.status);
      const blob = await res.blob();
      const url = URL.createObjectURL(blob);
      const frame = document.getElementById("pdf-preview-frame");
      const oldUrl = frame.dataset.blobUrl;
      frame.src = url;
      frame.dataset.blobUrl = url;
      if (oldUrl) URL.revokeObjectURL(oldUrl);
      status.textContent = "";
    } catch (err) {
      status.textContent = "Voorbeeld laden mislukt: " + err;
    }
  }

  async function loadTags() {
    if (tagsLoaded) return;
    try {
      const res = await fetch("api/reports/tags");
      availableTags = await res.json();
      tagsLoaded = true;
    } catch (err) {
      availableTags = [];
    }
  }

  async function loadImages(force) {
    if (imagesLoaded && !force) return;
    try {
      const res = await fetch("api/images");
      availableImages = await res.json();
      imagesLoaded = true;
    } catch (err) {
      availableImages = [];
    }
  }

  // --- Publieke API ---

  const REPORT_LABELS = { daily: "Dagrapport", monthly: "Maandrapport" };

  function updateCopyButtonLabel() {
    const other = currentKind === "daily" ? "monthly" : "daily";
    const btn = document.getElementById("pdf-copy-other");
    if (btn) btn.textContent = `Kopieer opmaak van ${other === "daily" ? "dagelijks" : "maandelijks"} rapport`;
  }

  async function init(pdfTemplate) {
    templates = {
      daily: JSON.parse(JSON.stringify((pdfTemplate.daily && pdfTemplate.daily.elements) || [])),
      monthly: JSON.parse(JSON.stringify((pdfTemplate.monthly && pdfTemplate.monthly.elements) || [])),
    };
    selectedId = null;
    await loadTags();
    await loadImages();
    render();

    if (!initialized) {
      initialized = true;
      document.getElementById("pdf-add-text").addEventListener("click", () => addElement("text"));
      document.getElementById("pdf-add-image").addEventListener("click", () => addElement("image"));
      document.getElementById("pdf-add-chart").addEventListener("click", () => addElement("chart"));
      document.getElementById("pdf-add-line").addEventListener("click", () => addElement("line"));
      document.getElementById("pdf-add-rect").addEventListener("click", () => addElement("rect"));

      document.getElementById("pdf-modal-close").addEventListener("click", closeEditor);
      document.getElementById("pdf-modal-overlay").addEventListener("pointerdown", (e) => {
        if (e.target.id === "pdf-modal-overlay") closeEditor();
      });

      document.getElementById("pdf-copy-other").addEventListener("click", () => {
        const other = currentKind === "daily" ? "monthly" : "daily";
        const otherLabel = other === "daily" ? "dagrapport" : "maandrapport";
        if (!confirm(`Opmaak van het ${otherLabel} overnemen? De huidige opmaak van dit rapport gaat verloren.`)) {
          return;
        }
        templates[currentKind] = JSON.parse(JSON.stringify(templates[other]));
        selectedId = null;
        render();
        markDirty();
      });

      document.getElementById("pdf-reset").addEventListener("click", async () => {
        if (!confirm("Standaardlayout terugzetten voor dit rapport? Eigen aanpassingen gaan verloren.")) {
          return;
        }
        const res = await fetch(`api/settings/pdf-template/default?kind=${currentKind}`);
        const template = await res.json();
        templates[currentKind] = template.elements;
        selectedId = null;
        render();
        markDirty();
      });

      page().addEventListener("pointerdown", (e) => {
        if (e.target === page()) selectElement(null);
      });

      document.querySelectorAll(".pdf-accordion-toggle").forEach((btn) => {
        btn.addEventListener("click", () => {
          const body = document.getElementById(btn.dataset.target);
          const arrow = btn.querySelector(".pdf-accordion-arrow");
          const collapsed = body.classList.toggle("collapsed");
          arrow.textContent = collapsed ? "▸" : "▾";
        });
      });
    }
  }

  function openEditor(kind) {
    currentKind = kind === "monthly" ? "monthly" : "daily";
    selectedId = null;
    document.getElementById("pdf-modal-title").textContent = `PDF-opmaak — ${REPORT_LABELS[currentKind]}`;
    updateCopyButtonLabel();
    document.getElementById("pdf-modal-overlay").classList.remove("hidden");
    render();
    refreshPreview();
  }

  function closeEditor() {
    document.getElementById("pdf-modal-overlay").classList.add("hidden");
  }

  function getTemplates() {
    return {
      daily: { elements: templates.daily },
      monthly: { elements: templates.monthly },
    };
  }

  return { init, openEditor, getTemplates };
})();

window.PdfEditor = PdfEditor;
