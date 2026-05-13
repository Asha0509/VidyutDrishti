// Backend origin. Empty in local dev, where the Vite proxy forwards /api to the
// backend; set VITE_API_BASE at build time for a deployed backend.
export const API_BASE: string = import.meta.env.VITE_API_BASE ?? ''
