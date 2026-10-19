export const State = {
  clones: [
    { id: 'emu-1', name: 'Redroid #1', active: true  },
    { id: 'emu-2', name: 'Redroid #2', active: true  },
    { id: 'emu-3', name: 'Redroid #3', active: false },
  ],
  selected: new Set(),
  targets: [],
  mediaType: 'video',
  action: 'sleep',
  humanize: true,
  apiOnline: false,
  queue: 0,
};
