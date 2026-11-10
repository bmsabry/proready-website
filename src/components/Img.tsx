import React from 'react';
import manifest from '../data/images.json';

/* One <img> for the whole site.
 *
 * Give it the path of the original in public/ ("/Bassam.jpg"). When
 * scripts/optimize-images.mjs has made lightweight copies of that file, the
 * browser is offered them at several widths and downloads the smallest one
 * that is still sharp on its screen; `sizes` tells it how wide the image is
 * drawn. With no copies on record the original is served, exactly as a plain
 * <img> would, so a newly added image works before the script has been run.
 *
 * width/height always come from the real file, so the page reserves the right
 * space before the image arrives and nothing jumps as it loads.
 *
 * `priority` is for the one image a visitor sees first on a page: it is
 * fetched at once instead of waiting for the lazy-loader.
 */

type Entry = { w: number; h: number; src: string; srcset: string; og?: string };
const IMAGES = manifest as Record<string, Entry>;

type ImgProps = Omit<React.ImgHTMLAttributes<HTMLImageElement>, 'src' | 'srcSet' | 'loading'> & {
  src: string;
  alt: string;
  /** How wide the image is drawn, in CSS terms. Default: the full viewport width. */
  sizes?: string;
  priority?: boolean;
};

const Img = ({ src, sizes = '100vw', priority = false, ...rest }: ImgProps) => {
  const entry = IMAGES[src];
  // React 18 does not know the camelCase `fetchPriority` prop; the lowercase
  // attribute passes straight through to the DOM.
  const loading = priority
    ? { loading: 'eager' as const, fetchpriority: 'high' }
    : { loading: 'lazy' as const };
  if (!entry) {
    return <img src={src} decoding="async" {...loading} {...rest} />;
  }
  return (
    <img
      src={entry.src}
      srcSet={entry.srcset}
      sizes={sizes}
      width={entry.w}
      height={entry.h}
      decoding="async"
      {...loading}
      {...rest}
    />
  );
};

export default Img;

/** Link-preview image for a page: the light copy when there is one. */
export const socialImage = (src: string): string => IMAGES[src]?.og ?? src;
