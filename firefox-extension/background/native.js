/**
 * native.js — Native messaging wrapper for ChromeBridge.
 * Handles communication with the Python bridge via stdin/stdout.
 */

const NativeHost = (() => {
  const HOST_NAME = "chromiumbridge";
  let _port = null;
  let _portListeners = [];

  /**
   * Send a one-shot message to the native host and return the response.
   * @param {Object} payload - JSON-serializable message to send.
   * @returns {Promise<Object>} The response from the bridge.
   */
  async function sendMessage(payload) {
    try {
      const response = await browser.runtime.sendNativeMessage(HOST_NAME, payload);
      return response;
    } catch (err) {
      console.error("[ChromeBridge] Native message error:", err);
      return { error: err.message || "Native messaging failed" };
    }
  }

  /**
   * Open a persistent connection to the native host.
   * Used for long-lived sessions where the bridge needs to push events.
   * @param {Function} onMessage - Callback for incoming messages.
   * @param {Function} onDisconnect - Callback when the connection drops.
   * @returns {Object} The port object.
   */
  function connect(onMessage, onDisconnect) {
    if (_port) {
      disconnect();
    }

    _port = browser.runtime.connectNative(HOST_NAME);

    const messageHandler = (msg) => {
      if (onMessage) onMessage(msg);
    };
    const disconnectHandler = (p) => {
      const err = p.error || browser.runtime.lastError;
      console.warn("[ChromeBridge] Native port disconnected:", err);
      _port = null;
      _portListeners = [];
      if (onDisconnect) onDisconnect(err);
    };

    _port.onMessage.addListener(messageHandler);
    _port.onDisconnect.addListener(disconnectHandler);
    _portListeners = [
      { event: _port.onMessage, handler: messageHandler },
      { event: _port.onDisconnect, handler: disconnectHandler },
    ];

    return _port;
  }

  /**
   * Disconnect the persistent port if one is open.
   */
  function disconnect() {
    if (_port) {
      _portListeners.forEach(({ event, handler }) => event.removeListener(handler));
      _portListeners = [];
      _port.disconnect();
      _port = null;
    }
  }

  /**
   * Send a message over the persistent port.
   * @param {Object} payload
   */
  function postMessage(payload) {
    if (!_port) {
      console.error("[ChromeBridge] No active port. Call connect() first.");
      return;
    }
    _port.postMessage(payload);
  }

  /**
   * Health check: ping the bridge and get status + detected browsers.
   * @returns {Promise<Object>} { status: "ok", browsers: [...] } or { error: "..." }
   */
  async function ping() {
    return sendMessage({ action: "ping" });
  }

  /**
   * Request browser detection from the bridge.
   * @returns {Promise<Object>} { browsers: [{ id, name, path, version }] }
   */
  async function detectBrowsers() {
    return sendMessage({ action: "detect" });
  }

  /**
   * Get bridge config.
   * @returns {Promise<Object>}
   */
  async function getConfig() {
    return sendMessage({ action: "config_get" });
  }

  /**
   * Update bridge config.
   * @param {Object} config - Partial config to merge.
   * @returns {Promise<Object>}
   */
  async function setConfig(config) {
    return sendMessage({ action: "config_set", config });
  }

  return {
    sendMessage,
    connect,
    disconnect,
    postMessage,
    ping,
    detectBrowsers,
    getConfig,
    setConfig,
  };
})();
