(() => {
  'use strict';

  const api = window.LightweightCharts;
  const host = document.getElementById('professional-chart');
  const region = document.getElementById('prediction-region');
  const tooltip = document.getElementById('chart-tooltip');
  const qualityNote = document.getElementById('chart-quality-note');
  const fallback = document.getElementById('forecast-chart');
  const state = { chart: null, signature: '', theme: '', series: [], markerTarget: null,
    markerPlugin: null, markers: [], forecastStart: null, pointByTime: new Map(), volumeSeries: null, volumeData: [] };
  const istDate = new Intl.DateTimeFormat('en-CA', { timeZone: 'Asia/Kolkata', year: 'numeric', month: '2-digit', day: '2-digit' });
  const istTime = new Intl.DateTimeFormat('en-IN', { timeZone: 'Asia/Kolkata', day: 'numeric', month: 'short', hour: 'numeric', minute: '2-digit', hour12: true });
  const priceFormat = new Intl.NumberFormat('en-IN', { minimumFractionDigits: 2, maximumFractionDigits: 2 });

  function color(name, fallbackColor) {
    return getComputedStyle(document.documentElement).getPropertyValue(name).trim() || fallbackColor;
  }

  function palette() {
    return {
      background: color('--surface-primary', '#ffffff'),
      text: color('--chart-axis', '#69717b'),
      grid: color('--chart-grid', '#e4e7ea'),
      observed: color('--chart-observed', '#4f5965'),
      predicted: color('--information', '#1457a6'),
      positive: color('--positive', '#176b45'),
      negative: color('--negative', '#a83a37'),
      actual: color('--warning', '#8a6116'),
      ema20: color('--warning', '#8a6116'),
      ema50: color('--information', '#1457a6'),
      band: color('--text-tertiary', '#6d747e'),
    };
  }

  function unix(timestamp) {
    const value = Date.parse(timestamp) / 1000;
    if (!Number.isFinite(value)) throw new Error('Invalid chart timestamp');
    return Math.floor(value);
  }

  function sessionKey(time) {
    return istDate.format(new Date(time * 1000));
  }

  function checked(points, ohlc = false) {
    let previous = -Infinity;
    return points.map((point) => {
      const time = unix(point.timestamp);
      if (time <= previous) throw new Error('Chart timestamps must be increasing and unique');
      previous = time;
      const close = Number(point.close);
      if (!Number.isFinite(close) || close <= 0) throw new Error('Invalid chart close');
      if (!ohlc) return { time, value: close };
      const data = { time, open: Number(point.open), high: Number(point.high), low: Number(point.low), close };
      if (![data.open, data.high, data.low].every(Number.isFinite) ||
          data.high < Math.max(data.open, data.close, data.low) ||
          data.low > Math.min(data.open, data.close, data.high)) return { time };
      return data;
    });
  }

  function sessions(points) {
    const groups = [];
    for (const point of points) {
      const key = sessionKey(point.time);
      if (!groups.length || groups[groups.length - 1].key !== key) groups.push({ key, data: [] });
      groups[groups.length - 1].data.push(point);
    }
    return groups.map((group) => group.data);
  }

  function bands(points) {
    const lower = [], upper = [];
    for (let index = 19; index < points.length; index += 1) {
      const windowValues = points.slice(index - 19, index + 1).map((point) => point.value);
      const mean = windowValues.reduce((sum, value) => sum + value, 0) / 20;
      const deviation = Math.sqrt(windowValues.reduce((sum, value) => sum + (value - mean) ** 2, 0) / 20);
      lower.push({ time: points[index].time, value: mean - 2 * deviation });
      upper.push({ time: points[index].time, value: mean + 2 * deviation });
    }
    return [lower, upper];
  }

  function add(role, type, options, data) {
    const series = state.chart.addSeries(type, options);
    series.setData(data);
    state.series.push({ role, series });
    return series;
  }

  function addSessionLines(role, points, options) {
    for (const segment of sessions(points)) add(role, api.LineSeries, options, segment);
  }

  function applyTheme() {
    if (!state.chart) return;
    const colors = palette();
    state.chart.applyOptions({
      layout: { background: { type: api.ColorType.Solid, color: colors.background }, textColor: colors.text },
      grid: { vertLines: { color: colors.grid }, horzLines: { color: colors.grid } },
      rightPriceScale: { borderColor: colors.grid },
      timeScale: { borderColor: colors.grid },
      crosshair: { vertLine: { color: colors.text, labelBackgroundColor: colors.observed },
        horzLine: { color: colors.text, labelBackgroundColor: colors.observed } },
    });
    for (const { role, series } of state.series) {
      if (role === 'observed-candle') series.applyOptions({ upColor: colors.observed, downColor: colors.observed,
        wickUpColor: colors.observed, wickDownColor: colors.observed, borderUpColor: colors.observed, borderDownColor: colors.observed });
      else if (role === 'predicted-candle') series.applyOptions({ upColor: colors.predicted, downColor: colors.predicted,
        wickUpColor: colors.predicted, wickDownColor: colors.predicted, borderUpColor: colors.predicted, borderDownColor: colors.predicted });
      else if (role === 'volume') series.setData(state.volumeData.map((point) => ({ time: point.time,
        value: point.value, color: point.kind === 'predicted' ? colors.predicted : colors.observed })));
      else series.applyOptions({ color: colors[role] || colors.observed });
    }
    state.theme = document.documentElement.dataset.theme || 'light';
  }

  function positionRegion() {
    if (!state.chart || state.forecastStart == null) return;
    const coordinate = state.chart.timeScale().timeToCoordinate(state.forecastStart);
    const width = host.clientWidth;
    if (coordinate == null || coordinate >= width) { region.hidden = true; return; }
    const start = Math.max(0, coordinate);
    region.hidden = false;
    region.style.width = `${Math.max(0, width - start)}px`;
    region.dataset.narrow = String(width - start < 170);
    region.querySelector('.prediction-boundary-label').hidden = coordinate < 0;
  }

  function updateTooltip(param) {
    if (!param.time || !param.point || param.point.x < 0 || param.point.x > host.clientWidth) {
      tooltip.hidden = true;
      return;
    }
    const point = state.pointByTime.get(Number(param.time));
    if (!point) { tooltip.hidden = true; return; }
    const label = point.kind === 'predicted' ? 'Predicted candle' : point.kind === 'actual' ? 'Actual future candle' : 'Observed candle';
    const time = istTime.format(new Date(Number(param.time) * 1000));
    const closeLabel = point.kind === 'predicted' ? 'Predicted close' : point.kind === 'actual' ? 'Actual close' : 'Observed close';
    const parts = [label, `${time} IST`, `${closeLabel} ₹${priceFormat.format(Number(point.close))}`];
    if (point.predictedClose != null) parts.push(`Predicted close ₹${priceFormat.format(Number(point.predictedClose))}`);
    if ([point.open, point.high, point.low].every((value) => Number.isFinite(Number(value)))) {
      parts.push(`O ₹${priceFormat.format(Number(point.open))}  H ₹${priceFormat.format(Number(point.high))}`);
      parts.push(`L ₹${priceFormat.format(Number(point.low))}  V ${new Intl.NumberFormat('en-IN').format(Number(point.volume) || 0)}`);
    }
    tooltip.replaceChildren(...parts.map((value, index) => {
      const item = document.createElement(index === 0 ? 'strong' : 'span');
      item.textContent = value;
      return item;
    }));
    tooltip.hidden = false;
  }

  function ensureChart() {
    if (state.chart) return;
    host.hidden = false;
    const colors = palette();
    state.chart = api.createChart(host, {
      width: Math.max(280, host.clientWidth), height: Math.max(240, host.clientHeight),
      layout: { background: { type: api.ColorType.Solid, color: colors.background }, textColor: colors.text,
        fontFamily: 'system-ui, Segoe UI, sans-serif', fontSize: 11 },
      grid: { vertLines: { color: colors.grid }, horzLines: { color: colors.grid } },
      timeScale: { timeVisible: true, secondsVisible: false, borderColor: colors.grid,
        tickMarkFormatter: (time) => istTime.format(new Date(Number(time) * 1000)) },
      localization: { timeFormatter: (time) => `${istTime.format(new Date(Number(time) * 1000))} IST` },
      rightPriceScale: { borderColor: colors.grid, scaleMargins: { top: 0.08, bottom: 0.28 } },
      crosshair: { mode: api.CrosshairMode.Normal },
      handleScale: true, handleScroll: true,
    });
    state.chart.subscribeCrosshairMove(updateTooltip);
    state.chart.timeScale().subscribeVisibleLogicalRangeChange(() => requestAnimationFrame(positionRegion));
  }

  function setMarkers() {
    if (!state.markerTarget || typeof api.createSeriesMarkers !== 'function') return;
    const available = new Set([...state.pointByTime.entries()].filter(([, point]) => point.kind === 'observed').map(([time]) => time));
    const markers = state.markers.filter((marker) => available.has(marker.time)).map((marker) => ({
      time: marker.time, position: 'aboveBar', shape: 'circle',
      color: marker.color || color('--information', '#1457a6'), text: String(marker.label || 'Event').slice(0, 28),
    }));
    state.markerPlugin = api.createSeriesMarkers(state.markerTarget, markers);
  }

  function render(result, mode, showBollinger) {
    if (!api || !host || !result?.chart) return false;
    const observed = result.chart.observed || [];
    const forecast = result.chart.forecast || [];
    const actual = result.validation?.actual || result.chart.actual || [];
    if (!observed.length || !forecast.length) return false;
    try {
      ensureChart();
      state.chart.resize(Math.max(280, host.clientWidth), Math.max(240, host.clientHeight));
      const signature = `${result.summary_fingerprint || result.forecast_created_at}|${mode}|${showBollinger}`;
      if (signature !== state.signature) {
        if (state.markerPlugin) { state.markerPlugin.detach?.(); state.markerPlugin = null; }
        for (const item of state.series) state.chart.removeSeries(item.series);
        state.series = [];
        state.markerTarget = null;
        state.volumeSeries = null;
        state.volumeData = [];
        state.pointByTime = new Map();
        const observedClose = checked(observed);
        const forecastClose = checked(forecast);
        const actualClose = checked(actual);
        const observedCandles = checked(observed, true);
        const forecastCandles = checked(forecast, true);
        const invalidObserved = observedCandles.filter((point) => point.close == null).length;
        const invalidForecast = forecastCandles.filter((point) => point.close == null).length;
        qualityNote.hidden = invalidForecast + invalidObserved === 0;
        qualityNote.textContent = invalidForecast + invalidObserved
          ? `${invalidForecast} predicted and ${invalidObserved} observed OHLC bars are internally inconsistent. Their closes remain plotted; malformed candle bodies are omitted.`
          : '';
        const colors = palette();
        for (const point of observed) state.pointByTime.set(unix(point.timestamp), { ...point, kind: 'observed' });
        for (const point of forecast) state.pointByTime.set(unix(point.timestamp), { ...point, kind: 'predicted' });
        for (const point of actual) {
          const time = unix(point.timestamp);
          state.pointByTime.set(time, { ...point, kind: 'actual',
            predictedClose: state.pointByTime.get(time)?.kind === 'predicted' ? state.pointByTime.get(time).close : null });
        }
        const candleMode = mode === 'candles' && [...observed, ...forecast].every((point) =>
          [point.open, point.high, point.low, point.close].every((value) => Number.isFinite(Number(value))));
        if (candleMode) {
          state.markerTarget = add('observed-candle', api.CandlestickSeries, { priceLineVisible: false,
            lastValueVisible: false }, observedCandles);
          add('predicted-candle', api.CandlestickSeries, { priceLineVisible: false,
            lastValueVisible: false }, forecastCandles);
        } else {
          for (const segment of sessions(observedClose)) {
            const series = add('observed', api.LineSeries, { lineWidth: 2, priceLineVisible: false,
              lastValueVisible: false }, segment);
            if (!state.markerTarget) state.markerTarget = series;
          }
        }
        addSessionLines('predicted', forecastClose, { color: colors.predicted, lineWidth: 2,
          lineStyle: api.LineStyle.Dashed, priceLineVisible: false, lastValueVisible: false });
        if (actualClose.length) addSessionLines('actual', actualClose, { color: colors.actual, lineWidth: 2,
          priceLineVisible: false, lastValueVisible: false });
        const analyticalEma = result.chart.analytical_ema || {};
        const ema20 = (analyticalEma.ema20 || []).map((point) => ({ time: unix(point.timestamp), value: Number(point.value) }));
        const ema50 = (analyticalEma.ema50 || []).map((point) => ({ time: unix(point.timestamp), value: Number(point.value) }));
        addSessionLines('ema20', ema20, { color: colors.ema20, lineWidth: 1,
          priceLineVisible: false, lastValueVisible: false });
        addSessionLines('ema50', ema50, { color: colors.ema50, lineWidth: 1,
          lineStyle: api.LineStyle.Dotted, priceLineVisible: false, lastValueVisible: false });
        if (showBollinger && observedClose.length >= 20) {
          for (const line of bands(observedClose)) addSessionLines('band', line, { color: colors.band,
            lineWidth: 1, lineStyle: api.LineStyle.Dotted, priceLineVisible: false, lastValueVisible: false });
        }
        const volumes = [...observed.map((point) => ({ ...point, kind: 'observed' })),
          ...forecast.map((point) => ({ ...point, kind: 'predicted' }))]
          .filter((point) => Number.isFinite(Number(point.volume)) && Number(point.volume) >= 0)
          .map((point) => ({ time: unix(point.timestamp), value: Number(point.volume), kind: point.kind }));
        if (volumes.length) {
          state.volumeData = volumes;
          const volume = add('volume', api.HistogramSeries, { priceScaleId: 'volume',
            priceFormat: { type: 'volume' }, priceLineVisible: false, lastValueVisible: false },
          volumes.map((point) => ({ time: point.time, value: point.value,
            color: point.kind === 'predicted' ? colors.predicted : colors.observed })));
          state.volumeSeries = volume;
          volume.priceScale().applyOptions({ scaleMargins: { top: 0.78, bottom: 0 } });
        }
        state.forecastStart = forecastClose[0].time;
        state.signature = signature;
        setMarkers();
        state.chart.timeScale().fitContent();
      }
      if (state.theme !== (document.documentElement.dataset.theme || 'light')) applyTheme();
      host.hidden = false;
      fallback.hidden = true;
      requestAnimationFrame(positionRegion);
      return true;
    } catch (error) {
      console.warn('Professional chart unavailable; using the accessible canvas chart.', error);
      host.hidden = true;
      region.hidden = true;
      tooltip.hidden = true;
      fallback.hidden = false;
      return false;
    }
  }

  window.kronosProfessionalChart = {
    render,
    setEventMarkers(markers) {
      state.markers = (Array.isArray(markers) ? markers : []).flatMap((marker) => {
        if (!marker || (marker.time == null && !marker.timestamp)) return [];
        const time = marker.time == null ? Date.parse(marker.timestamp) / 1000 : Number(marker.time);
        return Number.isFinite(time) ? [{ time: Math.floor(time), label: marker.label, color: marker.color }] : [];
      });
      if (state.chart && state.markerTarget) {
        if (state.markerPlugin) {
          const available = new Set([...state.pointByTime.entries()].filter(([, point]) => point.kind === 'observed').map(([time]) => time));
          state.markerPlugin.setMarkers(state.markers.filter((marker) => available.has(marker.time)).map((marker) => ({
            time: marker.time, position: 'aboveBar', shape: 'circle',
            color: marker.color || color('--information', '#1457a6'), text: String(marker.label || 'Event').slice(0, 28),
          })));
        } else setMarkers();
      }
    },
    inspect: () => ({ active: Boolean(state.chart && !host.hidden),
      forecastStart: state.forecastStart, points: state.pointByTime.size, signature: state.signature }),
  };
})();
