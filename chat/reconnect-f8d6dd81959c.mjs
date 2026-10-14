const transient = new Set(['observer_unavailable', 'worker_unavailable', 'connection_timeout', 'websocket_unavailable', 'disconnected']);

export class ObserveReconnect {
  constructor(callback, { setTimer = globalThis.setTimeout, clearTimer = globalThis.clearTimeout } = {}) {
    Object.assign(this, { callback, setTimer, clearTimer, enabled: false, attempts: 0, timer: null });
  }
  begin() { this.enabled = true; this.clear(); }
  clear() { if (this.timer !== null) this.clearTimer(this.timer); this.timer = null; }
  reset() { this.attempts = 0; }
  stop() { this.enabled = false; this.clear(); this.reset(); }
  schedule(error, authenticated) {
    if (!this.enabled || !authenticated || (!transient.has(error.code) && error.name !== 'TypeError')) return null;
    this.clear();
    const delay = Math.min(1000 * 2 ** Math.min(this.attempts++, 4), 15000);
    this.timer = this.setTimer(() => { this.timer = null; if (this.enabled) this.callback(); }, delay);
    return delay;
  }
}
