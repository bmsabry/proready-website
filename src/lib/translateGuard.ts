/**
 * Keep the site alive when the browser translates the page (2026-11-27).
 *
 * Chrome's "Translate this page" (and similar tools: other translators,
 * Grammarly, some reading extensions) replaces the page's text with its own
 * elements. React still holds the original text, and when it later removes
 * or inserts beside a piece of text that is no longer where it left it, the
 * browser throws "Failed to execute 'removeChild' on 'Node'" and the whole
 * page goes blank.
 *
 * On the written examination this happened at the worst moment: the line
 * ". Unanswered questions count as incorrect." disappears when the last
 * question is answered, so a candidate reading the paper translated lost the
 * page, and every answer with it, the instant they finished (reproduced with
 * React 18.3.1 and a simulated translation, 2026-11-27).
 *
 * The guard below is the long-standing workaround for that React issue: when
 * React asks to remove a node that the translator has already moved, or to
 * insert before one, the request is absorbed instead of crashing the page.
 * The translated text may lag behind until the next change, which is far
 * better than a blank screen. Installed once, before React renders.
 */
const INSTALLED = '__preTranslateGuard';

export function installTranslateGuard(): void {
  if (typeof Node !== 'function' || !Node.prototype) return;
  const proto = Node.prototype as Node & { [INSTALLED]?: boolean };
  if (proto[INSTALLED]) return;
  proto[INSTALLED] = true;

  const removeChild = proto.removeChild;
  proto.removeChild = function <T extends Node>(this: Node, child: T): T {
    if (child.parentNode !== this) {
      // Already moved or replaced by a translator: nothing left to remove here.
      return child;
    }
    return removeChild.call(this, child) as T;
  };

  const insertBefore = proto.insertBefore;
  proto.insertBefore = function <T extends Node>(this: Node, node: T, ref: Node | null): T {
    if (ref && ref.parentNode !== this) {
      // The reference was replaced by a translator: append instead of crashing.
      return insertBefore.call(this, node, null) as T;
    }
    return insertBefore.call(this, node, ref) as T;
  };
}

installTranslateGuard();
