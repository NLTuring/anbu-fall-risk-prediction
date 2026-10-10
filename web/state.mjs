export function deviceState(camera, online, paused) {
  if (!camera) return { label: '摄像头已断开', stale: true, detail: '未产生新的观察数据，请检查 USB 连接。' };
  if (paused) return { label: '观察已暂停', stale: true, detail: '尊重家人的私人时间，恢复后才会继续模拟观察。' };
  if (!online) return { label: '设备离线', stale: true, detail: '无法同步新数据，当前仅展示上次同步的示例。' };
  return { label: '模拟连接正常', stale: false, detail: '这是一条演示链路，没有连接真实设备。' };
}
export function transitionTask(current, action) {
  const transitions = { pending: { claim: 'claimed', defer: 'deferred' }, claimed: { complete: 'completed', defer: 'deferred' }, deferred: { claim: 'claimed' }, completed: {} };
  return transitions[current]?.[action] ?? current;
}
export function metricSeries(person, metric) {
  const speed = person === 'mother' ? [0.91, 0.94, 0.92, null, 0.86, 0.85, 0.88] : [1.02, 1.04, 1.01, null, 1.03, 1.05, 1.04];
  return metric === 'speed' ? speed : speed.map(v => v === null ? null : Math.round(v * 32 + 65));
}
export function chartSegments(values) {
  return values.reduce((segments, value, index) => {
    if (value === null) { segments.push([]); return segments; }
    segments[segments.length - 1].push({ index, value }); return segments;
  }, [[]]).filter(segment => segment.length);
}
