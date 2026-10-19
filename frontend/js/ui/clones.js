import { State } from '../state.js';
import { renderHeader } from './header.js';

const $ = (s) => document.querySelector(s);

export function renderClones() {
  const list = $('#clones-list');
  if (!State.clones.length) {
    list.innerHTML = `<p class="text-sm text-gray-500">No hay clones registrados.</p>`;
    return;
  }
  list.innerHTML = State.clones.map(c => `
    <label class="flex items-center gap-3 p-3 rounded-xl border ${c.active ? 'border-amber-100 bg-white' : 'border-gray-100 bg-gray-50 opacity-70'} shadow-card cursor-pointer hover:border-amber/60 transition">
      <input type="checkbox" data-id="${c.id}" ${State.selected.has(c.id) ? 'checked' : ''} ${c.active ? '' : 'disabled'} class="clone-check w-4 h-4 rounded accent-amber" />
      <div class="flex-1 min-w-0">
        <p class="text-sm font-medium truncate">${c.name}</p>
        <p class="text-xs text-gray-500">${c.id}</p>
      </div>
      <span class="text-[10px] uppercase tracking-wide px-2 py-0.5 rounded-full ${c.active ? 'bg-emerald-soft text-emerald' : 'bg-gray-100 text-gray-500'}">
        ${c.active ? 'activo' : 'inactivo'}
      </span>
    </label>
  `).join('');

  list.querySelectorAll('.clone-check').forEach(cb => {
    cb.addEventListener('change', (e) => {
      const id = e.target.dataset.id;
      if (e.target.checked) State.selected.add(id);
      else State.selected.delete(id);
      renderHeader();
      toggleStartButton();
    });
  });

  toggleStartButton();
}

function toggleStartButton() {
  const btn = $('#btn-start-batch');
  const disabled = State.selected.size === 0;
  btn.disabled = disabled;
  btn.classList.toggle('opacity-50', disabled);
}

export function bindClonesEvents() {
  $('#btn-refresh').addEventListener('click', renderClones);

  $('#select-media').addEventListener('change', (e) => (State.mediaType = e.target.value));
  $('#select-action').addEventListener('change', (e) => (State.action   = e.target.value));
  $('#toggle-humanize').addEventListener('change', (e) => (State.humanize = e.target.checked));
}
