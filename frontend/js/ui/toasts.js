export function toast(message, type = 'info') {
  const wrap = document.getElementById('toasts');
  const palette = {
    info:    'bg-white border-amber-100 text-ink',
    success: 'bg-emerald-soft border-emerald text-emerald',
    error:   'bg-coral-soft border-coral text-coral',
  };
  const el = document.createElement('div');
  el.className = `toast px-4 py-2 rounded-xl border shadow-lift text-sm ${palette[type] || palette.info}`;
  el.textContent = message;
  wrap.appendChild(el);
  setTimeout(() => el.remove(), 3500);
}
