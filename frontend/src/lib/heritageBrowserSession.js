import { apiEndpoint, normalizeApiBase } from "./apiEndpoint.js";
import {
  mergePageItems,
  nextPageState,
  pageLimitForState,
  PROJECT_PAGE_SIZE,
} from "./pagination.js";

function noop() {}

function fallbackMeta() {
  return { levels: [], capabilities: { realtime_voice: false } };
}

function initialPageState() {
  return {
    key: "",
    nextOffset: 0,
    startOffset: 0,
    wrapped: false,
    hasMore: true,
    error: false,
    loading: false,
    requestId: 0,
  };
}

export function initialHeritageBrowserState() {
  return {
    searchDraft: "",
    searchQuery: "",
    filters: { category: "", level: "" },
    items: [],
    total: 0,
    hasMoreItems: false,
    categories: [],
    meta: null,
    loading: true,
    searchError: "",
    selected: null,
    detailLoading: false,
    detailError: "",
  };
}

export class HeritageBrowserSession {
  constructor({
    apiBase = "",
    fetchFn = globalThis.fetch,
    promptSeed = 0,
    onChange = noop,
  } = {}) {
    this.apiBase = normalizeApiBase(apiBase);
    this.fetchFn = fetchFn;
    this.promptSeed = Number(promptSeed) || 0;
    this.onChange = onChange;
    this.state = initialHeritageBrowserState();
    this.searchController = null;
    this.searchGeneration = 0;
    this.detailController = null;
    this.bootstrapController = null;
    this.page = initialPageState();
    this.started = false;
    this.destroyed = false;
  }

  snapshot() {
    return {
      ...this.state,
      filters: { ...this.state.filters },
      items: [...this.state.items],
      categories: [...this.state.categories],
    };
  }

  emit() {
    if (!this.destroyed) this.onChange(this.snapshot());
  }

  patch(next) {
    this.state = { ...this.state, ...next };
    this.emit();
  }

  setApiBase(value) {
    this.apiBase = normalizeApiBase(value);
  }

  setPromptSeed(value) {
    this.promptSeed = Number(value) || 0;
  }

  url(path) {
    return apiEndpoint(this.apiBase, path);
  }

  async loadMeta(signal) {
    try {
      const response = await this.fetchFn(this.url("/api/meta"), { signal });
      if (!response?.ok) throw new Error("meta_failed");
      this.patch({ meta: await response.json() });
    } catch (error) {
      if (error?.name !== "AbortError") this.patch({ meta: fallbackMeta() });
    }
  }

  async loadCategories(signal) {
    try {
      const response = await this.fetchFn(this.url("/api/categories"), { signal });
      if (!response?.ok) throw new Error("categories_failed");
      const categories = await response.json();
      this.patch({ categories: Array.isArray(categories) ? categories : [] });
    } catch (error) {
      if (error?.name !== "AbortError") this.patch({ categories: [] });
    }
  }

  async start() {
    if (this.started || this.destroyed) return false;
    this.started = true;
    const controller = new AbortController();
    this.bootstrapController = controller;
    await Promise.allSettled([
      this.loadMeta(controller.signal),
      this.loadCategories(controller.signal),
    ]);
    if (this.destroyed || this.bootstrapController !== controller) return false;
    this.bootstrapController = null;
    await this.reload();
    return true;
  }

  searchKey() {
    return JSON.stringify([
      this.state.searchQuery,
      this.state.filters.category,
      this.state.filters.level,
    ]);
  }

  async reload() {
    if (this.destroyed || typeof this.fetchFn !== "function") return false;
    this.searchGeneration += 1;
    const requestId = this.searchGeneration;
    this.searchController?.abort();
    const controller = new AbortController();
    this.searchController = controller;

    const initialBrowse = !this.state.searchQuery
      && !this.state.filters.category
      && !this.state.filters.level;
    const itemCount = Math.max(0, Number(this.state.meta?.item_count) || 0);
    const startOffset = initialBrowse && itemCount > PROJECT_PAGE_SIZE
      ? this.promptSeed % (itemCount - PROJECT_PAGE_SIZE + 1)
      : 0;
    const key = this.searchKey();
    this.page = {
      key,
      nextOffset: startOffset,
      startOffset,
      wrapped: false,
      hasMore: true,
      error: false,
      loading: true,
      requestId,
    };
    this.patch({
      items: [],
      total: 0,
      hasMoreItems: true,
      loading: true,
      searchError: "",
    });
    return this.fetchPage({ controller, requestId, key, reset: true });
  }

  async fetchPage({ controller, requestId, key, reset = false }) {
    const page = this.page;
    const offset = page.nextOffset;
    const limit = pageLimitForState(page);
    const query = new URLSearchParams({
      q: this.state.searchQuery,
      category: this.state.filters.category,
      level: this.state.filters.level,
      limit: String(limit),
      offset: String(offset),
    });

    try {
      const response = await this.fetchFn(this.url(`/api/items?${query}`), {
        signal: controller.signal,
      });
      if (!response?.ok) throw new Error("search_failed");
      const data = await response.json();
      if (this.destroyed
        || requestId !== this.searchGeneration
        || this.page.key !== key
        || this.searchController !== controller) return false;

      const incoming = Array.isArray(data.items) ? data.items : [];
      const next = nextPageState({
        offset: Number(data.offset ?? offset),
        limit: Number(data.limit ?? PROJECT_PAGE_SIZE),
        total: Number(data.total || 0),
        received: incoming.length,
        startOffset: this.page.startOffset,
        wrapped: this.page.wrapped,
      });
      const items = reset
        ? mergePageItems([], incoming)
        : mergePageItems(this.state.items, incoming);
      this.page = {
        ...this.page,
        nextOffset: next.nextOffset,
        wrapped: next.wrapped,
        hasMore: next.hasMore,
        error: false,
        loading: false,
      };
      this.patch({
        items,
        total: Number(data.total || 0),
        hasMoreItems: next.hasMore,
        loading: false,
        searchError: "",
      });
      return true;
    } catch (error) {
      if (error?.name === "AbortError") return false;
      if (requestId !== this.searchGeneration
        || this.page.key !== key
        || this.searchController !== controller) return false;
      this.page = { ...this.page, loading: false, error: true };
      this.patch({
        loading: false,
        hasMoreItems: false,
        searchError: "加载失败",
      });
      return false;
    } finally {
      if (this.searchController === controller && !this.page.loading) {
        this.searchController = null;
      }
    }
  }

  async loadMore() {
    if (this.destroyed) return false;
    if (this.page.loading || (!this.page.hasMore && !this.page.error)) return false;
    const key = this.searchKey();
    if (this.page.key !== key) return this.reload();

    const requestId = this.searchGeneration;
    const controller = new AbortController();
    this.searchController = controller;
    this.page = { ...this.page, loading: true, error: false };
    this.patch({ loading: true, searchError: "" });
    return this.fetchPage({ controller, requestId, key, reset: false });
  }

  setSearchDraft(value) {
    const searchDraft = String(value ?? "");
    const shouldClear = !searchDraft.trim() && this.state.searchQuery;
    this.patch({ searchDraft });
    if (shouldClear) {
      this.state = { ...this.state, searchQuery: "" };
      void this.reload();
    }
  }

  submitSearch() {
    const searchQuery = this.state.searchDraft.trim();
    this.state = { ...this.state, searchQuery };
    void this.reload();
  }

  applyFilters(next) {
    this.closeItem();
    this.state = {
      ...this.state,
      searchQuery: this.state.searchDraft.trim(),
      filters: {
        category: String(next?.category || ""),
        level: String(next?.level || ""),
      },
    };
    this.emit();
    void this.reload();
  }

  retryItems() {
    if (!this.page.error) return false;
    this.page = { ...this.page, error: false, hasMore: true };
    this.patch({ searchError: "", hasMoreItems: true });
    void this.loadMore();
    return true;
  }

  async openItem(item) {
    if (!item?.id || this.destroyed) return false;
    this.detailController?.abort();
    const controller = new AbortController();
    this.detailController = controller;
    this.patch({ selected: item, detailLoading: true, detailError: "" });
    try {
      const response = await this.fetchFn(
        this.url(`/api/items/${encodeURIComponent(item.id)}`),
        { signal: controller.signal },
      );
      if (!response?.ok) throw new Error("detail_failed");
      const detail = await response.json();
      if (this.destroyed || this.detailController !== controller) return false;
      this.patch({ selected: detail, detailLoading: false, detailError: "" });
      return true;
    } catch (error) {
      if (error?.name !== "AbortError" && this.detailController === controller) {
        this.patch({ detailLoading: false, detailError: "暂时无法读取项目详情" });
      }
      return false;
    } finally {
      if (this.detailController === controller) this.detailController = null;
    }
  }

  closeItem() {
    this.detailController?.abort();
    this.detailController = null;
    this.patch({ selected: null, detailLoading: false, detailError: "" });
  }

  destroy() {
    if (this.destroyed) return;
    this.destroyed = true;
    this.bootstrapController?.abort();
    this.searchController?.abort();
    this.detailController?.abort();
    this.bootstrapController = null;
    this.searchController = null;
    this.detailController = null;
  }
}

export default HeritageBrowserSession;
