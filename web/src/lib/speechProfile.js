export function acknowledgementAudio(websocketPath = "") {
  const path = new URL(websocketPath || "/api/voice", "https://voice.invalid").pathname;
  return path === "/shizha/api/voice"
    ? "/assets/audio/ack-wozai-yunxia.mp3"
    : "/assets/audio/ack-wozai-x4-yezi.mp3";
}
