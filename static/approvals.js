(() => {
  "use strict";
  const root = document.querySelector('[data-section="approvals"]');
  if (!root) return;
  const list = document.querySelector("#approval-list"),
    filter = document.querySelector("#approval-filter");
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
  let page = 1;
  async function api(path, body) {
    const response = await fetch(
      "/platform/api/stock-requests" + path,
      body
        ? {
            method: "POST",
            headers: {
              "Content-Type": "application/json",
              "X-CSRF-Token": root.dataset.csrf,
            },
            body: JSON.stringify(body),
          }
        : {},
    );
    const result = await response.json();
    if (!response.ok) throw Error(result.error || "Unable to load requests.");
    return result;
  }
  function element(tag, text, className) {
    const node = document.createElement(tag);
    node.textContent = text;
    if (className) node.className = className;
    return node;
  }
  function error(err) {
    message.className = "error";
    message.textContent = err.message;
  }
  async function load() {
    const data = await api(
      "?" + new URLSearchParams({ status: filter.elements.status.value, page }),
    );
    list.replaceChildren();
    if (!data.rows.length)
      list.append(element("div", "No requests to show.", "card empty-state"));
    for (const r of data.rows) {
      const card = element("article", "", "card approval-card");
      card.append(
        element("h2", r.product_name),
        element(
          "p",
          `${r.requested_username} · ${displayTimestamp(r.created_at)} · ${r.status}`,
          "muted",
        ),
      );
      const changes = element("div", "", "approval-changes");
      for (const c of r.changes)
        changes.append(
          element(
            "p",
            `${c.location || c.slot}: ${c.previous ?? "—"} → ${c.new ?? "—"}`,
          ),
        );
      card.append(
        changes,
        element(
          "p",
          `${r.reason}${r.reference ? " · " + r.reference : ""}${r.note ? " · " + r.note : ""}`,
        ),
      );
      if (r.reviewed_username)
        card.append(
          element(
            "p",
            `Reviewed by ${r.reviewed_username}${r.review_note ? ": " + r.review_note : ""}`,
            "muted",
          ),
        );
      if (
        r.status === "pending" &&
        data.can_approve &&
        data.user_id !== r.requested_by
      ) {
        const actions = element("div", "", "platform-toolbar");
        const note = document.createElement("input");
        note.placeholder = "Review note (required to reject)";
        note.maxLength = 1000;
        note.setAttribute("aria-label", "Review note");
        actions.append(note);
        for (const decision of ["approve", "reject"]) {
          const button = element(
            "button",
            decision === "approve" ? "Approve change" : "Reject",
            "btn" + (decision === "reject" ? " platform-secondary" : ""),
          );
          button.onclick = async () => {
            if (decision === "reject" && !note.value.trim()) {
              note.focus();
              error(Error("Provide a rejection reason."));
              return;
            }
            if (
              !confirm(
                `${decision === "approve" ? "Approve" : "Reject"} this stock request for ${r.product_name}?`,
              )
            )
              return;
            actions
              .querySelectorAll("button")
              .forEach((b) => (b.disabled = true));
            try {
              const result = await api(
                "/" + encodeURIComponent(r._id) + "/review",
                { decision, revision: r.revision, note: note.value },
              );
              message.className =
                result.request.status === "stale" ? "error" : "success";
              message.textContent =
                result.request.status === "approved"
                  ? "Approved. Stock updated online and queued for Access sync."
                  : result.request.review_note ||
                    "Request rejected. Stock is unchanged.";
              await load();
            } catch (err) {
              error(err);
              actions
                .querySelectorAll("button")
                .forEach((b) => (b.disabled = false));
            }
          };
          actions.append(button);
        }
        card.append(actions);
      } else if (r.status === "pending")
        card.append(
          element("p", "Waiting for another Admin to review.", "muted"),
        );
      list.append(card);
    }
    document.querySelector("#approval-count").textContent =
      `Page ${page} · ${data.total} requests`;
    document.querySelector("#approval-prev").disabled = page === 1;
    document.querySelector("#approval-next").disabled = page * 50 >= data.total;
  }
  filter.onsubmit = (event) => {
    event.preventDefault();
    page = 1;
    load().catch(error);
  };
  document.querySelector("#approval-prev").onclick = () => {
    page--;
    load().catch(error);
  };
  document.querySelector("#approval-next").onclick = () => {
    page++;
    load().catch(error);
  };
  load().catch(error);
})();
