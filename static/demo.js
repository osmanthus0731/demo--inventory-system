document
  .querySelector("#demo-access")
  ?.addEventListener("click", async function () {
    this.disabled = true;
    const message = document.querySelector("#demo-message");
    try {
      const response = await fetch("/demo/simulate-access", {
        method: "POST",
        headers: { "X-CSRF-Token": this.dataset.token },
      });
      if (!response.ok)
        throw Error("Simulation failed. Sign in as a demo Admin.");
      message.textContent = (await response.json()).message;
    } catch (err) {
      message.textContent = err.message;
    } finally {
      this.disabled = false;
    }
  });
