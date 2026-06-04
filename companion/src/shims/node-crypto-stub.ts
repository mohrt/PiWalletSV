/**
 * Browser stub for `node:crypto` imports inside `@bsv/sdk`.
 *
 * The SDK probes native Node APIs and falls back to pure-TS implementations
 * when they are missing. Vite 8 externalizes `node:crypto` with a proxy that
 * throws on property access; an empty stub lets the fallback path run.
 */
const stub = Object.freeze({});

export default stub;
