/**
 * rules.js — Domain rule engine for ChromeBridge.
 * Manages per-domain rules stored in browser.storage.sync.
 */

const DomainRules = (() => {
  const STORAGE_KEY = "domainRules";

  /**
   * Extract the registrable domain from a URL.
   * e.g., "https://video.netflix.com/watch/123" → "netflix.com"
   * @param {string} url
   * @returns {string|null}
   */
  function extractDomain(url) {
    try {
      const hostname = new URL(url).hostname;
      // Simple TLD extraction: take last two parts (or three for co.uk etc.)
      const parts = hostname.split(".");
      if (parts.length <= 2) return hostname;
      // Handle common double TLDs
      const doubleTLDs = ["co.uk", "com.au", "co.jp", "co.kr", "com.br", "co.in", "org.uk"];
      const lastTwo = parts.slice(-2).join(".");
      if (doubleTLDs.includes(lastTwo)) {
        return parts.slice(-3).join(".");
      }
      return parts.slice(-2).join(".");
    } catch {
      return null;
    }
  }

  /**
   * Load all domain rules from storage.
   * @returns {Promise<Object>} Map of domain → rule.
   */
  async function getAllRules() {
    const result = await browser.storage.sync.get(STORAGE_KEY);
    return result[STORAGE_KEY] || {};
  }

  /**
   * Find a matching rule for a URL.
   * Checks exact domain first, then parent domain.
   * @param {string} url
   * @returns {Promise<{domain: string, rule: Object}|null>}
   */
  async function matchDomain(url) {
    const domain = extractDomain(url);
    if (!domain) return null;

    const rules = await getAllRules();

    // Exact match
    if (rules[domain]) {
      return { domain, rule: rules[domain] };
    }

    // Check if hostname is a subdomain of any rule
    const hostname = new URL(url).hostname;
    for (const ruleDomain of Object.keys(rules)) {
      if (hostname === ruleDomain || hostname.endsWith("." + ruleDomain)) {
        return { domain: ruleDomain, rule: rules[ruleDomain] };
      }
    }

    return null;
  }

  /**
   * Get the rule for a specific domain.
   * @param {string} domain
   * @returns {Promise<Object|null>}
   */
  async function getRuleForDomain(domain) {
    const rules = await getAllRules();
    return rules[domain] || null;
  }

  /**
   * Set or update a rule for a domain.
   * @param {string} domain
   * @param {Object} rule - { action, browser, mode, preset, profile }
   */
  async function setRule(domain, rule) {
    const rules = await getAllRules();
    rules[domain] = { ...rule, updatedAt: Date.now() };
    await browser.storage.sync.set({ [STORAGE_KEY]: rules });
  }

  /**
   * Delete a domain rule.
   * @param {string} domain
   */
  async function deleteRule(domain) {
    const rules = await getAllRules();
    delete rules[domain];
    await browser.storage.sync.set({ [STORAGE_KEY]: rules });
  }

  /**
   * Import rules from a JSON object (merges with existing).
   * @param {Object} importedRules - Map of domain → rule.
   * @returns {Promise<number>} Number of rules imported.
   */
  async function importRules(importedRules) {
    const rules = await getAllRules();
    let count = 0;
    for (const [domain, rule] of Object.entries(importedRules)) {
      rules[domain] = { ...rule, updatedAt: Date.now() };
      count++;
    }
    await browser.storage.sync.set({ [STORAGE_KEY]: rules });
    return count;
  }

  /**
   * Export all rules as a plain JSON object.
   * @returns {Promise<Object>}
   */
  async function exportRules() {
    return getAllRules();
  }

  return {
    extractDomain,
    getAllRules,
    matchDomain,
    getRuleForDomain,
    setRule,
    deleteRule,
    importRules,
    exportRules,
  };
})();
