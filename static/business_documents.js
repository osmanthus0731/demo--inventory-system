(() => {
  "use strict";
  const app = document.querySelector("#document-app"),
    view = document.querySelector("#document-view");
  async function json(response) {
    const data = await response.json().catch(() => ({}));
    if (!response.ok) throw new Error(data.error || "Action failed.");
    return data;
  }
  if (app) {
    const dismissSuggestions=(target)=>{for(const list of app.querySelectorAll('.document-results'))if(!target||!list.closest('.po-item')?.contains(target))list.dispatchEvent(new Event('dismiss'));};
    document.addEventListener('pointerdown',event=>dismissSuggestions(event.target));
    document.addEventListener('keydown',event=>{if(event.key==='Escape')dismissSuggestions();});
    const form = document.querySelector("#document-form"),
      items = document.querySelector("#document-items"),
      message = document.querySelector("#document-message"),
      initial = JSON.parse(
        document.querySelector("#document-data").textContent,
      ),
      preview = document.querySelector("#document-preview");
    const read = () => {
      const values = Object.fromEntries(new FormData(form));
      return {
        revision: Number(app.dataset.revision) || undefined,
        party: {
          record_id: values.party_record_id || '',
          name: values.party_name,
          details: values.party_details,
          address: values.party_address,
          contact: values.party_contact,
          shipping_name: values.party_shipping_name,
          shipping_address: values.party_shipping_address,
          shipping_contact: values.party_shipping_contact,
        },
        date: values.date,
        valid_until: values.valid_until,
        delivery_date: values.delivery_date,
        reference: values.reference,
        currency: values.currency,
        ...(app.dataset.kind === 'proforma' ? {payment_status: values.payment_status || initial.payment_status || 'unpaid'} : {}),
        remarks: values.remarks,
        terms: values.terms,
        items: [...items.children].map((row) =>
          Object.fromEntries(
            [...row.querySelectorAll("[data-k]")].map((input) => [
              input.dataset.k,
              input.value,
            ]),
          ),
        ),
      };
    };
    let previewTimer,
      previewGeneration = 0,
      previewUrl, previewController, previewPayload;
    function render() {
      clearTimeout(previewTimer);
      previewController?.abort();
      const generation = ++previewGeneration,
        status = document.querySelector("#document-preview-status");
      status.textContent = "Updating actual PDF preview...";
      previewTimer = setTimeout(async () => {
        const payload=JSON.stringify(read());
        if(payload===previewPayload){status.textContent='Preview up to date';return;}
        if(!form.checkValidity()){status.textContent='Complete customer and item details to preview.';return;}
        previewController=new AbortController();
        try {
          const response = await fetch(
            "/documents/api/" + app.dataset.kind + "/preview",
            {
              method: "POST",
              signal: previewController.signal,
              headers: {
                "Content-Type": "application/json",
                "X-CSRF-Token": app.dataset.csrf,
              },
              body: payload,
            },
          );
          if (!response.ok) {
            const error = await response.json().catch(() => ({}));
            throw Error(error.error || "Preview failed.");
          }
          const blob = await response.blob();
          if (generation !== previewGeneration) return;
          previewPayload=payload;
          if (previewUrl) URL.revokeObjectURL(previewUrl);
          previewUrl = URL.createObjectURL(blob);
          const frame = document.createElement("iframe");
          frame.className = "document-pdf-preview";
          frame.title = "Actual " + app.dataset.kind + " PDF preview";
          frame.src = previewUrl + "#toolbar=0&navpanes=0&view=FitH";
          preview.replaceChildren(frame);
          status.textContent = "Actual PDF format - preview up to date";
        } catch (error) {
          if (generation === previewGeneration && error.name !== 'AbortError')
            status.textContent = error.message;
        }
      }, 650);
    }
    window.addEventListener("beforeunload", () => {
      if (previewUrl) URL.revokeObjectURL(previewUrl);
    });
    const partySelect=document.querySelector('#party-select'),partySearch=document.querySelector('#party-search'),partyStatus=document.querySelector('#party-status');
    let savedParties=[];
    function showParties(){
      const query=partySearch.value.toLowerCase().trim(),chosen=form.elements.party_record_id.value;
      partySelect.replaceChildren(new Option('Select a customer / enter a new customer',''));
      for(const party of savedParties.filter(p=>[p.customer_code,p.name,p.address,p.contact,p.details].join(' ').toLowerCase().includes(query)))
        partySelect.append(new Option((party.customer_code?party.customer_code+' - ':'')+party.name+(party.address?' — '+party.address.split('\n')[0]:''),party.record_id));
      partySelect.value=[...partySelect.options].some(o=>o.value===chosen)?chosen:'';
    }
    async function loadParties(){
      try{const data=await json(await fetch('/documents/api/parties?kind='+encodeURIComponent(app.dataset.kind)));savedParties=data.rows;showParties();partyStatus.textContent=savedParties.length?'Select a saved contact to fill the fields below.':'No saved contacts yet. Enter the details below and save them for reuse.';}
      catch(error){partySelect.replaceChildren(new Option('Enter customer details below',''));partyStatus.textContent='Could not load saved contacts. '+error.message;}
    }
    partySearch.oninput=showParties;
    partySelect.onchange=()=>{
      const party=savedParties.find(p=>p.record_id===partySelect.value);
      form.elements.party_record_id.value=party?.record_id||'';
      if(party){for(const key of ['name','details','address','contact','shipping_name','shipping_address','shipping_contact'])form.elements['party_'+key].value=party[key]||'';if(party.currency && /^[A-Z]{3}$/.test(party.currency)) form.elements.currency.value=party.currency;
      if(party.terms) form.elements.terms.value=party.terms;
      partyStatus.textContent='Customer details filled. Review billing and shipping addresses before saving.';render();}
    };
    document.querySelector('#party-save').onclick=async()=>{
      const button=document.querySelector('#party-save');button.disabled=true;
      try{const data=await json(await fetch('/documents/api/parties',{method:'POST',headers:{'Content-Type':'application/json','X-CSRF-Token':app.dataset.csrf},body:JSON.stringify(read().party)}));form.elements.party_record_id.value=data.record_id;partySearch.value='';await loadParties();partyStatus.textContent='Customer saved. Available for Delivery Orders and Proforma Invoices.';}
      catch(error){partyStatus.textContent=error.message;}finally{button.disabled=false;}
    };
    loadParties();
    function tierPrice(tiers, quantity) {
      const levels = [
          ["10K", 10000],
          ["5K", 5000],
          ["3K", 3000],
          ["1K", 1000],
          ["S500", 500],
          ["S100", 100],
          ["S12", 12],
        ],
        match =
          levels.find(([, minimum]) => quantity >= minimum) || levels.at(-1);
      let tier = match[0],
        value = tiers?.[tier];
      if (tier === "10K" && !(Number(value) > 0)) {
        tier = "5K";
        value = tiers?.[tier];
      }
      return { tier, value };
    }
    function add(data = {}) {
      const row = document.createElement("div");
      row.className = "card po-item";
      row.innerHTML =
        '<label>Product UID<input data-k="uid" autocomplete="off"><span class="document-results"></span></label><label>Description<input data-k="description" required></label><label>Quantity<input data-k="quantity" value="1" required></label><label>Unit price<input data-k="unit_price" value="0.0000" required><small class="document-price-status">Select a product to load its selling tier.</small></label><label>Discount<input data-k="discount" value="0"></label><label>Tax %<input data-k="tax" value="0"></label><label>Location<input data-k="location"></label><button type="button" class="btn document-remove">Remove item</button>';
      for (const input of row.querySelectorAll("[data-k]"))
        if (data[input.dataset.k] != null) input.value = data[input.dataset.k];
      row.querySelector(".document-remove").onclick = () => {
        row.remove();
        render();
      };
      const uid = row.querySelector('[data-k="uid"]'),
        qty = row.querySelector('[data-k="quantity"]'),
        price = row.querySelector('[data-k="unit_price"]'),
        status = row.querySelector(".document-price-status"),
        results = row.querySelector(".document-results");
      let tiers, priceRequest, priceGeneration=0;
      results.hidden=true;
      uid.setAttribute('aria-autocomplete','list');
      async function applyPrice() {
        if (!uid.value) return;
        const current=++priceGeneration,product=uid.value;
        try {
          if(!tiers){
            if(!priceRequest || priceRequest.product!==product)priceRequest={product,promise:fetch('/api/pricing/'+encodeURIComponent(product)).then(json).then(data=>data.S)};
            const loaded=await priceRequest.promise;
            if(current!==priceGeneration||product!==uid.value||!row.isConnected)return;
            tiers=loaded;
          }
          const selected = tierPrice(tiers, Number(qty.value) || 0);
          if (selected.value != null) {
            price.value = Number(selected.value).toFixed(4);
            status.textContent = `${selected.tier} selling tier selected automatically for ${Number(qty.value || 0).toLocaleString()} pieces.`;
          } else
            status.textContent = `No ${selected.tier} selling price is available; enter the agreed price.`;
          render();
        } catch (_) {
          if(current!==priceGeneration)return;
          priceRequest=null;
          status.textContent =
            "Pricing could not be loaded; enter the agreed price.";
          render();
        }
      }
      const description=row.querySelector('[data-k="description"]');
      description.autocomplete='off';
      const descriptionResults=document.createElement('span');
      descriptionResults.className='document-results';
      description.after(descriptionResults);
      const selectProduct=choice=>{
        uid.value=choice.uid;description.value=choice.description;tiers=null;
        results.hidden=true;descriptionResults.hidden=true;
        applyPrice();
      };
      window.bindDocumentLookup(uid,results,'/documents/api/products?q=',selectProduct);
      window.bindDocumentLookup(description,descriptionResults,'/documents/api/products?q=',selectProduct);
      qty.addEventListener("input", applyPrice);
      items.append(row);
      if (uid.value && (Number(price.value) || 0) === 0) applyPrice();
    }
    document.querySelector("#document-add").onclick = () => {
      add();
      render();
    };
    (initial.items || []).forEach(add);
    if (!initial.items?.length) add();
    form.addEventListener("input", render);
    render();
    form.onsubmit = async (event) => {
      event.preventDefault();
      message.textContent = "Saving...";
      try {
        const editing = Boolean(app.dataset.number),
          data = await json(
            await fetch(
              "/documents/api/" +
                app.dataset.kind +
                (editing ? "/" + encodeURIComponent(app.dataset.number) : ""),
              {
                method: editing ? "PUT" : "POST",
                headers: {
                  "Content-Type": "application/json",
                  "X-CSRF-Token": app.dataset.csrf,
                },
                body: JSON.stringify(read()),
              },
            ),
          );
        location.href =
          "/documents/" +
          app.dataset.kind +
          "/" +
          encodeURIComponent(data.number);
      } catch (error) {
        message.textContent = error.message;
      }
    };
  }
  if (view) {
    if(view.dataset.kind==='proforma'){
      const panel=document.createElement('div');panel.className='card platform-toolbar';
      const label=document.createElement('strong');label.textContent='Payment: '+(view.dataset.paymentStatus==='paid'?'Paid':'Unpaid');panel.append(label);
      const button=document.createElement('button');button.type='button';button.className='btn platform-secondary';
      button.textContent=view.dataset.paymentStatus==='paid'?'Mark unpaid':'Mark paid';
      button.onclick=()=>action('payment',{payment_status:view.dataset.paymentStatus==='paid'?'unpaid':'paid',revision:Number(view.dataset.revision)});
      if(view.dataset.paymentEdit==='1')panel.append(button);view.querySelector('article').before(panel);
    }
    async function action(name, body = {}) {
      try {
        const data = await json(
          await fetch(
            "/documents/api/" +
              view.dataset.kind +
              "/" +
              encodeURIComponent(view.dataset.number) +
              "/" +
              name,
            {
              method: "POST",
              headers: {
                "Content-Type": "application/json",
                "X-CSRF-Token": view.dataset.csrf,
              },
              body: JSON.stringify(body),
            },
          ),
        );
        if (name === "dispatch") {
          alert(data.message);
          location.reload();
          return;
        }
        if (name === "convert") {
          location.href =
            "/documents/" +
            (view.dataset.kind === "quotation" ? "proforma" : "delivery") +
            "/" +
            encodeURIComponent(data.number);
          return;
        }
        location.reload();
      } catch (error) {
        alert(error.message);
      }
    }
    view
      .querySelector("[data-convert]")
      ?.addEventListener("click", () => action("convert"));
    view
      .querySelector("[data-duplicate]")
      ?.addEventListener("click", () => action("duplicate"));
    view.querySelector("[data-dispatch]")?.addEventListener("click", () => {
      if (confirm("Confirm dispatch and queue inventory deduction?"))
        action("dispatch");
    });
    for (const button of view.querySelectorAll("[data-status]"))
      button.addEventListener("click", () => {
        if (confirm("Change status to " + button.dataset.status + "?"))
          action("status", {
            status: button.dataset.status,
            revision: Number(view.dataset.revision),
          });
      });
  }
})();
