/// <reference types="vite/client" />

declare global {
  interface Window {
    /**
     * FastAPI root_path prefix injected by the backend when it serves
     * index.html (e.g. '' or '/qym'). All runtime URLs — hashed asset chunks
     * (see renderBuiltUrl in vite.config.ts), API calls (src/api/client.ts)
     * and the router basename — are prefixed with it.
     */
    __QYM_ROOT_PATH__?: string
  }
}

export {}
