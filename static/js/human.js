import { humanVideos, humanVideoIndexes, HUMAN_MIN_THINKING_MS, HUMAN_DISSOLVE_LEAD_MS } from './consts.js';
import { els } from './state.js';
import { stripMarkdown } from './markdown.js';

let humanIdleTimer = 0;
let humanLoopTimer = 0;
let humanTransitionTimer = 0;
let humanDissolveTimer = 0;
let humanTransitionSeq = 0;
export let currentHumanState = "idle";
export let activeHumanVideo = null;
export let standbyHumanVideo = null;

export function initHuman() {
  activeHumanVideo = els.digitalHumanVideo;
  standbyHumanVideo = els.digitalHumanVideoNext;
}

export function setDigitalHumanState(stateName, status, speech = "") {
  window.clearTimeout(humanIdleTimer);
  window.clearTimeout(humanLoopTimer);
  currentHumanState = stateName;
  els.digitalHumanPanel.dataset.state = stateName;
  els.digitalHumanStatus.textContent = status;
  els.digitalHumanSpeech.textContent = digitalHumanCaption(stateName, status, speech);

  const nextSrc = pickHumanVideo(stateName);
  transitionHumanVideo(nextSrc, stateName);
}

export function transitionHumanVideo(nextSrc, stateName = currentHumanState, options = {}) {
  if (!activeHumanVideo || (activeHumanVideo.src.endsWith(nextSrc) && !options.force)) {
    configureHumanVideoPlayback(activeHumanVideo, stateName);
    activeHumanVideo?.play().catch(() => {});
    scheduleHumanVideoAdvance(activeHumanVideo, stateName);
    return;
  }
  const transitionSeq = ++humanTransitionSeq;
  if (!standbyHumanVideo) {
    configureHumanVideoPlayback(activeHumanVideo, stateName);
    activeHumanVideo.src = nextSrc;
    activeHumanVideo.load();
    activeHumanVideo.play().catch(() => {});
    scheduleHumanVideoAdvance(activeHumanVideo, stateName);
    return;
  }

  window.clearTimeout(humanTransitionTimer);
  window.clearTimeout(humanDissolveTimer);

  // Clean up any stale dissolve state from interrupted transitions
  if (activeHumanVideo) {
    activeHumanVideo.classList.remove("is-dissolve-in", "is-dissolve-out");
    activeHumanVideo.style.opacity = "";
  }
  if (standbyHumanVideo) {
    standbyHumanVideo.classList.remove("is-dissolve-in", "is-dissolve-out");
    standbyHumanVideo.style.opacity = "";
  }
  els.digitalHumanVideo.parentElement?.classList.remove("is-dissolving");

  const incoming = standbyHumanVideo;
  const outgoing = activeHumanVideo;
  let started = false;

  incoming.pause();
  incoming.classList.remove("is-active");
  configureHumanVideoPlayback(incoming, stateName);
  incoming.src = nextSrc;
  incoming.load();

  const startTransition = () => {
    if (started || transitionSeq !== humanTransitionSeq) return;
    started = true;
    incoming.play().catch(() => {});
    window.requestAnimationFrame(() => {
      incoming.style.opacity = "0";
      incoming.classList.add("is-active");
      incoming.classList.add("is-dissolve-in");
      outgoing.classList.add("is-dissolve-out");
      els.digitalHumanVideo.parentElement?.classList.add("is-dissolving");
      window.requestAnimationFrame(() => {
        incoming.style.opacity = "";
        outgoing.classList.remove("is-active");
      });
    });
    humanDissolveTimer = window.setTimeout(() => {
      incoming.classList.remove("is-dissolve-in");
      outgoing.classList.remove("is-dissolve-out");
      els.digitalHumanVideo.parentElement?.classList.remove("is-dissolving");
    }, 980);
    activeHumanVideo = incoming;
    standbyHumanVideo = outgoing;
    scheduleHumanVideoAdvance(incoming, stateName);
    humanTransitionTimer = window.setTimeout(() => {
      outgoing.pause();
      outgoing.removeAttribute("src");
      outgoing.load();
    }, 1020);
  };

  incoming.addEventListener("loadeddata", startTransition, { once: true });
  incoming.addEventListener("canplay", startTransition, { once: true });
  window.setTimeout(startTransition, 500);
}

export function configureHumanVideoPlayback(video, stateName) {
  if (!video) return;
  video.loop = false;
  video.muted = true;
  video.playsInline = true;
}

export function scheduleHumanVideoAdvance(video, stateName = currentHumanState) {
  window.clearTimeout(humanLoopTimer);
  if (!video || currentHumanState !== stateName) {
    return;
  }

  const advance = () => {
    if (currentHumanState !== stateName || activeHumanVideo !== video) return;
    window.clearTimeout(humanLoopTimer);
    transitionHumanVideo(pickHumanVideo(stateName, { allowSame: true }), stateName, { force: true });
  };

  const schedule = () => {
    if (currentHumanState !== stateName || activeHumanVideo !== video) {
      return;
    }
    const duration = Number.isFinite(video.duration) ? video.duration : 5;
    const delay = Math.max(1200, duration * 1000 - HUMAN_DISSOLVE_LEAD_MS);
    humanLoopTimer = window.setTimeout(() => {
      if (currentHumanState === stateName && activeHumanVideo === video) {
        advance();
      }
    }, delay);
  };

  video.addEventListener("ended", advance, { once: true });

  if (video.readyState >= HTMLMediaElement.HAVE_METADATA) {
    schedule();
  } else {
    video.addEventListener("loadedmetadata", schedule, { once: true });
  }
}

export function pickHumanVideo(stateName, options = {}) {
  const source = humanVideos[stateName] || humanVideos.idle;
  const videos = Array.isArray(source) ? source : [source];
  let index = humanVideoIndexes[stateName] || 0;
  let next = videos[index % videos.length];
  if (!options.allowSame && videos.length > 1 && activeHumanVideo?.src.endsWith(next)) {
    index += 1;
    next = videos[index % videos.length];
  }
  humanVideoIndexes[stateName] = (index + 1) % videos.length;
  return next;
}

export function responseHumanState(query) {
  const farewellTerms = ["谢谢", "感谢", "辛苦了", "再见", "拜拜", "下次见"];
  return farewellTerms.some((term) => query.includes(term)) ? "farewell" : "speaking";
}

export function waitForThinkingDissolve(startedAt) {
  if (currentHumanState !== "thinking") {
    return Promise.resolve();
  }
  const elapsed = performance.now() - startedAt;
  const remaining = Math.max(0, HUMAN_MIN_THINKING_MS - elapsed);
  return remaining ? new Promise((resolve) => window.setTimeout(resolve, remaining)) : Promise.resolve();
}

export function scheduleHumanReturnToIdle(delayMs) {
  window.clearTimeout(humanIdleTimer);
  humanIdleTimer = window.setTimeout(() => {
    if (currentHumanState === "speaking" || currentHumanState === "farewell") {
      setDigitalHumanState("idle", "待机", "我在这里，可以继续问我。");
    }
  }, delayMs);
}

export function restoreHumanVideoAfterVisibility() {
  if (!activeHumanVideo) return;
  // Browser may have suspended playback while tab was hidden
  if (activeHumanVideo.paused) {
    activeHumanVideo.play().catch(() => {});
  }
  // Re-schedule the idle loop — background timer throttling may have expired it
  window.clearTimeout(humanLoopTimer);
  scheduleHumanVideoAdvance(activeHumanVideo, currentHumanState);
}

export function visualAnswerDuration(text) {
  const length = stripMarkdown(text).length;
  return Math.min(22000, Math.max(7500, 3600 + length * 90));
}

export function digitalHumanCaption(stateName, status, fallback = "") {
  const captions = {
    idle: "我在这里，可以继续问我。",
    thinking: "我先从资料库里找和问题最相关的内容。",
    speaking: "正在为你讲述。",
    farewell: "期待下次再见。",
  };
  if (status === "出现错误") {
    return "刚才没有答好，请再试一次。";
  }
  return captions[stateName] || fallback || "我在这里。";
}
