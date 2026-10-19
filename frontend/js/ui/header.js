import { State } from '../state.js';

const $ = (s) => document.querySelector(s);

export function renderHeader() {
  const apiEl = $('#api-status');
  if (State.apiOnline) {
    apiEl.className = 'inline-flex items-center gap-1.5 px-3 py-1.5 rounded-full text-xs font-medium bg-emerald-soft text-emerald';
    apiEl.innerHTML = '<span class="w-2 h-2 rounded-full bg-emerald animate-pulse"></span> API Online';
  } else {
    apiEl.className = 'inline-flex items-center gap-1.5 px-3 py-1.5 rounded-full text-xs font-medium bg-coral-soft text-coral';
    apiEl.innerHTML = '<span class="w-2 h-2 rounded-full bg-coral"></span> API Offline';
  }
  $('#stat-active').textContent = State.clones.filter(c => c.active).length;
  $('#stat-queue').textContent  = State.queue;
}
