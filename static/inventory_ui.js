document.addEventListener("click", (event) => {
  const button = event.target.closest("[data-qr]");
  if (!button) return;
  const panel = button.closest("td").querySelector(".qr-panel");
  panel.hidden = !panel.hidden;
  button.setAttribute("aria-expanded", String(!panel.hidden));
  if (!panel.hidden && !panel.firstChild) {
    const image = document.createElement("img");
    image.src = button.dataset.qrUrl;
    image.alt = "Product QR code";
    image.className = "qrimg";
    image.width = 84;
    image.height = 84;
    image.onerror = () => {
      panel.textContent = "QR could not load. Try again.";
    };
    panel.append(image);
  }
});
