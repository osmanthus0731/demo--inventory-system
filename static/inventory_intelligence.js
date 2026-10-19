(() => {
  "use strict";
  const root = document.querySelector(".platform-page");
  if (!root) return;
  const section = root.dataset.section,
    csrf = root.dataset.csrf,
    message = document.querySelector("#platform-message");
  let refresh = null,readLoading=false,readQueued=false;
  const esc = (v) =>
    String(v ?? "").replace(
      /[&<>"']/g,
      (c) =>
        ({
          "&": "&amp;",
          "<": "&lt;",
          ">": "&gt;",
          '"': "&quot;",
          "'": "&#39;",
        })[c],
    );
  const say = (text, bad = false) => {
    message.textContent = text || "";
    message.className = bad ? "error" : "success";
  };
  async function api(url, options) {
    const response = await fetch(url,{...options,...(!options?.method||options.method==='GET'?{signal:options?.signal||AbortSignal.timeout(15000)}:{})}),
      type = response.headers.get("content-type") || "",
      data = type.includes("application/json") ? await response.json() : null;
    if (!response.ok)
      throw Error(
        data?.error ||
          `Request failed (${response.status}). Restart the application if it was updated.`,
      );
    if (!data) throw Error("The server returned an unexpected response.");
    return data;
  }
  const busy = (on) => root.classList.toggle("is-loading", on);
  function td(value) {
    const cell = document.createElement("td");
    cell.textContent = value ?? "Not available";
    return cell;
  }
  const today = () =>
    root.dataset.today ||
    new Intl.DateTimeFormat("en-CA", {
      timeZone: "Asia/Kuala_Lumpur",
      year: "numeric",
      month: "2-digit",
      day: "2-digit",
    }).format(new Date());
  const displayTimestamp = (value) => {
    if (!value) return "Not available";
    const parsed = new Date(value);
    if (Number.isNaN(parsed.getTime())) return String(value);
    return new Intl.DateTimeFormat("en-GB", {
      timeZone: "Asia/Kuala_Lumpur",
      day: "2-digit",
      month: "2-digit",
      year: "numeric",
      hour: "2-digit",
      minute: "2-digit",
      second: "2-digit",
      hourCycle: "h23",
    })
      .format(parsed)
      .replace(",", "");
  };
  const closeOutside = (dialog) => {
    dialog.addEventListener("click", (event) => {
      if (event.target === dialog) dialog.close();
    });
    dialog.addEventListener("close", () =>
      document.body.classList.remove("modal-open"),
    );
    const show = dialog.showModal.bind(dialog);
    dialog.showModal = () => {
      document.body.classList.add("modal-open");
      show();
    };
  };

  if (section === "history") {
    const form = document.querySelector("#history-filter"),
      body = document.querySelector("#history-body"),
      count = document.querySelector("#history-count"),
      dialog = document.querySelector("#intelligence-dialog"),
      content = document.querySelector("#dialog-content");
    let page = 1;
    const initial = new URLSearchParams(location.search);
    for (const name of [
      "uid",
      "user",
      "source",
      "type",
      "location",
      "start",
      "end",
      "reference",
    ])
      if (initial.has(name) && form.elements[name])
        form.elements[name].value = initial.get(name);
    form.elements.start.value ||= today();
    form.elements.end.value ||= today();
    function constrainDates(changed) {
      let start = form.elements.start.value;
      let end = form.elements.end.value;
      if (start > today()) start = today();
      if (end > today()) end = today();
      if (start && end && start > end) {
        if (changed === "start") start = end;
        else end = start;
      }
      form.elements.start.value = start;
      form.elements.end.value = end;
      form.elements.start.max = end || today();
      form.elements.end.min = start || "";
      form.elements.end.max = today();
    }
    form.elements.start.onchange = () => constrainDates("start");
    form.elements.end.onchange = () => constrainDates("end");
    constrainDates();
    document.querySelector(".dialog-close").onclick = () => dialog.close();
    closeOutside(dialog);
    const calendar = document.createElement("div");
    calendar.className = "card history-date-panel";
    calendar.innerHTML =
      '<div class="platform-toolbar"><div><h2>Browse movements by date</h2><p class="muted">Choose a month, then select any date that contains activity.</p></div><label>Month<input type="month"></label><label>Activity date<select class="history-date-select" aria-label="Activity date"><option value="">Loading dates…</option></select></label></div><p class="history-date-summary" aria-live="polite"></p>';
    form.after(calendar);
    calendar.querySelector("input").value = today().slice(0, 7);
    calendar.querySelector("input").max = today().slice(0, 7);
    async function loadDates() {
      const params = new URLSearchParams(new FormData(form));
      params.delete("start");
      params.delete("end");
      params.set("month", calendar.querySelector("input").value);
      const data = await api("/platform/api/history/dates?" + params),
        select = calendar.querySelector(".history-date-select"),
        summary = calendar.querySelector(".history-date-summary");
      select.replaceChildren();
      select.append(new Option("Select a date with activity", ""));
      for (const day of data.days) {
        select.append(
          new Option(
            `${day.date} — ${day.count} movement${day.count === 1 ? "" : "s"}`,
            day.date,
          ),
        );
      }
      const current =
        form.elements.start.value === form.elements.end.value
          ? form.elements.start.value
          : "";
      if ([...select.options].some((option) => option.value === current))
        select.value = current;
      summary.textContent = data.days.length
        ? `${data.days.length} active date${data.days.length === 1 ? "" : "s"} available in this month.`
        : "No activity in this month.";
      select.disabled = !data.days.length;
    }
    function movementText(row) {
      if (row.classification === "initial_snapshot")
        return "Initial import - baseline recorded";
      if (row.quantity_difference == null) return row.explanation;
      if (Number(row.quantity_difference) === 0) {
        const before = row.before || {},
          after = row.after || {},
          locations = ["a", "b"]
            .filter(
              (slot) =>
                before["location_" + slot] !== after["location_" + slot],
            )
            .map(
              (slot) =>
                `Location ${slot.toUpperCase()}: ${before["location_" + slot] || "unnamed"} -> ${after["location_" + slot] || "unnamed"}`,
            );
        return locations.length
          ? `No net stock change; ${locations.join("; ")}`
          : row.explanation;
      }
      const sign = row.quantity_difference > 0 ? "+" : "";
      return `${row.before?.total ?? "Previous snapshot unavailable"} -> ${sign}${row.quantity_difference} -> ${row.after?.total ?? "Current snapshot unavailable"}`;
    }
    async function details(id) {
      const data = await api("/platform/api/history/detail?id=" + encodeURIComponent(id)),
        row = data.movement,
        changes = (row.changes || [])
          .map(
            (c) =>
              `<tr><td>${esc(c.location || c.slot)}</td><td>${esc(c.previous ?? "Unavailable")}</td><td>${esc(c.change ?? "Unavailable")}</td><td>${esc(c.new ?? "Unavailable")}</td></tr>`,
          )
          .join("");
      content.innerHTML = `<h2>Movement details</h2><dl class="detail-grid"><dt>Product</dt><dd>${esc(row.product_name)} (${esc(row.uid)})</dd><dt>Timestamp</dt><dd>${esc(displayTimestamp(row.timestamp))}</dd><dt>Classification</dt><dd>${esc(row.classification)}</dd><dt>Source</dt><dd>${esc(row.username)} / ${esc(row.source)}</dd><dt>Explanation</dt><dd>${esc(row.explanation)}</dd><dt>Review flags</dt><dd>${esc((row.review_flags || []).join(", ") || "None")}</dd></dl><div class="table-wrap"><table><thead><tr><th>Location</th><th>Before</th><th>Change</th><th>After</th></tr></thead><tbody>${changes || `<tr><td colspan="4">${esc(row.explanation)}</td></tr>`}</tbody></table></div><p class="muted">Historical quantities are permanent audit facts and cannot be rewritten here. You can correct the classification, reason, and remarks without changing stock.</p><h3>Correction history</h3>${data.corrections.length ? "<ul>" + data.corrections.map((x) => `<li>${esc(displayTimestamp(x.timestamp))} - ${esc(x.classification)} by ${esc(x.username)}: ${esc(x.remarks)}</li>`).join("") + "</ul>" : "<p>No classification corrections.</p>"}${row.eligible_for_edit ? `<form id="classification-form" class="platform-form"><input type="hidden" name="revision" value="${row.classification_revision || 0}"><label>Classification<select name="classification"><option value="sold">Sold</option><option value="received">Received</option><option value="external_adjustment">External Adjustment</option></select></label><label>Adjustment reason<select name="adjustment_reason"><option value="">Not applicable</option><option value="human_error">Human error</option><option value="stock_reconciliation">Stock reconciliation</option><option value="location_transfer">Location transfer</option><option value="damaged_stock">Damaged stock</option><option value="system_correction">System correction</option><option value="other">Other</option></select></label><label>Remarks<textarea name="remarks" required>${esc(row.classification_explanation || row.note || "")}</textarea></label><button class="btn">Save reason and classification</button></form>` : ""}`;
      dialog.showModal();
      const edit = content.querySelector("#classification-form");
      if (!edit) return;
      edit.elements.classification.value =
        row.classification === "sale"
          ? "sold"
          : row.classification === "received"
            ? "received"
            : "external_adjustment";
      edit.elements.adjustment_reason.value = row.adjustment_reason || "";
      edit.onsubmit = async (event) => {
        event.preventDefault();
        try {
          await api(
            "/platform/api/history/classification?id=" + encodeURIComponent(id),
            {
              method: "POST",
              headers: {
                "Content-Type": "application/json",
                "X-CSRF-Token": csrf,
              },
              body: JSON.stringify(Object.fromEntries(new FormData(edit))),
            },
          );
          dialog.close();
          say("Classification updated; stock quantity was unchanged.");
          load();
        } catch (error) {
          say(error.message, true);
        }
      };
    }
    async function load() {
      if(readLoading){readQueued=true;return;}readLoading=true;
      busy(true);
      try {
        const params = new URLSearchParams(new FormData(form));
        params.set("page", page);
        const data = await api("/platform/api/history?" + params);
        body.replaceChildren();
        for (const row of data.rows) {
          const tr = document.createElement("tr");
          tr.append(
            td(row.business_date),
            (() => { const cell=td(""); const link=document.createElement("a"); link.href="/item/"+encodeURIComponent(row.uid); link.textContent=`${row.uid} - ${row.product_name || ""}`; cell.append(link); return cell; })(),
            td(`${row.username || "Unknown"} / ${row.source || "Unknown"}`),
            td(row.classification.replaceAll("_", " ")),
            td(movementText(row)),
            td(row.reference || "None"),
            td(row.sync_status || "Unknown"),
          );
          const action = td(""),
            button = document.createElement("button");
          button.type = "button";
          button.className = "btn platform-secondary";
          button.textContent = "View details / Edit";
          button.dataset.movementId = row._id || row.event_id;
          action.append(button);
          tr.append(action);
          body.append(tr);
        }
        if (!data.rows.length) {
          const tr = document.createElement("tr"),
            cell = td("No movements match this day and filters.");
          cell.colSpan = 8;
          tr.append(cell);
          body.append(tr);
        }
        count.textContent = `${data.total} movement records - page ${page}`;
        document.querySelector("#csv-link").href =
          "/platform/api/history.csv?" + params;
      } catch (error) {
        say(error.message, true);
      } finally {
        busy(false);readLoading=false;if(readQueued){readQueued=false;queueMicrotask(load);}
      }
    }
    body.addEventListener("click", async (event) => {
      const button = event.target.closest("[data-movement-id]");
      if (!button) return;
      event.preventDefault();
      button.disabled = true;
      try {
        await details(button.dataset.movementId);
      } catch (error) {
        say("Unable to open movement: " + error.message, true);
      } finally {
        button.disabled = false;
      }
    });
    const csv = document.querySelector("#csv-link");
    csv.textContent = "Preview / Export CSV";
    csv.onclick = (event) => {
      event.preventDefault();
      content.innerHTML = `<h2>Preview stock history CSV</h2><form id="csv-preview-form" class="platform-toolbar"><label>From<input type="date" name="start" value="${esc(form.elements.start.value)}" required></label><label>To<input type="date" name="end" value="${esc(form.elements.end.value)}" required></label><button class="btn">Preview</button><a class="btn" id="csv-download">Download CSV</a></form><p id="csv-summary"></p><div class="table-wrap"><table><thead><tr><th>Date</th><th>Product</th><th>Classification</th><th>Change</th><th>Explanation</th></tr></thead><tbody id="csv-preview-body"></tbody></table></div>`;
      dialog.showModal();
      const previewForm = content.querySelector("#csv-preview-form");
      const preview = async (e) => {
        e?.preventDefault();
        const params = new URLSearchParams(new FormData(form));
        params.set("start", previewForm.elements.start.value);
        params.set("end", previewForm.elements.end.value);
        const data = await api("/platform/api/history?" + params),
          previewBody = content.querySelector("#csv-preview-body");
        previewBody.replaceChildren();
        for (const row of data.rows.slice(0, 20)) {
          const tr = document.createElement("tr");
          [
            row.business_date,
            `${row.uid} - ${row.product_name || ""}`,
            row.classification,
            row.quantity_difference,
            row.explanation,
          ].forEach((v) => tr.append(td(v)));
          previewBody.append(tr);
        }
        content.querySelector("#csv-summary").textContent =
          `${data.total} records; previewing ${Math.min(20, data.rows.length)}.`;
        content.querySelector("#csv-download").href =
          "/platform/api/history.csv?" + params;
      };
      previewForm.onsubmit = preview;
      preview();
    };
    body
      .closest("table")
      .querySelector("thead tr")
      .append(
        Object.assign(document.createElement("th"), { textContent: "Actions" }),
      );
    form.onsubmit = (event) => {
      event.preventDefault();
      page = 1;
      load();
    };
    calendar.querySelector("input").onchange = loadDates;
    calendar.querySelector(".history-date-select").onchange = (event) => {
      if (!event.target.value) return;
      form.elements.start.value = form.elements.end.value = event.target.value;
      constrainDates();
      page = 1;
      load();
    };
    refresh = load;
    load();
    loadDates();
  }

  if (section === "analytics") {
    const form = document.querySelector("#analytics-filter"),
      cards = document.querySelector("#analytics-cards"),
      body = document.querySelector("#analytics-body"),
      dialog = document.querySelector("#intelligence-dialog"),
      content = document.querySelector("#dialog-content"),
      more = document.querySelector("#analytics-show-more");
    const performanceSection = body.closest(".card");
    performanceSection.classList.add("performance-section");
    performanceSection.querySelector("h2").textContent =
      "Inventory performance";
    let latest,
      expanded = false,
      replenishmentExpanded = false,
      fastExpanded = false,
      slowExpanded = false;
    const palette = [
      "#315fba",
      "#397fd0",
      "#2f9fc1",
      "#1aa6a6",
      "#45b8b0",
      "#6f8ed6",
      "#8277d8",
      "#9b7ad9",
      "#b39be5",
      "#83b9db",
    ];
    document.querySelector(".dialog-close").onclick = () => dialog.close();
    closeOutside(dialog);
    const activity = document.createElement("div");
    activity.className = "card";
    activity.innerHTML =
      '<div class="platform-toolbar"><div><h2>Available analytics dates</h2><p class="muted">Only dates containing stock activity are clickable. Click once for the start and again for the end.</p></div><label>Month<input type="month" max="' +
      today().slice(0, 7) +
      '"></label></div><div class="history-calendar"></div>';
    form.after(activity);
    activity.querySelector("input").value = today().slice(0, 7);
    let rangeStart = null;
    async function loadActivityDates() {
      const data = await api(
          "/platform/api/history/dates?month=" +
            encodeURIComponent(activity.querySelector("input").value),
        ),
        box = activity.querySelector(".history-calendar");
      box.replaceChildren();
      for (const day of data.days) {
        const button = document.createElement("button");
        button.type = "button";
        button.className = "history-day";
        button.innerHTML = `<strong>${esc(day.date)}</strong><span>${day.count} movement${day.count === 1 ? "" : "s"}</span>`;
        button.onclick = () => {
          if (!rangeStart) {
            rangeStart = day.date;
            form.elements.start.value = form.elements.end.value = day.date;
          } else {
            const pair = [rangeStart, day.date].sort();
            form.elements.start.value = pair[0];
            form.elements.end.value = pair[1];
            rangeStart = null;
          }
          alignPeriod();
          loadActivityDates();
        };
        box.append(button);
      }
      if (!data.days.length)
        box.textContent = "No stock activity in this month.";
    }
    activity.querySelector("input").onchange = loadActivityDates;
    function open(title, rows) {
      content.innerHTML = `<h2>${esc(title)}</h2><p>Selected period: ${esc(latest.period.start)} to ${esc(latest.period.end)}.</p><div class="table-wrap"><table><thead><tr><th>UID</th><th>Product</th><th>Stock</th><th>Sold</th><th>Received</th><th>Adjustments</th><th>Movements</th></tr></thead><tbody>${rows.map((r) => `<tr data-uid="${esc(r.uid)}"><td>${esc(r.uid)}</td><td>${esc(r.name)}</td><td>${esc(r.stock)}</td><td>${esc(r.issued)}</td><td>${esc(r.received)}</td><td>${esc(r.adjustments)}</td><td>${esc(r.frequency)}</td></tr>`).join("")}</tbody></table></div>`;
      for (const tr of content.querySelectorAll("[data-uid]"))
        tr.onclick = () =>
          (location.href =
            "/platform/history?uid=" +
            encodeURIComponent(tr.dataset.uid) +
            "&start=" +
            latest.period.start +
            "&end=" +
            latest.period.end);
      dialog.showModal();
    }
    function openCategories() {
      const rows = Object.entries(latest.categories || {}).sort(
        (a, b) => b[1] - a[1],
      );
      content.innerHTML = `<h2>Demand by category</h2><p>Selected period: ${esc(latest.period.start)} to ${esc(latest.period.end)}.</p><canvas id="category-popup-chart" class="analytics-popup-chart"></canvas><div class="chart-legend" id="category-popup-legend"></div>${rows.length ? "" : "<p>No confirmed sales in this period.</p>"}`;
      dialog.showModal();
      drawBars(
        content.querySelector("#category-popup-chart"),
        rows.map(([category]) => category),
        rows.map(([, units]) => units),
        palette,
        content.querySelector("#category-popup-legend"),
      );
    }
    function openFlow() {
      const groups=[['Sold','issued'],['Received','received']];
      content.innerHTML=`<h2>Sold vs received trend</h2><p>Selected period: ${esc(latest.period.start)} to ${esc(latest.period.end)}.</p><div class="flow-sections">${groups.map(([title,key])=>{
        const rows=latest.rows.filter(row=>Number(row[key])>0).sort((a,b)=>b[key]-a[key]);
        const total=latest.daily.reduce((sum,row)=>sum+Number(row[key]||0),0);
        return `<section><header class="flow-total"><span>${title}</span><strong>${total.toLocaleString()} units</strong></header><div class="table-wrap"><table><thead><tr><th>Product</th><th>UID</th><th>${title}</th></tr></thead><tbody>${rows.map(row=>`<tr><td>${esc(row.name)}</td><td>${esc(row.uid)}</td><td><strong>${esc(row[key])}</strong></td></tr>`).join('')||'<tr><td colspan="3">No movements in this period.</td></tr>'}</tbody></table></div></section>`;
      }).join('')}</div>`;
      dialog.showModal();
    }
    function drawBars(canvas, labels, values, colors = ["#315fba"], legend) {
      const ratio = devicePixelRatio || 1,
        w = (canvas.width = canvas.clientWidth * ratio),
        h = (canvas.height = 250 * ratio),
        ctx = canvas.getContext("2d"),
        max = Math.max(1, ...values),
        left = 46 * ratio,
        right = 12 * ratio,
        top = 14 * ratio,
        bottom = (legend ? 12 : 42) * ratio,
        plotW = w - left - right,
        plotH = h - top - bottom;
      ctx.clearRect(0, 0, w, h);
      ctx.font = `${10 * ratio}px sans-serif`;
      ctx.fillStyle = "#7b8492";
      ctx.strokeStyle = "#e6eaf0";
      ctx.lineWidth = ratio;
      for (let step = 0; step <= 4; step += 1) {
        const value = Math.round((max * (4 - step)) / 4),
          y = top + (plotH * step) / 4;
        ctx.beginPath();
        ctx.moveTo(left, y);
        ctx.lineTo(w - right, y);
        ctx.stroke();
        ctx.textAlign = "right";
        ctx.fillText(String(value), left - 7 * ratio, y + 3 * ratio);
      }
      values.forEach((value, index) => {
        const slot = plotW / Math.max(1, values.length),
          bw = Math.max(4 * ratio, Math.min(56 * ratio, slot * 0.66)),
          x = left + index * slot + (slot - bw) / 2,
          bh = (value / max) * plotH;
        ctx.fillStyle = colors[index % colors.length];
        ctx.fillRect(x, top + plotH - bh, bw, bh);
        ctx.fillStyle = "#626d7c";
        ctx.textAlign = "center";
        const label = String(labels[index] || "");
        if (!legend) ctx.fillText(
          label.length > 10 ? label.slice(0, 9) + "…" : label,
          x + bw / 2,
          h - 18 * ratio,
        );
      });
      canvas.title = labels.map((x, i) => `${x}: ${values[i]}`).join("\n");
      if (legend) {
        legend.replaceChildren();
        labels.forEach((label, index) => {
          const item = document.createElement("span");
          item.innerHTML = `<i style="--legend:${colors[index % colors.length]}"></i>${esc(label)}: ${esc(values[index])}`;
          legend.append(item);
        });
      }
    }
    function drawDonut(canvas, values, legend) {
      const entries = Object.entries(values || {}).filter(
          ([, value]) => value > 0,
        ),
        ratio = devicePixelRatio || 1,
        w = (canvas.width = canvas.clientWidth * ratio),
        h = (canvas.height = 220 * ratio),
        ctx = canvas.getContext("2d"),
        total = entries.reduce((sum, [, value]) => sum + value, 0),
        radius = Math.min(w, h) * 0.25,
        cx = w / 2,
        cy = h / 2;
      ctx.clearRect(0, 0, w, h);
      let angle = -Math.PI / 2;
      entries.forEach(([, value], index) => {
        const next = angle + (value / Math.max(1, total)) * Math.PI * 2;
        ctx.beginPath();
        ctx.arc(cx, cy, radius, angle, next);
        ctx.lineWidth = radius * 0.48;
        ctx.strokeStyle = palette[index % palette.length];
        ctx.stroke();
        angle = next;
      });
      ctx.fillStyle =
        getComputedStyle(document.documentElement).getPropertyValue("--ink") ||
        "#202631";
      ctx.font = `bold ${16 * ratio}px sans-serif`;
      ctx.textAlign = "center";
      ctx.fillText(String(total), cx, cy + 5 * ratio);
      legend.replaceChildren();
      entries.forEach(([label, value], index) => {
        const item = document.createElement("span");
        item.innerHTML = `<i style="--legend:${palette[index % palette.length]}"></i>${esc(label)}: ${esc(value)}`;
        legend.append(item);
      });
    }
    function drawFlow(canvas, rows) {
      const ratio = devicePixelRatio || 1,
        w = (canvas.width = canvas.clientWidth * ratio),
        h = (canvas.height = 250 * ratio),
        ctx = canvas.getContext("2d"),
        max = Math.max(1, ...rows.flatMap((row) => [row.issued, row.received])),
        left = 46 * ratio,
        right = 12 * ratio,
        top = 14 * ratio,
        bottom = 34 * ratio,
        plotW = w - left - right,
        plotH = h - top - bottom;
      ctx.clearRect(0, 0, w, h);
      ctx.font = `${10 * ratio}px sans-serif`;
      for (let step = 0; step <= 4; step += 1) {
        const value = Math.round((max * (4 - step)) / 4),
          y = top + (plotH * step) / 4;
        ctx.strokeStyle = "#e6eaf0";
        ctx.lineWidth = ratio;
        ctx.beginPath();
        ctx.moveTo(left, y);
        ctx.lineTo(w - right, y);
        ctx.stroke();
        ctx.fillStyle = "#7b8492";
        ctx.textAlign = "right";
        ctx.fillText(String(value), left - 7 * ratio, y + 3 * ratio);
      }
      [
        ["issued", "#315fba"],
        ["received", "#1aa6a6"],
      ].forEach(([key, color]) => {
        ctx.beginPath();
        ctx.strokeStyle = color;
        ctx.lineWidth = 2 * ratio;
        rows.forEach((row, index) => {
          const x = left + (index / Math.max(1, rows.length - 1)) * plotW,
            y = top + plotH - (row[key] / max) * plotH;
          index ? ctx.lineTo(x, y) : ctx.moveTo(x, y);
        });
        ctx.stroke();
      });
      const tickIndexes = [
        ...new Set([0, Math.floor((rows.length - 1) / 2), rows.length - 1]),
      ];
      ctx.fillStyle = "#626d7c";
      ctx.textAlign = "center";
      tickIndexes.forEach((index) => {
        if (!rows[index]) return;
        const x = left + (index / Math.max(1, rows.length - 1)) * plotW;
        ctx.fillText(rows[index].date.slice(5), x, h - 12 * ratio);
      });
      canvas.title = rows
        .map(
          (row) => `${row.date}: Sold ${row.issued}, Received ${row.received}`,
        )
        .join("\n");
    }
    function stockStatus(row) {
      if (Number(row.stock) <= 0)
        return {
          label: Number(row.stock) < 0 ? "Negative" : "Out of stock",
          className: "out",
        };
      if (
        Number(row.reorder_threshold) > 0 &&
        Number(row.stock) <= Number(row.reorder_threshold)
      )
        return { label: "Low stock", className: "low" };
      return { label: "Healthy", className: "healthy" };
    }
    function renderSold() {
      const rows = latest?.rows || [],
        shown = expanded ? rows : rows.slice(0, 8);
      body.replaceChildren();
      shown.forEach((row, index) => {
        const tr = document.createElement("tr"),
          status = stockStatus(row),
          cell = document.createElement("td"),
          coverage =
            row.coverage_days == null
              ? "Not available"
              : `${Number(row.coverage_days).toFixed(1)} days`;
        tr.className = "performance-row";
        cell.colSpan = 13;
        cell.innerHTML = `<article class="performance-card"><div class="performance-rank">${index + 1}</div><div class="performance-title"><strong>${esc(row.name)}</strong><span>${esc(row.uid)} · ${esc(row.category)}</span></div><div class="performance-stat"><span>Stock</span><strong>${esc(row.stock)}</strong></div><div class="performance-stat"><span>Sold</span><strong>${esc(row.issued)}</strong></div><div class="performance-stat"><span>Received</span><strong>${esc(row.received)}</strong></div><div class="performance-stat"><span>Coverage</span><strong>${esc(coverage)}</strong></div><div class="performance-end"><span class="analytics-status ${status.className}">${esc(status.label)}</span><small>${esc(displayTimestamp(row.last_movement))}</small></div></article>`;
        tr.append(cell);
        tr.onclick = () => open(row.name, [row]);
        body.append(tr);
      });
      if (!shown.length) {
        const tr = document.createElement("tr"),
          cell = td("No inventory activity exists in this period.");
        cell.colSpan = 13;
        tr.append(cell);
        body.append(tr);
      }
      more.hidden = rows.length <= 8;
      more.textContent = expanded ? "Show top 8" : `Show all ${rows.length}`;
    }
    function renderActions() {
      const replenish = document.querySelector("#replenishment-body"),
        replenishmentRows = latest.replenishment || [],
        shownReplenishment = replenishmentExpanded
          ? replenishmentRows
          : replenishmentRows.slice(0, 5);
      replenish.replaceChildren();
      for (const row of shownReplenishment) {
        const tr = document.createElement("tr");
        [
          row.name,
          row.stock,
          Number(row.average_daily_demand).toFixed(2),
          row.coverage_days == null
            ? "—"
            : Number(row.coverage_days).toFixed(1) + " days",
          row.suggested_quantity ?? "—",
        ].forEach((value) => tr.append(td(value)));
        tr.onclick = () => open(row.name, [row]);
        replenish.append(tr);
      }
      if (!replenish.children.length) {
        const tr = document.createElement("tr"),
          cell = td("No products currently require replenishment.");
        cell.colSpan = 5;
        tr.append(cell);
        replenish.append(tr);
      }
      const ensureToggle = (container, id, rows, expandedState, onToggle) => {
        let button = document.querySelector("#" + id);
        if (!button) {
          button = document.createElement("button");
          button.type = "button";
          button.id = id;
          button.className = "text-action";
          container.prepend(button);
        }
        button.hidden = rows.length <= 5;
        button.textContent = expandedState
          ? "Show top 5"
          : `Show all ${rows.length}`;
        button.onclick = onToggle;
      };
      ensureToggle(
        replenish.closest(".card"),
        "replenishment-more",
        replenishmentRows,
        replenishmentExpanded,
        () => {
          replenishmentExpanded = !replenishmentExpanded;
          renderActions();
        },
      );
      const fill = (
        selector,
        rows,
        kind,
        expandedState,
        toggleId,
        onToggle,
      ) => {
        const list = document.querySelector(selector);
        list.replaceChildren();
        const shown = expandedState ? rows : rows.slice(0, 5),
          maximum = Math.max(
            1,
            ...rows.map(
              (row) => Number(kind === "fast" ? row.units : row.stock) || 0,
            ),
          );
        shown.forEach((row, index) => {
          const item = document.createElement("li");
          const value = Number(kind === "fast" ? row.units : row.stock) || 0;
          item.innerHTML = `<span class="mover-rank">${index + 1}</span><span class="mover-name"><strong>${esc(row.name)}</strong><small>${esc(row.uid || "")}</small><i style="--fill:${Math.max(4, (value / maximum) * 100)}%"></i></span><span class="mover-value"><strong>${esc(value)}</strong><small>${kind === "fast" ? "sold" : "in stock"}</small></span>`;
          item.onclick = () => {
            const detail = latest.rows.find((entry) => entry.uid === row.uid);
            if (detail) open(row.name, [detail]);
          };
          list.append(item);
        });
        if (!rows.length) {
          const item = document.createElement("li");
          item.textContent = "No matching products";
          list.append(item);
        }
        ensureToggle(
          list.closest("section"),
          toggleId,
          rows,
          expandedState,
          onToggle,
        );
      };
      fill(
        "#fast-movers",
        latest.fast_moving || [],
        "fast",
        fastExpanded,
        "fast-more",
        () => {
          fastExpanded = !fastExpanded;
          renderActions();
        },
      );
      fill(
        "#slow-movers",
        latest.slow_moving || [],
        "slow",
        slowExpanded,
        "slow-more",
        () => {
          slowExpanded = !slowExpanded;
          renderActions();
        },
      );
    }
    async function load() {
      if(readLoading){readQueued=true;return;}readLoading=true;
      busy(true);
      try {
        latest = await api(
          "/platform/api/analytics?" + new URLSearchParams(new FormData(form)),
        );
        cards.replaceChildren();
        for (const [label, value] of Object.entries(latest.cards)) {
          const button = document.createElement("button");
          button.className = "metric metric-button";
          button.innerHTML = `<span>${esc(label)}</span><strong>${esc(value)}</strong><small>View contributing products</small>`;
          button.onclick = () =>
            open(
              label,
              latest.rows.filter((row) =>
                label.includes("sold")
                  ? row.issued
                  : label.includes("received")
                    ? row.received
                    : label.includes("Adjustment")
                      ? row.adjustments
                      : true,
              ),
            );
          cards.append(button);
        }
        expanded = false;
        replenishmentExpanded = false;
        fastExpanded = false;
        slowExpanded = false;
        renderSold();
        renderActions();
        document.querySelector("#analytics-note").textContent =
          latest.note +
          " Selected: " +
          latest.period.start +
          " to " +
          latest.period.end +
          ".";
        drawDonut(
          document.querySelector("#stock-status-chart"),
          latest.stock_status,
          document.querySelector("#stock-status-legend"),
        );
        drawFlow(document.querySelector("#flow-chart"), latest.daily);
        drawBars(
          document.querySelector("#monthly-chart"),
          Object.keys(latest.monthly),
          Object.values(latest.monthly),
        );
        drawBars(
          document.querySelector("#category-chart"),
          Object.keys(latest.categories),
          Object.values(latest.categories),
          palette,
          document.querySelector("#category-legend"),
        );
        const activate = (element, action) => {
          element.onclick = action;
          element.onkeydown = (event) => {
            if (event.key === "Enter" || event.key === " ") {
              event.preventDefault();
              action();
            }
          };
        };
        activate(document.querySelector("#stock-status-card"), () =>
          open("Stock status overview", latest.rows),
        );
        activate(document.querySelector("#flow-card"), openFlow);
        activate(document.querySelector("#monthly-card"), () =>
          open(
            "Monthly demand",
            latest.rows.filter((row) => row.issued),
          ),
        );
        activate(document.querySelector("#category-card"), openCategories);
      } catch (error) {
        say(error.message, true);
      } finally {
        busy(false);readLoading=false;if(readQueued){readQueued=false;queueMicrotask(load);}
      }
    }
    const iso = (date) => date.toISOString().slice(0, 10);
    function bounds() {
      form.elements.end.max = today();
      form.elements.start.max = form.elements.end.value || today();
      form.elements.end.min = form.elements.start.value || "";
    }
    function setRange() {
      if (form.elements.period.value === "custom") {
        form.elements.start.value = "";
        form.elements.end.value = "";
        bounds();
        return;
      }
      const days = Number(form.elements.period.value),
        end = new Date(today() + "T00:00:00Z"),
        start = new Date(end);
      start.setUTCDate(start.getUTCDate() - days + 1);
      form.elements.start.value = iso(start);
      form.elements.end.value = iso(end);
      bounds();
    }
    function alignPeriod(changed) {
      let start = form.elements.start.value,
        end = form.elements.end.value;
      if (start > today()) start = today();
      if (end > today()) end = today();
      if (start && end && start > end) {
        if (changed === "start") start = end;
        else end = start;
      }
      form.elements.start.value = start;
      form.elements.end.value = end;
      bounds();
      if (!start || !end) {
        form.elements.period.value = "custom";
        return;
      }
      const first = new Date(start + "T00:00:00"),
        last = new Date(end + "T00:00:00"),
        span = Math.round((last - first) / 86400000) + 1,
        allowed = ["7", "14", "30", "90", "180", "365"];
      form.elements.period.value =
        end === today() && allowed.includes(String(span))
          ? String(span)
          : "custom";
    }
    form.elements.start.max = today();
    form.elements.end.max = today();
    form.elements.period.onchange = () => {
      setRange();
      rangeStart = null;
    };
    form.elements.start.onchange = () => alignPeriod("start");
    form.elements.end.onchange = () => alignPeriod("end");
    more.onclick = () => {
      expanded = !expanded;
      renderSold();
    };
    setRange();
    form.onsubmit = (event) => {
      event.preventDefault();
      alignPeriod();
      if (!form.elements.start.value || !form.elements.end.value) {
        say("Choose both From and To dates.", true);
        return;
      }
      load();
    };
    refresh = load;
    load();
    loadActivityDates();
  }

  if (section === "forecasting") {
    const form = document.querySelector("#forecast-filter"),
      box = document.querySelector("#forecast-cards"),
      start = new Date(today() + "T00:00:00");
    const maturity = document.querySelector(".maturity");
    if (maturity) {
      maturity.className = "forecast-intro";
      maturity.innerHTML =
        "<strong>What needs attention?</strong><span>Coverage uses confirmed Sold movements only. Products without enough history remain marked as Collecting data.</span>";
    }
    box.className = "card forecast-table-card";
    box.innerHTML = `<div class="section-heading"><div><h2>Replenishment forecast</h2><p class="muted">Current stock, estimated coverage, and the next action.</p></div><span class="forecast-count" id="forecast-count"></span></div><div class="table-wrap"><table class="forecast-table"><thead><tr><th>Product</th><th>Stock</th><th>Estimated coverage</th><th>Action</th></tr></thead><tbody id="forecast-body"></tbody></table></div>`;
    start.setDate(start.getDate() - 89);
    form.elements.start.value = start.toISOString().slice(0, 10);
    async function load() {
      if(readLoading){readQueued=true;return;}readLoading=true;
      busy(true);
      try {
        const data = await api(
          "/platform/api/forecasting?" +
            new URLSearchParams(new FormData(form)),
        );
        document.querySelector("#page-note").textContent = data.note;
        const body = document.querySelector("#forecast-body"),
          count = document.querySelector("#forecast-count");
        body.replaceChildren();
        count.textContent = `${data.rows.length} product${data.rows.length === 1 ? "" : "s"}`;
        for (const row of data.rows) {
          const analysis = row.analysis || {},
            plan = row.replenishment || {},
            demand = analysis.average_daily_demand,
            coverage = demand > 0 ? row.stock / demand : null,
            coverageDays =
              coverage == null ? null : Math.max(0, Math.floor(coverage)),
            status =
              coverageDays == null
                ? { label: "Collecting data", tone: "collecting" }
                : coverageDays <= 7
                  ? { label: "Urgent", tone: "urgent" }
                  : coverageDays <= 14
                    ? { label: "Reorder soon", tone: "soon" }
                    : { label: "Healthy", tone: "healthy" },
            suggested = Number(plan.suggested_quantity) || 0,
            tr = document.createElement("tr");
          tr.innerHTML = `<td><strong>${esc(row.name || row.uid)}</strong><small>${esc(row.uid)} · ${esc(analysis.status || "Collecting Data")}</small></td><td><strong>${esc(row.stock)}</strong><small>${demand > 0 ? `${Number(demand).toFixed(2)} avg/day` : "Demand not ready"}</small></td><td><strong>${coverageDays == null ? "Not available" : `${coverageDays} days`}</strong><small>${esc(plan.explanation || plan.status || "Waiting for enough sales history.")}</small></td><td><span class="forecast-action ${status.tone}">${status.label}</span>${suggested > 0 ? `<a class="forecast-order" href="/purchase-orders/new?uid=${encodeURIComponent(row.uid)}">Order ${esc(suggested)} units →</a>` : ""}</td>`;
          body.append(tr);
        }
        if (!data.rows.length) {
          const tr = document.createElement("tr");
          tr.innerHTML =
            '<td colspan="4" class="empty-state">No products match these filters.</td>';
          body.append(tr);
        }
      } catch (error) {
        say(error.message, true);
      } finally {
        busy(false);readLoading=false;if(readQueued){readQueued=false;queueMicrotask(load);}
      }
    }
    form.onsubmit = (event) => {
      event.preventDefault();
      load();
    };
    refresh = load;
    load();
  }
  if (refresh) {
    let timer;
    const schedule = () => {
      clearTimeout(timer);
      timer = setTimeout(() => {
        if (!document.hidden) refresh();
      }, 500);
    };
    window.addEventListener('meadow:update',event=>{
      if((event.detail.channels||[]).some(channel=>['inventory','history','analytics'].includes(channel)))schedule();
    });
    setInterval(() => {
      if (!document.hidden) refresh();
    }, 60000);
  }
})();
