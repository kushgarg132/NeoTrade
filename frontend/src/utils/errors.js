// FastAPI's error `detail` is a string for app errors but a list of objects
// for validation failures (422). Rendered raw, a list crashes React ("Objects
// are not valid as a React child") -- e.g. the whole Settings page on an
// out-of-range number. Every response passes through detailToText once, in
// the axios interceptor (utils/api.js), so pages can render detail as text.

const fieldName = (loc) => {
  const field = Array.isArray(loc) ? loc[loc.length - 1] : null;
  if (typeof field !== 'string') return null;
  const words = field.replace(/_/g, ' ');
  return words.charAt(0).toUpperCase() + words.slice(1);
};

const lowerFirst = (text) => (text ? text.charAt(0).toLowerCase() + text.slice(1) : text);

export function detailToText(detail) {
  if (typeof detail === 'string') return detail;
  if (Array.isArray(detail)) {
    const parts = detail
      .filter((item) => item && typeof item.msg === 'string')
      .map((item) => {
        const field = fieldName(item.loc);
        return field ? `${field}: ${lowerFirst(item.msg)}` : item.msg;
      });
    return parts.length ? parts.join(' · ') : undefined;
  }
  return undefined;
}
