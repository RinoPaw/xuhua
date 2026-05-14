export const state = {
  query: "",
  selectedId: "",
  currentTaskType: "",
  lastAskContext: null,
  sessionId: "",
};

export const els = {};

export function bindElements(map) {
  Object.assign(els, map);
}
