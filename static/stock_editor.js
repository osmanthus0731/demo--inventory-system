(() => {
  "use strict";
  const dialog = document.querySelector("#stock-dialog");
  if (!dialog) return;
  const form = document.querySelector("#stock-form");
  const message = document.querySelector("#stock-message");
  const token = dialog.dataset.csrf;
  let current = null;
  const addedSlots = new Set();

  async function request(path, options = {}) {
    const timeout = new AbortController();
    const timer = setTimeout(() => timeout.abort(), 10000);
    const response = await fetch("/platform" + path, {
      ...options,
      signal: options.signal || timeout.signal,
      headers: {
        "Content-Type": "application/json",
        "X-CSRF-Token": token,
        ...options.headers,
      },
    }).catch((error) => {
      if (error.name === "AbortError")
        throw Error("Product loading timed out. Please try again.");
      throw error;
    });
    clearTimeout(timer);
    let data;
    try {
      data = await response.json();
    } catch {
      throw Error("Request failed. Reload and try again.");
    }
    if (!response.ok) throw Error(data.error || "Request failed.");
    return data;
  }

  function show(text, error = false) {
    message.textContent = text;
    message.className = error ? "platform-error" : "";
  }

  function nextEventId() {
    return crypto.randomUUID
      ? crypto.randomUUID()
      : `${Date.now()}00000000-0000-4000-8000-000000000000`.slice(0, 36);
  }

  function review() {
    if (!current?.state) return;
    const mode = form.elements.mode.value;
    const lines = document.querySelector("#stock-review-lines");
    lines.replaceChildren();
    const summaries = [];
    for (const field of ["a", "b", "total"]) {
      const control = form.elements[field];
      if (control.disabled) continue;
      const before = current.state[field];
      const value = control.value.trim() === "" ? null : Number(control.value);
      const next =
        value === null
          ? null
          : mode === "adjust"
            ? (before ?? 0) + value
            : value;
      const label =
        field === "total"
          ? "Office stock"
          : form.elements["location_" + field].value.trim() || "New location";
      const row = document.createElement("div");
      row.className = "stock-review-line";
      const name = document.createElement("span");
      name.textContent = label;
      const amounts = document.createElement("b");
      amounts.textContent = `${before === null ? "\u2014" : before.toLocaleString()} \u2192 ${next === null ? "\u2014" : next.toLocaleString()}`;
      row.append(name, amounts);
      lines.append(row);
      summaries.push(
        `${label}: ${before} \u2192 ${next === null ? "\u2014" : next}`,
      );
    }
    document.querySelector("#stock-review p").textContent = current.writable
      ? ""
      : "Editing is unavailable for this record.";
    form.dataset.review = summaries.join("; ");
  }

  let loadVersion = 0;
  async function open(uid) {
    const version = ++loadVersion;
    current = null;
    addedSlots.clear();
    if (!dialog.open) dialog.showModal();
    form.reset();
    form.setAttribute("aria-busy", "true");
    document.querySelector("#stock-save").disabled = true;
    document.querySelector("#stock-product").textContent = "Loading product…";
    document.querySelector("#stock-meta").textContent = "";
    document.querySelector("#stock-review-lines").replaceChildren();
    document.querySelector("#stock-review p").textContent =
      "Loading the latest quantities…";
    show("");
    form.elements.uid.value = uid;
    form.elements.event_id.value = nextEventId();
    for (const field of ["a", "b", "total"]) {
      form.elements[field].value = "";
      form.elements[field].disabled = true;
    }
    for (const field of ["location_a", "location_b"]) {
      form.elements[field].value = "";
      form.elements[field].disabled = true;
      form.elements[field].hidden = true;
    }
    document.querySelector("#stock-add-location").hidden = true;
    try {
      const loaded = await request("/api/stock/" + encodeURIComponent(uid));
      if (version !== loadVersion) return;
      current = loaded;
      document.querySelector("#stock-product").textContent =
        current.name || "Unnamed product";
      form.elements.revision.value = current.revision;
      for (const field of ["a", "b", "total"]) {
        const available =
          current.state &&
          (field === "total" ||
            Boolean(current.state["location_" + field].trim()));
        const control = form.elements[field];
        control.value = current.state?.[field] ?? "";
        control.disabled = !available;
        control.required = Boolean(available);
        if (field !== "total") {
          document.querySelector("#stock-" + field + "-field").hidden =
            !available;
          document.querySelector("#stock-" + field + "-label").textContent =
            current.state?.["location_" + field] || "Unused location";
          const location = form.elements["location_" + field];
          location.value = current.state?.["location_" + field] || "";
          location.disabled = true;
          location.hidden = true;
          location.required = false;
        }
      }
      const updated = current.last_updated
        ? new Date(current.last_updated).toLocaleString(undefined, {
            dateStyle: "medium",
            timeStyle: "short",
          })
        : "No stock changes recorded";
      const states = {
        synced: "Synced with Access",
        pending: "Sync pending",
        uninitialised: "Not linked",
        conflict: "Needs review",
        failed: "Sync needs attention",
      };
      document.querySelector("#stock-meta").textContent =
        `${states[current.sync_status] || current.sync_status} \u00b7 ${updated}`;
      document.querySelector("#stock-save").disabled = !current.writable;
      document.querySelector("#stock-add-location").hidden =
        !current.writable ||
        !["a", "b"].some((field) => current.state[field] === null);
      show(
        current.error ||
          (!current.writable
            ? "Stock editing is currently unavailable for this record."
            : ""),
        Boolean(current.error),
      );
      if (current.linked_product_url) {
        const link = document.createElement("a");
        link.href = current.linked_product_url;
        link.textContent = " View the linked Access product";
        message.append(link);
      }
      if (!current.state)
        document.querySelector("#stock-review p").textContent =
          "No confirmed quantities are available for this record.";
      review();
    } catch (error) {
      if (version !== loadVersion) return;
      document.querySelector("#stock-product").textContent =
        "Unable to load product";
      show(error.message, true);
      document.querySelector("#stock-save").disabled = true;
    } finally {
      if (version === loadVersion) form.setAttribute("aria-busy", "false");
    }
  }

  document.addEventListener("click", (event) => {
    const button = event.target.closest("[data-stock-edit]");
    if (button) open(button.dataset.stockEdit);
    if (event.target.closest("[data-dialog-close]")) dialog.close();
  });
  document
    .querySelector("#stock-add-location")
    .addEventListener("click", () => {
      if (!current?.writable) return;
      const field = ["a", "b"].find(
        (slot) => current.state[slot] === null && !addedSlots.has(slot),
      );
      if (!field) return;
      addedSlots.add(field);
      const wrapper = document.querySelector("#stock-" + field + "-field");
      const location = form.elements["location_" + field];
      wrapper.hidden = false;
      location.hidden = false;
      location.disabled = false;
      location.required = true;
      form.elements[field].disabled = false;
      form.elements[field].required = true;
      form.elements[field].value = "0";
      document.querySelector("#stock-" + field + "-label").textContent =
        `New location ${field.toUpperCase()}`;
      document.querySelector("#stock-add-location").hidden = !["a", "b"].some(
        (slot) => current.state[slot] === null && !addedSlots.has(slot),
      );
      location.focus();
      review();
    });
  form.addEventListener("input", review);
  form.addEventListener("change", (event) => {
    if (event.target.name === "mode" && current?.state) {
      for (const field of ["a", "b", "total"]) {
        if (!form.elements[field].disabled)
          form.elements[field].value =
            form.elements.mode.value === "adjust"
              ? 0
              : (current.state[field] ?? 0);
      }
    }
    review();
  });
  form.addEventListener("submit", async (event) => {
    event.preventDefault();
    if (!current?.writable || !form.reportValidity()) return;
    const button = document.querySelector("#stock-save");
    button.disabled = true;
    const values = Object.fromEntries(new FormData(form));
    const body = {
      event_id: values.event_id,
      revision: values.revision,
      mode: values.mode,
      a: values.a ?? current.state.a,
      b: values.b ?? current.state.b,
      total: values.total,
      reason: values.reason,
      location_a: values.location_a ?? current.state.location_a,
      location_b: values.location_b ?? current.state.location_b,
      reference: values.reference,
      note: values.note,
    };
    try {
      await request("/api/stock/" + encodeURIComponent(values.uid), {
        method: "POST",
        body: JSON.stringify(body),
      });
      show(
        "Request submitted. Another Admin must approve it in Stock Requests. Stock is unchanged.",
      );
      button.disabled = true;
    } catch (error) {
      show(error.message, true);
      button.disabled = !current?.writable;
    }
  });

  const recent = document.querySelector("#recent-stock-movements");
  if (recent)
    request("/api/stock/" + encodeURIComponent(recent.dataset.uid))
      .then((data) => {
        recent.querySelector("p").remove();
        if (!data.recent.length) {
          const empty = document.createElement("p");
          empty.className = "muted";
          empty.textContent = "No stock movements recorded yet.";
          recent.append(empty);
        }
        for (const movement of data.recent) {
          const row = document.createElement("div");
          row.className = "loc";
          row.textContent =
            `${movement.business_date} · ${movement.reason} · ${movement.username} · ` +
            `${movement.changes.map((c) => `${c.location}: ${c.previous} → ${c.new}`).join("; ")} · ${movement.sync_status}`;
          recent.append(row);
        }
      })
      .catch((error) => {
        recent.querySelector("p").textContent = error.message;
      });
})();
