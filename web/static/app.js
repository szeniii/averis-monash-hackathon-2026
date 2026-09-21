"use strict";

const $ = (sel) => document.querySelector(sel);
const el = (tag, cls, text) => {
  const n = document.createElement(tag);
  if (cls) n.className = cls;
  if (text !== undefined) n.textContent = text;
  return n;
};

const FIELD_LABEL = {
  shipper: "Shipper",
  consignee: "Consignee",
  notify_party: "Notify party",
  port_of_loading: "Port of loading",
  port_of_discharge: "Port of discharge",
  container_count: "Container count",
  gross_weight_kg: "Gross weight",
};

const CATEGORY_LABEL = {
  BL_COMPARISON: "Comparison",
  SI_REQUEST: "SI request",
  INVOICE_QUERY: "Invoice",
  GENERAL: "General",
  SPAM: "Spam",
};

const CATEGORY_NOTE = {
  SI_REQUEST: "A request to prepare a Shipping Instruction. No documents to check.",
  INVOICE_QUERY: "A billing question. No documents to check.",
  GENERAL: "Operational traffic needing no document action.",
  SPAM: "Unsolicited mail. Dropped before any document work.",
};

const REASON_TEXT = {
  wrong_doc_type: "One attachment is not the document it claims to be.",
  missing_attachment: "A document needed for the comparison is not here.",
  unreadable: "A document could not be read well enough to judge it.",
  missing_value: "A value is blank in one document. Blank is uncertainty, not a discrepancy.",
};

let inboxCache = [];
let activeCategory = "ALL";

/* ---------------------------------------------------------------- fetch */

async function api(path, options) {
  const res = await fetch(path, options);
  const body = await res.json().catch(() => ({}));
  if (!res.ok) throw new Error(body.detail || `request failed (${res.status})`);
  return body;
}

function showError(message) {
  const box = $("#report");
  box.replaceChildren();
  box.append(el("p", "err", message));
}

/* ----------------------------------------------------------------- tabs */

document.querySelectorAll(".tab").forEach((tab) => {
  tab.addEventListener("click", () => {
    document.querySelectorAll(".tab").forEach((t) => t.classList.remove("is-on"));
    document.querySelectorAll(".tabpane").forEach((p) => p.classList.remove("is-on"));
    tab.classList.add("is-on");
    document.querySelector(`[data-pane="${tab.dataset.tab}"]`).classList.add("is-on");
  });
});

/* ---------------------------------------------------------------- inbox */

function categoryPill(category, confidence) {
  const pill = el("span", `pill cat-${category}`,
    CATEGORY_LABEL[category] || category);
  if (confidence !== undefined && confidence !== null) {
    pill.title = `confidence ${Math.round(confidence * 100)}%`;
  }
  return pill;
}

async function loadSummary() {
  let data;
  try {
    data = await api("/api/summary");
  } catch {
    return;
  }
  $("#source-badge").textContent =
    `inbox: ${data.emails} ${data.is_real_dataset ? "emails" : "demo emails"}`;

  const strip = $("#cat-strip");
  strip.replaceChildren();

  const all = el("button", "cat-chip" + (activeCategory === "ALL" ? " is-on" : ""));
  all.append(el("strong", null, String(data.emails)), el("span", null, "All"));
  all.addEventListener("click", () => { activeCategory = "ALL"; loadInbox(); });
  strip.append(all);

  Object.entries(data.by_category).forEach(([cat, count]) => {
    if (!count) return;
    const chip = el("button",
      `cat-chip cat-${cat}` + (activeCategory === cat ? " is-on" : ""));
    chip.append(el("strong", null, String(count)),
      el("span", null, CATEGORY_LABEL[cat] || cat));
    chip.addEventListener("click", () => { activeCategory = cat; loadInbox(); });
    strip.append(chip);
  });
}

async function loadInbox() {
  const q = $("#inbox-q").value.trim();
  let data;
  try {
    data = await api(`/api/inbox?category=${encodeURIComponent(activeCategory)}` +
      (q ? `&q=${encodeURIComponent(q)}` : ""));
  } catch (err) {
    $("#inbox-count").textContent = err.message;
    return;
  }
  inboxCache = data.emails;

  const shown = Math.min(data.total, 250);
  $("#inbox-count").textContent =
    `${data.total} email${data.total === 1 ? "" : "s"}` +
    (data.total > shown ? `, showing the first ${shown}` : "") +
    ` · ${data.source}`;

  const list = $("#inbox-list");
  list.replaceChildren();
  if (!data.total) {
    list.append(el("p", "empty", "Nothing matches."));
  }

  data.emails.slice(0, shown).forEach((row) => {
    const card = el("button", "mail");
    const head = el("div", "mail-head");
    head.append(categoryPill(row.category, row.confidence));
    if (row.attachment_count) {
      head.append(el("span", "clip", `${row.attachment_count} attached`));
    }
    head.append(el("span", "mail-id", row.email_id));

    card.append(head);
    card.append(el("div", "mail-subject", row.subject || "(no subject)"));
    card.append(el("div", "mail-from", row.from));

    card.addEventListener("click", () => runAndRender(
      api(`/api/inbox/${row.email_id}/run`, { method: "POST" }), card));
    list.append(card);
  });

  loadSummary();
}

let searchTimer = null;
$("#inbox-q").addEventListener("input", () => {
  clearTimeout(searchTimer);
  searchTimer = setTimeout(loadInbox, 220);
});

/* ------------------------------------------------------------- classify */

$("#run-classify").addEventListener("click", async (e) => {
  const button = e.currentTarget;
  const subject = $("#cls-subject").value;
  const body = $("#cls-body").value;
  if (!subject.trim() && !body.trim()) {
    return;
  }
  button.disabled = true;
  const out = $("#classify-out");
  try {
    const data = await api("/api/classify", {
      method: "POST",
      headers: { "Content-Type": "application/json" },
      body: JSON.stringify({ subject, body }),
    });
    out.replaceChildren();
    const card = el("div", "cls-card");
    const top = el("div", "cls-top");
    top.append(categoryPill(data.category, data.confidence));
    top.append(el("span", "cls-conf", `${Math.round(data.confidence * 100)}% confident`));
    card.append(top);
    card.append(el("p", "cls-note",
      data.goes_to_comparison
        ? "Goes on to the document check."
        : (CATEGORY_NOTE[data.category] || "No document check needed.")));
    card.append(el("p", "cls-meta", `decided by ${data.decided_by}`));
    out.append(card);
  } catch (err) {
    out.replaceChildren(el("p", "err", err.message));
  } finally {
    button.disabled = false;
  }
});

/* ---------------------------------------------------------------- report */

function emailHeader(email, category, confidence, decidedBy) {
  const box = el("div", "mailhead");
  const line = el("div", "mailhead-top");
  line.append(el("span", "mail-id", email.email_id));
  if (category) line.append(categoryPill(category, confidence));
  if (decidedBy) line.append(el("span", "cls-meta", `stage 1 by ${decidedBy}`));
  box.append(line);
  box.append(el("div", "mailhead-subject", email.subject || "(no subject)"));
  const meta = [email.from];
  if (email.attachments && email.attachments.length) {
    meta.push(email.attachments.join(", "));
  }
  box.append(el("div", "mailhead-meta", meta.filter(Boolean).join(" · ")));
  return box;
}

function verdictBlock(data) {
  const box = el("div", "verdict");
  const head = el("h3");
  const line = el("p");

  const notComparison = data.category && data.category !== "BL_COMPARISON";

  if (notComparison) {
    box.classList.add("v-info");
    head.textContent = `Classified as ${CATEGORY_LABEL[data.category] || data.category}`;
    line.textContent = CATEGORY_NOTE[data.category] || "No document check needed.";
  } else if (data.status === "OK") {
    box.classList.add("v-ok");
    head.textContent = "No mismatch detected";
    line.textContent = "All seven fields agree once the values are normalised.";
  } else if (data.status === "MISMATCH") {
    box.classList.add("v-bad");
    const n = data.defect_fields.length;
    head.textContent = `${n} field${n === 1 ? "" : "s"} do not match`;
    line.append(document.createTextNode("Flagged: "));
    data.defect_fields.forEach((f, i) => {
      if (i) line.append(document.createTextNode(", "));
      line.append(el("code", null, FIELD_LABEL[f] || f));
    });
  } else {
    box.classList.add("v-warn");
    head.textContent = "Sent for human review";
    line.textContent = REASON_TEXT[data.review_reason] || "The system would not decide this alone.";
  }

  box.append(head, line);
  if (data.escalation_detail) box.append(el("p", "sub", data.escalation_detail));
  if (data.human_reviewed) box.append(el("p", "sub", "Reviewed by a person."));
  return box;
}

function valueCell(raw, normalized, label) {
  const td = el("td");
  if (raw === null || raw === undefined || raw === "") {
    td.append(el("span", "val none", "not provided"));
    return td;
  }
  td.append(el("span", "val", raw));
  const note = normalized && normalized !== raw
    ? `${label || "unlabelled"} → ${normalized}` : (label || "");
  if (note) td.append(el("span", "lab", note));
  return td;
}

function fieldTable(fields) {
  const table = el("table");
  const thead = el("thead");
  const hr = el("tr");
  ["Field", "Shipping Instruction", "Draft Bill of Lading", "Verdict"]
    .forEach((h) => hr.append(el("th", null, h)));
  thead.append(hr);

  const tbody = el("tbody");
  fields.forEach((f) => {
    const tr = el("tr");
    if (f.status === "mismatch") tr.classList.add("row-bad");
    else if (f.status !== "match") tr.classList.add("row-soft");

    tr.append(el("td", "fieldname", FIELD_LABEL[f.field] || f.field));
    tr.append(valueCell(f.si_raw, f.si_normalized, f.si_label));
    tr.append(valueCell(f.bl_raw, f.bl_normalized, f.bl_label));

    const verdict = el("td");
    verdict.append(el("span", `pill p-${f.status}`, f.status));
    if (f.reason) verdict.append(el("span", "lab", f.reason));
    tr.append(verdict);
    tbody.append(tr);
  });

  table.append(thead, tbody);
  const wrap = el("div", "tablewrap");
  wrap.append(table);
  return wrap;
}

function docNote(documents) {
  const box = el("div", "docnote");
  documents.forEach((d) => {
    const bits = [`${d.role}: ${d.path || "not supplied"}`];
    if (d.read_method) bits.push(`read as ${d.read_method}`);
    if (d.doc_type_detected) bits.push(d.doc_type_detected.toLowerCase().replace(/_/g, " "));
    if (!d.read_ok && d.read_error) bits.push(d.read_error);
    box.append(el("span", null, bits.join(" · ")));
  });
  return box;
}

function reviewBlock(data) {
  const box = el("div", "review");
  box.append(el("h4", null, "Human review"));
  box.append(el("p", "hint",
    "Supply the value the system could not read, and the case is decided again from the corrected evidence."));

  const row = el("div", "review-row");

  const fieldWrap = el("div");
  const fieldLabel = el("label", null, "Field");
  fieldLabel.htmlFor = "rv-field";
  const select = el("select");
  select.id = "rv-field";
  (data.fields.length ? data.fields
    : Object.keys(FIELD_LABEL).map((f) => ({ field: f, status: "missing" })))
    .forEach((f) => {
      const opt = el("option", null, `${FIELD_LABEL[f.field] || f.field} (${f.status})`);
      opt.value = f.field;
      if (f.status !== "match") opt.selected = true;
      select.append(opt);
    });
  fieldWrap.append(fieldLabel, select);

  const siWrap = el("div");
  const siLabel = el("label", null, "SI value");
  siLabel.htmlFor = "rv-si";
  const siInput = el("input");
  siInput.type = "text";
  siInput.id = "rv-si";
  siInput.placeholder = "leave blank to keep";
  siWrap.append(siLabel, siInput);

  const blWrap = el("div");
  const blLabel = el("label", null, "BL value");
  blLabel.htmlFor = "rv-bl";
  const blInput = el("input");
  blInput.type = "text";
  blInput.id = "rv-bl";
  blInput.placeholder = "leave blank to keep";
  blWrap.append(blLabel, blInput);

  row.append(fieldWrap, siWrap, blWrap);
  box.append(row);

  const actions = el("div", "actions");

  const save = el("button", "primary", "Apply correction");
  save.addEventListener("click", async () => {
    save.disabled = true;
    try {
      render(await api(`/api/cases/${data.case_id}/resolve`, {
        method: "POST",
        headers: { "Content-Type": "application/json" },
        body: JSON.stringify({
          field: select.value,
          si_value: siInput.value.trim() || null,
          bl_value: blInput.value.trim() || null,
        }),
      }));
      loadQueue();
    } catch (err) {
      showError(err.message);
    }
  });

  const accept = el("button", null, "Accept as is");
  accept.addEventListener("click", async () => {
    accept.disabled = true;
    try {
      render(await api(`/api/cases/${data.case_id}/confirm`, { method: "POST" }));
      loadQueue();
    } catch (err) {
      showError(err.message);
    }
  });

  const retry = el("button", null, "Retry");
  retry.title = "Run this case again from the original documents";
  retry.addEventListener("click", async () => {
    retry.disabled = true;
    try {
      render(await api(`/api/cases/${data.case_id}/retry`, { method: "POST" }));
      loadQueue();
    } catch (err) {
      showError(err.message);
    }
  });

  actions.append(save, accept, retry);
  box.append(actions);

  if (data.corrections && data.corrections.length) {
    const trail = el("ul", "trail");
    data.corrections.forEach((c) => {
      const parts = [];
      if (c.si_value) parts.push(`SI → ${c.si_value}`);
      if (c.bl_value) parts.push(`BL → ${c.bl_value}`);
      trail.append(el("li", null,
        `${FIELD_LABEL[c.field] || c.field}: ${parts.join(", ")} (${c.at})`));
    });
    box.append(trail);
  }
  return box;
}

function render(data) {
  const box = $("#report");
  box.replaceChildren();

  if (data.email) {
    box.append(emailHeader(data.email, data.category,
      data.category_confidence, data.decided_by));
  }
  box.append(verdictBlock(data));

  if (data.fields && data.fields.length) box.append(fieldTable(data.fields));
  if (data.documents && data.documents.some((d) => d.path)) {
    box.append(docNote(data.documents));
  }
  if (data.documents && data.documents.every((d) => d.path)) {
    box.append(reviewBlock(data));
  }
  box.scrollIntoView({ behavior: "smooth", block: "nearest" });
}

/* ----------------------------------------------------------------- queue */

async function loadQueue() {
  let data;
  try {
    data = await api("/api/cases");
  } catch {
    return;
  }
  $("#queue-badge").textContent = `queue: ${data.open} open`;

  const box = $("#queue");
  box.replaceChildren();
  if (!data.cases.length) {
    box.append(el("p", "empty", "Nothing yet."));
    return;
  }

  data.cases.forEach((c) => {
    const row = el("div", "qrow");
    row.append(el("span", "qid", c.email && c.email.email_id ? c.email.email_id : c.case_id));
    row.append(el("span", `pill p-${c.status === "OK" ? "match"
      : c.status === "MISMATCH" ? "mismatch" : "missing"}`, c.status));

    let detail = c.escalation_detail || "";
    if (c.defect_fields.length) {
      detail = c.defect_fields.map((f) => FIELD_LABEL[f] || f).join(", ");
    }
    if (!detail && c.email && c.email.subject) detail = c.email.subject;
    row.append(el("span", "qdetail", detail || "all seven fields agree"));

    if (c.corrections) row.append(el("span", "tick", `${c.corrections} corrected`));
    if (c.human_reviewed) row.append(el("span", "tick", "reviewed"));

    const open = el("button", "qopen", "Open");
    open.addEventListener("click", async () => {
      try {
        render(await api(`/api/cases/${c.case_id}`));
      } catch (err) {
        showError(err.message);
      }
    });
    row.append(open);
    box.append(row);
  });
}

/* ------------------------------------------------------------- run paths */

async function runAndRender(promise, button) {
  if (button) button.disabled = true;
  try {
    render(await promise);
    loadQueue();
  } catch (err) {
    showError(err.message);
  } finally {
    if (button) button.disabled = false;
  }
}

async function loadDemos() {
  let data;
  try {
    data = await api("/api/demo");
  } catch {
    return;
  }
  const list = $("#demo-list");
  list.replaceChildren();
  data.cases.forEach((c) => {
    const card = el("button", "demo-card");
    card.append(el("strong", null, c.title), el("span", null, c.blurb));
    card.addEventListener("click", () =>
      runAndRender(api(`/api/demo/${c.id}`, { method: "POST" }), card));
    list.append(card);
  });
}

$("#run-paste").addEventListener("click", (e) =>
  runAndRender(api("/api/compare", {
    method: "POST",
    headers: { "Content-Type": "application/json" },
    body: JSON.stringify({
      si_text: $("#si-text").value,
      bl_text: $("#bl-text").value,
    }),
  }), e.currentTarget));

$("#run-upload").addEventListener("click", (e) => {
  const form = new FormData();
  const si = $("#si-file").files[0];
  const bl = $("#bl-file").files[0];
  if (!si && !bl) {
    showError("Choose at least one file.");
    return;
  }
  if (si) form.append("si_file", si);
  if (bl) form.append("bl_file", bl);
  runAndRender(api("/api/compare/upload", { method: "POST", body: form }),
    e.currentTarget);
});

/* ------------------------------------------------------------------ boot */

(async () => {
  try {
    const h = await api("/health");
    $("#engine-badge").textContent = `engine: ${h.engine}`;
  } catch {
    $("#engine-badge").textContent = "engine: unreachable";
  }
  loadInbox();
  loadDemos();
  loadQueue();
})();
