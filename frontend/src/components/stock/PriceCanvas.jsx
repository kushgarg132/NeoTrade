import React, { useEffect, useRef, useState } from 'react';
import {
  AreaSeries, CandlestickSeries, CrosshairMode, HistogramSeries, LineStyle, createChart, createSeriesMarkers,
} from 'lightweight-charts';
import { chartTime } from '../../utils/stock';

// lightweight-charts paints a canvas, so CSS variables must become concrete colours: a hidden probe
// element resolves each token (and color-mix alphas) through the browser's own cascade. The computed
// value can be `color(srgb …)`, which the library cannot parse, so one canvas pixel turns it into rgba().
const resolver = (probe) => {
  const px = document.createElement('canvas').getContext('2d', { willReadFrequently: true });
  return (css) => {
    probe.style.color = '';
    probe.style.color = css;
    px.clearRect(0, 0, 1, 1);
    px.fillStyle = getComputedStyle(probe).color;
    px.fillRect(0, 0, 1, 1);
    const [r, g, b, a] = px.getImageData(0, 0, 1, 1).data;
    return `rgba(${r}, ${g}, ${b}, ${(a / 255).toFixed(3)})`;
  };
};
const soft = (token, pct) => `color-mix(in srgb, var(${token}) ${pct}%, transparent)`;

// A business-day time comes back from the library as {year, month, day}; a timestamp as a number.
const pad = (n) => String(n).padStart(2, '0');
const timeKey = (t) => (typeof t === 'object' && t ? `${t.year}-${pad(t.month)}-${pad(t.day)}` : String(t));

const NEWS_HIT_PX = 16;

const axisPrice = (p) => Number(p).toLocaleString('en-IN', { maximumFractionDigits: 2 });

/**
 * The price canvas behind TradingChart. `bars` from utils/stock.js::toBars; `mode` 'candle' | 'area';
 * `markers` [{date, kind: 'buy'|'sell'|'news', direction?, impact?}]; `priceLines` [{price, tone, title}]
 * (stop/target, their axis labels hidden under hide-amounts via `hidePrices`); `baseline` a dotted
 * previous-close line. `onCrosshair(bar|null)` drives the readout; `onPickDate(date)` fires on a click
 * on a day that carries a news marker. Drag pans, pinch/wheel zooms, double-click fits everything.
 */
const PriceCanvas = ({ bars, mode, markers, priceLines, baseline, hidePrices, onCrosshair, onPickDate }) => {
  const box = useRef(null);
  const probe = useRef(null);
  const chartRef = useRef(null);
  const latest = useRef({});
  const fitKey = useRef('');
  const [theme, setTheme] = useState(0);
  latest.current = { bars, markers, onCrosshair, onPickDate };

  // The chart lives as long as the component; data changes below reuse it.
  useEffect(() => {
    const chart = createChart(box.current, {
      autoSize: true,
      layout: { background: { color: 'transparent' }, fontSize: 12 },
      grid: { vertLines: { visible: false } },
      rightPriceScale: { borderVisible: false },
      timeScale: { borderVisible: false, rightOffset: 2 },
      crosshair: { mode: CrosshairMode.Normal },
      handleScroll: { vertTouchDrag: false }, // a vertical swipe scrolls the page, not the chart
      localization: { priceFormatter: axisPrice },
    });
    chartRef.current = chart;
    const at = (param) => {
      if (!param.time || !param.point) return null;
      const key = timeKey(param.time);
      return latest.current.bars.find((b) => String(chartTime(b.date)) === key) || null;
    };
    const move = (param) => latest.current.onCrosshair?.(at(param));
    // A tap opens the nearest news dot within NEWS_HIT_PX: at 1Y on a phone a bar is about 1 px wide.
    const click = (param) => {
      if (!param.point) return;
      let best = null;
      for (const m of latest.current.markers || []) {
        if (m.kind !== 'news') continue;
        const x = chart.timeScale().timeToCoordinate(chartTime(m.date));
        const gap = x == null ? Infinity : Math.abs(x - param.point.x);
        if (gap <= NEWS_HIT_PX && (!best || gap < best.gap)) best = { date: m.date, gap };
      }
      if (best) latest.current.onPickDate?.(best.date);
    };
    chart.subscribeCrosshairMove(move);
    chart.subscribeClick(click);
    const el = box.current;
    const fit = () => chart.timeScale().fitContent();
    el.addEventListener('dblclick', fit);
    const watch = new MutationObserver(() => setTheme((n) => n + 1)); // ThemeContext toggles <html class="dark">
    watch.observe(document.documentElement, { attributes: true, attributeFilter: ['class', 'data-theme'] });
    return () => {
      watch.disconnect();
      el.removeEventListener('dblclick', fit);
      chart.unsubscribeCrosshairMove(move);
      chart.unsubscribeClick(click);
      chart.remove();
      chartRef.current = null;
    };
  }, []);

  // Rebuild the series on any input change: a handful of series, cheaper than diffing them.
  useEffect(() => {
    const chart = chartRef.current;
    if (!chart || !bars.length) return undefined;
    const color = resolver(probe.current);
    const gain = color('var(--gain)');
    const loss = color('var(--loss)');
    const muted = color('var(--text-muted)');
    const intraday = String(bars[0].date).length !== 10;
    chart.applyOptions({
      layout: { textColor: muted },
      grid: { horzLines: { color: color(soft('--border', 70)) } },
      crosshair: { vertLine: { color: muted, labelBackgroundColor: muted }, horzLine: { color: muted, labelBackgroundColor: muted } },
      timeScale: { timeVisible: intraday, secondsVisible: false },
    });

    const up = bars.at(-1).close >= bars[0].close;
    const hasVolume = bars.some((b) => b.volume > 0);
    const margins = { top: 0.12, bottom: hasVolume ? 0.24 : 0.08 };
    const main = mode === 'candle'
      ? chart.addSeries(CandlestickSeries, {
        upColor: gain, downColor: loss, wickUpColor: gain, wickDownColor: loss, borderVisible: false,
      })
      : chart.addSeries(AreaSeries, {
        lineColor: up ? gain : loss,
        topColor: color(soft(up ? '--gain' : '--loss', 25)),
        bottomColor: color(soft(up ? '--gain' : '--loss', 0)),
        lineWidth: 2,
      });
    main.priceScale().applyOptions({ scaleMargins: margins });
    main.setData(bars.map((b) => (mode === 'candle'
      ? { time: chartTime(b.date), open: b.open, high: b.high, low: b.low, close: b.close }
      : { time: chartTime(b.date), value: b.close })));

    let volume = null;
    if (hasVolume) {
      const upVol = color(soft('--gain', 22));
      const downVol = color(soft('--loss', 22));
      volume = chart.addSeries(HistogramSeries, { priceScaleId: 'vol', priceFormat: { type: 'volume' }, lastValueVisible: false, priceLineVisible: false });
      chart.priceScale('vol').applyOptions({ scaleMargins: { top: 0.8, bottom: 0 } });
      volume.setData(bars.map((b) => ({ time: chartTime(b.date), value: b.volume || 0, color: b.close >= b.open ? upVol : downVol })));
    }

    const newsColor = (d) => (d > 0 ? gain : d < 0 ? loss : muted);
    const marks = (markers || [])
      .map((m) => (m.kind === 'news'
        ? { time: chartTime(m.date), position: 'aboveBar', shape: 'circle', color: newsColor(m.direction), size: 0.6 + Math.min(10, m.impact || 0) / 10 }
        : m.kind === 'sell'
          ? { time: chartTime(m.date), position: 'aboveBar', shape: 'arrowDown', color: loss, text: 'S' }
          : { time: chartTime(m.date), position: 'belowBar', shape: 'arrowUp', color: gain, text: 'B' }))
      .sort((a, b) => (a.time < b.time ? -1 : a.time > b.time ? 1 : 0));
    const markerApi = createSeriesMarkers(main, marks);

    for (const l of priceLines || []) {
      main.createPriceLine({
        price: l.price, color: l.tone === 'loss' ? loss : gain, lineWidth: 1, lineStyle: LineStyle.Dashed,
        axisLabelVisible: !hidePrices, title: l.title,
      });
    }
    if (baseline != null) {
      main.createPriceLine({ price: baseline, color: muted, lineWidth: 1, lineStyle: LineStyle.Dotted, axisLabelVisible: false, title: '' });
    }

    // Refit only when the range or mode changes, so a 60 s poll keeps the reader's zoom.
    const key = `${bars[0].date}|${mode}`;
    if (fitKey.current !== key) {
      chart.timeScale().fitContent();
      fitKey.current = key;
    }
    return () => {
      if (chartRef.current !== chart) return; // unmounting: chart.remove() already took the series with it
      markerApi.detach();
      if (volume) chart.removeSeries(volume);
      chart.removeSeries(main);
    };
  }, [bars, mode, markers, priceLines, baseline, hidePrices, theme]);

  return (
    <div className="relative h-full w-full">
      <span ref={probe} aria-hidden="true" className="hidden" />
      <div ref={box} className="h-full w-full" />
    </div>
  );
};

export default PriceCanvas;
