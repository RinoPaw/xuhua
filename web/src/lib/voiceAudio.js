export function rms(samples) {
  let sum = 0;
  for (let index = 0; index < samples.length; index += 1) {
    sum += samples[index] * samples[index];
  }
  return Math.sqrt(sum / Math.max(1, samples.length));
}

export function spectrumBars(samples, { count = 24, scale = 0.12 } = {}) {
  return Array.from({ length: count }, (_, index) => {
    const start = Math.floor((index / count) * samples.length);
    const end = Math.max(start + 1, Math.floor(((index + 1) / count) * samples.length));
    let energy = 0;
    for (let cursor = start; cursor < end; cursor += 1) {
      energy += samples[cursor] * samples[cursor];
    }
    return Math.min(1, Math.sqrt(energy / Math.max(1, end - start)) / scale);
  });
}
