import { defineConfig } from 'vite'
import react from '@vitejs/plugin-react'

// https://vite.dev/config/
export default defineConfig({
  plugins: [react()],
  build: {
    rollupOptions: {
      output: {
        manualChunks: (id) => {
          if (/node_modules\/(react|react-dom|react-router|react-router-dom|scheduler|clsx|tailwind-merge)\//.test(id)) return 'vendor';
          if (/node_modules\/(recharts|d3-)/.test(id)) return 'recharts';
          return undefined;
        },
      },
    },
  },
})
