// localStorage throws when storage is blocked (private modes, strict
// cookie settings); a preference or token read must never crash the app.
export const safeGet = (key) => {
  try {
    return localStorage.getItem(key);
  } catch {
    return null;
  }
};

export const safeSet = (key, value) => {
  try {
    localStorage.setItem(key, value);
  } catch {
    /* storage unavailable: the value just doesn't persist */
  }
};
