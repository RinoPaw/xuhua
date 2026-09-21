import { useCallback, useEffect, useRef, useState } from "react";

const CLIPS = Object.freeze({
  idle: [
    "/assets/avatar/greet1.mp4",
    "/assets/avatar/wait1.mp4",
    "/assets/avatar/wait2.mp4",
  ],
  speaking: [
    "/assets/avatar/speak1.mp4",
    "/assets/avatar/speak2.mp4",
    "/assets/avatar/speak3.mp4",
  ],
});

const LABELS = Object.freeze({
  idle: "叙华待机动画",
  speaking: "叙华讲解动画",
});

const TRANSITION_MS = 360;

function stopVideo(video) {
  if (!video) return;
  video.pause();
  video.oncanplay = null;
  video.onerror = null;
}

export function DigitalHuman({ mode = "idle" }) {
  const normalizedMode = mode === "speaking" ? "speaking" : "idle";
  const videosRef = useRef([]);
  const activeSlotRef = useRef(0);
  const modeRef = useRef(normalizedMode);
  const generationRef = useRef(0);
  const cursorRef = useRef({ idle: 0, speaking: 0 });
  const transitionTimerRef = useRef(null);
  const [activeSlot, setActiveSlot] = useState(0);

  const nextClip = useCallback((targetMode) => {
    const pool = CLIPS[targetMode];
    const cursor = cursorRef.current[targetMode] % pool.length;
    cursorRef.current[targetMode] = cursor + 1;
    return pool[cursor];
  }, []);

  const transitionTo = useCallback((targetMode) => {
    const currentSlot = activeSlotRef.current;
    const nextSlot = currentSlot === 0 ? 1 : 0;
    const current = videosRef.current[currentSlot];
    const next = videosRef.current[nextSlot];
    if (!next) return;

    generationRef.current += 1;
    const generation = generationRef.current;
    window.clearTimeout(transitionTimerRef.current);
    stopVideo(next);
    next.src = nextClip(targetMode);
    next.currentTime = 0;
    next.load();

    const reveal = async () => {
      if (generationRef.current !== generation || modeRef.current !== targetMode) return;
      next.oncanplay = null;
      try {
        await next.play();
      } catch {
        return;
      }
      if (generationRef.current !== generation || modeRef.current !== targetMode) {
        next.pause();
        return;
      }
      activeSlotRef.current = nextSlot;
      setActiveSlot(nextSlot);
      transitionTimerRef.current = window.setTimeout(() => stopVideo(current), TRANSITION_MS);
    };

    next.oncanplay = reveal;
    next.onerror = () => {
      if (generationRef.current === generation) stopVideo(next);
    };
  }, [nextClip]);

  useEffect(() => {
    modeRef.current = normalizedMode;
    transitionTo(normalizedMode);
  }, [normalizedMode, transitionTo]);

  useEffect(() => () => {
    generationRef.current += 1;
    window.clearTimeout(transitionTimerRef.current);
    videosRef.current.forEach(stopVideo);
  }, []);

  const handleEnded = (slot) => {
    if (slot !== activeSlotRef.current) return;
    transitionTo(modeRef.current);
  };

  return (
    <div className="human-stage">
      <img className="human-poster" src="/assets/portraits/xuhua-guide.webp" alt="" />
      {[0, 1].map((slot) => (
        <video
          key={slot}
          ref={(node) => { videosRef.current[slot] = node; }}
          className={`human-video ${slot === activeSlot ? "is-active" : ""}`}
          muted
          playsInline
          preload="auto"
          aria-hidden={slot !== activeSlot}
          aria-label={slot === activeSlot ? LABELS[normalizedMode] : undefined}
          onEnded={() => handleEnded(slot)}
        />
      ))}
      <div className="human-vignette" />
      <div className="human-caption">
        <div className="human-brand">
          <img src="/assets/brand/xuhua-seal.png" alt="" />
          <div>
            <strong>叙华</strong>
            <small>非遗资料助手</small>
          </div>
        </div>
      </div>
    </div>
  );
}

export default DigitalHuman;
