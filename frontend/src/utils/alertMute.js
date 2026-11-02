// The whole mute map is what the API replaces, so a flip sends the merged map
// and an undo touches only the key that changed.
export const flipMute = (mute, kind) => ({ ...mute, [kind]: !mute[kind] });
export const undoMute = (mute, kind, wasMuted) => ({ ...mute, [kind]: Boolean(wasMuted) });
