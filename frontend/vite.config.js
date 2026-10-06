import { defineConfig } from 'vite'
import react from '@vitejs/plugin-react'

// https://vite.dev/config/
export default defineConfig({
  plugins: [react()],
  // The commit Vercel built, shown in the handbook's Deployed now panel.
  define: { 'import.meta.env.VITE_GIT_SHA': JSON.stringify(process.env.VERCEL_GIT_COMMIT_SHA || '') },
  build: {
    rollupOptions: {
      output: {
        manualChunks: (id) => {
          if (/node_modules\/(react|react-dom|react-router|react-router-dom|scheduler|clsx|tailwind-merge)\//.test(id)) return 'vendor';
          return undefined;
        },
      },
    },
  },
})
