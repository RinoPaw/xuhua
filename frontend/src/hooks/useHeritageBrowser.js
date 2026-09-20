import { useCallback, useEffect, useRef, useState } from "react";

import {
  mergePageItems,
  nextPageState,
  pageLimitForState,
  PROJECT_PAGE_SIZE,
} from "../lib/pagination.js";

function joinApiPath(base, path) {
  return `${base || ""}${path}`;
}

export function useHeritageBrowser({ apiBase = "", promptSeed = 0 } = {}) {
  const [searchDraft, setSearchDraft] = useState("");
  const [searchQuery, setSearchQuery] = useState("");
  const [filters, setFilters] = useState({ category: "", level: "" });
  const [items, setItems] = useState([]);
  const [total, setTotal] = useState(0);
  const [hasMoreItems, setHasMoreItems] = useState(false);
  const [categories, setCategories] = useState([]);
  const [meta, setMeta] = useState(null);
  const [loading, setLoading] = useState(true);
  const [searchError, setSearchError] = useState("");
  const [selected, setSelected] = useState(null);
  const [detailLoading, setDetailLoading] = useState(false);
  const [detailError, setDetailError] = useState("");

  const searchAbort = useRef(null);
  const searchSeq = useRef(0);
  const detailAbort = useRef(null);
  const sourceListRef = useRef(null);
  const itemPageRef = useRef({
    key: "",
    nextOffset: 0,
    startOffset: 0,
    wrapped: false,
    hasMore: true,
    loading: false,
    requestId: 0,
  });

  useEffect(() => {
    const controller = new AbortController();
    Promise.all([
      fetch(joinApiPath(apiBase, "/api/meta"), { signal: controller.signal }),
      fetch(joinApiPath(apiBase, "/api/categories"), { signal: controller.signal }),
    ]).then(async ([metaResponse, categoriesResponse]) => {
      if (metaResponse.ok) setMeta(await metaResponse.json());
      else setMeta({ levels: [], capabilities: { realtime_voice: false } });
      if (categoriesResponse.ok) setCategories(await categoriesResponse.json());
    }).catch((error) => {
      if (error?.name !== "AbortError") {
        setMeta({ levels: [], capabilities: { realtime_voice: false } });
      }
    });
    return () => controller.abort();
  }, [apiBase]);

  const fetchItemPage = useCallback(async ({ reset = false } = {}) => {
    const initialBrowse = !searchQuery && !filters.category && !filters.level;
    if (initialBrowse && meta === null) return;
    const key = JSON.stringify([searchQuery, filters.category, filters.level]);
    const page = itemPageRef.current;
    if (!reset && (page.loading || (!page.hasMore && !page.error) || page.key !== key)) return;

    const requestId = reset ? ++searchSeq.current : page.requestId;
    if (reset) {
      searchAbort.current?.abort();
      const itemCount = Math.max(0, Number(meta?.item_count) || 0);
      const startOffset = initialBrowse && itemCount > PROJECT_PAGE_SIZE
        ? promptSeed % (itemCount - PROJECT_PAGE_SIZE + 1)
        : 0;
      itemPageRef.current = {
        key,
        nextOffset: startOffset,
        startOffset,
        wrapped: false,
        hasMore: true,
        error: false,
        loading: true,
        requestId,
      };
      setItems([]);
      setTotal(0);
      setHasMoreItems(true);
      setSearchError("");
    } else {
      itemPageRef.current = { ...page, error: false, loading: true };
    }

    const controller = new AbortController();
    searchAbort.current = controller;
    setLoading(true);
    const currentPage = itemPageRef.current;
    const offset = currentPage.nextOffset;
    const pageLimit = pageLimitForState(currentPage);
    const query = new URLSearchParams({
      q: searchQuery,
      category: filters.category,
      level: filters.level,
      limit: String(pageLimit),
      offset: String(offset),
    });

    try {
      const response = await fetch(joinApiPath(apiBase, `/api/items?${query}`), {
        signal: controller.signal,
      });
      if (!response.ok) throw new Error("search_failed");
      const data = await response.json();
      const current = itemPageRef.current;
      if (requestId !== searchSeq.current || current.key !== key) return;
      const incoming = Array.isArray(data.items) ? data.items : [];
      const pageState = nextPageState({
        offset: Number(data.offset ?? offset),
        limit: Number(data.limit ?? PROJECT_PAGE_SIZE),
        total: Number(data.total || 0),
        received: incoming.length,
        startOffset: current.startOffset,
        wrapped: current.wrapped,
      });
      setItems((previous) => (
        reset ? mergePageItems([], incoming) : mergePageItems(previous, incoming)
      ));
      setTotal(Number(data.total || 0));
      setHasMoreItems(pageState.hasMore);
      itemPageRef.current = {
        ...current,
        nextOffset: pageState.nextOffset,
        wrapped: pageState.wrapped,
        hasMore: pageState.hasMore,
        error: false,
        loading: false,
      };
    } catch (error) {
      if (error?.name !== "AbortError"
        && requestId === searchSeq.current
        && itemPageRef.current.key === key) {
        setSearchError("加载失败");
        itemPageRef.current = { ...itemPageRef.current, loading: false, error: true };
        setHasMoreItems(false);
      }
    } finally {
      if (requestId === searchSeq.current && itemPageRef.current.key === key) {
        itemPageRef.current = { ...itemPageRef.current, loading: false };
        setLoading(false);
      }
    }
  }, [apiBase, filters, meta, promptSeed, searchQuery]);

  const searchItems = useCallback(() => fetchItemPage({ reset: true }), [fetchItemPage]);
  const loadMoreItems = useCallback(() => fetchItemPage(), [fetchItemPage]);

  useEffect(() => { void searchItems(); }, [searchItems]);
  useEffect(() => {
    const list = sourceListRef.current;
    if (!list || loading || !hasMoreItems || items.length === 0) return;
    if (list.scrollHeight <= list.clientHeight + 8) void loadMoreItems();
  }, [hasMoreItems, items.length, loadMoreItems, loading]);
  useEffect(() => () => {
    searchAbort.current?.abort();
    detailAbort.current?.abort();
  }, []);

  const openItem = useCallback(async (item) => {
    if (!item?.id) return;
    setSelected(item);
    setDetailLoading(true);
    setDetailError("");
    detailAbort.current?.abort();
    const controller = new AbortController();
    detailAbort.current = controller;
    try {
      const response = await fetch(
        joinApiPath(apiBase, `/api/items/${encodeURIComponent(item.id)}`),
        { signal: controller.signal },
      );
      if (!response.ok) throw new Error("detail_failed");
      const detail = await response.json();
      if (detailAbort.current !== controller) return;
      setSelected(detail);
    } catch (error) {
      if (error?.name !== "AbortError" && detailAbort.current === controller) {
        setDetailError("暂时无法读取项目详情");
      }
    } finally {
      if (detailAbort.current === controller) setDetailLoading(false);
    }
  }, [apiBase]);

  const closeItem = useCallback(() => {
    detailAbort.current?.abort();
    detailAbort.current = null;
    setDetailLoading(false);
    setDetailError("");
    setSelected(null);
  }, []);

  const applyFilters = useCallback((next) => {
    setSelected(null);
    setSearchQuery(searchDraft.trim());
    setFilters(next);
  }, [searchDraft]);

  const updateSearchDraft = useCallback((value) => {
    setSearchDraft(value);
    if (!value.trim()) setSearchQuery("");
  }, []);

  const submitSearch = useCallback(() => {
    const nextQuery = searchDraft.trim();
    setSearchQuery(nextQuery);
    if (searchQuery === nextQuery) void searchItems();
  }, [searchDraft, searchItems, searchQuery]);

  const retryItems = useCallback(() => {
    setSearchError("");
    void loadMoreItems();
  }, [loadMoreItems]);

  const handleSourceScroll = useCallback((event) => {
    const list = event.currentTarget;
    if (loading || !hasMoreItems) return;
    if (list.scrollHeight - list.scrollTop - list.clientHeight < 180) void loadMoreItems();
  }, [hasMoreItems, loadMoreItems, loading]);

  return {
    searchDraft,
    filters,
    items,
    total,
    hasMoreItems,
    categories,
    meta,
    loading,
    searchError,
    selected,
    detailLoading,
    detailError,
    sourceListRef,
    openItem,
    closeItem,
    applyFilters,
    updateSearchDraft,
    submitSearch,
    retryItems,
    handleSourceScroll,
  };
}

export default useHeritageBrowser;
