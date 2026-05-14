import { els, state } from './state.js';
import { pickSuggestionQueries } from './consts.js';
import { renderRelatedItems, fetchJson } from './search.js';
import { renderSuggestionStrip, askQuestion } from './ask.js';

export function resizeQuestionInput() {
  els.questionInput.style.height = "auto";
  const styles = window.getComputedStyle(els.questionInput);
  const maxHeight = Number.parseFloat(styles.maxHeight) || 132;
  const nextHeight = Math.min(els.questionInput.scrollHeight, maxHeight);
  els.questionInput.style.height = `${nextHeight}px`;
  els.questionInput.classList.toggle("is-scrollable", els.questionInput.scrollHeight > maxHeight + 1);
}

export function handleQuestionInput() {
  resizeQuestionInput();
}

export function bindQueryChips(scope) {
  scope?.querySelectorAll?.(".query-chip[data-query]")?.forEach((button) => {
    button.addEventListener("click", () => {
      els.questionInput.value = button.dataset.query || "";
      resizeQuestionInput();
      if (button.dataset.submit !== "0") {
        askQuestion();
      } else {
        els.questionInput.focus();
      }
    });
  });
}

export function renderQuerySuggestions() {
  if (!els.querySuggestions) {
    return;
  }
  els.querySuggestions.innerHTML = renderSuggestionStrip(pickSuggestionQueries(6), { submit: true });
  bindQueryChips(els.querySuggestions);
}

export function syncRestoredQuestion() {
  resizeQuestionInput();
  const restoredQuery = els.questionInput.value.trim();
  if (!restoredQuery) {
    renderRelatedItems([]);
  }
}

export async function loadMeta() {
  try {
    const data = await fetchJson("/api/meta");
    els.metaText.textContent = `${data.item_count} 项 · ${data.category_count} 类`;
  } catch {
    els.metaText.textContent = "资料库已就绪";
  }
}
