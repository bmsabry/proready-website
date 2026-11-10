import { useEffect, useRef } from 'react';

type Answers = Record<string, unknown>;

/**
 * Keeps a learner's answers safe while a quiz or examination is open.
 *
 * Before this, answers lived only in the page. A reload, the Back button, or a
 * phone quietly discarding the tab lost all of them (up to 100 on the written
 * examination) with no warning. Now:
 *
 *  - every change is written to this browser tab's session storage, and put
 *    back when the same paper is opened again;
 *  - the browser asks before the page is closed or reloaded with unsent answers;
 *  - the saved copy is removed as soon as the paper is handed in.
 *
 * Only answers to questions on the paper being shown are restored, so answers
 * to an earlier paper can never be handed in against a new one. Session
 * storage ends with the tab, so nothing is left behind on a shared computer.
 *
 * `key` identifies the paper and is null until it has loaded.
 */
export function useAnswerDraft(
  key: string | null,
  itemCodes: string[],
  answers: Answers,
  setAnswers: (next: Answers) => void,
  handedIn: boolean,
): void {
  const restoredFor = useRef<string | null>(null);

  useEffect(() => {
    if (!key || restoredFor.current === key) return;
    restoredFor.current = key;
    try {
      const raw = window.sessionStorage.getItem(key);
      if (!raw) return;
      const saved = JSON.parse(raw) as Answers;
      const onPaper = new Set(itemCodes);
      const kept: Answers = {};
      for (const [code, value] of Object.entries(saved ?? {})) {
        if (onPaper.has(code) && value !== undefined && value !== '') kept[code] = value;
      }
      if (Object.keys(kept).length > 0) setAnswers(kept);
    } catch {
      /* storage unavailable or unreadable: carry on without a saved copy */
    }
    // The item codes belong to `key`; restoring is once per paper.
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [key]);

  useEffect(() => {
    if (!key || restoredFor.current !== key) return;
    try {
      if (handedIn || Object.keys(answers).length === 0) window.sessionStorage.removeItem(key);
      else window.sessionStorage.setItem(key, JSON.stringify(answers));
    } catch {
      /* storage full or blocked: the answers are still on the page */
    }
  }, [key, answers, handedIn]);

  const unsent =
    !handedIn && Object.values(answers).some((value) => value !== undefined && value !== '');
  useEffect(() => {
    if (!unsent) return;
    const ask = (event: BeforeUnloadEvent) => {
      event.preventDefault();
      event.returnValue = '';
    };
    window.addEventListener('beforeunload', ask);
    return () => window.removeEventListener('beforeunload', ask);
  }, [unsent]);
}
