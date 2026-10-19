/* Shared, cancellable product lookup for dynamically added document rows. */
window.bindDocumentLookup = (input, list, endpoint, select) => {
  let timer, controller, generation = 0, active = -1, choices = [];
  const close = () => {
    clearTimeout(timer); controller?.abort(); generation++;
    list.hidden = true; active = -1;
    input.setAttribute('aria-expanded', 'false');
  };
  const choose = choice => { close(); select(choice); input.focus(); };
  input.setAttribute('aria-autocomplete', 'list');
  list.setAttribute('role', 'listbox');
  list.hidden = true;
  input.oninput = () => {
    close();
    const query = input.value.trim(), current = generation;
    if (query.length < 2) return;
    timer = setTimeout(async () => {
      controller = new AbortController();
      try {
        const response = await fetch(endpoint + encodeURIComponent(query), {signal: controller.signal});
        if (!response.ok) throw Error('Search unavailable');
        const data = await response.json();
        if (current !== generation || !input.isConnected) return;
        choices = data;
        list.replaceChildren(...choices.map(choice => {
          const button = document.createElement('button');
          button.type = 'button'; button.setAttribute('role', 'option');
          button.textContent = (choice.description || choice.name) + ' · ' + (choice.uid || choice.product_id);
          button.onpointerdown = event => event.preventDefault();
          button.onclick = () => choose(choice);
          return button;
        }));
        list.hidden = !choices.length;
        input.setAttribute('aria-expanded', String(choices.length > 0));
      } catch (error) { if (current === generation && error.name !== 'AbortError') close(); }
    }, 180);
  };
  input.addEventListener('keydown', event => {
    if (event.key === 'Escape') { close(); return; }
    if (list.hidden) return;
    if (event.key === 'Enter' && active >= 0) { event.preventDefault(); choose(choices[active]); }
    else if (event.key === 'ArrowDown' || event.key === 'ArrowUp') {
      event.preventDefault();
      active = (active + (event.key === 'ArrowDown' ? 1 : -1) + choices.length) % choices.length;
      [...list.children].forEach((button, index) => button.setAttribute('aria-selected', String(index === active)));
      list.children[active]?.scrollIntoView({block: 'nearest'});
    }
  });
  input.addEventListener('blur', () => { timer = setTimeout(close, 150); });
  list.addEventListener('dismiss', close);
};
