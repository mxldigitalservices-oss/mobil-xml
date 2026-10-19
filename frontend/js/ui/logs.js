const $ = (s) => document.querySelector(s);

export function logLine(message, level = 'info') {
  const box = $('#logs-console');
  const colors = {
    info:    'text-gray-200',
    success: 'text-emerald-300',
    warn:    'text-amber-300',
    error:   'text-red-300',
  };
  const line = document.createElement('div');
  line.className = colors[level] || colors.info;
  const ts = new Date().toLocaleTimeString();
  line.textContent = `[${ts}] ${message}`;
  box.appendChild(line);
  box.scrollTop = box.scrollHeight;
}

export function bindLogsEvents() {
  $('#btn-clear-logs').addEventListener('click', () => {
    $('#logs-console').innerHTML = `<div class="text-gray-400">[sistema] Consola limpia.</div>`;
  });
}
