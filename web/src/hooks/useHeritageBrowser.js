import { useCallback, useEffect, useRef, useState } from "react";

import HeritageBrowserSession, {
  initialHeritageBrowserState,
} from "../lib/heritageBrowserSession.js";

const browserFetch = (...args) => globalThis.fetch(...args);

export function useHeritageBrowser({
  apiBase = "",
  fetchFn = browserFetch,
  promptSeed = 0,
} = {}) {
  const [snapshot, setSnapshot] = useState(initialHeritageBrowserState);
  const sourceListRef = useRef(null);
  const sessionRef = useRef(null);

  if (!sessionRef.current) {
    sessionRef.current = new HeritageBrowserSession({
      apiBase,
      fetchFn,
      promptSeed,
      onChange: setSnapshot,
    });
  }

  sessionRef.current.setApiBase(apiBase);
  sessionRef.current.setPromptSeed(promptSeed);
  sessionRef.current.fetchFn = fetchFn;

  const openItem = useCallback((item) => sessionRef.current.openItem(item), []);
  const closeItem = useCallback(() => sessionRef.current.closeItem(), []);
  const applyFilters = useCallback((next) => sessionRef.current.applyFilters(next), []);
  const updateSearchDraft = useCallback(
    (value) => sessionRef.current.setSearchDraft(value),
    [],
  );
  const submitSearch = useCallback(() => sessionRef.current.submitSearch(), []);
  const retryItems = useCallback(() => sessionRef.current.retryItems(), []);
  const loadMoreItems = useCallback(() => sessionRef.current.loadMore(), []);

  useEffect(() => {
    void sessionRef.current.start();
    return () => sessionRef.current?.destroy();
  }, []);

  useEffect(() => {
    const list = sourceListRef.current;
    if (!list || snapshot.loading || !snapshot.hasMoreItems || snapshot.items.length === 0) return;
    if (list.scrollHeight <= list.clientHeight + 8) void loadMoreItems();
  }, [loadMoreItems, snapshot.hasMoreItems, snapshot.items.length, snapshot.loading]);

  const handleSourceScroll = useCallback((event) => {
    const list = event.currentTarget;
    if (snapshot.loading || !snapshot.hasMoreItems) return;
    if (list.scrollHeight - list.scrollTop - list.clientHeight < 180) void loadMoreItems();
  }, [loadMoreItems, snapshot.hasMoreItems, snapshot.loading]);

  return {
    ...snapshot,
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
