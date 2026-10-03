import { useSearchParams } from 'react-router-dom';

/**
 * Which tab a long page is showing, kept in `?tab=` so a link can open a page
 * on the right tab and Back returns to the one you left. An unknown or missing
 * value falls back to the first tab.
 */
export const useTab = (ids) => {
  const [params, setParams] = useSearchParams();
  const requested = params.get('tab');
  const active = ids.includes(requested) ? requested : ids[0];
  const select = (id) =>
    setParams(
      (current) => {
        const next = new URLSearchParams(current);
        if (id === ids[0]) next.delete('tab');
        else next.set('tab', id);
        return next;
      },
      { replace: true }
    );
  return [active, select];
};
