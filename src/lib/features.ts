/* Release switches for features that ship to production hidden, so the owner
 * can test them on the live site by direct URL before visitors can find them.
 *
 * false: no public link to the page anywhere on the site, the page carries
 *        noindex,nofollow and is left out of the sitemap (it still works by
 *        direct URL, and is still prerendered).
 * true:  the page is advertised normally (header, sections, footer, sitemap).
 *
 * Going public is a one-line change here, then a normal build and deploy.
 */

/** /consult (paid expert calls) and every call-to-action that leads to it. */
export const CONSULT_PUBLIC = false;

/** /about/bassam-abdelnabi (the expert's profile) and the links to it. */
export const PROFILE_PUBLIC = false;
