import { Api } from '../api.js';
import { State } from '../state.js';
import { toast } from './toasts.js';

const $ = (s) => document.querySelector(s);

export async function loadTargets() {
  try {
    const categories = ['VIDEO', 'AUDIO_STREAM', 'SOCIAL_PROFILE', 'PLAYLIST'];
    const lists = await Promise.all(categories.map(c => Api.listTargets(c).catch(() => [])));
    State.targets = lists.flat();
  } catch {
    State.targets = [];
  }
  renderTargets();
}

export function renderTargets() {
  const tbody = $('#targets-body');
  $('#targets-count').textContent = `${State.targets.length} registros`;

  if (!State.targets.length) {
    tbody.innerHTML = `<tr><td colspan="4" class="py-4 text-center text-sm text-gray-500">Sin objetivos todavía.</td></tr>`;
    return;
  }
  tbody.innerHTML = State.targets.map(t => `
    <tr class="hover:bg-cream/60">
      <td class="py-2 pr-3 max-w-[280px] truncate"><a href="${t.url}" target="_blank" rel="noopener" class="text-amber hover:underline">${t.url}</a></td>
      <td class="py-2 pr-3"><span class="text-[11px] uppercase tracking-wide px-2 py-0.5 rounded-full bg-amber-soft text-amber">${t.category}</span></td>
      <td class="py-2 pr-3 text-gray-600">${t.label ?? '—'}</td>
      <td class="py-2 pr-3 text-right">
        <button data-id="${t.id}" class="target-del text-xs text-coral hover:underline">Desactivar</button>
      </td>
    </tr>
  `).join('');

  tbody.querySelectorAll('.target-del').forEach(b => {
    b.addEventListener('click', () => {
      toast('Desactivación no disponible en backend (pendiente endpoint).', 'info');
    });
  });
}

export function bindTargetsEvents() {
  $('#target-form').addEventListener('submit', async (e) => {
    e.preventDefault();
    const fd = new FormData(e.target);
    const body = {
      url: fd.get('url'),
      category: fd.get('category'),
      label: fd.get('label') || null,
    };
    try {
      await Api.createTarget(body);
      toast('Objetivo agregado', 'success');
      e.target.reset();
      loadTargets();
    } catch (err) {
      toast(`Error: ${err.message}`, 'error');
    }
  });
}
