(() => {
  "use strict";
  const cache = new Map();
  document
    .querySelectorAll(".product-autocomplete, .product-lookup")
    .forEach((wrapper) => {
      const input = wrapper.querySelector("input");
      const list = wrapper.querySelector(".product-suggestions");
      if (!input || !list) return;
      let timer,
        controller,
        active = -1,
        items = [];
      const close = () => {
        list.hidden = true;
        list.replaceChildren();
        active = -1;
        input.setAttribute("aria-expanded", "false");
      };
      const choose = (item) => {
        input.value = item.uid || item.name;
        close();
        input.dispatchEvent(new Event("change", { bubbles: true }));
        if (wrapper.classList.contains("product-autocomplete"))
          input.form?.requestSubmit();
        else input.focus();
      };
      const render = (results) => {
        items = results;
        list.replaceChildren();
        active = -1;
        if (!items.length) {
          const empty = document.createElement("span");
          empty.className = "product-suggestions-empty";
          empty.textContent = "No matching products.";
          list.append(empty);
        }
        items.forEach((item, index) => {
          const option = document.createElement("button");
          option.type = "button";
          option.className = "product-suggestion";
          option.setAttribute("role", "option");
          option.id = `product-suggestion-${index}`;
          const name = document.createElement("strong");
          name.textContent = item.name || "Unnamed product";
          const detail = document.createElement("small");
          detail.textContent = [item.uid, item.readable_id]
            .filter(Boolean)
            .join(" · ");
          option.append(name, detail);
          option.onpointerdown = (e) => {
            e.preventDefault();
            choose(item);
          };
          list.append(option);
        });
        list.hidden = false;
        input.setAttribute("aria-expanded", "true");
      };
      const search = async () => {
        const q = input.value.trim();
        if (!q) {
          close();
          return;
        }
        const key = q.toLowerCase();
        if (cache.has(key)) {
          render(cache.get(key));
          return;
        }
        controller?.abort();
        controller = new AbortController();
        try {
          const response = await fetch(
            "/api/products/suggest?q=" + encodeURIComponent(q),
            { signal: controller.signal },
          );
          if (!response.ok) throw Error();
          const results = await response.json();
          cache.set(key, results);
          render(results);
        } catch (error) {
          if (error.name !== "AbortError") close();
        }
      };
      input.addEventListener("input", () => {
        clearTimeout(timer);
        timer = setTimeout(search, 100);
      });
      input.addEventListener("keydown", (event) => {
        const options = [...list.querySelectorAll('[role="option"]')];
        if (event.key === "ArrowDown" || event.key === "ArrowUp") {
          event.preventDefault();
          if (!options.length) {
            search();
            return;
          }
          active =
            (active + (event.key === "ArrowDown" ? 1 : -1) + options.length) %
            options.length;
          options.forEach((o, i) => o.classList.toggle("active", i === active));
          options[active].scrollIntoView({ block: "nearest" });
        } else if (event.key === "Enter" && active >= 0) {
          event.preventDefault();
          choose(items[active]);
        } else if (event.key === "Escape") close();
      });
      input.addEventListener("focus", () => {
        if (input.value.trim() && !list.children.length) search();
      });
      document.addEventListener("pointerdown", (event) => {
        if (!wrapper.contains(event.target)) close();
      });
    });
})();
