// Reusable "type the name to confirm" modal (GitHub-repo-deletion style).
// confirmByName({ title, body, expected }) → Promise<boolean>

export function confirmByName({ title, body, expected, confirmLabel = 'Conferma' }) {
  return new Promise((resolve) => {
    const root = document.getElementById('modalRoot');
    root.innerHTML = `
      <div class="fixed inset-0 bg-black/60 flex items-center justify-center z-40">
        <div class="bg-slate-900 border border-slate-700 rounded-lg w-full max-w-md p-5 space-y-3">
          <h3 class="font-semibold text-rose-300">${title}</h3>
          <p class="text-sm text-slate-300">${body}</p>
          <input id="cbName" class="w-full rounded bg-slate-950 border border-slate-700 px-2 py-1 font-mono"
                 autocomplete="off" placeholder="${expected}" />
          <div class="flex justify-end gap-2 pt-2">
            <button id="cbCancel" class="text-sm px-3 py-1 rounded bg-slate-700 hover:bg-slate-600">Annulla</button>
            <button id="cbOk" disabled
              class="text-sm px-3 py-1 rounded bg-rose-700 hover:bg-rose-600 disabled:opacity-40 disabled:cursor-not-allowed">
              ${confirmLabel}
            </button>
          </div>
        </div>
      </div>`;
    const input = root.querySelector('#cbName');
    const ok    = root.querySelector('#cbOk');
    input.addEventListener('input', () => ok.disabled = input.value.trim() !== expected);
    input.focus();
    const close = (v) => { root.innerHTML = ''; resolve(v); };
    root.querySelector('#cbCancel').onclick = () => close(false);
    ok.onclick = () => close(true);
  });
}

// Simple alert-style modal for forms like Add Credential
export function openModal(html) {
  const root = document.getElementById('modalRoot');
  root.innerHTML = `
    <div class="fixed inset-0 bg-black/60 flex items-center justify-center z-40">
      <div class="bg-slate-900 border border-slate-700 rounded-lg w-full max-w-md p-5 space-y-3">
        ${html}
      </div>
    </div>`;
  return {
    close: () => { root.innerHTML = ''; },
    root,
  };
}
