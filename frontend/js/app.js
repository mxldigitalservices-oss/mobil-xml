import { Api } from './api.js';
import { State } from './state.js';
import { renderHeader } from './ui/header.js';
import { renderClones, bindClonesEvents } from './ui/clones.js';
import { loadTargets, bindTargetsEvents } from './ui/targets.js';
import { bindLogsEvents, logLine } from './ui/logs.js';
import { toast } from './ui/toasts.js';

const $ = (s) => document.querySelector(s);

async function checkHealth() {
  try {
    await Api.health();
    State.apiOnline = true;
  } catch {
    State.apiOnline = false;
  }
  renderHeader();
}

async function init() {
  renderClones();
  bindClonesEvents();
  bindTargetsEvents();
  bindLogsEvents();

  await checkHealth();
  await loadTargets();

  // Botón iniciar lote
  $('#btn-start-batch').addEventListener('click', async () => {
    if (!State.selected.size) return;
    const body = {
      clone_ids: [...State.selected],
      humanize: State.humanize,
      media_type: State.mediaType,
      action: State.action,
      payload: {},
    };
    try {
      const res = await Api.batchStart(body);
      State.queue += res.queued ?? 0;
      renderHeader();
      logLine(`Lote encolado: ${res.queued} tareas · media=${body.media_type} · humanize=${body.humanize}`, 'success');
      toast(`Lote iniciado (${res.queued})`, 'success');
    } catch (err) {
      logLine(`Error al iniciar lote: ${err.message}`, 'error');
      toast(`Error: ${err.message}`, 'error');
    }
  });

  // Botón emergencia
  $('#btn-emergency').addEventListener('click', async () => {
    const cloneIds = State.selected.size ? [...State.selected] : null;
    try {
      const res = await Api.emergencyStop({ reason: 'manual_emergency', clone_ids: cloneIds });
      State.queue = 0;
      renderHeader();
      logLine(`PARADA DE EMERGENCIA · detenidos=${res.stopped?.length ?? 0}`, 'warn');
      toast('Parada de emergencia ejecutada', 'error');
    } catch (err) {
      logLine(`Error en parada: ${err.message}`, 'error');
      toast(`Error: ${err.message}`, 'error');
    }
  });

  // Health cada 15s
  setInterval(checkHealth, 15000);

  logLine('Frontend inicializado.', 'info');
}

document.addEventListener('DOMContentLoaded', init);
