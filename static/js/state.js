export const state = {
  query: "",
  selectedId: "",
  currentTaskType: "",
  lastAskContext: null,
};

export const els = {};

export function bindElements(map) {
  Object.assign(els, map);
}
