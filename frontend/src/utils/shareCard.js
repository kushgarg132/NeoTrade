// The weekly report's share image: percentages only, never rupees, and no advice.
import { pct } from '../components/ui/format.js';

const SIZE = 1080;
// The dark theme's tokens (index.css): an image cannot read CSS variables once it leaves the app.
const C = { bg: '#0b0b0c', surface: '#141416', border: '#27272a', text: '#ededef', muted: '#a1a1aa', accent: '#10b981', gain: '#3ddc97', loss: '#ff6b6b' };
const FONT = 'Geist, ui-sans-serif, system-ui, sans-serif';
const toneOf = (x) => (x > 0 ? 'gain' : x < 0 ? 'loss' : 'muted');

/** What the card says. null when the week has no return to share. */
export const shareRows = (you) => {
  if (typeof you?.ret !== 'number') return null;
  const rows = [{ label: 'My week', value: pct(you.ret, { sign: true, dp: 1 }), tone: toneOf(you.ret), big: true }];
  if (typeof you.nifty === 'number') rows.push({ label: 'NIFTY', value: pct(you.nifty, { sign: true, dp: 1 }), tone: toneOf(you.nifty) });
  if (typeof you.excess === 'number') {
    rows.push({ label: you.excess < 0 ? 'Behind NIFTY by' : 'Ahead of NIFTY by', value: pct(Math.abs(you.excess), { dp: 1 }), tone: toneOf(you.excess) });
  }
  return rows;
};

export const shareName = (week) => `neotrade-${week}.png`;

const draw = (ctx, rows, range) => {
  ctx.fillStyle = C.bg;
  ctx.fillRect(0, 0, SIZE, SIZE);
  ctx.textBaseline = 'alphabetic';
  ctx.fillStyle = C.text;
  ctx.font = `700 52px ${FONT}`;
  ctx.fillText('NeoTrade', 80, 130);
  ctx.fillStyle = C.muted;
  ctx.font = `500 38px ${FONT}`;
  ctx.fillText(range, 80, 190);

  const [hero, ...rest] = rows;
  ctx.font = `500 44px ${FONT}`;
  ctx.fillText(hero.label, 80, 370);
  ctx.fillStyle = C[hero.tone];
  ctx.font = `700 190px ${FONT}`;
  ctx.fillText(hero.value, 72, 550);

  rest.forEach((row, i) => {
    const y = 680 + i * 110;
    ctx.fillStyle = C.border;
    ctx.fillRect(80, y - 62, SIZE - 160, 2);
    ctx.fillStyle = C.muted;
    ctx.font = `500 42px ${FONT}`;
    ctx.textAlign = 'left';
    ctx.fillText(row.label, 80, y);
    ctx.fillStyle = C[row.tone];
    ctx.font = `700 52px ${FONT}`;
    ctx.textAlign = 'right';
    ctx.fillText(row.value, SIZE - 80, y);
    ctx.textAlign = 'left';
  });

  ctx.fillStyle = C.muted;
  ctx.font = `400 32px ${FONT}`;
  ctx.fillText('Not investment advice.', 80, SIZE - 70);
};

const render = (rows, range) => new Promise((resolve, reject) => {
  const canvas = document.createElement('canvas');
  canvas.width = SIZE;
  canvas.height = SIZE;
  draw(canvas.getContext('2d'), rows, range);
  canvas.toBlob((blob) => (blob ? resolve(blob) : reject(new Error('The image could not be drawn'))), 'image/png');
});

const download = (file) => {
  const url = URL.createObjectURL(file);
  const link = Object.assign(document.createElement('a'), { href: url, download: file.name });
  link.click();
  setTimeout(() => URL.revokeObjectURL(url), 1000);
};

/** The phone's share sheet when it can take a file, else a download. Closing the sheet is not an error. */
export const deliver = async (file, nav = navigator, save = download) => {
  if (!nav.canShare?.({ files: [file] })) {
    save(file);
    return 'saved';
  }
  try {
    await nav.share({ files: [file] });
    return 'shared';
  } catch (err) {
    if (err?.name === 'AbortError') return 'cancelled';
    throw err;
  }
};

export const shareWeek = async (week, range, you) => {
  const blob = await render(shareRows(you), range);
  return deliver(new File([blob], shareName(week), { type: 'image/png' }));
};
