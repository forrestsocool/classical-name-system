function dragState(dx, dy, width = 375) {
  const progress = Math.min(1, Math.abs(dx) / Math.min(100, width * 0.26));
  const rotate = Math.round(Math.max(-18, Math.min(18, dx / width * 28)) * 1000) / 1000;
  const translateY = Math.round(dy * 18) / 100;
  const stackY = Math.round(14 * (1 - progress) * 1000) / 1000;
  const stackScale = Math.round((0.96 + 0.04 * progress) * 10000) / 10000;
  const stackOpacity = Math.round((0.55 + 0.45 * progress) * 10000) / 10000;
  return {
    cardStyle: `transform:translate3d(${dx}px,${translateY}px,0) rotate(${rotate}deg);transition:none;`,
    stackStyle: `transform:translateY(${stackY}px) scale(${stackScale});opacity:${stackOpacity};`,
    likeOpacity: dx > 0 ? progress : 0, skipOpacity: dx < 0 ? progress : 0
  };
}
function releaseDirection(dx, dy, elapsed, width = 375) {
  if (Math.abs(dx) <= Math.abs(dy) * 1.15) return 0;
  const far = Math.abs(dx) >= Math.min(100, width * 0.26);
  const fast = elapsed > 0 && elapsed < 350 && Math.abs(dx) >= 35 && Math.abs(dx) / elapsed >= 0.65;
  return far || fast ? (dx > 0 ? 1 : -1) : 0;
}
module.exports = {dragState, releaseDirection};
