/* Play, pause, step. The cursor is the only state.
 *
 * Everything the scene shows is `fold(cues, cursor)`, so controlling the show
 * means controlling one integer. That is the whole point of the split: there
 * is no second notion of "how far along are we" that could drift out of step
 * with what is on screen.
 *
 * The cursor does not advance on a timer. The scene advances it when a beat
 * has actually finished playing (`onBeatDone`), because a beat takes as long
 * as Poyo takes to walk there -- a timer would run ahead of him on a long
 * walk and the log would narrate things he had not reached yet.
 *
 * A live drill grows its own timeline while you watch it. So the cursor resets
 * on a change of *run*, never on a change of length: a new event arriving must
 * extend the show, not start it over.
 */
const { useCallback, useEffect, useRef, useState } = React;

/**
 * `length` is the number of cues; the cursor runs -1 .. length-1, where -1 is
 * the opening state before any beat has played. `resetKey` identifies the run:
 * change it and playback starts over. `live` means more cues are still coming,
 * so reaching the end is a wait rather than an ending.
 */
export function useTransport(length, resetKey, live = false) {
  const [cursor, setCursor] = useState(-1);
  const [playing, setPlaying] = useState(true);
  // Lets the scene finish one beat's motion while paused, so "step forward"
  // walks him there instead of teleporting him.
  const stepOnce = useRef(false);
  const playingRef = useRef(playing);
  playingRef.current = playing;

  // A different run starts over rather than keeping a cursor that pointed into
  // the previous one. Keyed on the run, not the length: a live drill appends
  // cues as its events land, and that must not rewind the viewer.
  useEffect(() => {
    setCursor(-1);
    setPlaying(true);
  }, [resetKey]);

  const atEnd = cursor >= length - 1;
  const atStart = cursor <= -1;

  const seek = useCallback((to) => {
    setCursor(Math.max(-1, Math.min(length - 1, to)));
  }, [length]);

  /** Let one beat animate even though we are paused. */
  const allowOneBeat = useCallback(() => { stepOnce.current = true; }, []);

  const forward = useCallback(() => {
    if (!playingRef.current) allowOneBeat();
    setCursor((c) => Math.min(length - 1, c + 1));
  }, [length, allowOneBeat]);

  /** Step back one beat. Going back is a deliberate look, so it pauses. */
  const back = useCallback(() => {
    setPlaying(false);
    setCursor((c) => Math.max(-1, c - 1));
  }, []);

  const restart = useCallback(() => {
    setCursor(-1);
  }, []);

  const play = useCallback(() => {
    // Pressing play at the end replays from the top rather than doing nothing.
    setCursor((c) => (c >= length - 1 ? -1 : c));
    setPlaying(true);
  }, [length]);

  const pause = useCallback(() => setPlaying(false), []);
  const toggle = useCallback(() => (playingRef.current ? pause() : play()), [pause, play]);

  /** The scene calls this when the current beat has finished playing out. */
  const onBeatDone = useCallback(() => {
    stepOnce.current = false;
    if (!playingRef.current) return;
    setCursor((c) => {
      if (c >= length - 1) {
        // Hold on the last beat instead of looping. A live drill stays in
        // "playing" so the next event it writes carries straight on.
        if (!live) setPlaying(false);
        return c;
      }
      return c + 1;
    });
  }, [length, live]);

  /** True while the scene is allowed to move: playing, or stepping one beat. */
  const moving = useCallback(() => playingRef.current || stepOnce.current, []);

  return {
    cursor, playing, atEnd, atStart, length,
    play, pause, toggle, back, forward, seek, restart,
    onBeatDone, moving,
  };
}
