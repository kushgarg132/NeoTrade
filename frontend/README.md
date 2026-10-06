# NeoTrade Frontend

React 19 + Vite (plain JSX), Tailwind v4, React Router 7. Deployed on Vercel; the backend it
talks to runs on the project's VM — see the root [`README.md`](../README.md) and
the handbook in [`src/handbook/`](src/handbook/).

In production the API base URL is the relative path `/api/v1`, proxied to the backend by the
rewrite in `vercel.json`. That proxy is what keeps the refresh cookie first-party, so Safari
and Firefox don't drop it — don't bypass it. The WebSocket connects to the backend directly,
since Vercel rewrites don't proxy upgrades.

This project was scaffolded from Vite's React template.

Currently, two official plugins are available:

- [@vitejs/plugin-react](https://github.com/vitejs/vite-plugin-react/blob/main/packages/plugin-react) uses [Babel](https://babeljs.io/) (or [oxc](https://oxc.rs) when used in [rolldown-vite](https://vite.dev/guide/rolldown)) for Fast Refresh
- [@vitejs/plugin-react-swc](https://github.com/vitejs/vite-plugin-react/blob/main/packages/plugin-react-swc) uses [SWC](https://swc.rs/) for Fast Refresh

## React Compiler

The React Compiler is not enabled on this template because of its impact on dev & build performances. To add it, see [this documentation](https://react.dev/learn/react-compiler/installation).

## Expanding the ESLint configuration

If you are developing a production application, we recommend using TypeScript with type-aware lint rules enabled. Check out the [TS template](https://github.com/vitejs/vite/tree/main/packages/create-vite/template-react-ts) for information on how to integrate TypeScript and [`typescript-eslint`](https://typescript-eslint.io) in your project.
