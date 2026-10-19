(() => {
  "use strict";

  const root = document.querySelector(".platform-page");
  if (!root) return;
  const section = root.dataset.section;
  const csrfToken = root.dataset.csrf;
  const message = document.querySelector("#platform-message");
  const displayTimestamp = (value) => {
    const parsed = new Date(value);
    if (!value || Number.isNaN(parsed.getTime())) return value || "—";
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

  function showMessage(text, isError = false) {
    if (!message) return;
    message.textContent = text || "";
    message.className = isError ? "error" : "success";
  }

  async function api(path, options = {}) {
    const response = await fetch(`/platform${path}`, {
      ...options,
      headers: {
        "Content-Type": "application/json",
        "X-CSRF-Token": csrfToken,
        ...options.headers,
      },
    });
    let data;
    try {
      data = await response.json();
    } catch {
      throw new Error("The server returned an invalid response.");
    }
    if (!response.ok) throw new Error(data.error || "Request failed.");
    return data;
  }

  function formValues(form) {
    const values = Object.fromEntries(new FormData(form));
    for (const input of form.querySelectorAll('input[type="checkbox"]')) {
      values[input.name] = input.checked;
    }
    return values;
  }

  function addCell(row, value) {
    const cell = document.createElement("td");
    cell.textContent = value ?? "—";
    row.append(cell);
    return cell;
  }

  function showEmptyRow(body, columns, text) {
    const row = document.createElement("tr");
    const cell = addCell(row, text);
    cell.colSpan = columns;
    cell.className = "empty-state";
    body.append(row);
  }

  function initUsers() {
    const body = document.querySelector("#users-body");
    const form = document.querySelector("#user-form");
    const activity = document.querySelector("#user-activity");
    const roleLabel=form.elements.role.closest('label');
    const pinLabel=document.createElement('label');
    pinLabel.innerHTML='Login PIN<input name="pin" type="password" inputmode="numeric" pattern="[0-9]{4,8}" minlength="4" maxlength="8" autocomplete="new-password" placeholder="4 to 8 digits"><small>Required for new accounts. Leave blank when editing to keep the current PIN.</small>';
    if(!document.querySelector('.demo-banner'))roleLabel.before(pinLabel);

    function resetForm() {
      form.reset();
      form.elements.id.value = "";
      if(form.elements.pin)form.elements.pin.value = "";
      form.elements.role.value = "worker";
      form.elements.active.checked = true;
      document.querySelector("#user-form-title").textContent = "Create account";
    }

    async function loadUsers() {
      const users = await api("/api/users");
      body.replaceChildren();
      for (const user of users) {
        const row = document.createElement("tr");
        addCell(row, user.username);
        addCell(row, user.display_name);
        addCell(row, user.role);
        addCell(row, user.active ? "Active" : "Inactive");
        addCell(row, displayTimestamp(user.created_at));
        addCell(row, displayTimestamp(user.last_login));
        const actions = addCell(row, "");

        const edit = document.createElement("button");
        edit.className = "btn";
        edit.textContent = "Edit";
        edit.onclick = () => {
          form.elements.id.value = user.id;
          form.elements.revision.value = user.revision;
          form.elements.username.value = user.username;
          form.elements.display_name.value = user.display_name;
          if(form.elements.pin)form.elements.pin.value = "";
          form.elements.role.value = user.role;
          form.elements.active.checked = user.active;
          document.querySelector("#user-form-title").textContent =
            "Edit account";
        };

        const viewActivity = document.createElement("button");
        viewActivity.className = "btn platform-secondary";
        viewActivity.textContent = "Activity";
        viewActivity.onclick = async () => {
          try {
            const events = await api(
              `/api/users/${encodeURIComponent(user.id)}/activity`,
            );
            activity.textContent = events.length
              ? events
                  .map(
                    (event) =>
                      `${displayTimestamp(event.timestamp)} · ${event.action} · ${event.username || ""}`,
                  )
                  .join("\n")
              : "No recorded activity.";
          } catch (error) {
            showMessage(error.message, true);
          }
        };

        const remove = document.createElement("button");
        remove.className = "btn platform-secondary";
        remove.textContent = "Delete";
        remove.onclick = async () => {
          if (
            !confirm(
              `Delete ${user.username}? Access will be removed. Historical records will remain.`,
            )
          )
            return;
          remove.disabled = true;
          try {
            const result = await api(
              `/api/users/${encodeURIComponent(user.id)}`,
              {
                method: "DELETE",
                body: JSON.stringify({ revision: user.revision }),
              },
            );
            showMessage(result.message);
            await loadUsers();
          } catch (error) {
            showMessage(error.message, true);
            remove.disabled = false;
          }
        };

        actions.append(edit, " ", viewActivity, " ", remove);
        body.append(row);
      }
    }

    form.onsubmit = async (event) => {
      event.preventDefault();
      const values = formValues(form);
      const id = values.id;
      values.revision = Number(values.revision || 0);
      delete values.id;
      try {
        await api(`/api/users${id ? `/${encodeURIComponent(id)}` : ""}`, {
          method: id ? "PUT" : "POST",
          body: JSON.stringify(values),
        });
        showMessage("Account saved.");
        resetForm();
        await loadUsers();
      } catch (error) {
        showMessage(error.message, true);
      }
    };

    document.querySelector("#user-reset").onclick = resetForm;
    loadUsers().catch((error) => showMessage(error.message, true));
  }

  function initSync() {
    const cards = document.querySelector("#sync-cards");
    const body = document.querySelector("#sync-body");
    const syncButton = document.querySelector("#sync-now");
    let loading = false;

    function addMetric(label, value, attribute = "") {
      const card = document.createElement("div");
      card.className = "metric";
      if (attribute) card.dataset[attribute] = "1";
      card.append(`${label}: `);
      const strong = document.createElement("strong");
      strong.textContent = value ?? "—";
      card.append(strong);
      cards.append(card);
    }

    async function refreshSync(force = false) {
      if (loading || (document.hidden && !force)) return;
      loading = true;
      try {
        const data = await api("/api/sync");
        const heartbeat = data.heartbeat || {};
        const progress =
          heartbeat.scan_progress ?? heartbeat.scanned_products ?? 0;
        const total = heartbeat.scan_total ?? heartbeat.total_products;
        const progressText =
          heartbeat.phase === "scanning_access"
            ? `${progress}${total ? ` / ${total}` : ""} products`
            : progress
              ? `${progress} products (last scan)`
              : "Waiting for worker";

        cards.replaceChildren();
        addMetric("Access", heartbeat.access || "No heartbeat");
        addMetric("MongoDB", data.mongo);
        addMetric(
          "Worker status",
          (heartbeat.phase || "unknown").replaceAll("_", " "),
        );
        addMetric("Scan progress", progressText, "scanProgress");
        addMetric("Worker heartbeat", heartbeat.heartbeat);
        addMetric("Last sync", heartbeat.last_success);
        addMetric("Pending", data.pending);
        addMetric("Failed", data.failed);
        addMetric("Conflicts", data.conflicts);
        addMetric("Duration (s)", heartbeat.duration_seconds);

        body.replaceChildren();
        if (!data.events.length)
          showEmptyRow(
            body,
            6,
            "All clear. No pending or failed stock changes.",
          );
        for (const syncEvent of data.events) {
          const row = document.createElement("tr");
          addCell(row, syncEvent._id);
          addCell(row, syncEvent.uid);
          addCell(row, syncEvent.status);
          addCell(row, syncEvent.attempts);
          addCell(
            row,
            `${syncEvent.error || ""}${syncEvent.observed_access ? ` · ${JSON.stringify(syncEvent.observed_access)}` : ""}`,
          );
          const actions = addCell(row, "");
          if (syncEvent.status === "conflict" && syncEvent.observed_access) {
            const retry = document.createElement("button");
            retry.className = "btn";
            retry.textContent = "Retry cloud values";
            retry.onclick = async () => {
              const note = prompt(
                "Reason for keeping the cloud values and retrying against this Access snapshot:",
              );
              if (!note) return;
              try {
                const result = await api(
                  `/api/sync/${encodeURIComponent(syncEvent._id)}/resolve`,
                  {
                    method: "POST",
                    body: JSON.stringify({
                      decision: "keep_cloud",
                      expected: syncEvent.observed_access,
                      note,
                    }),
                  },
                );
                showMessage(result.message);
                await refreshSync(true);
              } catch (error) {
                showMessage(error.message, true);
              }
            };
            actions.append(retry);
          }
          body.append(row);
        }
      } catch (error) {
        showMessage(error.message, true);
      } finally {
        loading = false;
      }
    }

    syncButton.textContent = "Force reconciliation";
    syncButton.onclick = async () => {
      syncButton.disabled = true;
      try {
        const result = await api("/api/sync/wake", {
          method: "POST",
          body: "{}",
        });
        showMessage(result.message);
        await refreshSync(true);
      } catch (error) {
        showMessage(error.message, true);
      } finally {
        syncButton.disabled = false;
      }
    };

    refreshSync(true);
    setInterval(refreshSync, 15000);
    document.addEventListener("visibilitychange", () => refreshSync());
    window.addEventListener("meadow:update", () => refreshSync(true));
  }

  function initSettings() {
    const accessibilityForm = document.querySelector("#accessibility-form");
    accessibilityForm.elements.theme.value =
      localStorage.getItem("app_theme") || "light";
    accessibilityForm.elements.text_size.value =
      localStorage.getItem("app_text_size") || "default";
    accessibilityForm.onchange = () => {
      const theme = accessibilityForm.elements.theme.value;
      const textSize = accessibilityForm.elements.text_size.value;
      localStorage.setItem("app_theme", theme);
      localStorage.setItem("app_text_size", textSize);
      document.documentElement.dataset.theme = theme;
      document.documentElement.dataset.textSize = textSize;
      showMessage("Accessibility settings saved.");
    };

    const policyForm = document.createElement("form");
    policyForm.id = "policy-form";
    policyForm.className = "card platform-form";
    policyForm.innerHTML =
      '<h2>Product replenishment policy</h2><label>Product UID<input name="uid" required></label><label>Lead time (days)<input name="lead_time" type="number" min="0" value="7"></label><label>Review period (days)<input name="review_period" type="number" min="1" value="7"></label><label>Minimum order<input name="minimum_order" type="number" min="0" value="0"></label><label>Order multiple<input name="order_multiple" type="number" min="1" value="1"></label><label>Service level %<input name="service_level" type="number" min="50" max="99" value="95"></label><label>Reorder threshold<input name="reorder_threshold" type="number" min="0" value="0"></label><button class="btn">Save policy</button>';
    root.append(policyForm);
    policyForm.onsubmit = async (event) => {
      event.preventDefault();
      try {
        const result = await api("/api/settings/product", {
          method: "POST",
          body: JSON.stringify(Object.fromEntries(new FormData(policyForm))),
        });
        showMessage(result.message);
      } catch (error) {
        showMessage(error.message, true);
      }
    };

    const companyForm = document.createElement("form");
    companyForm.className = "card platform-form";
    const fields = [
      "name",
      "registration",
      "address",
      "telephone",
      "fax",
      "email",
    ];
    companyForm.innerHTML =
      "<h2>Company document settings</h2>" +
      fields
        .map(
          (field) =>
            `<label>${field}<input name="${field}" ${field === "name" ? "required" : ""}></label>`,
        )
        .join("") +
      '<button class="btn">Save company settings</button>';
    root.append(companyForm);
    companyForm.onsubmit = async (event) => {
      event.preventDefault();
      try {
        const result = await api("/api/settings/company", {
          method: "POST",
          body: JSON.stringify(Object.fromEntries(new FormData(companyForm))),
        });
        showMessage(result.message);
      } catch (error) {
        showMessage(error.message, true);
      }
    };
  }

  function initAudit() {
    root.insertAdjacentHTML(
      "beforeend",
      '<form class="card platform-toolbar" id="audit-filter"><label>Action<input name="action"></label><label>User<input name="user"></label><button class="btn">Filter</button></form><div class="card table-wrap"><table><thead><tr><th>Timestamp</th><th>Action</th><th>User</th><th>Reference</th><th>Details</th></tr></thead><tbody id="audit-body"></tbody></table><p id="audit-count"></p></div>',
    );
    const form = document.querySelector("#audit-filter");
    const body = document.querySelector("#audit-body");
    async function loadAudit() {
      try {
        const data = await api(
          `/api/audit?${new URLSearchParams(new FormData(form))}`,
        );
        body.replaceChildren();
        for (const event of data.rows) {
          const row = document.createElement("tr");
          addCell(row, displayTimestamp(event.timestamp));
          addCell(row, event.action);
          addCell(row, event.username || event.user_id);
          addCell(
            row,
            event.event_id || event.request_id || event.target_user_id || "—",
          );
          addCell(row, JSON.stringify(event.values || event.reason || ""));
          body.append(row);
        }
        document.querySelector("#audit-count").textContent =
          `${data.total} audit events`;
      } catch (error) {
        showMessage(error.message, true);
      }
    }
    form.onsubmit = (event) => {
      event.preventDefault();
      loadAudit();
    };
    loadAudit();
  }

  ({
    users: initUsers,
    sync: initSync,
    settings: initSettings,
    audit: initAudit,
  })[section]?.();
})();
