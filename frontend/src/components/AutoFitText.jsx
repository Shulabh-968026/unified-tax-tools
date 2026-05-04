/**
 * AutoFitText — shrinks the font-size so the rendered text always fits
 * inside the parent container width, regardless of the underlying value
 * length.  Used on the Clause 44 KPI tiles where some clients have
 * 9–10 digit aggregates (e.g. ₹56,58,19,949.99) that previously
 * overflowed their tile.
 *
 * Strategy:
 *   1. Render the text at the requested `maxFontPx`.
 *   2. After paint, compare `scrollWidth` vs `clientWidth` of the wrapper.
 *   3. If overflowing, scale font-size down by `clientWidth / scrollWidth`
 *      with a small safety margin, clamped to `minFontPx`.
 *   4. Re-measure on container resize via ResizeObserver.
 *
 * Why not CSS-only?  `clamp()` + container queries can't react to the
 * *content* width — only the viewport / container.  And SVG <text> with
 * preserveAspectRatio works but loses kerning + crisp font rendering.
 * A small JS measure-and-scale loop is the most robust path for our
 * monospaced-fiscal numbers where character widths are predictable.
 */
import { useEffect, useLayoutEffect, useRef, useState } from "react";

export default function AutoFitText({
  children,
  maxFontPx = 20,
  minFontPx = 11,
  className = "",
  testid,
}) {
  const wrapRef = useRef(null);
  const innerRef = useRef(null);
  const [fontPx, setFontPx] = useState(maxFontPx);

  const recompute = () => {
    const wrap = wrapRef.current;
    const inner = innerRef.current;
    if (!wrap || !inner) return;
    // Reset to max first so we can measure the *natural* content width.
    inner.style.fontSize = `${maxFontPx}px`;
    const avail = wrap.clientWidth;
    if (avail <= 0) return;
    const needed = inner.scrollWidth;
    if (needed <= avail) {
      setFontPx((prev) => (prev === maxFontPx ? prev : maxFontPx));
      return;
    }
    // Scale down with a 4% safety margin, clamp to min.
    const scaled = Math.max(minFontPx, Math.floor(maxFontPx * (avail / needed) * 0.96));
    setFontPx((prev) => (prev === scaled ? prev : scaled));
  };

  // Re-measure whenever the value or the container width changes.
  useLayoutEffect(() => {
    recompute();
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [children, maxFontPx, minFontPx]);

  useEffect(() => {
    if (typeof ResizeObserver === "undefined" || !wrapRef.current) return;
    let raf = 0;
    // Defer to next frame to avoid the "ResizeObserver loop completed
    // with undelivered notifications" warning that fires when the
    // observer triggers a synchronous layout change inside its own
    // callback (we set font-size, which can affect width).
    const ro = new ResizeObserver(() => {
      cancelAnimationFrame(raf);
      raf = requestAnimationFrame(() => recompute());
    });
    ro.observe(wrapRef.current);
    return () => {
      cancelAnimationFrame(raf);
      ro.disconnect();
    };
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, []);

  return (
    <div ref={wrapRef} className="w-full overflow-hidden" data-testid={testid}>
      <span
        ref={innerRef}
        className={`inline-block whitespace-nowrap ${className}`}
        style={{ fontSize: `${fontPx}px`, lineHeight: 1.15 }}
      >
        {children}
      </span>
    </div>
  );
}
